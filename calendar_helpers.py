"""
Google Calendar Helper Functions
=================================
Handles creating and managing calendar events for follow-up meetings.

SETUP REQUIRED (one-time):
  1. Enable the Google Calendar API in your Google Cloud project
     (same project as Gmail)
  2. Run: python3 calendar_helpers.py
     This will open a browser to authorize calendar access.

REQUIREMENTS:
  pip3 install google-auth google-auth-oauthlib google-api-python-client
"""

import os
import json
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE

# Calendar API scope
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Token files per advisor
CALENDAR_TOKEN_FILES = {
    "udayan@withmoneyiq.com": "calendar_token_udayan.json",
    "rishabh.mishra@withmoneyiq.com": "calendar_token_rishabh.json",
}

# Environment variable names for tokens (Railway deployment)
CALENDAR_TOKEN_ENV_VARS = {
    "udayan@withmoneyiq.com": "GCAL_TOKEN_UDAYAN_JSON",
    "rishabh.mishra@withmoneyiq.com": "GCAL_TOKEN_RISHABH_JSON",
}

DEFAULT_CALENDAR_TOKEN = "calendar_token.json"

# Cache of calendar services
_calendar_services = {}


def _load_calendar_creds_from_env(advisor_email):
    """Load calendar credentials from environment variable (for Railway)."""
    env_var = CALENDAR_TOKEN_ENV_VARS.get(advisor_email.lower() if advisor_email else "")
    if not env_var:
        return None

    token_json = os.environ.get(env_var, "")
    if not token_json:
        return None

    try:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, CALENDAR_SCOPES)
        print(f"  Loaded Calendar token from env var ({env_var})")
        return creds
    except Exception as e:
        print(f"  Failed to load calendar token from env var {env_var}: {e}")
        return None


def get_calendar_service(advisor_email=None):
    """
    Connect to Google Calendar API for a specific advisor.
    Same pattern as get_gmail_service.
    """
    token_file = DEFAULT_CALENDAR_TOKEN
    if advisor_email and advisor_email.lower() in CALENDAR_TOKEN_FILES:
        token_file = CALENDAR_TOKEN_FILES[advisor_email.lower()]

    if token_file in _calendar_services:
        return _calendar_services[token_file]

    creds = None

    # Try 1: Load from token file
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, CALENDAR_SCOPES)

    # Try 2: Load from environment variable
    if not creds:
        creds = _load_calendar_creds_from_env(advisor_email)

    # Refresh or authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                try:
                    with open(token_file, "w") as f:
                        f.write(creds.to_json())
                except (IOError, OSError):
                    pass
            except Exception as e:
                print(f"  Failed to refresh calendar token: {e}")
                return None
        elif not creds:
            if os.path.exists(GMAIL_CREDENTIALS_FILE):
                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            else:
                print("  No calendar credentials available.")
                return None

    service = build("calendar", "v3", credentials=creds)
    _calendar_services[token_file] = service
    return service


def create_pending_meeting(
    advisor_email,
    summary,
    description,
    start_datetime,
    end_datetime,
    attendee_emails,
    timezone="Asia/Kolkata"
):
    """
    Create a calendar event WITHOUT sending invites (pending approval).
    Returns the event ID so we can send invites later when approved.
    """
    service = get_calendar_service(advisor_email)
    if not service:
        print("  ❌ Calendar service not available")
        return None

    event = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_datetime,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_datetime,
            "timeZone": timezone,
        },
        "attendees": [{"email": email} for email in attendee_emails],
        "conferenceData": {
            "createRequest": {
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
                "requestId": f"moneyiq-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 30},
                {"method": "email", "minutes": 60},
            ],
        },
    }

    try:
        created_event = service.events().insert(
            calendarId="primary",
            body=event,
            sendUpdates="none",  # No notifications yet - pending approval
            conferenceDataVersion=1,
        ).execute()

        event_id = created_event.get("id")
        html_link = created_event.get("htmlLink")
        meet_link = ""
        if created_event.get("conferenceData", {}).get("entryPoints"):
            for ep in created_event["conferenceData"]["entryPoints"]:
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri", "")
                    break

        print(f"  📅 Pending meeting created: {event_id}")
        print(f"  🔗 Calendar link: {html_link}")
        if meet_link:
            print(f"  🎥 Meet link: {meet_link}")

        return {
            "event_id": event_id,
            "html_link": html_link,
            "meet_link": meet_link,
        }

    except Exception as e:
        print(f"  ❌ Failed to create calendar event: {e}")
        return None


def approve_and_send_invites(advisor_email, event_id):
    """
    Approve a pending meeting by sending invites to all attendees.
    Called when the advisor clicks the approval link.
    """
    service = get_calendar_service(advisor_email)
    if not service:
        print("  ❌ Calendar service not available for approval")
        return False

    try:
        # Fetch the existing event
        event = service.events().get(
            calendarId="primary",
            eventId=event_id
        ).execute()

        # Re-save the same event but now with sendUpdates='all'
        # This triggers invite notifications to all attendees
        updated = service.events().update(
            calendarId="primary",
            eventId=event_id,
            body=event,
            sendUpdates="all",
        ).execute()

        print(f"  ✅ Meeting approved! Invites sent for: {updated.get('summary')}")
        return True

    except Exception as e:
        print(f"  ❌ Failed to approve meeting: {e}")
        return False


def delete_meeting(advisor_email, event_id):
    """Delete a pending meeting that was rejected."""
    service = get_calendar_service(advisor_email)
    if not service:
        return False

    try:
        service.events().delete(
            calendarId="primary",
            eventId=event_id,
            sendUpdates="none",
        ).execute()
        print(f"  🗑️ Meeting deleted: {event_id}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to delete meeting: {e}")
        return False


# ══════════════════════════════════════════════
# STANDALONE AUTH - run this file to authorize
# ══════════════════════════════════════════════

if __name__ == "__main__":
    print("\nGoogle Calendar Authorization")
    print("=" * 40)
    print("\nThis will open a browser window to authorize calendar access.")
    print("Use your @withmoneyiq.com account.\n")

    advisor = input("Which advisor? (udayan / rishabh): ").strip().lower()
    if advisor == "udayan":
        email = "udayan@withmoneyiq.com"
    elif advisor == "rishabh":
        email = "rishabh.mishra@withmoneyiq.com"
    else:
        print("Invalid advisor name.")
        exit(1)

    service = get_calendar_service(email)
    if service:
        print(f"\n✅ Calendar authorized for {email}")
        print(f"Token saved to: {CALENDAR_TOKEN_FILES[email]}")

        # Quick test - list upcoming events
        now = datetime.utcnow().isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary", timeMin=now,
            maxResults=3, singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if events:
            print(f"\nUpcoming events:")
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                print(f"  - {start}: {event.get('summary', 'No title')}")
    else:
        print("\n❌ Authorization failed. Check your credentials file.")
