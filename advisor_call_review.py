"""
Advisor Call Review  - Weekly Performance Report
=================================================
Pulls all meetings from Notion, analyzes quality scores and patterns,
and generates a report for each advisor + an overall team report.

HOW TO RUN:
  python3 advisor_call_review.py              → last 7 days
  python3 advisor_call_review.py --days 30    → last 30 days

REQUIREMENTS:
  pip3 install requests anthropic google-auth google-auth-oauthlib google-api-python-client
"""

import sys
import json
import requests
from datetime import datetime, date, timedelta
from anthropic import Anthropic

from config import (
    CLAUDE_API_KEY, ADVISORS, HIGH_VALUE_ALERT_EMAIL
)
from gmail_helpers import send_email
from notion_helpers import (
    HEADERS as NOTION_HEADERS, BASE_URL as NOTION_BASE_URL,
    MEETINGS_DB_ID, CONTACTS_DB_ID,
    get_contact_field
)

client = Anthropic(api_key=CLAUDE_API_KEY)


# ══════════════════════════════════════════════
# FETCH MEETINGS FROM NOTION
# ══════════════════════════════════════════════

def get_meeting_field(page, field_name):
    """Extract a field value from a meeting page."""
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
    elif field_type == "url":
        return field.get("url", "")
    elif field_type == "relation":
        rels = field.get("relation", [])
        return [r["id"] for r in rels]
    return None


def get_recent_meetings(days_back=7):
    """Fetch meetings from Notion within the given date range."""
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    url = f"{NOTION_BASE_URL}/databases/{MEETINGS_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Meeting Date",
            "date": {"on_or_after": cutoff}
        },
        "sorts": [
            {"property": "Meeting Date", "direction": "descending"}
        ]
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        print(f"  📋 Found {len(results)} meeting(s) in the last {days_back} days")
        return results
    print(f"  ❌ Failed to fetch meetings: {response.text}")
    return []


def get_contact_name(contact_id):
    """Fetch a contact's name by their page ID."""
    url = f"{NOTION_BASE_URL}/pages/{contact_id}"
    response = requests.get(url, headers=NOTION_HEADERS)
    if response.status_code == 200:
        page = response.json()
        return get_contact_field(page, "Name")
    return "Unknown"


# ══════════════════════════════════════════════
# ANALYZE AND BUILD REPORT
# ══════════════════════════════════════════════

def parse_meetings(meetings):
    """Parse meeting pages into a structured list."""
    parsed = []
    for m in meetings:
        title = get_meeting_field(m, "Meeting Title")
        advisor = get_meeting_field(m, "Advisor")
        meeting_date = get_meeting_field(m, "Meeting Date")
        meeting_number = get_meeting_field(m, "Meeting Number")
        quality_score = get_meeting_field(m, "Meeting Quality Score")
        summary = get_meeting_field(m, "Transcript Summary")
        action_items = get_meeting_field(m, "Action Items")
        insurance = get_meeting_field(m, "Insurance Flagged")
        ca_intro = get_meeting_field(m, "CA Intro Flagged")
        fireflies_link = get_meeting_field(m, "Fireflies Link")
        contact_ids = get_meeting_field(m, "Contact")

        # Get client name
        client_name = "Unknown"
        if contact_ids and isinstance(contact_ids, list) and len(contact_ids) > 0:
            client_name = get_contact_name(contact_ids[0])

        parsed.append({
            "title": title,
            "advisor": advisor,
            "date": meeting_date,
            "meeting_number": meeting_number,
            "quality_score": quality_score,
            "summary": summary,
            "action_items": action_items,
            "insurance_flagged": insurance,
            "ca_intro_flagged": ca_intro,
            "fireflies_link": fireflies_link,
            "client_name": client_name
        })

    return parsed


def build_advisor_stats(parsed_meetings):
    """Build per-advisor statistics."""
    stats = {}

    for m in parsed_meetings:
        advisor = m.get("advisor", "Unknown")
        if advisor not in stats:
            stats[advisor] = {
                "total_meetings": 0,
                "meetings": [],
                "quality_scores": [],
                "insurance_flags": 0,
                "ca_intro_flags": 0,
                "first_meetings": 0,
                "follow_up_meetings": 0
            }

        stats[advisor]["total_meetings"] += 1
        stats[advisor]["meetings"].append(m)

        # Parse quality score
        qs = m.get("quality_score", "")
        if qs:
            score_map = {"Excellent": 9, "Good": 7, "Needs Improvement": 4}
            if qs in score_map:
                stats[advisor]["quality_scores"].append(score_map[qs])

        if m.get("insurance_flagged"):
            stats[advisor]["insurance_flags"] += 1
        if m.get("ca_intro_flagged"):
            stats[advisor]["ca_intro_flags"] += 1

        mn = m.get("meeting_number", 1)
        if mn and mn == 1:
            stats[advisor]["first_meetings"] += 1
        elif mn and mn > 1:
            stats[advisor]["follow_up_meetings"] += 1

    return stats


def generate_coaching_summary(advisor_name, meetings_data):
    """Use Claude to generate a coaching summary for an advisor."""
    meetings_text = ""
    for m in meetings_data:
        meetings_text += (
            f"\n--- Meeting: {m.get('title', 'Unknown')} ---\n"
            f"Client: {m.get('client_name', 'Unknown')}\n"
            f"Date: {m.get('date', 'Unknown')}\n"
            f"Quality: {m.get('quality_score', 'Not scored')}\n"
            f"Summary: {m.get('summary', 'No summary')}\n"
        )

    prompt = f"""You are a senior wealth management trainer reviewing {advisor_name}'s meetings this week.

Here are the meetings:
{meetings_text}

Write a SHORT coaching summary (5-8 sentences max). Include:
1. Overall performance trend (improving, consistent, declining)
2. One specific strength you noticed across meetings
3. One specific area for improvement
4. A concrete tip for next week

Keep it encouraging but honest. Write in second person ("You did well at...").
Return ONLY the coaching text, nothing else."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"  ❌ Claude API error: {e}")
        return "Could not generate coaching summary."


# ══════════════════════════════════════════════
# BUILD THE REPORT
# ══════════════════════════════════════════════

def build_call_review_report(parsed_meetings, advisor_stats, days_back, coaching_notes):
    """Build a clean text report."""
    report = []
    report.append("ADVISOR CALL REVIEW REPORT")
    report.append(f"{'='*55}")
    report.append(f"Period: Last {days_back} days ({(date.today() - timedelta(days=days_back)).strftime('%d %b')}  - {date.today().strftime('%d %b %Y')})")
    report.append(f"Total meetings: {len(parsed_meetings)}")
    report.append("")

    # Team overview
    report.append("TEAM OVERVIEW")
    report.append(f"{'─'*55}")
    total_insurance = sum(s["insurance_flags"] for s in advisor_stats.values())
    total_ca = sum(s["ca_intro_flags"] for s in advisor_stats.values())
    total_first = sum(s["first_meetings"] for s in advisor_stats.values())
    total_followup = sum(s["follow_up_meetings"] for s in advisor_stats.values())

    report.append(f"  First meetings (discovery):  {total_first}")
    report.append(f"  Follow-up meetings:          {total_followup}")
    report.append(f"  Insurance referrals:         {total_insurance}")
    report.append(f"  CA introductions:            {total_ca}")
    report.append("")

    # Per-advisor breakdown
    for advisor, stats in advisor_stats.items():
        report.append(f"{'='*55}")
        report.append(f"ADVISOR: {advisor}")
        report.append(f"{'='*55}")
        report.append(f"  Meetings this period:   {stats['total_meetings']}")
        report.append(f"  First meetings:         {stats['first_meetings']}")
        report.append(f"  Follow-ups:             {stats['follow_up_meetings']}")

        if stats["quality_scores"]:
            avg_score = sum(stats["quality_scores"]) / len(stats["quality_scores"])
            report.append(f"  Avg quality score:      {avg_score:.1f}/10")
        else:
            report.append(f"  Avg quality score:      Not scored yet")

        report.append(f"  Insurance referrals:    {stats['insurance_flags']}")
        report.append(f"  CA introductions:       {stats['ca_intro_flags']}")
        report.append("")

        # Meeting details
        report.append(f"  MEETING DETAILS")
        report.append(f"  {'─'*50}")
        for m in stats["meetings"]:
            report.append(f"  📅 {m.get('date', '?')}  - {m.get('client_name', 'Unknown')}")
            report.append(f"     Quality: {m.get('quality_score', 'Not scored')} | Meeting #{m.get('meeting_number', '?')}")
            if m.get("summary"):
                # Truncate summary to 150 chars
                summary = m["summary"][:150]
                if len(m["summary"]) > 150:
                    summary += "..."
                report.append(f"     Summary: {summary}")
            if m.get("fireflies_link"):
                report.append(f"     Recording: {m['fireflies_link']}")
            report.append("")

        # Coaching note
        coaching = coaching_notes.get(advisor, "")
        if coaching:
            report.append(f"  COACHING NOTE")
            report.append(f"  {'─'*50}")
            for line in coaching.split("\n"):
                report.append(f"  {line}")
            report.append("")

    return "\n".join(report)


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

def run_call_review(days_back=7):
    print("\n" + "=" * 60)
    print("  📊 ADVISOR CALL REVIEW  - Starting")
    print(f"  Period: Last {days_back} days")
    print("=" * 60)

    # Fetch and parse meetings
    meetings = get_recent_meetings(days_back)
    if not meetings:
        print("\n  No meetings found in this period. Nothing to review.")
        return

    parsed = parse_meetings(meetings)
    stats = build_advisor_stats(parsed)

    # Generate coaching notes for each advisor
    print("\n  🧠 Generating coaching summaries...")
    coaching_notes = {}
    for advisor, advisor_stats in stats.items():
        if advisor_stats["total_meetings"] > 0:
            print(f"     Analyzing {advisor}...")
            coaching_notes[advisor] = generate_coaching_summary(
                advisor, advisor_stats["meetings"]
            )

    # Build and send report
    report = build_call_review_report(parsed, stats, days_back, coaching_notes)

    # Print to console
    print(f"\n{report}")

    # Send to Udayan (as the team lead)
    udayan_email = ADVISORS["udayan"]["email"]
    send_email(
        sender=f"MoneyIQ Agent <{udayan_email}>",
        to=udayan_email,
        subject=f"Weekly Call Review  - {len(parsed)} meetings ({date.today().strftime('%d %b %Y')})",
        body=report
    )

    # Send individual coaching notes to each advisor
    for advisor, coaching in coaching_notes.items():
        advisor_email = None
        for adv in ADVISORS.values():
            if adv["name"] == advisor:
                advisor_email = adv["email"]
                break
        if advisor_email and advisor_email != udayan_email:
            advisor_meetings = stats[advisor]["total_meetings"]
            send_email(
                sender=f"MoneyIQ Agent <{advisor_email}>",
                to=advisor_email,
                subject=f"Your Weekly Coaching Note  - {advisor_meetings} meeting(s) reviewed ({date.today().strftime('%d %b')})",
                body=(
                    f"Hi {advisor.split()[0]},\n\n"
                    f"Here's your coaching note from the past {days_back} days "
                    f"({advisor_meetings} meeting(s) reviewed):\n\n"
                    f"{'─'*40}\n"
                    f"{coaching}\n"
                    f"{'─'*40}\n\n"
                    f"Keep up the good work!\n"
                    f" - MoneyIQ Agent"
                )
            )

    print(f"\n{'='*60}")
    print(f"  ✅ Call Review complete! Report sent.")
    print(f"{'='*60}")


# ══════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════
if __name__ == "__main__":
    days = 7
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])

    run_call_review(days_back=days)
