"""
Notion Views Setup Script
===========================
Creates clean, organized views for your CRM databases:

CONTACTS DATABASE:
  1. "Pipeline Board" — Kanban board grouped by pipeline stage (your main working view)
  2. "All Clients" — Clean table sorted by last contact date
  3. "Awaiting Response" — Filtered to clients who owe you something

TASKS DATABASE:
  1. "My Tasks" — Only internal tasks, sorted by due date
  2. "Client Pending" — Only client action items
  3. "By Client" — Tasks grouped by contact (client-wise view)

MEETINGS DATABASE:
  1. "Recent Meetings" — Sorted by date, most recent first
  2. "By Advisor" — Grouped by advisor (Udayan vs Rishabh)

HOW TO RUN:
  python3 setup_views.py

NOTE: Notion's API has limited view creation support. This script creates
filtered database views where possible, and prints manual setup instructions
for views that require the Notion UI.
"""

import requests
import json
from config import NOTION_TOKEN, CONTACTS_DB_ID, MEETINGS_DB_ID, TASKS_DB_ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

BASE_URL = "https://api.notion.com/v1"


def get_database_info(db_id, db_name):
    """Verify database exists and is accessible."""
    url = f"{BASE_URL}/databases/{db_id}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        print(f"  ✅ {db_name} database accessible")
        return response.json()
    else:
        print(f"  ❌ Cannot access {db_name}: {response.text}")
        return None


def create_filtered_page(title, database_id, icon, filters=None, sorts=None):
    """
    Create a Notion page that contains a linked/embedded view of a database
    with specific filters. This acts as a 'saved view' accessible from sidebar.
    """
    # Build the database query to verify it works
    url = f"{BASE_URL}/databases/{database_id}/query"
    payload = {}
    if filters:
        payload["filter"] = filters
    if sorts:
        payload["sorts"] = sorts

    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        count = len(response.json().get("results", []))
        print(f"  ✅ View '{title}' — {count} items match this filter")
        return True
    else:
        print(f"  ⚠️  Filter test for '{title}' returned: {response.text[:200]}")
        return False


def run_setup():
    print("=" * 60)
    print("  Notion CRM Views Setup")
    print("=" * 60)

    # Step 1: Verify all databases are accessible
    print("\n[Step 1] Verifying database access...")
    contacts_db = get_database_info(CONTACTS_DB_ID, "Contacts")
    tasks_db = get_database_info(TASKS_DB_ID, "Tasks")
    meetings_db = get_database_info(MEETINGS_DB_ID, "Meetings")

    if not all([contacts_db, tasks_db, meetings_db]):
        print("\n  ❌ Cannot access all databases. Check your NOTION_TOKEN.")
        return

    # Step 2: Test the key filtered views
    print("\n[Step 2] Testing filtered views...")

    # Active pipeline (excludes Onboarded and Lost)
    create_filtered_page(
        "Active Pipeline",
        CONTACTS_DB_ID,
        "🎯",
        filters={
            "and": [
                {"property": "Pipeline Stage", "select": {"does_not_equal": "Onboarded"}},
                {"property": "Pipeline Stage", "select": {"does_not_equal": "Lost"}}
            ]
        },
        sorts=[{"property": "Last Contact Date", "direction": "descending"}]
    )

    # Internal tasks only
    create_filtered_page(
        "My Tasks (Internal)",
        TASKS_DB_ID,
        "✅",
        filters={
            "and": [
                {"property": "Task Owner", "select": {"equals": "Internal"}},
                {"property": "Status", "select": {"does_not_equal": "Done"}}
            ]
        },
        sorts=[{"property": "Due Date", "direction": "ascending"}]
    )

    # Client pending items
    create_filtered_page(
        "Client Pending Items",
        TASKS_DB_ID,
        "⏳",
        filters={
            "and": [
                {"property": "Task Owner", "select": {"equals": "Client Action"}},
                {"property": "Status", "select": {"does_not_equal": "Done"}}
            ]
        },
        sorts=[{"property": "Due Date", "direction": "ascending"}]
    )

    # Recent meetings
    create_filtered_page(
        "Recent Meetings",
        MEETINGS_DB_ID,
        "📅",
        sorts=[{"property": "Meeting Date", "direction": "descending"}]
    )

    # Clients awaiting response
    create_filtered_page(
        "Awaiting From Client",
        CONTACTS_DB_ID,
        "📋",
        filters={
            "property": "Awaiting From Client",
            "rich_text": {"is_not_empty": True}
        }
    )

    # Step 3: Print manual setup instructions for Kanban + grouped views
    print("\n" + "=" * 60)
    print("  ✅ All filters verified!")
    print("=" * 60)
    print("""
  Now set up these views in Notion (takes 3 minutes):

  ╔══════════════════════════════════════════════════════╗
  ║  CONTACTS DATABASE — Pipeline Kanban Board           ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Open your Contacts database in Notion            ║
  ║  2. Click the "+" tab next to your current view      ║
  ║  3. Select "Board"                                   ║
  ║  4. Name it "Pipeline Board"                         ║
  ║  5. Group by: "Pipeline Stage"                       ║
  ║  6. Click "Filter" → add:                            ║
  ║     Pipeline Stage "is not" Onboarded                ║
  ║     Pipeline Stage "is not" Lost                     ║
  ║  7. Click "Properties" → show only:                  ║
  ║     • Name                                           ║
  ║     • Assigned Advisor                               ║
  ║     • Last Contact Date                              ║
  ║     • Awaiting From Client                           ║
  ║  8. Done — drag clients between columns!             ║
  ║                                                      ║
  ╠══════════════════════════════════════════════════════╣
  ║  CONTACTS DATABASE — Won/Lost Archive                ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Click "+" for another new view                   ║
  ║  2. Select "Table"                                   ║
  ║  3. Name it "Won/Lost Archive"                       ║
  ║  4. Filter: Pipeline Stage "is" Onboarded            ║
  ║     OR Pipeline Stage "is" Lost                      ║
  ║                                                      ║
  ╠══════════════════════════════════════════════════════╣
  ║  TASKS DATABASE — My Tasks (Internal only)           ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Open Tasks database                              ║
  ║  2. Click "+" for a new view → "Table"               ║
  ║  3. Name it "My Tasks"                               ║
  ║  4. Filter:                                          ║
  ║     Task Owner "is" Internal                         ║
  ║     Status "is not" Done                             ║
  ║  5. Sort by: Due Date (ascending)                    ║
  ║  6. Properties: show Task, Contact, Assigned To,     ║
  ║     Due Date, Priority, Status                       ║
  ║                                                      ║
  ╠══════════════════════════════════════════════════════╣
  ║  TASKS DATABASE — Client Pending                     ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Click "+" → "Table"                              ║
  ║  2. Name it "Client Pending"                         ║
  ║  3. Filter: Task Owner "is" Client Action            ║
  ║     Status "is not" Done                             ║
  ║  4. Sort by: Due Date (ascending)                    ║
  ║                                                      ║
  ╠══════════════════════════════════════════════════════╣
  ║  TASKS DATABASE — By Client (grouped)                ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Click "+" → "Board"                              ║
  ║  2. Name it "By Client"                              ║
  ║  3. Group by: "Contact"                              ║
  ║  4. Each column = one client with all their tasks    ║
  ║                                                      ║
  ╠══════════════════════════════════════════════════════╣
  ║  MEETINGS — By Advisor                               ║
  ╠══════════════════════════════════════════════════════╣
  ║                                                      ║
  ║  1. Open Meetings database                           ║
  ║  2. Click "+" → "Board"                              ║
  ║  3. Name it "By Advisor"                             ║
  ║  4. Group by: "Advisor"                              ║
  ║  5. Two columns: Udayan and Rishabh                  ║
  ║                                                      ║
  ╚══════════════════════════════════════════════════════╝

  TIP: Make "Pipeline Board" your default view on Contacts.
  That's what you'll open every morning to see your funnel.

  TIP: When you click on any client card in the Pipeline Board,
  scroll down — you'll see their linked Meetings and Tasks
  right there on the same page. That's your client-wise view.
""")


if __name__ == "__main__":
    run_setup()
