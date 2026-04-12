"""
Agent 3  - Daily Lead Checker
==============================
Scans your Notion CRM for leads that need attention:
  1. Qualified leads who haven't booked a meeting in X days → drafts reminder email
  2. Clients stuck in a pipeline stage too long → flags for advisor review
  3. Pending tasks that are overdue → sends summary to advisor
  4. Clients who had Meeting 1 but no Meeting 2 booked → nudge email

HOW TO RUN:
  python3 daily_lead_checker.py

REQUIREMENTS:
  pip3 install requests anthropic google-auth google-auth-oauthlib google-api-python-client
"""

import json
from datetime import datetime, date, timedelta
from anthropic import Anthropic

from config import (
    CLAUDE_API_KEY, ADVISORS, DAYS_BEFORE_REMINDER,
    HIGH_VALUE_ALERT_EMAIL
)
from gmail_helpers import save_draft, send_email
from notion_helpers import (
    find_contact_by_email, find_contact_by_name,
    get_contact_field, get_contacts_by_stage,
    update_contact, create_task,
    HEADERS as NOTION_HEADERS, BASE_URL as NOTION_BASE_URL
)
from config import CONTACTS_DB_ID, TASKS_DB_ID, MEETINGS_DB_ID
import requests

client = Anthropic(api_key=CLAUDE_API_KEY)


# ══════════════════════════════════════════════
# HELPER: Query Notion with custom filters
# ══════════════════════════════════════════════

def get_all_active_contacts():
    """Get all contacts NOT in Onboarded or Lost stages."""
    url = f"{NOTION_BASE_URL}/databases/{CONTACTS_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Pipeline Stage", "select": {"does_not_equal": "Onboarded"}},
                {"property": "Pipeline Stage", "select": {"does_not_equal": "Lost"}}
            ]
        }
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        return response.json().get("results", [])
    print(f"  ❌ Failed to query contacts: {response.text}")
    return []


def get_overdue_tasks():
    """Get all tasks that are overdue and not done."""
    today_str = date.today().isoformat()
    url = f"{NOTION_BASE_URL}/databases/{TASKS_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Status", "select": {"does_not_equal": "Done"}},
                {"property": "Due Date", "date": {"before": today_str}}
            ]
        },
        "sorts": [
            {"property": "Due Date", "direction": "ascending"}
        ]
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        return response.json().get("results", [])
    return []


def get_pending_tasks_for_contact(contact_id):
    """Get pending tasks linked to a specific contact."""
    url = f"{NOTION_BASE_URL}/databases/{TASKS_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Status", "select": {"does_not_equal": "Done"}},
                {"property": "Contact", "relation": {"contains": contact_id}}
            ]
        }
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        return response.json().get("results", [])
    return []


def get_task_field(task_page, field_name):
    """Extract a field value from a task page."""
    props = task_page.get("properties", {})
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
    elif field_type == "date":
        d = field.get("date")
        return d["start"] if d else ""
    elif field_type == "relation":
        rels = field.get("relation", [])
        return [r["id"] for r in rels]
    return None


def get_meeting_summaries_for_contact(contact_id):
    """Fetch all meeting summaries linked to a contact from Notion."""
    url = f"{NOTION_BASE_URL}/databases/{MEETINGS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Contact",
            "relation": {"contains": contact_id}
        },
        "sorts": [
            {"property": "Meeting Date", "direction": "descending"}
        ]
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code != 200:
        return []

    meetings = response.json().get("results", [])
    summaries = []
    for m in meetings:
        title = get_task_field(m, "Meeting Title") or ""
        meeting_date = get_task_field(m, "Meeting Date") or ""
        summary = get_task_field(m, "Transcript Summary") or ""
        action_items = get_task_field(m, "Action Items") or ""

        if summary or action_items:
            summaries.append({
                "title": title,
                "date": meeting_date,
                "summary": summary,
                "action_items": action_items
            })

    return summaries


# ══════════════════════════════════════════════
# CHECK 1: Leads needing follow-up
# ══════════════════════════════════════════════

def check_stale_leads(days_threshold=None):
    """
    Find contacts whose last contact date is older than the threshold.
    These are leads going cold  - need a nudge.
    """
    if days_threshold is None:
        days_threshold = DAYS_BEFORE_REMINDER

    cutoff_date = (date.today() - timedelta(days=days_threshold)).isoformat()
    nudge_cooldown = (date.today() - timedelta(days=days_threshold)).isoformat()
    stale_leads = []

    contacts = get_all_active_contacts()
    for contact in contacts:
        last_contact = get_contact_field(contact, "Last Contact Date")
        stage = get_contact_field(contact, "Pipeline Stage")
        name = get_contact_field(contact, "Name")

        # Skip contacts with no last contact date (brand new)
        if not last_contact:
            continue

        # Skip if already nudged within the cooldown period
        last_nudge = get_contact_field(contact, "Last Nudge Date")
        if last_nudge and last_nudge >= nudge_cooldown:
            continue

        # If last contact was before the cutoff, it's stale
        if last_contact < cutoff_date:
            # Pull past meeting summaries for context
            meeting_summaries = get_meeting_summaries_for_contact(contact["id"])

            stale_leads.append({
                "id": contact["id"],
                "name": name,
                "email": get_contact_field(contact, "Email"),
                "phone": get_contact_field(contact, "Phone") or get_contact_field(contact, "WhatsApp Number"),
                "stage": stage,
                "last_contact": last_contact,
                "days_since_contact": (date.today() - date.fromisoformat(last_contact)).days,
                "advisor": get_contact_field(contact, "Assigned Advisor"),
                "awaiting": get_contact_field(contact, "Awaiting From Client"),
                "goals": get_contact_field(contact, "Financial Goals"),
                "meeting_summaries": meeting_summaries
            })

    print(f"  🔍 Found {len(stale_leads)} stale lead(s) (no contact in {days_threshold}+ days)")
    return stale_leads


# ══════════════════════════════════════════════
# CHECK 2: Discovery Call Booked but no show
# ══════════════════════════════════════════════

def check_booked_no_meeting(days_threshold=3):
    """
    Find clients at 'Discovery Call Booked' whose booking date
    was more than X days ago but still haven't moved to Meeting 1 Done.
    Possible no-show or needs rescheduling.
    """
    contacts = get_contacts_by_stage("Discovery Call Booked")
    nudge_cooldown = (date.today() - timedelta(days=days_threshold)).isoformat()
    no_show = []

    for contact in contacts:
        booking_date = get_contact_field(contact, "Booking Date")
        name = get_contact_field(contact, "Name")

        if not booking_date:
            continue

        # Skip if already nudged recently
        last_nudge = get_contact_field(contact, "Last Nudge Date")
        if last_nudge and last_nudge >= nudge_cooldown:
            continue

        days_since = (date.today() - date.fromisoformat(booking_date)).days
        if days_since >= days_threshold:
            no_show.append({
                "id": contact["id"],
                "name": name,
                "email": get_contact_field(contact, "Email"),
                "phone": get_contact_field(contact, "Phone") or get_contact_field(contact, "WhatsApp Number"),
                "days_since_booking": days_since,
                "advisor": get_contact_field(contact, "Assigned Advisor")
            })

    print(f"  🔍 Found {len(no_show)} client(s) booked {days_threshold}+ days ago but no meeting recorded")
    return no_show


# ══════════════════════════════════════════════
# DRAFT NUDGE EMAILS using Claude
# ══════════════════════════════════════════════

def draft_nudge_email(lead_info, nudge_type="follow_up"):
    """Use Claude to draft a warm, personalised nudge email that adds value."""
    advisor_name = lead_info.get("advisor", "Udayan Adhye")
    client_first = lead_info.get("name", "there").split()[0]

    if nudge_type == "no_show":
        context = (
            f"This client booked a discovery call {lead_info.get('days_since_booking', '?')} days ago "
            f"but there's no meeting recorded. They might have missed it or need to reschedule."
        )
        past_calls_context = ""
    else:
        context = (
            f"Last contacted {lead_info.get('days_since_contact', '?')} days ago. "
            f"Current stage: {lead_info.get('stage', 'Unknown')}. "
            f"Financial goals: {lead_info.get('goals', 'financial planning')}. "
            f"Awaiting from client: {lead_info.get('awaiting', 'Nothing specific')}."
        )

        # Build context from past meeting summaries
        past_calls_context = ""
        meeting_summaries = lead_info.get("meeting_summaries", [])
        if meeting_summaries:
            past_calls_context = "\n\nPAST MEETING NOTES (use these to add value in the email):\n"
            for ms in meeting_summaries[:3]:  # max 3 most recent
                past_calls_context += (
                    f"\n--- Meeting on {ms.get('date', 'unknown date')} ---\n"
                    f"Summary: {ms.get('summary', 'No summary')}\n"
                )
                if ms.get("action_items"):
                    past_calls_context += f"Action items: {ms['action_items']}\n"

    prompt = f"""You are drafting a follow-up email for {advisor_name} at MoneyIQ.

CLIENT: {lead_info.get('name', 'Unknown')}
SITUATION: {context}
{past_calls_context}

Draft a SHORT, warm, VALUE-ADDING follow-up email. Rules:
- Start with "Hi {client_first},"
- Keep it to 4-6 sentences MAX
- The email MUST reference something specific from their past conversations, a topic they discussed, a concern they raised, or a goal they mentioned
- Add genuine value: share a quick insight, a useful perspective, or a relevant tip related to what they discussed. Make them think "this person actually remembers my situation and cares"
- End with a soft call to action (suggest a quick call or ask if they have questions)
- Tone should be warm and personal, like a WhatsApp message, NOT corporate
- Sign off as {advisor_name}
- Do NOT use phrases like "I hope this email finds you well", "touching base", or "just checking in"
- Do NOT use exclamation marks excessively
- Do NOT start with "I wanted to follow up", instead lead with the value
- NEVER use the word "advisor" anywhere in the email. Use the person's first name instead.
- NEVER use the phrase "investment advice". Use "financial planning" or "your goals" instead.
- NEVER use em dashes. Use regular dashes (-) or commas instead.

Return ONLY the email body text, nothing else."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"  ❌ Claude API error: {e}")
        return None


# ══════════════════════════════════════════════
# BUILD DAILY REPORT
# ══════════════════════════════════════════════

def build_daily_report(stale_leads, no_shows, overdue_tasks):
    """Build a clean daily summary email for the advisor."""
    report = []
    report.append("DAILY LEAD & TASK REPORT")
    report.append(f"{'='*50}")
    report.append(f"Date: {date.today().strftime('%A, %d %B %Y')}")
    report.append("")

    # Section 1: Overdue Tasks
    if overdue_tasks:
        report.append(f"⚠️  OVERDUE TASKS ({len(overdue_tasks)})")
        report.append(f"{'─'*50}")
        for task in overdue_tasks:
            task_name = get_task_field(task, "Task")
            due = get_task_field(task, "Due Date")
            assigned = get_task_field(task, "Assigned To")
            priority = get_task_field(task, "Priority")
            days_overdue = (date.today() - date.fromisoformat(due)).days if due else "?"
            report.append(f"  • {task_name}")
            report.append(f"    Due: {due} ({days_overdue} days overdue) | Assigned: {assigned} | Priority: {priority}")
        report.append("")

    # Section 2: Stale Leads
    if stale_leads:
        report.append(f"🔔 LEADS GOING COLD ({len(stale_leads)})")
        report.append(f"{'─'*50}")
        for lead in stale_leads:
            report.append(f"  • {lead['name']}  - {lead['stage']}")
            report.append(f"    Last contact: {lead['last_contact']} ({lead['days_since_contact']} days ago)")
            if lead.get("awaiting"):
                report.append(f"    Awaiting: {lead['awaiting']}")
            report.append(f"    Advisor: {lead['advisor']}")
        report.append("")

    # Section 3: Possible No-shows
    if no_shows:
        report.append(f"❓ BOOKED BUT NO MEETING ({len(no_shows)})")
        report.append(f"{'─'*50}")
        for lead in no_shows:
            report.append(f"  • {lead['name']}  - Booked {lead['days_since_booking']} days ago")
            report.append(f"    Advisor: {lead['advisor']}")
        report.append("")

    # Summary
    total_actions = len(stale_leads) + len(no_shows) + len(overdue_tasks)
    if total_actions == 0:
        report.append("✅ All clear! No leads need immediate attention today.")
    else:
        report.append(f"{'─'*50}")
        report.append(f"Total items needing attention: {total_actions}")

    return "\n".join(report)


# ══════════════════════════════════════════════
# MAIN: Run all checks
# ══════════════════════════════════════════════

def run_daily_lead_checker():
    print("\n" + "=" * 60)
    print("  📋 DAILY LEAD CHECKER  - Starting")
    print(f"  Date: {date.today().strftime('%A, %d %B %Y')}")
    print("=" * 60)

    # Run all checks
    print("\n  Running checks...")
    stale_leads = check_stale_leads(days_threshold=DAYS_BEFORE_REMINDER)
    no_shows = check_booked_no_meeting(days_threshold=3)
    overdue_tasks = get_overdue_tasks()

    print(f"\n  📊 SUMMARY")
    print(f"  {'─'*40}")
    print(f"  Stale leads:         {len(stale_leads)}")
    print(f"  Possible no-shows:   {len(no_shows)}")
    print(f"  Overdue tasks:       {len(overdue_tasks)}")

    # Nudge emails DISABLED — follow-ups are now handled by the
    # workflow dashboard + followup_manager sequence system.
    # The daily lead checker only generates the summary report.
    drafts_saved = 0
    print(f"\n  📧 Nudge drafts disabled (handled by workflow dashboard)")

    # Build and send daily report to Udayan
    report = build_daily_report(stale_leads, no_shows, overdue_tasks)

    total_items = len(stale_leads) + len(no_shows) + len(overdue_tasks)

    # Send report to Udayan
    udayan_email = ADVISORS["udayan"]["email"]
    send_email(
        sender=f"MoneyIQ Agent <{udayan_email}>",
        to=udayan_email,
        subject=f"Daily Lead Report  - {total_items} item(s) need attention ({date.today().strftime('%d %b')})",
        body=report
    )

    # Also send to Rishabh if he has stale leads assigned
    rishabh_items = [l for l in stale_leads + no_shows if l.get("advisor") == "Rishabh Mishra"]
    if rishabh_items:
        rishabh_email = ADVISORS["rishabh"]["email"]
        send_email(
            sender=f"MoneyIQ Agent <{rishabh_email}>",
            to=rishabh_email,
            subject=f"Daily Lead Report  - {len(rishabh_items)} item(s) assigned to you ({date.today().strftime('%d %b')})",
            body=report
        )

    print(f"\n{'='*60}")
    print(f"  ✅ Daily Lead Checker complete!")
    print(f"{'='*60}")


# ══════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════
if __name__ == "__main__":
    run_daily_lead_checker()
