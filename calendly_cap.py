"""
Calendly Appointment Cap Enforcer
==================================
Caps Calendly bookings at MAX_PER_DAY per advisor per day.

How it works:
  1. For each day in the next N days, count meeting events on the calendar.
  2. If count >= MAX_PER_DAY, place an all-day busy block on that day so
     Calendly's availability check sees no free slots.
  3. If count later drops below MAX_PER_DAY (e.g. an event is cancelled),
     remove the block automatically.

The advisor can still create events manually past the cap — only Calendly
bookings are prevented.

CLI usage:
  python3 calendly_cap.py                              # all advisors, next 30 days
  python3 calendly_cap.py --advisor udayan@withmoneyiq.com
  python3 calendly_cap.py --max 4 --days 14
"""

import argparse
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

from calendar_helpers import get_calendar_service
from config import ADVISORS

CAP_BLOCK_MARKER = "[MONEYIQ-CAL-CAP]"
CAP_BLOCK_TITLE = f"Calendly cap reached — day full {CAP_BLOCK_MARKER}"

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_MAX_PER_DAY = 4
DEFAULT_DAYS_AHEAD = 30


def _is_cap_block(event):
    """True if this event is one we created to enforce the cap."""
    ext = (event.get("extendedProperties") or {}).get("private") or {}
    if ext.get("moneyiq_cap") == "1":
        return True
    return CAP_BLOCK_MARKER in (event.get("summary") or "")


def _is_all_day(event):
    return "date" in (event.get("start") or {})


def _user_declined(event, user_email):
    for a in event.get("attendees") or []:
        if (a.get("email") or "").lower() == user_email.lower():
            return a.get("responseStatus") == "declined"
    return False


def _count_appointments(service, day_start_utc, day_end_utc, user_email):
    """Returns (count_of_real_appointments, existing_cap_block_id_or_None)."""
    result = service.events().list(
        calendarId="primary",
        timeMin=day_start_utc.isoformat().replace("+00:00", "Z"),
        timeMax=day_end_utc.isoformat().replace("+00:00", "Z"),
        singleEvents=True,
        showDeleted=False,
        maxResults=100,
    ).execute()

    count = 0
    cap_block_id = None
    for ev in result.get("items", []):
        if ev.get("status") == "cancelled":
            continue
        if _is_cap_block(ev):
            cap_block_id = ev.get("id")
            continue
        if _is_all_day(ev):
            continue
        if _user_declined(ev, user_email):
            continue
        if (ev.get("transparency") or "opaque") == "transparent":
            continue
        count += 1

    return count, cap_block_id


def _create_cap_block(service, date_obj):
    next_day = date_obj + timedelta(days=1)
    body = {
        "summary": CAP_BLOCK_TITLE,
        "description": (
            "Auto-created by MoneyIQ. This day already has the maximum "
            "number of appointments. Calendly will not offer slots while "
            "this event is on the calendar. Delete it to reopen the day."
        ),
        "start": {"date": date_obj.isoformat()},
        "end":   {"date": next_day.isoformat()},
        "transparency": "opaque",
        "extendedProperties": {"private": {"moneyiq_cap": "1"}},
        "reminders": {"useDefault": False},
    }
    return service.events().insert(calendarId="primary", body=body).execute()


def _delete_event(service, event_id):
    service.events().delete(calendarId="primary", eventId=event_id).execute()


def enforce_cap_for_advisor(advisor_email, max_per_day=DEFAULT_MAX_PER_DAY, days_ahead=DEFAULT_DAYS_AHEAD):
    service = get_calendar_service(advisor_email)
    if not service:
        print(f"  No calendar service for {advisor_email}")
        return {
            "advisor": advisor_email,
            "blocks_added": 0,
            "blocks_removed": 0,
            "days_at_cap": [],
            "error": "no_service",
        }

    today = datetime.now(IST).date()
    blocks_added = 0
    blocks_removed = 0
    days_at_cap = []

    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        day_start = datetime.combine(d, time.min, tzinfo=IST)
        day_end = day_start + timedelta(days=1)

        try:
            count, cap_block_id = _count_appointments(
                service,
                day_start.astimezone(timezone.utc),
                day_end.astimezone(timezone.utc),
                advisor_email,
            )
        except Exception as e:
            print(f"  Failed to read events for {advisor_email} {d}: {e}")
            continue

        if count >= max_per_day and not cap_block_id:
            try:
                _create_cap_block(service, d)
                blocks_added += 1
                days_at_cap.append(d.isoformat())
                print(f"  BLOCK ADDED  {advisor_email} {d} ({count} appts)")
            except Exception as e:
                print(f"  Could not create block on {d}: {e}")
        elif count < max_per_day and cap_block_id:
            try:
                _delete_event(service, cap_block_id)
                blocks_removed += 1
                print(f"  BLOCK REMOVED {advisor_email} {d} ({count} appts)")
            except Exception as e:
                print(f"  Could not remove block on {d}: {e}")
        elif count >= max_per_day:
            days_at_cap.append(d.isoformat())

    return {
        "advisor": advisor_email,
        "blocks_added": blocks_added,
        "blocks_removed": blocks_removed,
        "days_at_cap": days_at_cap,
    }


def enforce_cap_all_advisors(max_per_day=DEFAULT_MAX_PER_DAY, days_ahead=DEFAULT_DAYS_AHEAD):
    return [
        enforce_cap_for_advisor(adv["email"], max_per_day, days_ahead)
        for adv in ADVISORS.values()
    ]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--advisor", help="Single advisor email; default = all advisors")
    p.add_argument("--max", type=int, default=DEFAULT_MAX_PER_DAY)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS_AHEAD)
    args = p.parse_args()

    print(f"\nCalendly cap enforcer  max={args.max}/day  horizon={args.days} days\n")

    if args.advisor:
        print(enforce_cap_for_advisor(args.advisor, args.max, args.days))
    else:
        for r in enforce_cap_all_advisors(args.max, args.days):
            print(r)
