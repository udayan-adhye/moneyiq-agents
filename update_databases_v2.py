"""
Database Update Script V2 — Calendly Fields
=============================================
Adds Calendly routing form fields to your Contacts database.
Run this ONCE after your databases are already created.

HOW TO RUN:
  python3 update_databases_v2.py
"""

import requests
from config import NOTION_TOKEN, CONTACTS_DB_ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

BASE_URL = "https://api.notion.com/v1"


def add_property_to_database(database_id, db_name, property_name, property_config):
    """Add a single new property to an existing Notion database."""
    url = f"{BASE_URL}/databases/{database_id}"
    payload = {
        "properties": {
            property_name: property_config
        }
    }
    response = requests.patch(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"  ✅ Added '{property_name}' to {db_name}")
    else:
        error_body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        # If property already exists, that's fine
        if "already exists" in str(error_body).lower() or response.status_code == 200:
            print(f"  ⚠️  '{property_name}' may already exist in {db_name} — skipping")
        else:
            print(f"  ❌ Failed to add '{property_name}': {error_body}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Adding Calendly routing form fields to Contacts")
    print("=" * 60)

    calendly_fields = [
        # Contact basics (from Calendly)
        ("WhatsApp Number", {"phone_number": {}}),
        ("Location", {"rich_text": {}}),

        # Lead qualification data
        ("Investing Timeline", {
            "select": {
                "options": [
                    {"name": "Within 15 days", "color": "green"},
                    {"name": "15-30 days", "color": "blue"},
                    {"name": "30-60 days", "color": "yellow"},
                    {"name": "After 2 months", "color": "orange"},
                    {"name": "Just exploring", "color": "gray"}
                ]
            }
        }),
        ("Annual Income", {
            "select": {
                "options": [
                    {"name": "0-15 lakhs", "color": "gray"},
                    {"name": "15-30 lakhs", "color": "blue"},
                    {"name": "32-50 lakhs", "color": "green"},
                    {"name": "50 lakhs - 1 crore", "color": "yellow"},
                    {"name": "1 crore+", "color": "red"}
                ]
            }
        }),
        ("Monthly Surplus", {
            "select": {
                "options": [
                    {"name": "Under ₹25k", "color": "gray"},
                    {"name": "₹25k-50k", "color": "blue"},
                    {"name": "₹50k-1L", "color": "green"},
                    {"name": "₹1L+", "color": "red"}
                ]
            }
        }),
        ("SIP Interest", {
            "select": {
                "options": [
                    {"name": "No SIP", "color": "gray"},
                    {"name": "0-15k", "color": "blue"},
                    {"name": "₹15k-30k", "color": "green"},
                    {"name": "₹30k-60k", "color": "yellow"},
                    {"name": "₹60k-1L", "color": "orange"},
                    {"name": "₹1L+", "color": "red"}
                ]
            }
        }),
        ("Lumpsum Interest", {
            "select": {
                "options": [
                    {"name": "Don't want lumpsum", "color": "gray"},
                    {"name": "0 - 10 lakhs", "color": "blue"},
                    {"name": "15 - 25 lakhs", "color": "green"},
                    {"name": "25 - 50 lakhs", "color": "yellow"},
                    {"name": "50 lakhs+", "color": "red"}
                ]
            }
        }),
        ("Investing Goals", {"rich_text": {}}),
        ("Insurance Status", {
            "select": {
                "options": [
                    {"name": "Private Health Insurance", "color": "green"},
                    {"name": "Term Insurance", "color": "blue"},
                    {"name": "Both", "color": "purple"},
                    {"name": "Neither", "color": "red"}
                ]
            }
        }),

        # Metadata
        ("Calendly Event Type", {"rich_text": {}}),
        ("Booking Date", {"date": {}}),
        ("Lead Source", {"rich_text": {}}),
    ]

    total = len(calendly_fields)
    for i, (field_name, field_config) in enumerate(calendly_fields, 1):
        print(f"\n[{i}/{total}] Adding '{field_name}'...")
        add_property_to_database(CONTACTS_DB_ID, "Contacts", field_name, field_config)

    print("\n" + "=" * 60)
    print("  ✅ Done! Calendly fields added to Contacts database.")
    print("=" * 60)
    print("\n  Your CRM now captures everything from the Calendly routing form.")
    print("  When a new booking comes in, the intake agent will auto-fill all these fields.")
