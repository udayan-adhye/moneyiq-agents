"""
Google Sheets Helper Functions
================================
Creates per-client copies of the onboarding information sheet.
Uses the same OAuth credentials as Gmail/Calendar.

SETUP REQUIRED (one-time):
  1. Enable the Google Sheets API + Google Drive API in your Google Cloud project
     (same project as Gmail/Calendar)
  2. Run: python3 sheets_helpers.py
     This will open a browser to authorize Sheets + Drive access.

REQUIREMENTS:
  pip3 install google-auth google-auth-oauthlib google-api-python-client
"""

import os
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE

# Sheets + Drive scopes (Drive needed to copy files and set sharing permissions)
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Token files per advisor
SHEETS_TOKEN_FILES = {
    "udayan@withmoneyiq.com": "sheets_token_udayan.json",
    "rishabh.mishra@withmoneyiq.com": "sheets_token_rishabh.json",
}

SHEETS_TOKEN_ENV_VARS = {
    "udayan@withmoneyiq.com": "GSHEETS_TOKEN_UDAYAN_JSON",
    "rishabh.mishra@withmoneyiq.com": "GSHEETS_TOKEN_RISHABH_JSON",
}

DEFAULT_SHEETS_TOKEN = "sheets_token.json"

# Template sheet ID — set this after creating the template (see setup instructions below)
TEMPLATE_SHEET_ID = os.environ.get("ONBOARDING_TEMPLATE_SHEET_ID", "")

_sheets_services = {}
_drive_services = {}


def _load_sheets_creds_from_env(advisor_email):
    env_var = SHEETS_TOKEN_ENV_VARS.get(advisor_email.lower() if advisor_email else "")
    if not env_var:
        return None
    token_json = os.environ.get(env_var, "")
    if not token_json:
        return None
    try:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, SHEETS_SCOPES)
        print(f"  Loaded Sheets token from env var ({env_var})")
        return creds
    except Exception as e:
        print(f"  Failed to load Sheets token from env var {env_var}: {e}")
        return None


def _get_creds(advisor_email=None):
    token_file = DEFAULT_SHEETS_TOKEN
    if advisor_email and advisor_email.lower() in SHEETS_TOKEN_FILES:
        token_file = SHEETS_TOKEN_FILES[advisor_email.lower()]

    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SHEETS_SCOPES)

    if not creds:
        creds = _load_sheets_creds_from_env(advisor_email)

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
                print(f"  Failed to refresh Sheets token: {e}")
                return None
        elif not creds:
            if os.path.exists(GMAIL_CREDENTIALS_FILE):
                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, SHEETS_SCOPES
                )
                creds = flow.run_local_server(port=0)
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            else:
                print("  No credentials available for Sheets.")
                return None

    return creds, token_file


def get_drive_service(advisor_email=None):
    result = _get_creds(advisor_email)
    if not result:
        return None
    creds, token_file = result
    key = f"drive_{token_file}"
    if key not in _drive_services:
        _drive_services[key] = build("drive", "v3", credentials=creds)
    return _drive_services[key]


def create_client_onboarding_sheet(client_name, client_email, advisor_email, ops_email="ops@withmoneyiq.com"):
    """
    Copy the master onboarding template and share it with the client + ops.

    Returns:
        dict with "sheet_url" and "sheet_id", or None on failure.
    """
    if not TEMPLATE_SHEET_ID:
        print("  ❌ ONBOARDING_TEMPLATE_SHEET_ID not set — cannot create onboarding sheet")
        return None

    drive = get_drive_service(advisor_email)
    if not drive:
        print("  ❌ Cannot create sheet — Google Drive not connected")
        return None

    try:
        # Copy the template
        copy = drive.files().copy(
            fileId=TEMPLATE_SHEET_ID,
            body={"name": f"Master Information - {client_name}"}
        ).execute()

        sheet_id = copy["id"]
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

        print(f"  ✅ Created onboarding sheet: {sheet_url}")

        # Share with client (edit access)
        if client_email:
            drive.permissions().create(
                fileId=sheet_id,
                body={
                    "type": "user",
                    "role": "writer",
                    "emailAddress": client_email
                },
                sendNotificationEmail=False
            ).execute()
            print(f"  ✅ Shared with client: {client_email}")

        # Share with ops (edit access)
        drive.permissions().create(
            fileId=sheet_id,
            body={
                "type": "user",
                "role": "writer",
                "emailAddress": ops_email
            },
            sendNotificationEmail=False
        ).execute()
        print(f"  ✅ Shared with ops: {ops_email}")

        return {"sheet_id": sheet_id, "sheet_url": sheet_url}

    except Exception as e:
        print(f"  ❌ Failed to create onboarding sheet: {e}")
        return None


# ══════════════════════════════════════════════
# FIRST-TIME SETUP — run this file directly to authorize
# ══════════════════════════════════════════════

if __name__ == "__main__":
    print("Google Sheets + Drive Authorization")
    print("=" * 40)
    print("This will open your browser to authorize Sheets & Drive access.")
    print("You only need to do this once per advisor.\n")

    email = input("Advisor email (e.g. udayan@withmoneyiq.com): ").strip()
    if not email:
        print("No email provided. Exiting.")
    else:
        result = _get_creds(email)
        if result:
            print(f"\n✅ Authorized! Token saved.")
        else:
            print(f"\n❌ Authorization failed.")
