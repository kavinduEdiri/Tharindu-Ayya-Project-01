# Sahan Rent a Tool — Web App

A mobile-friendly Flask web application for managing construction tool rentals.

## Features
- 🔐 Login system
- 📊 Dashboard with stats
- 🧰 Equipment Items management (Add / Edit / Delete)
- 📋 New Rental form with auto total calculation
- 📁 Rental records with filter (Active / Returned)
- 🔍 Rental detail view with return date picker
- 🧾 Invoice generation (Print / Save as PDF)

## Setup & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open: http://localhost:5000

## Demo Login
- Email: admin@sahanrent.lk
- Password: admin123

## Tech Stack
- Python Flask (backend)
- Jinja2 templates (HTML)
- Plain CSS (no framework needed)
- Google Fonts + FontAwesome icons
- JSON file for data storage (no database needed)
