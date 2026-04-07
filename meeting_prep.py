"""
Meeting Prep Agent
==================
Every morning at 7 AM IST, scans each advisor's Google Calendar for today's
meetings. For any meeting where the attendee is an existing client with
Meeting Count >= 1 (i.e. NOT a brand-new first Calendly meeting), generates
a prep document and emails it to the advisor.

The prep doc pulls pre-extracted Family Details, Psychological Profile,
Personal Context, and Closing Phrases from the Notion contact (extracted
during prior meeting processing — no transcript replay needed).

HOW TO RUN:
  python3 meeting_prep.py             → run for today
  python3 meeting_prep.py --tomorrow  → run for tomorrow's meetings
"""

import sys
import json
from datetime import datetime, date, timedelta, timezone
from anthropic import Anthropic

from config import CLAUDE_API_KEY, ADVISORS
from calendar_helpers import list_upcoming_events
from gmail_helpers import send_email
from notion_helpers import find_contact_by_email, get_contact_field
from daily_lead_checker import get_meeting_summaries_for_contact

client = Anthropic(api_key=CLAUDE_API_KEY)

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_day_window(target_date):
    """Return (start_dt, end_dt) covering the full day in IST."""
    start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=IST)
    end = start + timedelta(days=1)
    return start, end


def _is_advisor_email(email):
    return any(adv["email"].lower() == email.lower() for adv in ADVISORS.values())


def _resolve_client_contact(attendee_emails):
    """Find the first non-advisor attendee that maps to a Notion contact."""
    for email in attendee_emails:
        if _is_advisor_email(email):
            continue
        contact = find_contact_by_email(email)
        if contact:
            return contact, email
    return None, None


def generate_prep_doc(contact, advisor_name, meeting_event):
    """Use Claude to synthesize a prep doc from stored CRM data."""
    name = get_contact_field(contact, "Name") or "Client"
    family = get_contact_field(contact, "Family Details") or ""
    psych = get_contact_field(contact, "Psychological Profile") or ""
    personal = get_contact_field(contact, "Personal Context") or ""
    closing = get_contact_field(contact, "Closing Phrases") or ""
    goals = get_contact_field(contact, "Financial Goals") or ""
    insurance_flagged = get_contact_field(contact, "Insurance Flagged")
    insurance_req = get_contact_field(contact, "Insurance Requirements") or ""
    awaiting = get_contact_field(contact, "Awaiting From Client") or ""
    investment_amount = get_contact_field(contact, "Investment Amount") or 0
    sip_interest = get_contact_field(contact, "SIP Interest") or ""
    lumpsum_interest = get_contact_field(contact, "Lumpsum Interest") or ""
    annual_income = get_contact_field(contact, "Annual Income") or ""
    meeting_count = get_contact_field(contact, "Meeting Count") or 0

    # Pull last meeting summary + action items
    summaries = get_meeting_summaries_for_contact(contact["id"])
    last_meeting = summaries[0] if summaries else {}
    prior_meetings_block = ""
    for m in summaries[:3]:
        prior_meetings_block += (
            f"\n--- {m.get('date', '')} | {m.get('title', '')} ---\n"
            f"Summary: {m.get('summary', '')}\n"
            f"Action items: {m.get('action_items', '')}\n"
        )

    prompt = f"""You are preparing {advisor_name} for an upcoming wealth management meeting with a returning client.

CLIENT: {name}
Meeting #{int(meeting_count) + 1} (they have had {int(meeting_count)} meeting(s) with us before)

UPCOMING MEETING:
Title: {meeting_event.get('summary', '')}
Time: {meeting_event.get('start', '')}

STORED CLIENT PROFILE (from prior meetings):
Family Details: {family or '(none)'}
Psychological Profile: {psych or '(none)'}
Personal Context: {personal or '(none)'}
Closing Phrases that resonate: {closing or '(none)'}

FINANCIAL CONTEXT:
Goals: {goals or '(none)'}
Annual Income bracket: {annual_income or '(unknown)'}
SIP Interest: {sip_interest or '(unknown)'}
Lumpsum Interest: {lumpsum_interest or '(unknown)'}
Investment amount discussed: ₹{investment_amount}
Insurance flagged: {'Yes' if insurance_flagged else 'No'}
Insurance details: {insurance_req or '(none)'}
Currently awaiting from client: {awaiting or '(nothing)'}

PRIOR MEETING HISTORY (most recent first):
{prior_meetings_block or '(no prior summaries)'}

Generate a CONCISE meeting prep document for {advisor_name}. Use this exact structure:

1. CLIENT SNAPSHOT (3-4 lines): Who they are, family, what matters most to them.

2. WHAT WAS DISCUSSED LAST TIME: Key topics from the most recent meeting.

3. ACTION ITEMS FROM LAST MEETING: What was promised/pending. Flag anything overdue.

4. PRIMARY OBJECTIVES: What this client is fundamentally trying to achieve (retirement, kids' education, etc).

5. PSYCHOLOGICAL READ: How to approach them today — communication style, what to avoid, what builds trust.

6. INSURANCE & PROTECTION STATUS: Whether they have term/health insurance, gaps to address.

7. AGENDA FOR TODAY'S MEETING: 3-5 specific things to discuss in this call.

8. CLOSING PHRASES TO USE: 2-3 specific phrases tailored to this client's personality that could help move them toward a decision.

9. OPEN ITEMS / DOCS PENDING: What you are still waiting on from them.

Keep it tight — this is a morning brief, not a report. Use bullet points where natural. No fluff.
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"  ❌ Claude prep doc failed: {e}")
        return None


def run_meeting_prep(target_date=None):
    if target_date is None:
        target_date = datetime.now(IST).date()

    print("\n" + "=" * 60)
    print("  📋 MEETING PREP AGENT  - Starting")
    print(f"  Date: {target_date.strftime('%A, %d %B %Y')}")
    print("=" * 60)

    start_dt, end_dt = _ist_day_window(target_date)

    prep_count = 0

    for advisor_key, advisor_info in ADVISORS.items():
        advisor_email = advisor_info["email"]
        advisor_name = advisor_info["name"]
        print(f"\n  📅 Checking calendar for {advisor_name}...")

        events = list_upcoming_events(advisor_email, start_dt, end_dt)
        print(f"     Found {len(events)} event(s)")

        for ev in events:
            attendees = ev.get("attendees", [])
            if not attendees:
                continue

            contact, client_email = _resolve_client_contact(attendees)
            if not contact:
                continue

            meeting_count = get_contact_field(contact, "Meeting Count") or 0
            if int(meeting_count) < 1:
                # First-time meeting (Calendly intake) — skip per requirements
                print(f"     ⏭️  Skipping {client_email} — first meeting (no prep needed)")
                continue

            client_name = get_contact_field(contact, "Name") or client_email
            print(f"     ✍️  Generating prep doc for {client_name}...")

            prep_doc = generate_prep_doc(contact, advisor_name, ev)
            if not prep_doc:
                continue

            # Format start time for the email subject
            start_str = ev.get("start", "")
            try:
                start_obj = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                start_obj = start_obj.astimezone(IST)
                time_str = start_obj.strftime("%I:%M %p IST")
            except Exception:
                time_str = ""

            subject = f"Meeting Prep: {client_name} ({time_str})" if time_str else f"Meeting Prep: {client_name}"

            body = (
                f"MEETING PREP\n"
                f"{'=' * 50}\n"
                f"Client: {client_name}\n"
                f"Meeting: {ev.get('summary', '')}\n"
                f"Time: {start_str}\n"
                f"{'=' * 50}\n\n"
                f"{prep_doc}\n\n"
                f"{'─' * 50}\n"
                f"Calendar link: {ev.get('html_link', '')}\n"
                f"— MoneyIQ Meeting Prep Agent"
            )

            send_email(
                sender=f"MoneyIQ Agent <{advisor_email}>",
                to=advisor_email,
                subject=subject,
                body=body
            )
            prep_count += 1

    print(f"\n  ✅ Generated {prep_count} prep doc(s)")
    print("=" * 60)
    return prep_count


if __name__ == "__main__":
    target = datetime.now(IST).date()
    if "--tomorrow" in sys.argv:
        target = target + timedelta(days=1)
    elif "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            target = target + timedelta(days=int(sys.argv[idx + 1]))
    run_meeting_prep(target)
