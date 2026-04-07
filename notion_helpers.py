"""
Notion Helper Functions
========================
Handles all reading and writing to your Notion CRM databases.
Used by all three agents.
"""

import requests
import json
from datetime import datetime, date
from config import NOTION_TOKEN, CONTACTS_DB_ID, MEETINGS_DB_ID, TASKS_DB_ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

BASE_URL = "https://api.notion.com/v1"


def ensure_contact_fields():
    """One-time setup: ensure new prep-related fields exist on the Contacts DB."""
    new_fields = {
        "Family Details": {"rich_text": {}},
        "Psychological Profile": {"rich_text": {}},
        "Personal Context": {"rich_text": {}},
        "Closing Phrases": {"rich_text": {}},
    }
    url = f"{BASE_URL}/databases/{CONTACTS_DB_ID}"
    resp = requests.patch(url, headers=HEADERS, json={"properties": new_fields})
    if resp.status_code == 200:
        print("  ✅ Notion contact fields ensured (Family/Psych/Context/Closing)")
        return True
    print(f"  ❌ Failed to add fields: {resp.status_code} {resp.text[:200]}")
    return False


# ══════════════════════════════════════════════
# CONTACTS
# ══════════════════════════════════════════════

def find_contact_by_email(email):
    url = f"{BASE_URL}/databases/{CONTACTS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Email",
            "email": {"equals": email}
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        return results[0] if results else None
    return None


def find_contact_by_name(name):
    url = f"{BASE_URL}/databases/{CONTACTS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Name",
            "title": {"contains": name}
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        return results[0] if results else None
    return None


def create_contact(name, email=None, phone=None, lead_source=None,
                   assigned_advisor=None, pipeline_stage="Form Submitted"):
    url = f"{BASE_URL}/pages"
    properties = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Pipeline Stage": {"select": {"name": pipeline_stage}},
        "Meeting Count": {"number": 0},
        "Follow-up Email Number": {"number": 0},
        "Qualified": {"checkbox": False},
        "Insurance Flagged": {"checkbox": False},
        "CA Introduction Needed": {"checkbox": False},
        "CA Introduced": {"checkbox": False},
        "Created Date": {"date": {"start": date.today().isoformat()}}
    }
    if email:
        properties["Email"] = {"email": email}
    if phone:
        properties["Phone"] = {"phone_number": phone}
    if lead_source:
        properties["Lead Source"] = {"rich_text": [{"text": {"content": lead_source}}]}
    if assigned_advisor:
        properties["Assigned Advisor"] = {"select": {"name": assigned_advisor}}

    payload = {
        "parent": {"database_id": CONTACTS_DB_ID},
        "properties": properties
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"  ✅ Contact created: {name}")
        return response.json()
    else:
        print(f"  ❌ Failed to create contact: {response.text}")
        return None


def update_contact(contact_page_id, updates):
    url = f"{BASE_URL}/pages/{contact_page_id}"
    properties = {}

    # Fields that are SELECT type in Notion
    SELECT_FIELDS = [
        "Pipeline Stage", "Assigned Advisor",
        "Investing Timeline", "Annual Income", "Monthly Surplus",
        "SIP Interest", "Lumpsum Interest", "Insurance Status"
    ]

    # Fields that are CHECKBOX type
    CHECKBOX_FIELDS = [
        "Qualified", "Insurance Flagged", "CA Introduction Needed", "CA Introduced"
    ]

    # Fields that are NUMBER type
    NUMBER_FIELDS = [
        "Meeting Count", "Follow-up Email Number", "Investment Amount"
    ]

    # Fields that are DATE type
    DATE_FIELDS = [
        "Last Meeting Date", "Last Contact Date", "Created Date", "Booking Date",
        "Last Nudge Date"
    ]

    # Fields that are RICH_TEXT type
    RICH_TEXT_FIELDS = [
        "Insurance Requirements", "Financial Goals", "Notes",
        "Awaiting From Client", "Location", "Investing Goals",
        "Calendly Event Type", "Lead Source",
        "Family Details", "Psychological Profile", "Personal Context", "Closing Phrases"
    ]

    # Fields that are PHONE_NUMBER type
    PHONE_FIELDS = ["Phone", "WhatsApp Number"]

    for key, value in updates.items():
        if key in SELECT_FIELDS:
            properties[key] = {"select": {"name": value}}
        elif key in CHECKBOX_FIELDS:
            properties[key] = {"checkbox": value}
        elif key in NUMBER_FIELDS:
            properties[key] = {"number": value}
        elif key in DATE_FIELDS:
            properties[key] = {"date": {"start": value}}
        elif key in RICH_TEXT_FIELDS:
            properties[key] = {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
        elif key == "Email":
            properties[key] = {"email": value}
        elif key in PHONE_FIELDS:
            properties[key] = {"phone_number": value}
    payload = {"properties": properties}
    response = requests.patch(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"  ✅ Contact updated")
        return response.json()
    else:
        print(f"  ❌ Failed to update contact: {response.text}")
        return None


def get_contact_field(contact_page, field_name):
    props = contact_page.get("properties", {})
    field = props.get(field_name, {})
    field_type = field.get("type")
    if field_type == "title":
        items = field.get("title", [])
        return items[0]["plain_text"] if items else ""
    elif field_type == "rich_text":
        items = field.get("rich_text", [])
        return items[0]["plain_text"] if items else ""
    elif field_type == "email":
        return field.get("email", "")
    elif field_type == "phone_number":
        return field.get("phone_number", "")
    elif field_type == "select":
        sel = field.get("select")
        return sel["name"] if sel else ""
    elif field_type == "checkbox":
        return field.get("checkbox", False)
    elif field_type == "number":
        return field.get("number", 0)
    elif field_type == "date":
        d = field.get("date")
        return d["start"] if d else ""
    elif field_type == "url":
        return field.get("url", "")
    return None


def get_contacts_by_stage(stage):
    url = f"{BASE_URL}/databases/{CONTACTS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Pipeline Stage",
            "select": {"equals": stage}
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json().get("results", [])
    return []


# ══════════════════════════════════════════════
# MEETINGS
# ══════════════════════════════════════════════

def meeting_already_processed(transcript_id):
    """Check if a meeting with this Fireflies transcript ID already exists in Notion."""
    fireflies_url = f"https://app.fireflies.ai/view/{transcript_id}"
    url = f"{BASE_URL}/databases/{MEETINGS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Fireflies Link",
            "url": {
                "equals": fireflies_url
            }
        },
        "page_size": 1
    }
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        if response.status_code == 200:
            results = response.json().get("results", [])
            return len(results) > 0
    except Exception as e:
        print(f"  ⚠️ Error checking for duplicate meeting: {e}")
    return False


def create_meeting(title, contact_page_id, meeting_date, advisor,
                   meeting_number, fireflies_link=None, summary=None,
                   action_items=None, insurance_flagged=False,
                   ca_intro_flagged=False, quality_score=None):
    url = f"{BASE_URL}/pages"
    properties = {
        "Meeting Title": {"title": [{"text": {"content": title}}]},
        "Contact": {"relation": [{"id": contact_page_id}]},
        "Meeting Date": {"date": {"start": meeting_date}},
        "Advisor": {"select": {"name": advisor}},
        "Meeting Number": {"number": meeting_number},
        "Insurance Flagged": {"checkbox": insurance_flagged},
        "CA Intro Flagged": {"checkbox": ca_intro_flagged},
        "Follow-up Email Drafted": {"checkbox": False}
    }
    if fireflies_link:
        properties["Fireflies Link"] = {"url": fireflies_link}
    if summary:
        properties["Transcript Summary"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}
    if action_items:
        properties["Action Items"] = {"rich_text": [{"text": {"content": action_items[:2000]}}]}
    if quality_score:
        properties["Meeting Quality Score"] = {"select": {"name": quality_score}}

    payload = {
        "parent": {"database_id": MEETINGS_DB_ID},
        "properties": properties
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"  ✅ Meeting created: {title}")
        return response.json()
    else:
        print(f"  ❌ Failed to create meeting: {response.text}")
        return None


# ══════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════

def create_task(task_name, contact_page_id=None, assigned_to="Team",
                due_date=None, priority="Medium", task_type="Other", notes=None,
                task_owner="Internal"):
    """
    Create a task. task_owner can be:
      "Internal" — for your team (shows in your main task view)
      "Client Action" — something the client needs to do (shows on client page only)
    """
    url = f"{BASE_URL}/pages"
    properties = {
        "Task": {"title": [{"text": {"content": task_name}}]},
        "Assigned To": {"select": {"name": assigned_to}},
        "Status": {"select": {"name": "Pending"}},
        "Priority": {"select": {"name": priority}},
        "Task Type": {"select": {"name": task_type}},
        "Task Owner": {"select": {"name": task_owner}}
    }
    if contact_page_id:
        properties["Contact"] = {"relation": [{"id": contact_page_id}]}
    if due_date:
        properties["Due Date"] = {"date": {"start": due_date}}
    if notes:
        properties["Notes"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}

    payload = {
        "parent": {"database_id": TASKS_DB_ID},
        "properties": properties
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"  ✅ Task created: {task_name}")
        return response.json()
    else:
        print(f"  ❌ Failed to create task: {response.text}")
        return None
