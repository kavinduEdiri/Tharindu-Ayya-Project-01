from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from datetime import datetime, date
from functools import wraps
#from dotenv import load_dotenv
#load_dotenv()
import os
import uuid



app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")


# =========================
# MONGODB CONFIG
# =========================
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("MONGO_URI is not set. Please add it in your environment variables.")

client = MongoClient(MONGO_URI)
db = client["construction_rent_db"]

users_collection = db["users"]
items_collection = db["items"]
rentals_collection = db["rentals"]


# =========================
# INITIAL SETUP
# =========================
def setup_default_user():
    existing_user = users_collection.find_one({"email": "tharindu@gmail.com"})
    if not existing_user:
        users_collection.insert_one({
            "email": "tharindu@gmail.com",
            "password": "1234",
            "name": "Tharindu"
        })


setup_default_user()


# =========================
# HELPERS
# =========================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def calculate_days(rent_date_str, return_date_str):
    rent_dt = datetime.strptime(rent_date_str, '%Y-%m-%d')
    ret_dt = datetime.strptime(return_date_str, '%Y-%m-%d')
    return max((ret_dt - rent_dt).days, 1)


def enrich_rental_for_view(rental):
    rental_items = rental.get("items", [])
    rental["item_name"] = ", ".join([i["item_name"] for i in rental_items]) if rental_items else ""
    rental["quantity"] = sum(i.get("quantity", 0) for i in rental_items)
    rental["total_items_count"] = len(rental_items)
    rental["price_per_day"] = sum(i.get("price_per_day", 0) for i in rental_items)
    return rental


def ping_mongodb():
    try:
        client.admin.command("ping")
        print("MongoDB connected successfully!")
    except Exception as e:
        print("MongoDB connection failed:", e)


ping_mongodb()


# =========================
# AUTH
# =========================
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    error = None

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        user = users_collection.find_one({
            "email": email,
            "password": password
        })

        if user:
            session['user'] = user['name']
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid email or password. Please try again.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# =========================
# DASHBOARD
# =========================
@app.route('/dashboard')
@login_required
def dashboard():
    total_items = items_collection.count_documents({})
    total_rentals = rentals_collection.count_documents({})
    active_rentals = rentals_collection.count_documents({"status": "Rented"})

    returned_rentals = list(rentals_collection.find({"status": "Returned"}, {"_id": 0}))
    total_revenue = sum(r.get("total_amount", 0) for r in returned_rentals)

    recent_raw = list(
        rentals_collection.find({}, {"_id": 0}).sort("rent_date", -1).limit(5)
    )
    recent = [enrich_rental_for_view(r) for r in recent_raw]

    return render_template(
        'dashboard.html',
        user=session['user'],
        total_items=total_items,
        total_rentals=total_rentals,
        active_rentals=active_rentals,
        total_revenue=total_revenue,
        recent_rentals=recent
    )


# =========================
# ITEMS
# =========================
@app.route('/items')
@login_required
def items():
    all_items = list(items_collection.find({}, {"_id": 0}))
    return render_template('items.html', items=all_items, user=session['user'])


@app.route('/items/add', methods=['GET', 'POST'])
@login_required
def add_item():
    if request.method == 'POST':
        item = {
            "id": str(uuid.uuid4())[:8],
            "name": request.form['name'].strip(),
            "price_per_day": float(request.form['price_per_day']),
            "quantity": int(request.form['quantity'])
        }
        items_collection.insert_one(item)
        return redirect(url_for('items'))

    return render_template('item_form.html', item=None, user=session['user'], action='Add')


@app.route('/items/edit/<item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = items_collection.find_one({"id": item_id}, {"_id": 0})

    if not item:
        return redirect(url_for('items'))

    if request.method == 'POST':
        items_collection.update_one(
            {"id": item_id},
            {"$set": {
                "name": request.form['name'].strip(),
                "price_per_day": float(request.form['price_per_day']),
                "quantity": int(request.form['quantity'])
            }}
        )
        return redirect(url_for('items'))

    return render_template('item_form.html', item=item, user=session['user'], action='Edit')


@app.route('/items/delete/<item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    items_collection.delete_one({"id": item_id})
    return redirect(url_for('items'))


@app.route('/api/item/<item_id>')
@login_required
def get_item(item_id):
    item = items_collection.find_one({"id": item_id}, {"_id": 0})
    if item:
        return jsonify(item)
    return jsonify({}), 404


# =========================
# RENTALS - MULTI ITEM
# =========================
@app.route('/rent', methods=['GET', 'POST'])
@login_required
def rent_item():
    if request.method == 'POST':
        customer_name = request.form['customer_name'].strip()
        customer_phone = request.form['customer_phone'].strip()
        address = request.form['address'].strip()
        nic = request.form['nic'].strip()
        rent_date = request.form['rent_date']

        item_ids = request.form.getlist('item_id[]')
        quantities = request.form.getlist('quantity[]')

        if not item_ids or not any(item_ids):
            all_items = list(items_collection.find({}, {"_id": 0}))
            today = date.today().isoformat()
            return render_template(
                'rent_form.html',
                items=all_items,
                user=session['user'],
                today=today,
                error="Please add at least one item."
            )

        rental_items = []
        estimated_total_per_day = 0

        for idx, item_id in enumerate(item_ids):
            item_id = item_id.strip()
            if not item_id:
                continue

            qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 0
            if qty <= 0:
                continue

            db_item = items_collection.find_one({"id": item_id}, {"_id": 0})
            if not db_item:
                all_items = list(items_collection.find({}, {"_id": 0}))
                today = date.today().isoformat()
                return render_template(
                    'rent_form.html',
                    items=all_items,
                    user=session['user'],
                    today=today,
                    error="One selected item was not found."
                )

            available_qty = int(db_item.get("quantity", 0))
            if qty > available_qty:
                all_items = list(items_collection.find({}, {"_id": 0}))
                today = date.today().isoformat()
                return render_template(
                    'rent_form.html',
                    items=all_items,
                    user=session['user'],
                    today=today,
                    error=f"Only {available_qty} available for {db_item['name']}."
                )

            line_total_per_day = float(db_item["price_per_day"]) * qty

            rental_items.append({
                "item_id": db_item["id"],
                "item_name": db_item["name"],
                "quantity": qty,
                "price_per_day": float(db_item["price_per_day"]),
                "line_total_per_day": float(line_total_per_day)
            })

            estimated_total_per_day += line_total_per_day

        if not rental_items:
            all_items = list(items_collection.find({}, {"_id": 0}))
            today = date.today().isoformat()
            return render_template(
                'rent_form.html',
                items=all_items,
                user=session['user'],
                today=today,
                error="Please add valid items."
            )

        rental = {
            "id": "r" + str(uuid.uuid4())[:8],
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "address": address,
            "nic": nic,
            "rent_date": rent_date,
            "return_date": None,
            "status": "Rented",
            "items": rental_items,
            "num_days": 1,
            "total_amount": float(estimated_total_per_day)
        }

        rentals_collection.insert_one(rental)

        for rented_item in rental_items:
            items_collection.update_one(
                {"id": rented_item["item_id"]},
                {"$inc": {"quantity": -rented_item["quantity"]}}
            )

        return redirect(url_for('received_items'))

    all_items = list(items_collection.find({}, {"_id": 0}))
    today = date.today().isoformat()
    return render_template('rent_form.html', items=all_items, user=session['user'], today=today)


@app.route('/received')
@login_required
def received_items():
    rentals_raw = list(rentals_collection.find({}, {"_id": 0}).sort("rent_date", -1))
    rentals = [enrich_rental_for_view(r) for r in rentals_raw]
    return render_template('received.html', rentals=rentals, user=session['user'])


@app.route('/rental/<rental_id>')
@login_required
def rental_detail(rental_id):
    rental = rentals_collection.find_one({"id": rental_id}, {"_id": 0})
    if not rental:
        return redirect(url_for('received_items'))

    rental = enrich_rental_for_view(rental)
    today = date.today().isoformat()
    return render_template('rental_detail.html', rental=rental, user=session['user'], today=today)


@app.route('/rental/<rental_id>/return', methods=['POST'])
@login_required
def mark_returned(rental_id):
    rental = rentals_collection.find_one({"id": rental_id}, {"_id": 0})

    if rental and rental['status'] == 'Rented':
        return_date = request.form.get('return_date', date.today().isoformat())
        number_of_days = calculate_days(rental['rent_date'], return_date)

        new_total_amount = 0
        for rental_item in rental.get("items", []):
            new_total_amount += rental_item['price_per_day'] * rental_item['quantity'] * number_of_days

        rentals_collection.update_one(
            {"id": rental_id},
            {"$set": {
                "return_date": return_date,
                "status": "Returned",
                "num_days": number_of_days,
                "total_amount": float(new_total_amount)
            }}
        )

        for rental_item in rental.get("items", []):
            items_collection.update_one(
                {"id": rental_item['item_id']},
                {"$inc": {"quantity": rental_item['quantity']}}
            )

    return redirect(url_for('rental_detail', rental_id=rental_id))


@app.route('/rental/<rental_id>/invoice')
@login_required
def generate_invoice(rental_id):
    rental = rentals_collection.find_one({"id": rental_id}, {"_id": 0})
    if not rental:
        return redirect(url_for('received_items'))

    rental = enrich_rental_for_view(rental)
    return render_template('invoice.html', rental=rental)


# =========================
# DELETE RENTAL
# =========================
@app.route('/rental/<rental_id>/delete', methods=['POST'])
@login_required
def delete_rental(rental_id):
    rental = rentals_collection.find_one({"id": rental_id}, {"_id": 0})

    if rental:
        # If still rented, restore item quantities back to inventory
        if rental.get('status') == 'Rented':
            for rental_item in rental.get("items", []):
                items_collection.update_one(
                    {"id": rental_item['item_id']},
                    {"$inc": {"quantity": rental_item['quantity']}}
                )
        rentals_collection.delete_one({"id": rental_id})

    return redirect(url_for('received_items'))


# =========================
# HEALTH CHECK
# =========================
@app.route('/health')
def health():
    return {"status": "ok"}, 200


# =========================
# LOCAL RUN
# =========================
if __name__ == '__main__':
    app.run(debug=True)