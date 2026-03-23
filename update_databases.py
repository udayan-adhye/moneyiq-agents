"""
Database Update Script
=======================
Adds new fields to your existing Notion databases:
  - Contacts: "Awaiting From Client" field
  - Tasks: "Task Owner" field (Internal vs Client Action)

Run this ONCE after your databases are already created.

HOW TO RUN:
  python3 update_databases.py
"""

import requests
from config import NOTION_TOKEN, CONTACTS_DB_ID, TASKS_DB_ID

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
        print(f"  ❌ Failed to add '{property_name}' to {db_name}: {response.text}")


if __name__ == "__main__":
    print("=" * 55)
    print("  Updating Notion databases with new fields")
    print("=" * 55)

    # Add "Awaiting From Client" to Contacts
    # This shows what the client needs to submit/do
    print("\n[1/2] Adding 'Awaiting From Client' to Contacts...")
    add_property_to_database(
        CONTACTS_DB_ID,
        "Contacts",
        "Awaiting From Client",
        {"rich_text": {}}
    )

    # Add "Task Owner" to Tasks
    # Internal = for your team | Client Action = client needs to do this
    print("\n[2/2] Adding 'Task Owner' to Tasks...")
    add_property_to_database(
        TASKS_DB_ID,
        "Tasks",
        "Task Owner",
        {
            "select": {
                "options": [
                    {"name": "Internal", "color": "blue"},
                    {"name": "Client Action", "color": "orange"}
                ]
            }
        }
    )

    print("\n" + "=" * 55)
    print("  ✅ Done! New fields added.")
    print("=" * 55)
    print("\n  In Notion, you can now:")
    print("  • Filter Tasks by 'Task Owner = Internal' for your team view")
    print("  • Filter Tasks by 'Task Owner = Client Action' to see what clients owe you")
    print("  • Check 'Awaiting From Client' on any contact to see pending items")
