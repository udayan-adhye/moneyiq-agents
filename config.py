"""
Configuration File - Wealth Management Agent System
=====================================================
All secrets are loaded from environment variables.
For local development, create a .env file (see .env.example).
On Railway, set these in the Variables tab.
"""

import os

# Load .env file if it exists (for local development)
def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key not in os.environ:
                        os.environ[key] = value

_load_env()


# -----------------------------------------
# API KEYS - loaded from environment
# -----------------------------------------
CLAUDE_API_KEY     = os.environ.get("CLAUDE_API_KEY", "")
FIREFLIES_API_KEY  = os.environ.get("FIREFLIES_API_KEY", "")
NOTION_TOKEN       = os.environ.get("NOTION_TOKEN", "")
CALENDLY_API_KEY   = os.environ.get("CALENDLY_API_KEY", "")

# -----------------------------------------
# NOTION DATABASE IDs
# -----------------------------------------
CONTACTS_DB_ID  = os.environ.get("CONTACTS_DB_ID", "")
MEETINGS_DB_ID  = os.environ.get("MEETINGS_DB_ID", "")
TASKS_DB_ID     = os.environ.get("TASKS_DB_ID", "")
FOLLOWUP_DB_ID  = os.environ.get("FOLLOWUP_DB_ID", "403c199167914baaa09db29395577a30")

# -----------------------------------------
# GMAIL - OAuth credentials file
# -----------------------------------------
GMAIL_CREDENTIALS_FILE = "gmail_credentials.json"

# -----------------------------------------
# TEAM INFO
# -----------------------------------------
ADVISORS = {
    "udayan": {
        "name": "Udayan Adhye",
        "email": "udayan@withmoneyiq.com",
        "phone": "+91 8149128009"
    },
    "rishabh": {
        "name": "Rishabh Mishra",
        "email": "rishabh.mishra@withmoneyiq.com",
        "phone": "+91 9205736720"
    }
}

INSURANCE_TEAM_EMAIL = "directsuppport@oneassure.in"
CA_CONTACT_EMAIL     = "asmeet@anarco.in"
CA_CONTACT_PHONE     = "+91 9370275430"
CA_CONTACT_NAME      = "Asmeet Shah"

# -----------------------------------------
# AGENT SETTINGS
# -----------------------------------------
DAYS_BEFORE_REMINDER = 3

# Research-backed follow-up sequence (Belkins 2025, Gong Labs, Growth List 2026)
# Day 0 = meeting recap email (already built)
# Day 1 = WhatsApp warm check-in
# Day 3 = WhatsApp nudge (conditional — only if items pending)
# Day 7 = Email value-add touchpoint
# Day 14 = WhatsApp soft re-engagement
FOLLOWUP_SEQUENCE = [
    {"day": 1,  "channel": "WhatsApp", "type": "warm_checkin",    "conditional": False},
    {"day": 3,  "channel": "WhatsApp", "type": "action_nudge",    "conditional": True},   # skips if nothing pending
    {"day": 7,  "channel": "Email",    "type": "value_add",       "conditional": False},
    {"day": 14, "channel": "WhatsApp", "type": "soft_reengage",   "conditional": False},
]
FOLLOWUP_SEQUENCE_LENGTH = len(FOLLOWUP_SEQUENCE)

# WhatsApp Business API (Meta Cloud API direct)
WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_ID  = os.environ.get("WHATSAPP_PHONE_ID", "")

# -----------------------------------------
# HIGH-VALUE CLIENT THRESHOLDS
# -----------------------------------------
HIGH_VALUE_SIP_MONTHLY = 100000        # 1 lakh/month SIP
HIGH_VALUE_LUMPSUM_YEARLY = 2000000    # 20 lakhs lumpsum
HIGH_VALUE_ALERT_EMAIL = "udayan@withmoneyiq.com"

# -----------------------------------------
# SERVER URL (for approval links in emails)
# -----------------------------------------
SERVER_URL = os.environ.get("SERVER_URL", "https://web-production-9acaee.up.railway.app")
