"""
Backfill Prep Data
==================
One-time script: for any client who has a meeting scheduled in the next 7 days,
extract Family Details, Psychological Profile, Personal Context, and Closing
Phrases from their stored Notion meeting summaries (no Fireflies refetch).

This populates the new fields so the meeting prep agent has data to work with
on day 1.

USAGE:
  python3 backfill_prep_data.py             → next 7 days
  python3 backfill_prep_data.py --days 14   → next 14 days
"""

import sys
import json
from datetime import datetime, date, timedelta, timezone
from anthropic import Anthropic

from config import CLAUDE_API_KEY, ADVISORS
from calendar_helpers import list_upcoming_events
from notion_helpers import find_contact_by_email, get_contact_field, update_contact
from daily_lead_checker import get_meeting_summaries_for_contact

client = Anthropic(api_key=CLAUDE_API_KEY)
IST = timezone(timedelta(hours=5, minutes=30))


def _is_advisor_email(email):
    return any(adv["email"].lower() == email.lower() for adv in ADVISORS.values())


def extract_profile_from_summaries(client_name, summaries):
    """Use Claude to derive family/psych/context/closing fields from meeting summaries."""
    if not summaries:
        return None

    summaries_text = ""
    for m in summaries[:5]:  # cap at 5 most recent meetings
        summaries_text += (
            f"\n--- {m.get('date', '')} | {m.get('title', '')} ---\n"
            f"Summary: {m.get('summary', '')}\n"
            f"Action items: {m.get('action_items', '')}\n"
        )

    prompt = f"""You are extracting client profile data from prior meeting summaries for {client_name}.

PRIOR MEETINGS:
{summaries_text}

Based ONLY on what is mentioned in these summaries, return a JSON object with these exact keys:

{{
  "family_details": "Names, ages, relationships of spouse/kids/parents/siblings — anything personal mentioned. Empty string if nothing mentioned.",
  "psychological_profile": "A 3-5 sentence read of the client: risk tolerance, decision-making style, anxieties, motivations. Empty string if not enough info.",
  "personal_context": "Hobbies, life events, career, health notes, anything personal not in family details. Empty string if nothing.",
  "closing_phrases": "2-4 specific phrases or framings that could resonate with this client based on their personality. Empty string if not enough info."
}}

Return ONLY valid JSON, no markdown, no code blocks. Be honest — if a field has no data, return empty string.
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"     ❌ Claude extraction failed: {e}")
        return None


def run_backfill(days_ahead=7):
    print("\n" + "=" * 60)
    print(f"  🔄 PREP DATA BACKFILL  - next {days_ahead} day(s)")
    print("=" * 60)

    today = datetime.now(IST).date()
    start_dt = datetime.combine(today, datetime.min.time()).replace(tzinfo=IST)
    end_dt = start_dt + timedelta(days=days_ahead)

    seen_contacts = set()
    backfilled = 0

    for advisor_key, advisor_info in ADVISORS.items():
        advisor_email = advisor_info["email"]
        advisor_name = advisor_info["name"]
        print(f"\n  📅 Scanning {advisor_name}'s calendar...")

        events = list_upcoming_events(advisor_email, start_dt, end_dt)
        print(f"     Found {len(events)} event(s) in next {days_ahead} day(s)")

        for ev in events:
            for attendee_email in ev.get("attendees", []):
                if _is_advisor_email(attendee_email):
                    continue

                contact = find_contact_by_email(attendee_email)
                if not contact:
                    continue

                contact_id = contact["id"]
                if contact_id in seen_contacts:
                    continue
                seen_contacts.add(contact_id)

                meeting_count = get_contact_field(contact, "Meeting Count") or 0
                if int(meeting_count) < 1:
                    continue  # no prior meetings to extract from

                # Skip if profile already populated
                already = (
                    get_contact_field(contact, "Family Details")
                    or get_contact_field(contact, "Psychological Profile")
                )
                if already:
                    print(f"     ⏭️  {get_contact_field(contact, 'Name')} already has profile data")
                    continue

                client_name = get_contact_field(contact, "Name") or attendee_email
                print(f"     ✍️  Backfilling {client_name}...")

                summaries = get_meeting_summaries_for_contact(contact_id)
                if not summaries:
                    print(f"        (no stored summaries — skipping)")
                    continue

                profile = extract_profile_from_summaries(client_name, summaries)
                if not profile:
                    continue

                updates = {}
                if profile.get("family_details"):
                    updates["Family Details"] = profile["family_details"]
                if profile.get("psychological_profile"):
                    updates["Psychological Profile"] = profile["psychological_profile"]
                if profile.get("personal_context"):
                    updates["Personal Context"] = profile["personal_context"]
                if profile.get("closing_phrases"):
                    updates["Closing Phrases"] = profile["closing_phrases"]

                if updates:
                    update_contact(contact_id, updates)
                    print(f"        ✅ Updated {len(updates)} field(s)")
                    backfilled += 1

    print(f"\n  ✅ Backfilled {backfilled} contact(s)")
    print("=" * 60)
    return backfilled


if __name__ == "__main__":
    days = 7
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])
    run_backfill(days)
