"""
Calendly Helper Functions
==========================
Fetches bookings and routing form answers from the Calendly API.

SETUP REQUIRED:
  1. Go to https://calendly.com/integrations/api_webhooks
  2. Click "Generate New Token"
  3. Copy the token and paste it in config.py as CALENDLY_API_KEY

REQUIREMENTS:
  pip3 install requests
"""

import requests
from datetime import datetime, timedelta
from config import CALENDLY_API_KEY

BASE_URL = "https://api.calendly.com"
HEADERS = {
    "Authorization": f"Bearer {CALENDLY_API_KEY}",
    "Content-Type": "application/json"
}


def get_current_user():
    """Get the current Calendly user info (needed for org URI)."""
    response = requests.get(f"{BASE_URL}/users/me", headers=HEADERS)
    if response.status_code == 200:
        data = response.json()["resource"]
        print(f"  ✅ Connected to Calendly as: {data['name']} (Admin)")
        return data
    else:
        print(f"  ❌ Calendly auth failed: {response.text}")
        return None


def get_recent_events(days_back=1):
    """
    Fetch recent events for the ENTIRE organization.
    Since you're the admin, your token can see all team members' events.
    We query by organization only (no user filter) to get everyone's bookings.
    """
    user = get_current_user()
    if not user:
        return []

    org_uri = user.get("current_organization")

    # Get events from the past N days
    min_start = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    max_start = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    params = {
        "organization": org_uri,
        # NOTE: No "user" filter — this fetches ALL team events
        "min_start_time": min_start,
        "max_start_time": max_start,
        "status": "active",
        "count": 100
    }

    response = requests.get(f"{BASE_URL}/scheduled_events", headers=HEADERS, params=params)
    if response.status_code == 200:
        events = response.json().get("collection", [])
        print(f"  📅 Found {len(events)} event(s) across ALL advisors in the last {days_back} day(s)")
        return events
    else:
        print(f"  ❌ Failed to fetch events: {response.text}")
        return []


def get_event_invitees(event_uri):
    """Get the invitee(s) for a specific event — this has the client's details."""
    response = requests.get(f"{event_uri}/invitees", headers=HEADERS)
    if response.status_code == 200:
        return response.json().get("collection", [])
    else:
        print(f"  ❌ Failed to fetch invitees: {response.text}")
        return []


def extract_invitee_data(invitee):
    """
    Extract all useful data from a Calendly invitee.
    This includes name, email, and all routing form answers.
    """
    data = {
        "name": invitee.get("name", ""),
        "email": invitee.get("email", ""),
        "first_name": invitee.get("first_name", ""),
        "last_name": invitee.get("last_name", ""),
        "created_at": invitee.get("created_at", ""),
        "routing_form_answers": {},
        "custom_answers": {}
    }

    # Extract answers from routing form submission
    routing = invitee.get("routing_form_submission")
    if isinstance(routing, str):
        # Fetch the routing form submission from the URI
        resp = requests.get(routing, headers=HEADERS)
        if resp.status_code == 200:
            routing = resp.json().get("resource", {})
        else:
            routing = {}
    elif not isinstance(routing, dict):
        routing = {}

    if routing:
        questions = routing.get("questions_and_answers", [])
        for qa in questions:
            question = qa.get("question", "").strip()
            answer = qa.get("answer", "").strip() if qa.get("answer") else ""
            data["routing_form_answers"][question] = answer

    # Extract answers from regular custom questions
    questions_and_answers = invitee.get("questions_and_answers", [])
    for qa in questions_and_answers:
        question = qa.get("question", "").strip()
        answer = qa.get("answer", "").strip() if qa.get("answer") else ""
        data["custom_answers"][question] = answer

    return data


def _normalize_for_notion(answer, field_type):
    """
    Normalize Calendly answers to Notion-safe select options.
    Notion doesn't allow commas in select option names.
    """
    if not answer:
        return answer

    # Monthly surplus mapping (Calendly → Notion)
    surplus_map = {
        "Under ₹25,000": "Under ₹25k",
        "Under 25,000": "Under ₹25k",
        "₹25k-50,000": "₹25k-50k",
        "25,000-50,000": "₹25k-50k",
        "₹50k-1,00,000": "₹50k-1L",
        "50,000-1,00,000": "₹50k-1L",
        "1 lakh+": "₹1L+",
        "1,00,000+": "₹1L+",
    }

    # SIP interest mapping (Calendly → Notion)
    sip_map = {
        "Don't want an SIP": "No SIP",
        "0-15,000": "0-15k",
        "₹15k-30,000": "₹15k-30k",
        "15,000-30,000": "₹15k-30k",
        "₹30k-60,000": "₹30k-60k",
        "30,000-60,000": "₹30k-60k",
        "₹60k-1 lakh": "₹60k-1L",
        "60,000-1,00,000": "₹60k-1L",
        "₹1 lakh+": "₹1L+",
        "1,00,000+": "₹1L+",
    }

    if field_type == "monthly_surplus":
        return surplus_map.get(answer, answer.replace(",", ""))
    elif field_type == "sip_interest":
        return sip_map.get(answer, answer.replace(",", ""))
    else:
        # For any other field, just strip commas as safety
        return answer


def map_calendly_to_crm(invitee_data):
    """
    Map Calendly routing form answers to CRM field names.
    This function matches your specific Calendly questions to Notion fields.
    """
    answers = {**invitee_data.get("routing_form_answers", {}), **invitee_data.get("custom_answers", {})}

    crm_data = {
        "name": invitee_data.get("name", ""),
        "email": invitee_data.get("email", ""),
        "first_name": invitee_data.get("first_name", ""),
        "last_name": invitee_data.get("last_name", ""),
    }

    # Map each routing form question to a CRM field
    # We use flexible matching since question text might vary slightly
    for question, answer in answers.items():
        q = question.lower()

        if "whatsapp" in q or ("phone" in q and "number" in q):
            crm_data["whatsapp_number"] = answer
        elif "where" in q and "live" in q:
            crm_data["location"] = answer
        elif "when" in q and ("begin" in q or "start" in q) and "invest" in q:
            crm_data["investing_timeline"] = answer
        elif "annual" in q and "income" in q:
            crm_data["annual_income"] = answer
        elif "monthly" in q and "surplus" in q:
            crm_data["monthly_surplus"] = _normalize_for_notion(answer, "monthly_surplus")
        elif "monthly sip" in q or ("sip" in q and "amount" in q) or ("sip" in q and "investment" in q):
            crm_data["sip_interest"] = _normalize_for_notion(answer, "sip_interest")
        elif "one-time" in q or "one time" in q or "lumpsum" in q or "lump sum" in q:
            crm_data["lumpsum_interest"] = answer
        elif "goal" in q or "investing goals" in q:
            crm_data["investing_goals"] = answer
        elif "insurance" in q and "cover" in q:
            crm_data["insurance_status"] = answer

    return crm_data


# ══════════════════════════════════════════════
# TEST — run this file directly to verify connection
# ══════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  Calendly Connection Test")
    print("=" * 55)

    user = get_current_user()
    if user:
        print(f"\n  Name: {user['name']}")
        print(f"  Email: {user['email']}")
        print(f"  Scheduling URL: {user.get('scheduling_url', 'N/A')}")

        print("\n  Fetching recent events (last 7 days)...")
        events = get_recent_events(days_back=7)
        for event in events:
            print(f"\n  📅 {event.get('name', 'Unnamed Event')}")
            print(f"     Start: {event.get('start_time', 'N/A')}")

            invitees = get_event_invitees(event["uri"])
            for inv in invitees:
                inv_data = extract_invitee_data(inv)
                crm_data = map_calendly_to_crm(inv_data)
                print(f"     Client: {crm_data.get('name', 'N/A')}")
                print(f"     Email: {crm_data.get('email', 'N/A')}")
                print(f"     WhatsApp: {crm_data.get('whatsapp_number', 'N/A')}")
                print(f"     Timeline: {crm_data.get('investing_timeline', 'N/A')}")
                print(f"     SIP: {crm_data.get('sip_interest', 'N/A')}")
                print(f"     Lumpsum: {crm_data.get('lumpsum_interest', 'N/A')}")
    else:
        print("\n  ❌ Could not connect. Check your CALENDLY_API_KEY in config.py")
