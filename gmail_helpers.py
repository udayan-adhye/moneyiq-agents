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
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE

# Gmail API scope - needs to send emails and create drafts
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

# Token files - one per advisor so each sends from their own email
TOKEN_FILES = {
    "udayan@withmoneyiq.com": "gmail_token_udayan.json",
    "rishabh.mishra@withmoneyiq.com": "gmail_token_rishabh.json",
}

# Environment variable names for tokens (used on Railway when files don't exist)
TOKEN_ENV_VARS = {
    "udayan@withmoneyiq.com": "GMAIL_TOKEN_UDAYAN_JSON",
    "rishabh.mishra@withmoneyiq.com": "GMAIL_TOKEN_RISHABH_JSON",
}

# Default token (backward compatibility)
DEFAULT_TOKEN_FILE = "gmail_token.json"

# Cache of Gmail services so we don't reconnect every time
_gmail_services = {}


def _load_creds_from_env(advisor_email):
    """Try to load Gmail credentials from environment variables (for Railway)."""
    env_var = TOKEN_ENV_VARS.get(advisor_email.lower() if advisor_email else "")
    if not env_var:
        return None

    token_json = os.environ.get(env_var, "")
    if not token_json:
        return None

    try:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        print(f"  Loaded Gmail token from environment variable ({env_var})")
        return creds
    except Exception as e:
        print(f"  Failed to load token from env var {env_var}: {e}")
        return None


def _load_credentials_json_from_env():
    """Try to load gmail_credentials.json from environment variable."""
    creds_json = os.environ.get("GMAIL_CREDENTIALS_JSON", "")
    if not creds_json:
        return None
    try:
        return json.loads(creds_json)
    except Exception:
        return None


def get_gmail_service(advisor_email=None):
    """
    Connect to Gmail API for a specific advisor.
    Each advisor has their own token file so emails send from their account.

    Checks in order:
    1. Cached service (already connected this session)
    2. Token file on disk (local development)
    3. Environment variable (Railway deployment)
    """
    # Determine which token file to use
    token_file = DEFAULT_TOKEN_FILE
    if advisor_email and advisor_email.lower() in TOKEN_FILES:
        token_file = TOKEN_FILES[advisor_email.lower()]

    # Return cached service if available
    if token_file in _gmail_services:
        return _gmail_services[token_file]

    creds = None

    # Try 1: Load from token file on disk
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    # Try 2: Load from environment variable (Railway)
    if not creds:
        creds = _load_creds_from_env(advisor_email)

    # If no token or it's expired, try to refresh
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token back to file if possible
                try:
                    with open(token_file, "w") as f:
                        f.write(creds.to_json())
                except (IOError, OSError):
                    pass  # On Railway, filesystem may be read-only
            except Exception as e:
                print(f"  Failed to refresh token: {e}")
                return None
        elif not creds:
            # No token at all - check if we can do initial auth (local only)
            if os.path.exists(GMAIL_CREDENTIALS_FILE):
                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
                with open(token_file, "w") as token:
                    token.write(creds.to_json())
            else:
                # Check env var for credentials
                creds_data = _load_credentials_json_from_env()
                if creds_data:
                    print("  Gmail credentials found in env but cannot run OAuth flow on server.")
                    print("  Please authorize locally first, then set GMAIL_TOKEN env vars.")
                else:
                    print(f"  Missing {GMAIL_CREDENTIALS_FILE}")
                    print(f"     Follow GMAIL_SETUP_GUIDE.md to create it.")
                return None

    service = build("gmail", "v1", credentials=creds)
    _gmail_services[token_file] = service
    print(f"  Connected to Gmail ({advisor_email or 'default'})")
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


def save_draft(sender, to, subject, body, cc=None, advisor_email=None, attachments=None):
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
        advisor_email: Which advisor's Gmail to save draft in
        attachments:  Optional list of file paths to attach
    """
    # Extract advisor email from sender if not provided
    if not advisor_email and "<" in sender and ">" in sender:
        advisor_email = sender.split("<")[1].split(">")[0]

    service = get_gmail_service(advisor_email)
    if not service:
        print(f"  ❌ Cannot save draft — Gmail not connected for: {advisor_email}")
        print(f"     → Check if GMAIL_TOKEN env var is set for this advisor on Railway")
        token_var = TOKEN_ENV_VARS.get(advisor_email.lower(), "UNKNOWN") if advisor_email else "UNKNOWN"
        print(f"     → Expected env var: {token_var}")
        return None

    # Convert plain text body to simple HTML
    body_html = body.replace("\n", "<br>")

    # Use mixed multipart if attachments, otherwise alternative
    if attachments:
        message = MIMEMultipart("mixed")
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body, "plain"))
        body_part.attach(MIMEText(body_html, "html"))
        message.attach(body_part)

        for filepath in attachments:
            if os.path.exists(filepath):
                filename = os.path.basename(filepath)
                part = MIMEBase("application", "octet-stream")
                with open(filepath, "rb") as f:
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                message.attach(part)
                print(f"  📎 Attached: {filename}")
            else:
                print(f"  ⚠️ Attachment not found: {filepath}")
    else:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(body_html, "html"))

    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc

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
