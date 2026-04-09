"""
Agent 1 — Calendly Intake Agent
==================================
When someone books a call via Calendly, this agent:
  1. Fetches the booking details + routing form answers
  2. Creates or updates the contact in Notion CRM
  3. Fills in all lead qualification data (income, SIP interest, goals, etc.)
  4. Assigns to the right advisor based on event type

Can run as:
  - A webhook handler (instant, triggered by Calendly)
  - A manual catch-up (python3 calendly_intake.py --days 7)

HOW TO RUN:
  python3 calendly_intake.py            → check last 1 day
  python3 calendly_intake.py --days 7   → catch up on last 7 days

REQUIREMENTS:
  pip3 install requests
"""

import sys
from datetime import date
from config import ADVISORS
from calendly_helpers import (
    get_recent_events, get_event_invitees,
    extract_invitee_data, map_calendly_to_crm
)
from notion_helpers import (
    find_contact_by_email, create_contact, update_contact
)


def determine_advisor_from_event(event):
    """
    Figure out which advisor this booking is for.
    Checks the event memberships (who the calendar belongs to).
    """
    memberships = event.get("event_memberships", [])
    for member in memberships:
        user_email = member.get("user_email", "").lower()
        for advisor_key, advisor_info in ADVISORS.items():
            if advisor_info["email"].lower() == user_email:
                return advisor_info["name"]

    # Fallback: check event name for advisor hints
    event_name = event.get("name", "").lower()
    for advisor_key, advisor_info in ADVISORS.items():
        if advisor_info["name"].lower().split()[0].lower() in event_name:
            return advisor_info["name"]

    # Default to first advisor
    return list(ADVISORS.values())[0]["name"]


def process_single_booking(event):
    """Process one Calendly booking — create/update the CRM contact."""
    event_name = event.get("name", "Unknown Event")
    start_time = event.get("start_time", "")
    event_uri = event.get("uri", "")

    print(f"\n{'─'*60}")
    print(f"  📅 Processing: {event_name}")
    print(f"     Scheduled: {start_time}")
    print(f"{'─'*60}")

    # Determine which advisor
    advisor_name = determine_advisor_from_event(event)
    print(f"  👤 Advisor: {advisor_name}")

    # Get invitee details
    invitees = get_event_invitees(event_uri)
    if not invitees:
        print("  ⚠️  No invitees found. Skipping.")
        return

    for invitee in invitees:
        inv_data = extract_invitee_data(invitee)
        crm_data = map_calendly_to_crm(inv_data)

        client_name = crm_data.get("name", "Unknown")
        client_email = crm_data.get("email", "")

        print(f"  👤 Client: {client_name}")
        print(f"  📧 Email: {client_email}")
        print(f"  📱 WhatsApp: {crm_data.get('whatsapp_number', 'Not provided')}")

        # Check if contact already exists
        existing_contact = None
        if client_email:
            existing_contact = find_contact_by_email(client_email)

        if existing_contact:
            print(f"  ✅ Contact already exists — updating with Calendly data")
            contact_id = existing_contact["id"]
        else:
            print(f"  📝 Creating new contact: {client_name}")
            new_contact = create_contact(
                name=client_name,
                email=client_email,
                assigned_advisor=advisor_name,
                pipeline_stage="New Lead"
            )
            if not new_contact:
                print(f"  ❌ Failed to create contact. Skipping.")
                continue
            contact_id = new_contact["id"]

        # Build the update payload with all Calendly data
        updates = {
            "Pipeline Stage": "Discovery Call Booked",
            "Assigned Advisor": advisor_name,
            "Last Contact Date": date.today().isoformat(),
            "Lead Source": "Calendly"
        }

        # Add email if available
        if client_email:
            updates["Email"] = client_email

        # Add WhatsApp number
        if crm_data.get("whatsapp_number"):
            updates["WhatsApp Number"] = crm_data["whatsapp_number"]

        # Add location
        if crm_data.get("location"):
            updates["Location"] = crm_data["location"]

        # Add lead qualification data from routing form
        if crm_data.get("investing_timeline"):
            updates["Investing Timeline"] = crm_data["investing_timeline"]

        if crm_data.get("annual_income"):
            updates["Annual Income"] = crm_data["annual_income"]

        if crm_data.get("monthly_surplus"):
            updates["Monthly Surplus"] = crm_data["monthly_surplus"]

        if crm_data.get("sip_interest"):
            updates["SIP Interest"] = crm_data["sip_interest"]

        if crm_data.get("lumpsum_interest"):
            updates["Lumpsum Interest"] = crm_data["lumpsum_interest"]

        if crm_data.get("investing_goals"):
            updates["Investing Goals"] = crm_data["investing_goals"]

        if crm_data.get("insurance_status"):
            updates["Insurance Status"] = crm_data["insurance_status"]

        # Event metadata
        updates["Calendly Event Type"] = event_name
        booking_date = start_time.split("T")[0] if "T" in start_time else date.today().isoformat()
        updates["Booking Date"] = booking_date

        # Update the contact in Notion
        update_contact(contact_id, updates)
        print(f"  ✅ Contact updated with all Calendly data")

        # Save to Google Contacts (shows name in WhatsApp)
        try:
            from google_contacts_helpers import save_to_google_contacts
            advisor_email = None
            for adv in ADVISORS.values():
                if adv["name"] == advisor_name:
                    advisor_email = adv["email"]
                    break
            save_to_google_contacts(
                name=client_name,
                phone=crm_data.get("whatsapp_number"),
                email=client_email,
                advisor_email=advisor_email
            )
        except Exception as e:
            print(f"  ⚠️ Google Contacts save failed: {e}")

        # Print summary
        print(f"\n  📊 LEAD QUALIFICATION SUMMARY:")
        print(f"     Timeline: {crm_data.get('investing_timeline', 'N/A')}")
        print(f"     Annual Income: {crm_data.get('annual_income', 'N/A')}")
        print(f"     Monthly Surplus: {crm_data.get('monthly_surplus', 'N/A')}")
        print(f"     SIP Interest: {crm_data.get('sip_interest', 'N/A')}")
        print(f"     Lumpsum Interest: {crm_data.get('lumpsum_interest', 'N/A')}")
        print(f"     Insurance: {crm_data.get('insurance_status', 'N/A')}")
        print(f"     Goals: {crm_data.get('investing_goals', 'N/A')[:80]}...")


def run_calendly_intake(days_back=1):
    """Main function — fetch recent Calendly bookings and process them."""
    print("\n" + "=" * 60)
    print("  📅 CALENDLY INTAKE AGENT — Starting")
    print(f"  Checking for bookings in the last {days_back} day(s)")
    print("=" * 60)

    events = get_recent_events(days_back=days_back)
    if not events:
        print("\n  No new bookings found. Nothing to process.")
        return

    for event in events:
        process_single_booking(event)

    print(f"\n{'='*60}")
    print(f"  🎉 Done! Processed {len(events)} booking(s).")
    print(f"{'='*60}")


# ══════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════
if __name__ == "__main__":
    days = 1
    if "--days" in sys.argv:
        try:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            days = 1

    run_calendly_intake(days_back=days)
