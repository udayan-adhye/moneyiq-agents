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
CONTACTS_DB_ID = os.environ.get("CONTACTS_DB_ID", "")
MEETINGS_DB_ID = os.environ.get("MEETINGS_DB_ID", "")
TASKS_DB_ID    = os.environ.get("TASKS_DB_ID", "")

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
        "email": "udayan@withmoneyiq.com"
    },
    "rishabh": {
        "name": "Rishabh Mishra",
        "email": "rishabh.mishra@withmoneyiq.com"
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
FOLLOWUP_SEQUENCE_LENGTH = 5
FOLLOWUP_INTERVAL_DAYS = [2, 4, 7, 14, 21]

# -----------------------------------------
# HIGH-VALUE CLIENT THRESHOLDS
# -----------------------------------------
HIGH_VALUE_SIP_MONTHLY = 100000        # 1 lakh/month SIP
HIGH_VALUE_LUMPSUM_YEARLY = 2000000    # 20 lakhs lumpsum
HIGH_VALUE_ALERT_EMAIL = "udayan@withmoneyiq.com"
