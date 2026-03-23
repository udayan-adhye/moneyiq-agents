"""
Gmail Helper Functions
=======================
Handles sending emails and saving drafts via the Gmail API.

SETUP REQUIRED (one-time):
  1. Create a Google Cloud project
  2. Enable the Gmail API
  3. Create OAuth credentials
  4. Download credentials.json to this folder
  5. Run this file once to authorize: python3 gmail_helpers.py
  See GMAIL_SETUP_GUIDE.md for step-by-step instructions.

REQUIREMENTS:
  pip3 install google-auth google-auth-oauthlib google-api-python-client
"""

import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE

# Gmail API scope — needs to send emails and create drafts
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

# Token files — one per advisor so each sends from their own email
# Udayan: gmail_token_udayan.json
# Rishabh: gmail_token_rishabh.json
TOKEN_FILES = {
    "udayan@withmoneyiq.com": "gmail_token_udayan.json",
    "rishabh.mishra@withmoneyiq.com": "gmail_token_rishabh.json",
}

# Default token (backward compatibility)
DEFAULT_TOKEN_FILE = "gmail_token.json"

# Cache of Gmail services so we don't reconnect every time
_gmail_services = {}


def get_gmail_service(advisor_email=None):
    """
    Connect to Gmail API for a specific advisor.
    Each advisor has their own token file so emails send from their account.

    First time for each advisor: opens a browser window to log in.
    After that: uses the saved token automatically.
    """
    # Determine which token file to use
    token_file = DEFAULT_TOKEN_FILE
    if advisor_email and advisor_email.lower() in TOKEN_FILES:
        token_file = TOKEN_FILES[advisor_email.lower()]

    # Return cached service if available
    if token_file in _gmail_services:
        return _gmail_services[token_file]

    creds = None

    # Check if we already have a saved token
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    # If no token or it's expired, re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GMAIL_CREDENTIALS_FILE):
                print(f"  ❌ Missing {GMAIL_CREDENTIALS_FILE}")
                print(f"     Follow GMAIL_SETUP_GUIDE.md to create it.")
                return None

            flow = InstalledAppFlow.from_client_secrets_file(
                GMAIL_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    _gmail_services[token_file] = service
    print(f"  ✅ Connected to Gmail ({advisor_email or 'default'})")
    return service


def _build_email(sender, to, subject, body_html):
    """Build a MIME email message."""
    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject

    # Plain text version (fallback)
    plain_text = body_html.replace("<br>", "\n").replace("</p>", "\n\n")
    # Strip remaining HTML tags for plain text
    import re
    plain_text = re.sub(r"<[^>]+>", "", plain_text)

    part1 = MIMEText(plain_text, "plain")
    part2 = MIMEText(body_html, "html")

    message.attach(part1)
    message.attach(part2)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_email(sender, to, subject, body, cc=None, advisor_email=None):
    """
    Send an email immediately.
    Use this for: insurance team notifications, meeting quality feedback.

    Args:
        sender:       "Udayan <udayan@withmoneyiq.com>"
        to:           "insurance@yourdomain.com"
        subject:      "Insurance Requirement — Client Name"
        body:         The email body (plain text — will be converted)
        cc:           Optional CC address
        advisor_email: Which advisor's Gmail to send from (e.g. "udayan@withmoneyiq.com")
    """
    # Extract advisor email from sender if not provided
    if not advisor_email and "<" in sender and ">" in sender:
        advisor_email = sender.split("<")[1].split(">")[0]

    service = get_gmail_service(advisor_email)
    if not service:
        print("  ❌ Cannot send email — Gmail not connected")
        return None

    # Convert plain text body to simple HTML
    body_html = body.replace("\n", "<br>")

    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc

    part1 = MIMEText(body, "plain")
    part2 = MIMEText(body_html, "html")
    message.attach(part1)
    message.attach(part2)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()
        print(f"  ✅ Email SENT to {to} — Subject: {subject}")
        return sent
    except Exception as e:
        print(f"  ❌ Failed to send email: {e}")
        return None


def save_draft(sender, to, subject, body, cc=None, advisor_email=None):
    """
    Save an email as a DRAFT (not sent).
    Use this for: client follow-up emails, CA introduction emails.
    The advisor reviews and sends manually.

    Args:
        sender:       "Udayan <udayan@withmoneyiq.com>"
        to:           "client@email.com"
        subject:      "Following up on our meeting — Udayan"
        body:         The email body (plain text)
        cc:           Optional CC address
        advisor_email: Which advisor's Gmail to save draft in (e.g. "rishabh.mishra@withmoneyiq.com")
    """
    # Extract advisor email from sender if not provided
    if not advisor_email and "<" in sender and ">" in sender:
        advisor_email = sender.split("<")[1].split(">")[0]

    service = get_gmail_service(advisor_email)
    if not service:
        print("  ❌ Cannot save draft — Gmail not connected")
        return None

    # Convert plain text body to simple HTML
    body_html = body.replace("\n", "<br>")

    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc

    part1 = MIMEText(body, "plain")
    part2 = MIMEText(body_html, "html")
    message.attach(part1)
    message.attach(part2)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}}
        ).execute()
        print(f"  ✅ DRAFT saved — To: {to} — Subject: {subject}")
        return draft
    except Exception as e:
        print(f"  ❌ Failed to save draft: {e}")
        return None


# ══════════════════════════════════════════════
# FIRST-TIME SETUP — run this file directly to authorize
#
# Usage:
#   python3 gmail_helpers.py                                    → authorize default account
#   python3 gmail_helpers.py udayan@withmoneyiq.com             → authorize Udayan
#   python3 gmail_helpers.py rishabh.mishra@withmoneyiq.com     → authorize Rishabh
# ══════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    advisor_email = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 55)
    print("  Gmail Authorization Setup")
    print("=" * 55)
    if advisor_email:
        print(f"\n  Authorizing: {advisor_email}")
    print("  This will open your browser to log into Gmail.")
    print("  After you approve, the connection is saved.\n")

    service = get_gmail_service(advisor_email)
    if service:
        # Test by getting profile
        profile = service.users().getProfile(userId="me").execute()
        print(f"\n  ✅ Successfully connected to: {profile['emailAddress']}")
        print(f"  You're all set! The agents can now send emails and save drafts.")
    else:
        print("\n  ❌ Authorization failed. Check GMAIL_SETUP_GUIDE.md")
