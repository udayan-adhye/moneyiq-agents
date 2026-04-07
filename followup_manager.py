"""
Follow-Up Sequence Manager
===========================
Research-backed post-meeting follow-up system.

Based on: Belkins 2025 (16.5M emails), Gong Labs (304K emails),
Growth List 2026, Broadridge Financial Advisor Report 2024.

Key findings applied:
  - 2-3 follow-ups optimal (not 5-12)
  - 3-7-14 day spacing captures ~93% of replies
  - Value-add > "just checking in" (Gong: -20% bookings for generic check-ins)
  - Multi-channel (Email + WhatsApp) outperforms single-channel
  - Sequence auto-pauses on client reply

SEQUENCE:
  Day 0  → Email recap (already built in meeting_processor.py)
  Day 1  → WhatsApp warm check-in + document reminder
  Day 3  → WhatsApp nudge (CONDITIONAL — only if items pending)
  Day 7  → Email value-add touchpoint
  Day 14 → WhatsApp soft re-engagement
"""

import json
import requests
from datetime import date, datetime, timedelta
from urllib.parse import quote

from config import (
    NOTION_TOKEN, FOLLOWUP_DB_ID, FOLLOWUP_SEQUENCE,
    ADVISORS, SERVER_URL, WHATSAPP_API_TOKEN, WHATSAPP_PHONE_ID
)
from gmail_helpers import (
    save_draft, check_for_client_reply, get_email_thread_context
)
from notion_helpers import (
    get_contact_field, update_contact
)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
BASE_URL = "https://api.notion.com/v1"


# ══════════════════════════════════════════════
# CREATE FOLLOW-UP SEQUENCE
# ══════════════════════════════════════════════

def create_followup_sequence(contact_id, contact_name, client_email, client_phone,
                              advisor_name, meeting_id, meeting_date_str,
                              followup_messages):
    """
    Create the full follow-up sequence in Notion after a meeting is processed.
    Called from meeting_processor.py after Day 0 email draft is saved.

    Args:
        contact_id:       Notion page ID of the contact
        contact_name:     "Tanmay Deshmukh"
        client_email:     "tanmay@example.com"
        client_phone:     "+919876543210"
        advisor_name:     "Udayan Adhye"
        meeting_id:       Notion page ID of the meeting record
        meeting_date_str: "2026-04-04" (ISO date)
        followup_messages: List of dicts from Claude with message content per touchpoint
                          [{day: 1, channel: "WhatsApp", message: "...", subject: "..."}, ...]
    """
    meeting_date = date.fromisoformat(meeting_date_str)
    created_count = 0

    for i, touchpoint in enumerate(followup_messages):
        day_num = touchpoint.get("day", FOLLOWUP_SEQUENCE[i]["day"] if i < len(FOLLOWUP_SEQUENCE) else 0)
        channel = touchpoint.get("channel", "WhatsApp")
        message = touchpoint.get("message", "")
        subject = touchpoint.get("subject", "")
        touchpoint_type = touchpoint.get("type", "")

        scheduled_date = meeting_date + timedelta(days=day_num)

        # Generate wa.me link for WhatsApp messages
        wa_link = None
        if channel == "WhatsApp" and client_phone:
            # Clean phone number: remove spaces, dashes, keep + and digits
            clean_phone = "".join(c for c in client_phone if c.isdigit() or c == "+")
            if clean_phone.startswith("+"):
                clean_phone = clean_phone[1:]  # wa.me doesn't want the +
            wa_link = f"https://wa.me/{clean_phone}?text={quote(message)}"

        # Create touchpoint label
        type_labels = {
            "warm_checkin": "Warm Check-In",
            "action_nudge": "Action Item Nudge",
            "value_add": "Value-Add Insight",
            "soft_reengage": "Soft Re-Engagement",
        }
        label = f"Day {day_num} — {type_labels.get(touchpoint_type, touchpoint_type)}"

        # Create the Notion record
        properties = {
            "Touchpoint": {"title": [{"text": {"content": label}}]},
            "Advisor": {"select": {"name": advisor_name}},
            "Channel": {"select": {"name": channel}},
            "Day Number": {"number": day_num},
            "Sequence Number": {"number": i + 1},
            "Scheduled Date": {"date": {"start": scheduled_date.isoformat()}},
            "Message Content": {"rich_text": [{"text": {"content": message[:2000]}}]},
            "Status": {"select": {"name": "Pending"}},
            "Client Replied": {"checkbox": False},
            "Email Opened": {"checkbox": False},
            "Client Email": {"email": client_email} if client_email else {"email": ""},
            "Client Phone": {"phone_number": client_phone} if client_phone else {"phone_number": ""},
            "Client Name": {"rich_text": [{"text": {"content": contact_name}}]},
            "Contact ID": {"rich_text": [{"text": {"content": contact_id}}]},
            "Meeting ID": {"rich_text": [{"text": {"content": meeting_id}}]},
        }

        if wa_link:
            properties["WhatsApp Link"] = {"url": wa_link}
        if subject:
            properties["Email Subject"] = {"rich_text": [{"text": {"content": subject}}]}

        payload = {
            "parent": {"database_id": FOLLOWUP_DB_ID},
            "properties": properties
        }

        try:
            response = requests.post(f"{BASE_URL}/pages", headers=HEADERS, json=payload)
            if response.status_code == 200:
                created_count += 1
            else:
                print(f"  ❌ Failed to create touchpoint {label}: {response.text[:200]}")
        except Exception as e:
            print(f"  ❌ Error creating touchpoint {label}: {e}")

    print(f"  ✅ Follow-up sequence created: {created_count} touchpoints for {contact_name}")
    return created_count


# ══════════════════════════════════════════════
# DAILY FOLLOW-UP CHECKER
# ══════════════════════════════════════════════

def get_todays_followups(advisor_name=None):
    """
    Query Notion for all follow-up touchpoints scheduled for today (or overdue).
    Optionally filter by advisor.

    Returns list of Notion page objects.
    """
    today = date.today().isoformat()

    # Get all Pending touchpoints where Scheduled Date <= today
    filter_conditions = [
        {
            "property": "Status",
            "select": {"equals": "Pending"}
        },
        {
            "property": "Scheduled Date",
            "date": {"on_or_before": today}
        }
    ]

    if advisor_name:
        filter_conditions.append({
            "property": "Advisor",
            "select": {"equals": advisor_name}
        })

    payload = {
        "filter": {"and": filter_conditions},
        "sorts": [
            {"property": "Scheduled Date", "direction": "ascending"},
            {"property": "Sequence Number", "direction": "ascending"}
        ]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/databases/{FOLLOWUP_DB_ID}/query",
            headers=HEADERS, json=payload
        )
        if response.status_code == 200:
            results = response.json().get("results", [])
            return results
        else:
            print(f"  ❌ Error querying follow-ups: {response.text[:200]}")
            return []
    except Exception as e:
        print(f"  ❌ Error querying follow-ups: {e}")
        return []


def get_followup_field(page, field_name):
    """Extract a field value from a follow-up Notion page."""
    props = page.get("properties", {})
    field = props.get(field_name, {})
    field_type = field.get("type")

    if field_type == "title":
        items = field.get("title", [])
        return items[0]["plain_text"] if items else ""
    elif field_type == "rich_text":
        items = field.get("rich_text", [])
        return items[0]["plain_text"] if items else ""
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
    elif field_type == "email":
        return field.get("email", "")
    elif field_type == "phone_number":
        return field.get("phone_number", "")
    elif field_type == "url":
        return field.get("url", "")
    return None


def update_followup_status(page_id, status, skip_reason=None, sent_date=None):
    """Update a follow-up touchpoint's status in Notion."""
    properties = {
        "Status": {"select": {"name": status}}
    }
    if skip_reason:
        properties["Skip Reason"] = {"rich_text": [{"text": {"content": skip_reason}}]}
    if sent_date:
        properties["Sent Date"] = {"date": {"start": sent_date}}

    payload = {"properties": properties}
    try:
        response = requests.patch(
            f"{BASE_URL}/pages/{page_id}",
            headers=HEADERS, json=payload
        )
        return response.status_code == 200
    except Exception as e:
        print(f"  ❌ Error updating follow-up: {e}")
        return False


def mark_email_opened(page_id):
    """Mark a follow-up as email opened (called by tracking pixel endpoint)."""
    payload = {
        "properties": {
            "Email Opened": {"checkbox": True}
        }
    }
    try:
        requests.patch(f"{BASE_URL}/pages/{page_id}", headers=HEADERS, json=payload)
    except Exception:
        pass


# ══════════════════════════════════════════════
# SMART PAUSE/SKIP LOGIC
# ══════════════════════════════════════════════

def should_skip_touchpoint(touchpoint_page, advisor_email=None):
    """
    Check if a touchpoint should be skipped based on smart rules.

    Returns: (should_skip: bool, reason: str)
    """
    client_email = get_followup_field(touchpoint_page, "Client Email")
    contact_id = get_followup_field(touchpoint_page, "Contact ID")
    scheduled_date = get_followup_field(touchpoint_page, "Scheduled Date")
    channel = get_followup_field(touchpoint_page, "Channel")
    sequence_num = get_followup_field(touchpoint_page, "Sequence Number") or 0
    touchpoint_name = get_followup_field(touchpoint_page, "Touchpoint") or ""

    # Rule 1: Check if client replied via email
    if client_email and advisor_email:
        reply_check = check_for_client_reply(
            client_email,
            since_date=scheduled_date or date.today().isoformat(),
            advisor_email=advisor_email
        )
        if reply_check.get("replied"):
            return True, f"Client replied via email: {reply_check.get('snippet', '')[:100]}"

    # Rule 2: Check Notion contact status
    if contact_id:
        try:
            response = requests.get(
                f"{BASE_URL}/pages/{contact_id}",
                headers=HEADERS
            )
            if response.status_code == 200:
                contact = response.json()
                pipeline_stage = get_contact_field(contact, "Pipeline Stage")
                awaiting = get_contact_field(contact, "Awaiting From Client")

                # If client is Onboarded or Lost, cancel sequence
                if pipeline_stage in ["Onboarded", "Lost"]:
                    return True, f"Contact is {pipeline_stage} — sequence cancelled"

                # If this is the Day 3 "action nudge" and nothing is pending, skip
                if "action_nudge" in touchpoint_name.lower() or "nudge" in touchpoint_name.lower():
                    if not awaiting or awaiting.strip() == "":
                        return True, "No pending items from client — nudge not needed"

                # If a new meeting was booked (meeting count increased), pause
                # This is checked by comparing Last Meeting Date to scheduled date
                last_meeting = get_contact_field(contact, "Last Meeting Date")
                if last_meeting and scheduled_date:
                    if last_meeting > scheduled_date:
                        return True, f"New meeting happened on {last_meeting} — sequence paused"

        except Exception as e:
            print(f"  ⚠️ Error checking contact status: {e}")

    return False, ""


# ══════════════════════════════════════════════
# PAUSE ALL REMAINING TOUCHPOINTS FOR A CONTACT
# ══════════════════════════════════════════════

def pause_sequence_for_contact(contact_id, reason="Client replied"):
    """Pause all pending follow-ups for a specific contact."""
    payload = {
        "filter": {
            "and": [
                {"property": "Contact ID", "rich_text": {"equals": contact_id}},
                {"property": "Status", "select": {"equals": "Pending"}}
            ]
        }
    }

    try:
        response = requests.post(
            f"{BASE_URL}/databases/{FOLLOWUP_DB_ID}/query",
            headers=HEADERS, json=payload
        )
        if response.status_code == 200:
            results = response.json().get("results", [])
            for page in results:
                update_followup_status(page["id"], "Paused", skip_reason=reason)
            if results:
                print(f"  ⏸️ Paused {len(results)} follow-ups for contact: {reason}")
            return len(results)
    except Exception as e:
        print(f"  ❌ Error pausing sequence: {e}")
    return 0


# ══════════════════════════════════════════════
# PROCESS TODAY'S FOLLOW-UPS
# ══════════════════════════════════════════════

def process_due_followups():
    """
    Main daily job: check all due follow-ups, apply smart rules,
    and mark them as Ready for the dashboard.

    Called by the scheduler at 9 AM IST.
    """
    print(f"\n{'='*60}")
    print(f"  📋 FOLLOW-UP PROCESSOR — Checking due touchpoints")
    print(f"  Date: {date.today().isoformat()}")
    print(f"{'='*60}")

    followups = get_todays_followups()
    if not followups:
        print(f"  No follow-ups due today.")
        return {"ready": 0, "skipped": 0, "paused": 0}

    print(f"  Found {len(followups)} follow-up(s) due today")

    stats = {"ready": 0, "skipped": 0, "paused": 0}

    for fp in followups:
        page_id = fp["id"]
        touchpoint = get_followup_field(fp, "Touchpoint")
        client_name = get_followup_field(fp, "Client Name")
        advisor = get_followup_field(fp, "Advisor")
        channel = get_followup_field(fp, "Channel")

        print(f"\n  Checking: {touchpoint} — {client_name} ({channel})")

        # Determine advisor email for Gmail checks
        advisor_email = None
        for key, info in ADVISORS.items():
            if info["name"] == advisor:
                advisor_email = info["email"]
                break

        # Apply smart skip/pause rules
        should_skip, reason = should_skip_touchpoint(fp, advisor_email)

        if should_skip:
            # If client replied, pause ALL remaining touchpoints for this contact
            if "replied" in reason.lower() or "meeting" in reason.lower():
                contact_id = get_followup_field(fp, "Contact ID")
                if contact_id:
                    pause_sequence_for_contact(contact_id, reason)
                    stats["paused"] += 1
            else:
                update_followup_status(page_id, "Skipped", skip_reason=reason)
                stats["skipped"] += 1
            print(f"    → Skipped: {reason}")
            continue

        # Mark as Ready — will appear on advisor dashboard
        update_followup_status(page_id, "Ready")
        stats["ready"] += 1
        print(f"    → Marked as Ready for {advisor}")

        # For email touchpoints, also create a Gmail draft
        if channel == "Email":
            client_email = get_followup_field(fp, "Client Email")
            subject = get_followup_field(fp, "Email Subject")
            message = get_followup_field(fp, "Message Content")

            if client_email and advisor_email and message:
                # Add tracking pixel to the email
                tracking_url = f"{SERVER_URL}/track/open/{page_id}.png"
                body_with_tracking = message + f'\n\n<img src="{tracking_url}" width="1" height="1" style="display:none" />'

                sender = f"{advisor} <{advisor_email}>"
                save_draft(
                    sender=sender,
                    to=client_email,
                    subject=subject or f"Quick update — {advisor.split()[0] if advisor else 'MoneyIQ'}",
                    body=body_with_tracking,
                    advisor_email=advisor_email
                )
                print(f"    → Gmail draft created for {client_email}")

    print(f"\n  📊 Summary: {stats['ready']} ready, {stats['skipped']} skipped, {stats['paused']} paused")
    return stats


# ══════════════════════════════════════════════
# DASHBOARD DATA
# ══════════════════════════════════════════════

def get_dashboard_followups(advisor_name=None):
    """
    Get all Ready follow-ups for the advisor dashboard.
    Returns structured data for rendering.
    """
    filter_conditions = [
        {"property": "Status", "select": {"equals": "Ready"}}
    ]

    if advisor_name:
        filter_conditions.append({
            "property": "Advisor",
            "select": {"equals": advisor_name}
        })

    payload = {
        "filter": {"and": filter_conditions},
        "sorts": [
            {"property": "Scheduled Date", "direction": "ascending"},
            {"property": "Sequence Number", "direction": "ascending"}
        ]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/databases/{FOLLOWUP_DB_ID}/query",
            headers=HEADERS, json=payload
        )
        if response.status_code != 200:
            return []

        results = response.json().get("results", [])
        dashboard_items = []

        for fp in results:
            dashboard_items.append({
                "id": fp["id"],
                "touchpoint": get_followup_field(fp, "Touchpoint"),
                "client_name": get_followup_field(fp, "Client Name"),
                "channel": get_followup_field(fp, "Channel"),
                "message": get_followup_field(fp, "Message Content"),
                "whatsapp_link": get_followup_field(fp, "WhatsApp Link"),
                "email_subject": get_followup_field(fp, "Email Subject"),
                "client_email": get_followup_field(fp, "Client Email"),
                "scheduled_date": get_followup_field(fp, "Scheduled Date"),
                "advisor": get_followup_field(fp, "Advisor"),
                "sequence_num": get_followup_field(fp, "Sequence Number"),
                "contact_id": get_followup_field(fp, "Contact ID"),
            })

        return dashboard_items

    except Exception as e:
        print(f"  ❌ Error getting dashboard data: {e}")
        return []


def mark_as_sent(page_id):
    """Mark a follow-up as sent (called from dashboard when advisor clicks Send)."""
    return update_followup_status(
        page_id,
        status="Sent",
        sent_date=date.today().isoformat()
    )


# ══════════════════════════════════════════════
# WHATSAPP CLOUD API (Meta Direct)
# ══════════════════════════════════════════════

def send_whatsapp_message(phone_number, message_text):
    """
    Send a WhatsApp message via Meta's Cloud API.
    Falls back to wa.me link if API not configured.

    NOTE: This requires:
    1. Meta Business Account
    2. WhatsApp Business API access
    3. WHATSAPP_API_TOKEN and WHATSAPP_PHONE_ID env vars

    Returns: {sent: bool, method: 'api'|'link', link: str}
    """
    # Clean phone number
    clean_phone = "".join(c for c in phone_number if c.isdigit())
    if not clean_phone.startswith("91"):
        clean_phone = "91" + clean_phone

    # Always generate wa.me link as fallback
    wa_link = f"https://wa.me/{clean_phone}?text={quote(message_text)}"

    # Try Meta Cloud API if configured
    if WHATSAPP_API_TOKEN and WHATSAPP_PHONE_ID:
        try:
            url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"
            headers = {
                "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_phone,
                "type": "text",
                "text": {"body": message_text}
            }
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"  ✅ WhatsApp sent via API to {phone_number}")
                return {"sent": True, "method": "api", "link": wa_link}
            else:
                print(f"  ⚠️ WhatsApp API error: {response.text[:200]}")
        except Exception as e:
            print(f"  ⚠️ WhatsApp API error: {e}")

    # Fallback: return wa.me link for manual send
    return {"sent": False, "method": "link", "link": wa_link}
