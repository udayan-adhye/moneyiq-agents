"""
Google Contacts Helper Functions
==================================
Saves contacts to Google Contacts via the People API so they appear
in the advisor's phone and WhatsApp automatically.

SETUP REQUIRED (one-time):
  1. Enable the People API in your Google Cloud project
     (same project as Gmail/Calendar)
  2. Run: python3 google_contacts_helpers.py
     This will open a browser to authorize Contacts access.

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

# People API scope
CONTACTS_SCOPES = ["https://www.googleapis.com/auth/contacts"]

# Token files per advisor
CONTACTS_TOKEN_FILES = {
    "udayan@withmoneyiq.com": "contacts_token_udayan.json",
    "rishabh.mishra@withmoneyiq.com": "contacts_token_rishabh.json",
}

CONTACTS_TOKEN_ENV_VARS = {
    "udayan@withmoneyiq.com": "GCONTACTS_TOKEN_UDAYAN_JSON",
    "rishabh.mishra@withmoneyiq.com": "GCONTACTS_TOKEN_RISHABH_JSON",
}

DEFAULT_CONTACTS_TOKEN = "contacts_token.json"

_people_services = {}


def _load_contacts_creds_from_env(advisor_email):
    env_var = CONTACTS_TOKEN_ENV_VARS.get(advisor_email.lower() if advisor_email else "")
    if not env_var:
        return None
    token_json = os.environ.get(env_var, "")
    if not token_json:
        return None
    try:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, CONTACTS_SCOPES)
        return creds
    except Exception as e:
        print(f"  Failed to load Contacts token from env: {e}")
        return None


def get_people_service(advisor_email=None):
    token_file = DEFAULT_CONTACTS_TOKEN
    if advisor_email and advisor_email.lower() in CONTACTS_TOKEN_FILES:
        token_file = CONTACTS_TOKEN_FILES[advisor_email.lower()]

    if token_file in _people_services:
        return _people_services[token_file]

    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, CONTACTS_SCOPES)

    if not creds:
        creds = _load_contacts_creds_from_env(advisor_email)

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
                print(f"  Failed to refresh Contacts token: {e}")
                return None
        elif not creds:
            if os.path.exists(GMAIL_CREDENTIALS_FILE):
                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, CONTACTS_SCOPES
                )
                creds = flow.run_local_server(port=0)
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            else:
                print("  No credentials available for Contacts.")
                return None

    service = build("people", "v1", credentials=creds)
    _people_services[token_file] = service
    return service


def save_to_google_contacts(name, phone=None, email=None, advisor_email=None, company=None):
    """
    Create or update a contact in the advisor's Google Contacts.
    WhatsApp reads from Google Contacts, so the name will appear there automatically.

    Returns the created/updated contact resource name, or None on failure.
    """
    service = get_people_service(advisor_email)
    if not service:
        print(f"  ⚠️ Google Contacts not connected for {advisor_email}")
        return None

    if not name or (not phone and not email):
        return None

    # Check if contact already exists (by phone or email) to avoid duplicates
    existing = _find_existing_contact(service, phone=phone, email=email)
    if existing:
        print(f"  ⏭️  Contact already in Google Contacts: {name}")
        return existing

    # Build the contact body — append "MIQ" suffix so advisor knows it's MoneyIQ-sourced
    name_parts = name.strip().split()
    given_name = name_parts[0] if name_parts else name
    family_name = " ".join(name_parts[1:]) + " MIQ" if len(name_parts) > 1 else "MIQ"
    body = {
        "names": [{"givenName": given_name, "familyName": family_name}],
    }

    if phone:
        # Ensure phone has country code
        phone_clean = phone.strip()
        if not phone_clean.startswith("+"):
            phone_clean = "+91" + phone_clean.lstrip("0")
        body["phoneNumbers"] = [{"value": phone_clean, "type": "mobile"}]

    if email:
        body["emailAddresses"] = [{"value": email, "type": "work"}]

    if company:
        body["organizations"] = [{"name": company}]

    try:
        result = service.people().createContact(body=body).execute()
        resource_name = result.get("resourceName", "")
        print(f"  ✅ Saved to Google Contacts: {name}" + (f" ({phone})" if phone else ""))
        return resource_name
    except Exception as e:
        print(f"  ❌ Failed to save Google Contact: {e}")
        return None


def _find_existing_contact(service, phone=None, email=None):
    """Search for an existing contact by phone or email to avoid duplicates."""
    try:
        query = phone or email
        if not query:
            return None

        results = service.people().searchContacts(
            query=query,
            readMask="names,phoneNumbers,emailAddresses",
            pageSize=5
        ).execute()

        for match in results.get("results", []):
            person = match.get("person", {})
            resource = person.get("resourceName")
            if resource:
                return resource
    except Exception:
        pass  # Search failed — proceed to create
    return None


# ══════════════════════════════════════════════
# FIRST-TIME SETUP — run this file directly to authorize
# ══════════════════════════════════════════════

if __name__ == "__main__":
    print("Google Contacts (People API) Authorization")
    print("=" * 45)
    print("This will open your browser to authorize Contacts access.")
    print("You only need to do this once per advisor.\n")

    email = input("Advisor email (e.g. udayan@withmoneyiq.com): ").strip()
    if not email:
        print("No email provided. Exiting.")
    else:
        svc = get_people_service(email)
        if svc:
            print(f"\n✅ Authorized! Token saved.")
        else:
            print(f"\n❌ Authorization failed.")
