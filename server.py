"""
Webhook Server - Instant Meeting Processing + Dashboard
=========================================================
This runs a small web server that listens for Fireflies webhooks.
When a meeting transcript is ready, Fireflies pings this server,
and the Meeting Processor agent runs immediately.

Includes a live dashboard at /dashboard to monitor all agents.

HOW TO RUN:
  python3 server.py

REQUIREMENTS:
  pip3 install flask requests anthropic
"""

from flask import Flask, request, jsonify, Response, session, redirect, url_for
import threading
import json
import os
import time
import base64
from datetime import datetime, timedelta, timezone

from meeting_processor import process_single_meeting, run_meeting_processor
from calendly_intake import run_calendly_intake
from daily_lead_checker import run_daily_lead_checker
from advisor_call_review import run_call_review
from meeting_prep import run_meeting_prep
from config import ADVISORS
from activity_log import (
    log_agent_start, log_agent_complete, log_agent_error,
    log_action, get_dashboard_data
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "moneyiq-workflow-secret-2026")

# Simple auth token to protect cron endpoints (set this in env vars)
CRON_SECRET = os.environ.get("CRON_SECRET", "moneyiq-cron-2024")
# Optional: protect dashboard with a password
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

# Workflow login users: "username:password:role" — role is "admin" (sees all) or advisor name
# Format: WORKFLOW_USERS=udayan:pass123:admin,rishabh:pass456:Rishabh Mishra
_raw_users = os.environ.get("WORKFLOW_USERS", "udayan:moneyiq123:admin,rishabh:moneyiq123:Rishabh Mishra")
WORKFLOW_USERS = {}
for entry in _raw_users.split(","):
    parts = entry.strip().split(":", 2)
    if len(parts) == 3:
        WORKFLOW_USERS[parts[0]] = {"password": parts[1], "role": parts[2]}


def get_workflow_user():
    """Check if user is logged in to the workflow dashboard. Returns user dict or None."""
    username = session.get("workflow_user")
    if username and username in WORKFLOW_USERS:
        return {"username": username, **WORKFLOW_USERS[username]}
    return None

# Scheduled poll times in IST (24h format) — only check Fireflies at these hours
# 10:00 AM IST = catch any overnight transcripts before the day starts
# 8:00 PM IST = catch all daytime meetings after the last usual call
POLL_HOURS_IST = [int(h) for h in os.environ.get("POLL_HOURS_IST", "10,20").split(",")]

# Hour (IST) to run the meeting prep agent each morning
MEETING_PREP_HOUR_IST = int(os.environ.get("MEETING_PREP_HOUR_IST", 7))

# Server start time
SERVER_START_TIME = datetime.now().isoformat()

# Lock to prevent overlapping scheduler runs (if a run takes longer than the interval)
_processing_lock = threading.Lock()

# ══════════════════════════════════════════════
# INTERNAL SCHEDULER - polls at 10 AM and 8 PM IST only
# ══════════════════════════════════════════════

def _get_ist_now():
    """Get current time in IST (UTC+5:30)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)

def meeting_check_loop():
    """Background thread that runs scheduled tasks at IST times.
    - Fireflies polling at 10 AM and 8 PM IST
    - Meeting prep agent at 7 AM IST
    Webhook handles real-time meeting processing; polling is the safety net."""
    time.sleep(60)
    print(f"\n  SCHEDULER: Loop started (Fireflies poll {POLL_HOURS_IST} IST, prep {MEETING_PREP_HOUR_IST} IST)")

    last_poll_date_hour = None
    last_prep_date = None

    while True:
        ist_now = _get_ist_now()
        current_key = (ist_now.date(), ist_now.hour)

        # Fireflies polling
        if ist_now.hour in POLL_HOURS_IST and current_key != last_poll_date_hour:
            if _processing_lock.locked():
                print(f"\n  SCHEDULER: Previous run still in progress. Skipping.")
            else:
                with _processing_lock:
                    try:
                        print(f"\n{'='*60}")
                        print(f"  SCHEDULER: Fireflies poll at {ist_now.strftime('%I:%M %p IST')}")
                        print(f"{'='*60}")
                        logged_run_meeting_processor(1)
                        last_poll_date_hour = current_key
                    except Exception as e:
                        print(f"  SCHEDULER ERROR: {e}")
                        log_agent_error("scheduler", str(e))

        # Meeting prep at 7 AM IST (once per day)
        if ist_now.hour == MEETING_PREP_HOUR_IST and last_prep_date != ist_now.date():
            try:
                print(f"\n{'='*60}")
                print(f"  SCHEDULER: Meeting prep at {ist_now.strftime('%I:%M %p IST')}")
                print(f"{'='*60}")
                logged_run_meeting_prep()
                last_prep_date = ist_now.date()
            except Exception as e:
                print(f"  SCHEDULER ERROR (prep): {e}")
                log_agent_error("meeting_prep", str(e))

        # Check every 5 minutes if it's time to run anything
        time.sleep(300)


_scheduler_started = False
_scheduler_lock = threading.Lock()

def start_internal_scheduler():
    """Start the background meeting check scheduler.
    Uses a flag + lock to ensure only ONE scheduler runs,
    even if Gunicorn spawns multiple workers."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            print(f"  SCHEDULER: Already running in another thread. Skipping.")
            return
        _scheduler_started = True

    scheduler_thread = threading.Thread(
        target=meeting_check_loop,
        daemon=True,
        name="meeting-scheduler"
    )
    scheduler_thread.start()
    print(f"  SCHEDULER: Background meeting checker enabled (polls at {POLL_HOURS_IST} IST)")


# Start the scheduler when the module loads (works with Gunicorn)
start_internal_scheduler()


# ══════════════════════════════════════════════
# WRAPPED AGENT RUNNERS (with logging)
# ══════════════════════════════════════════════

def logged_process_single_meeting(transcript_id):
    """Wrap process_single_meeting with activity logging."""
    agent = "meeting_processor"
    log_agent_start(agent)
    try:
        result = process_single_meeting(transcript_id)
        content_ideas_count = len(result) if result else 0
        log_agent_complete(agent, {
            "transcript_id": transcript_id,
            "content_ideas": content_ideas_count
        })
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


def logged_run_meeting_processor(days_back):
    """Wrap run_meeting_processor with activity logging."""
    agent = "meeting_processor"
    log_agent_start(agent)
    try:
        run_meeting_processor(days_back)
        log_agent_complete(agent, {"days_back": days_back})
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


def logged_run_calendly_intake(days_back):
    """Wrap run_calendly_intake with activity logging."""
    agent = "calendly_intake"
    log_agent_start(agent)
    try:
        run_calendly_intake(days_back)
        log_agent_complete(agent, {"days_back": days_back})
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


def logged_run_daily_lead_checker():
    """Wrap run_daily_lead_checker with activity logging."""
    agent = "daily_lead_checker"
    log_agent_start(agent)
    try:
        run_daily_lead_checker()
        log_agent_complete(agent, {})
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


def logged_run_meeting_prep():
    """Wrap run_meeting_prep with activity logging."""
    agent = "meeting_prep"
    log_agent_start(agent)
    try:
        count = run_meeting_prep()
        log_agent_complete(agent, {"prep_docs": count})
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


def logged_run_call_review(days_back):
    """Wrap run_call_review with activity logging."""
    agent = "call_review"
    log_agent_start(agent)
    try:
        run_call_review(days_back)
        log_agent_complete(agent, {"days_back": days_back})
    except Exception as e:
        log_agent_error(agent, str(e))
        raise


# ══════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════

@app.route("/", methods=["GET"])
def home():
    """Health check - confirms the server is running."""
    return jsonify({
        "status": "running",
        "service": "MoneyIQ Agent Server",
        "started": SERVER_START_TIME,
        "dashboard": "/dashboard"
    })


@app.route("/webhook/fireflies", methods=["POST"])
def fireflies_webhook():
    """Receives webhook notifications from Fireflies."""
    print(f"\n{'='*60}")
    print(f"  WEBHOOK RECEIVED from Fireflies")
    print(f"{'='*60}")

    try:
        data = request.json or {}
        print(f"  Payload: {json.dumps(data, indent=2)[:500]}")

        log_action("webhook", "fireflies_received", {"payload_keys": list(data.keys())})

        transcript_id = (
            data.get("meetingId") or
            data.get("meeting_id") or
            data.get("transcriptId") or
            data.get("transcript_id") or
            data.get("id") or
            data.get("data", {}).get("meetingId") or
            data.get("data", {}).get("transcriptId")
        )

        if transcript_id:
            print(f"  Transcript ID: {transcript_id}")
            thread = threading.Thread(
                target=logged_process_single_meeting,
                args=(transcript_id,)
            )
            thread.start()
            return jsonify({"status": "processing", "transcript_id": transcript_id}), 200
        else:
            print("  No transcript ID in webhook - processing last day's meetings")
            thread = threading.Thread(
                target=logged_run_meeting_processor,
                args=(1,)
            )
            thread.start()
            return jsonify({"status": "processing_recent"}), 200

    except Exception as e:
        print(f"  Error processing webhook: {e}")
        log_agent_error("webhook", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/approve-meeting/<event_id>", methods=["GET"])
def approve_meeting(event_id):
    """Advisor clicks this link to approve a pending calendar invite."""
    advisor_email = request.args.get("advisor", "")
    print(f"\n  📅 MEETING APPROVAL: {event_id} by {advisor_email}")

    if not advisor_email:
        return "<h2>Error: Missing advisor email</h2>", 400

    try:
        from calendar_helpers import approve_and_send_invites
        success = approve_and_send_invites(advisor_email, event_id)

        if success:
            log_action("calendar", "meeting_approved", {
                "event_id": event_id, "advisor": advisor_email
            })
            return """
            <html>
            <body style="font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5;">
                <div style="text-align: center; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                    <h2 style="color: #1a7f37; margin-bottom: 8px;">Meeting Approved!</h2>
                    <p style="color: #666;">Calendar invites have been sent to all attendees.</p>
                    <p style="color: #999; font-size: 14px; margin-top: 16px;">You can close this tab.</p>
                </div>
            </body>
            </html>
            """, 200
        else:
            return """
            <html>
            <body style="font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5;">
                <div style="text-align: center; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                    <h2 style="color: #cf222e;">Could not approve meeting</h2>
                    <p style="color: #666;">The calendar service may not be connected. Please check your calendar token.</p>
                </div>
            </body>
            </html>
            """, 500
    except Exception as e:
        print(f"  Error approving meeting: {e}")
        return f"<h2>Error: {e}</h2>", 500


@app.route("/reject-meeting/<event_id>", methods=["GET"])
def reject_meeting(event_id):
    """Advisor clicks this link to reject/delete a pending calendar invite."""
    advisor_email = request.args.get("advisor", "")
    print(f"\n  🗑️ MEETING REJECTED: {event_id} by {advisor_email}")

    if not advisor_email:
        return "<h2>Error: Missing advisor email</h2>", 400

    try:
        from calendar_helpers import delete_meeting
        success = delete_meeting(advisor_email, event_id)

        log_action("calendar", "meeting_rejected", {
            "event_id": event_id, "advisor": advisor_email
        })

        return """
        <html>
        <body style="font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5;">
            <div style="text-align: center; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🗑️</div>
                <h2 style="color: #666;">Meeting Cancelled</h2>
                <p style="color: #999;">The pending calendar event has been removed.</p>
                <p style="color: #999; font-size: 14px; margin-top: 16px;">You can close this tab.</p>
            </div>
        </body>
        </html>
        """, 200
    except Exception as e:
        print(f"  Error rejecting meeting: {e}")
        return f"<h2>Error: {e}</h2>", 500


@app.route("/run", methods=["POST", "GET"])
def manual_run():
    """Manual trigger - run the meeting processor on demand."""
    days_back = request.args.get("days", 1, type=int)
    print(f"\n  Manual run triggered - processing last {days_back} day(s)")

    thread = threading.Thread(
        target=logged_run_meeting_processor,
        args=(days_back,)
    )
    thread.start()

    return jsonify({
        "status": "processing",
        "days_back": days_back,
        "message": f"Processing meetings from the last {days_back} day(s)"
    })


def check_cron_auth():
    """Check that cron requests have the correct secret."""
    token = request.args.get("secret") or request.headers.get("X-Cron-Secret")
    if token != CRON_SECRET:
        return False
    return True


@app.route("/cron/calendly-intake", methods=["GET", "POST"])
def cron_calendly_intake():
    """Scheduled: Pull new Calendly bookings into Notion CRM."""
    if not check_cron_auth():
        return jsonify({"error": "Unauthorized"}), 401

    days = request.args.get("days", 1, type=int)
    print(f"\n  CRON: Calendly intake (last {days} day(s))")
    thread = threading.Thread(target=logged_run_calendly_intake, args=(days,))
    thread.start()
    return jsonify({"status": "processing", "agent": "calendly_intake", "days": days})


@app.route("/cron/daily-lead-checker", methods=["GET", "POST"])
def cron_daily_lead_checker():
    """Scheduled: Check for stale leads, no-shows, overdue tasks."""
    if not check_cron_auth():
        return jsonify({"error": "Unauthorized"}), 401

    print(f"\n  CRON: Daily lead checker")
    thread = threading.Thread(target=logged_run_daily_lead_checker)
    thread.start()
    return jsonify({"status": "processing", "agent": "daily_lead_checker"})


@app.route("/cron/meeting-prep", methods=["GET", "POST"])
def cron_meeting_prep():
    """Scheduled: Generate morning meeting prep docs for today's meetings."""
    if not check_cron_auth():
        return jsonify({"error": "Unauthorized"}), 401

    print(f"\n  CRON: Meeting prep")
    thread = threading.Thread(target=logged_run_meeting_prep)
    thread.start()
    return jsonify({"status": "processing", "agent": "meeting_prep"})


@app.route("/cron/call-review", methods=["GET", "POST"])
def cron_call_review():
    """Scheduled: Weekly call review with coaching notes."""
    if not check_cron_auth():
        return jsonify({"error": "Unauthorized"}), 401

    days = request.args.get("days", 7, type=int)
    print(f"\n  CRON: Call review (last {days} days)")
    thread = threading.Thread(target=logged_run_call_review, args=(days,))
    thread.start()
    return jsonify({"status": "processing", "agent": "call_review", "days": days})


# ══════════════════════════════════════════════
# WORKFLOW DASHBOARD API (session-protected)
# ══════════════════════════════════════════════

def _require_workflow_auth():
    """Returns user dict if authenticated, or a 401 response."""
    user = get_workflow_user()
    if not user:
        return None
    return user


@app.route("/api/workflow/tasks", methods=["GET"])
def api_workflow_tasks():
    """Get action items from Notion Tasks DB with resolved contact names."""
    user = _require_workflow_auth()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    import requests as req
    from config import TASKS_DB_ID, NOTION_TOKEN
    from daily_lead_checker import get_task_field
    from notion_helpers import get_contact_field

    today = datetime.now().strftime("%Y-%m-%d")
    advisor_filter = request.args.get("advisor")
    if user["role"] != "admin":
        advisor_filter = user["role"]

    filter_conds = [
        {"property": "Status", "select": {"does_not_equal": "Done"}}
    ]
    if advisor_filter:
        filter_conds.append({"property": "Assigned To", "select": {"equals": advisor_filter}})

    payload = {
        "filter": {"and": filter_conds},
        "sorts": [{"property": "Due Date", "direction": "ascending"}],
        "page_size": 100
    }
    notion_headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    resp = req.post(f"https://api.notion.com/v1/databases/{TASKS_DB_ID}/query",
                    headers=notion_headers, json=payload)

    # Resolve contact names from relation IDs (batch to avoid N+1)
    contact_cache = {}

    def resolve_contact_name(task_page):
        rel = task_page.get("properties", {}).get("Contact", {}).get("relation", [])
        if not rel:
            return ""
        cid = rel[0].get("id", "")
        if cid in contact_cache:
            return contact_cache[cid]
        try:
            cr = req.get(f"https://api.notion.com/v1/pages/{cid}", headers=notion_headers)
            if cr.status_code == 200:
                name = get_contact_field(cr.json(), "Name") or ""
                contact_cache[cid] = name
                return name
        except Exception:
            pass
        contact_cache[cid] = ""
        return ""

    tasks = []
    if resp.status_code == 200:
        for t in resp.json().get("results", []):
            due = get_task_field(t, "Due Date") or ""
            tasks.append({
                "id": t["id"],
                "task": get_task_field(t, "Task") or "",
                "assigned_to": get_task_field(t, "Assigned To") or "",
                "status": get_task_field(t, "Status") or "",
                "due_date": due,
                "priority": get_task_field(t, "Priority") or "",
                "contact_name": resolve_contact_name(t),
                "overdue": due < today if due else False,
                "due_today": due == today if due else False,
            })
    return jsonify(tasks)


@app.route("/api/workflow/tasks/<task_id>/complete", methods=["POST"])
def api_complete_task(task_id):
    """Mark a task as Done in Notion."""
    import requests as req
    headers = {
        "Authorization": f"Bearer {os.environ.get('NOTION_TOKEN', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    resp = req.patch(f"https://api.notion.com/v1/pages/{task_id}",
                     headers=headers,
                     json={"properties": {"Status": {"select": {"name": "Done"}}}})
    return jsonify({"ok": resp.status_code == 200})


@app.route("/api/workflow/followups", methods=["GET"])
def api_workflow_followups():
    """Get pending/ready follow-ups for the dashboard."""
    user = _require_workflow_auth()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    from followup_manager import get_dashboard_followups, get_todays_followups
    advisor = request.args.get("advisor")
    if user["role"] != "admin":
        advisor = user["role"]

    # First get Ready items (processed by daily checker)
    items = get_dashboard_followups(advisor)

    # Also include Pending items scheduled for today or earlier (not yet processed)
    pending = get_todays_followups(advisor)
    from followup_manager import get_followup_field
    ready_ids = {i["id"] for i in items}

    for p in pending:
        if p["id"] not in ready_ids:
            items.append({
                "id": p["id"],
                "touchpoint": get_followup_field(p, "Touchpoint"),
                "client_name": get_followup_field(p, "Client Name"),
                "channel": get_followup_field(p, "Channel"),
                "message": get_followup_field(p, "Message Content"),
                "whatsapp_link": get_followup_field(p, "WhatsApp Link"),
                "email_subject": get_followup_field(p, "Email Subject"),
                "client_email": get_followup_field(p, "Client Email"),
                "scheduled_date": get_followup_field(p, "Scheduled Date"),
                "advisor": get_followup_field(p, "Advisor"),
                "sequence_num": get_followup_field(p, "Sequence Number"),
                "contact_id": get_followup_field(p, "Contact ID"),
            })

    return jsonify(items)


@app.route("/api/workflow/followups/<followup_id>/send", methods=["POST"])
def api_send_followup(followup_id):
    """Send a follow-up email and mark as sent."""
    from followup_manager import mark_as_sent, get_followup_field
    import requests as req

    # Get the followup details
    headers = {
        "Authorization": f"Bearer {os.environ.get('NOTION_TOKEN', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    resp = req.get(f"https://api.notion.com/v1/pages/{followup_id}", headers=headers)
    if resp.status_code != 200:
        return jsonify({"ok": False, "error": "Not found"}), 404

    fp = resp.json()
    channel = get_followup_field(fp, "Channel")
    client_email = get_followup_field(fp, "Client Email")
    advisor_name = get_followup_field(fp, "Advisor")
    message = request.json.get("message") or get_followup_field(fp, "Message Content")
    subject = request.json.get("subject") or get_followup_field(fp, "Email Subject")

    if channel == "Email" and client_email:
        advisor_email = None
        for adv in ADVISORS.values():
            if adv["name"] == advisor_name:
                advisor_email = adv["email"]
                break
        if advisor_email:
            from gmail_helpers import send_email as gmail_send
            gmail_send(
                sender=f"{advisor_name} <{advisor_email}>",
                to=client_email,
                subject=subject or f"Following up - {advisor_name.split()[0]}",
                body=message
            )

    mark_as_sent(followup_id)
    return jsonify({"ok": True})


@app.route("/api/workflow/followups/<followup_id>/skip", methods=["POST"])
def api_skip_followup(followup_id):
    """Skip a follow-up."""
    from followup_manager import update_followup_status
    reason = request.json.get("reason", "Skipped from dashboard")
    update_followup_status(followup_id, "Skipped", skip_reason=reason)
    return jsonify({"ok": True})


@app.route("/api/workflow/followups/<followup_id>/snooze", methods=["POST"])
def api_snooze_followup(followup_id):
    """Snooze a follow-up by X days."""
    import requests as req
    days = request.json.get("days", 2)
    new_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    headers = {
        "Authorization": f"Bearer {os.environ.get('NOTION_TOKEN', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    req.patch(f"https://api.notion.com/v1/pages/{followup_id}",
              headers=headers,
              json={"properties": {
                  "Scheduled Date": {"date": {"start": new_date}},
                  "Status": {"select": {"name": "Pending"}}
              }})
    return jsonify({"ok": True, "new_date": new_date})


# ══════════════════════════════════════════════
# DASHBOARD API
# ══════════════════════════════════════════════

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """API endpoint for dashboard data."""
    data = get_dashboard_data()
    data["server_start"] = SERVER_START_TIME
    data["server_time"] = datetime.now().isoformat()
    return jsonify(data)


# ══════════════════════════════════════════════
# DASHBOARD HTML
# ══════════════════════════════════════════════

@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Live dashboard showing all agent activity."""
    # Optional password protection
    if DASHBOARD_PASSWORD:
        pwd = request.args.get("pwd", "")
        if pwd != DASHBOARD_PASSWORD:
            return "Access denied. Add ?pwd=your_password to the URL.", 401

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoneyIQ Agent Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1117;
            color: #e1e4e8;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%);
            border-bottom: 1px solid #2d333b;
            padding: 20px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 22px;
            font-weight: 600;
            color: #f0f3f6;
        }
        .header h1 span {
            color: #58a6ff;
        }
        .header-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .server-status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #8b949e;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #3fb950;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .refresh-btn {
            background: #21262d;
            border: 1px solid #363b42;
            color: #c9d1d9;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: background 0.2s;
        }
        .refresh-btn:hover { background: #30363d; }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 10px;
            padding: 20px;
            transition: border-color 0.2s;
        }
        .card:hover { border-color: #363b42; }
        .card-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #8b949e;
            margin-bottom: 8px;
        }
        .card-value {
            font-size: 28px;
            font-weight: 700;
            color: #f0f3f6;
        }
        .card-sub {
            font-size: 12px;
            color: #8b949e;
            margin-top: 4px;
        }
        .agent-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .agent-card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 10px;
            padding: 20px;
            position: relative;
            overflow: hidden;
        }
        .agent-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
        }
        .agent-card.idle::before { background: #363b42; }
        .agent-card.running::before { background: #58a6ff; animation: shimmer 1.5s infinite; }
        .agent-card.error::before { background: #f85149; }
        .agent-card.never::before { background: #363b42; }
        @keyframes shimmer {
            0% { opacity: 0.5; }
            50% { opacity: 1; }
            100% { opacity: 0.5; }
        }
        .agent-name {
            font-size: 16px;
            font-weight: 600;
            color: #f0f3f6;
            margin-bottom: 4px;
        }
        .agent-desc {
            font-size: 12px;
            color: #8b949e;
            margin-bottom: 12px;
        }
        .agent-status {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-idle {
            background: #1c2128;
            color: #8b949e;
            border: 1px solid #363b42;
        }
        .status-running {
            background: #0d2137;
            color: #58a6ff;
            border: 1px solid #1f4a7a;
        }
        .status-error {
            background: #3d1418;
            color: #f85149;
            border: 1px solid #6e3630;
        }
        .status-never {
            background: #1c2128;
            color: #6e7681;
            border: 1px solid #2d333b;
        }
        .agent-meta {
            margin-top: 12px;
            font-size: 12px;
            color: #8b949e;
            line-height: 1.6;
        }
        .agent-meta strong { color: #c9d1d9; }
        .agent-actions {
            margin-top: 12px;
            display: flex;
            gap: 8px;
        }
        .run-btn {
            background: #21262d;
            border: 1px solid #363b42;
            color: #58a6ff;
            padding: 5px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
        }
        .run-btn:hover {
            background: #0d2137;
            border-color: #1f4a7a;
        }
        .run-btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        .section-title {
            font-size: 16px;
            font-weight: 600;
            color: #f0f3f6;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .activity-feed {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 10px;
            overflow: hidden;
        }
        .activity-item {
            display: flex;
            align-items: flex-start;
            padding: 12px 20px;
            border-bottom: 1px solid #21262d;
            gap: 12px;
            font-size: 13px;
            transition: background 0.15s;
        }
        .activity-item:hover { background: #1c2128; }
        .activity-item:last-child { border-bottom: none; }
        .activity-icon {
            width: 28px;
            height: 28px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            flex-shrink: 0;
            margin-top: 2px;
        }
        .icon-started {
            background: #0d2137;
            color: #58a6ff;
        }
        .icon-completed {
            background: #0d2d1a;
            color: #3fb950;
        }
        .icon-error {
            background: #3d1418;
            color: #f85149;
        }
        .icon-action {
            background: #2d1f00;
            color: #d29922;
        }
        .activity-content { flex: 1; }
        .activity-agent {
            font-weight: 600;
            color: #c9d1d9;
        }
        .activity-event { color: #8b949e; }
        .activity-time {
            font-size: 12px;
            color: #6e7681;
            white-space: nowrap;
        }
        .activity-details {
            font-size: 11px;
            color: #6e7681;
            margin-top: 2px;
        }
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #6e7681;
        }
        .auto-refresh-note {
            text-align: center;
            padding: 12px;
            font-size: 11px;
            color: #484f58;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span>MoneyIQ</span> Agent Dashboard</h1>
        <div class="header-right">
            <div class="server-status">
                <div class="status-dot"></div>
                <span id="server-uptime">Server running</span>
            </div>
            <button class="refresh-btn" onclick="loadData()">Refresh</button>
        </div>
    </div>

    <div class="container">
        <!-- Time Saved Cards -->
        <div class="section-title">Time Saved</div>
        <div class="grid" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 24px;">
            <div class="card" style="border-color: #1f4a7a;">
                <div class="card-label">Today</div>
                <div class="card-value" style="color: #58a6ff;" id="time-today">-</div>
                <div class="card-sub" id="time-today-sub">hours saved</div>
            </div>
            <div class="card" style="border-color: #1f4a7a;">
                <div class="card-label">This Week</div>
                <div class="card-value" style="color: #58a6ff;" id="time-week">-</div>
                <div class="card-sub" id="time-week-sub">hours saved</div>
            </div>
            <div class="card" style="border-color: #1f4a7a;">
                <div class="card-label">Lifetime</div>
                <div class="card-value" style="color: #58a6ff;" id="time-lifetime">-</div>
                <div class="card-sub" id="time-lifetime-sub">hours saved</div>
            </div>
        </div>

        <!-- Summary Cards -->
        <div class="grid" id="summary-cards">
            <div class="card">
                <div class="card-label">Total Agent Runs</div>
                <div class="card-value" id="total-runs">-</div>
                <div class="card-sub" id="total-runs-sub">Loading...</div>
            </div>
            <div class="card">
                <div class="card-label">Active Agents</div>
                <div class="card-value" id="active-agents">-</div>
                <div class="card-sub">Currently running</div>
            </div>
            <div class="card">
                <div class="card-label">Last Activity</div>
                <div class="card-value" id="last-activity" style="font-size:18px">-</div>
                <div class="card-sub" id="last-activity-sub"></div>
            </div>
            <div class="card">
                <div class="card-label">Errors (24h)</div>
                <div class="card-value" id="error-count">-</div>
                <div class="card-sub" id="error-sub">Across all agents</div>
            </div>
        </div>

        <!-- Agent Status -->
        <div class="section-title">Agent Status</div>
        <div class="agent-grid" id="agent-grid">
            <!-- Filled by JS -->
        </div>

        <!-- Recent Activity -->
        <div class="section-title">Recent Activity</div>
        <div class="activity-feed" id="activity-feed">
            <div class="empty-state">Loading activity...</div>
        </div>
        <div class="auto-refresh-note">Auto-refreshes every 30 seconds</div>
    </div>

    <script>
        const AGENTS = {
            "meeting_processor": {
                name: "Meeting Processor",
                desc: "Analyzes Fireflies transcripts, updates CRM, drafts emails",
                trigger: "Auto - every 15 min",
                runUrl: "/run"
            },
            "calendly_intake": {
                name: "Calendly Intake",
                desc: "Pulls new bookings into Notion CRM",
                trigger: "Cron - every 15 min",
                runUrl: null
            },
            "daily_lead_checker": {
                name: "Daily Lead Checker",
                desc: "Flags stale leads, no-shows, overdue tasks",
                trigger: "Cron - daily 8 AM",
                runUrl: null
            },
            "calendar_agent": {
                name: "Calendar Agent",
                desc: "Detects next meeting from transcript, creates pending invite for approval",
                trigger: "Auto (via Meeting Processor)",
                runUrl: null
            },
            "call_review": {
                name: "Call Review",
                desc: "Weekly advisor performance report with coaching notes",
                trigger: "Cron - weekly Monday",
                runUrl: null
            }
        };

        function timeAgo(isoStr) {
            if (!isoStr) return "Never";
            const diff = Date.now() - new Date(isoStr).getTime();
            const mins = Math.floor(diff / 60000);
            if (mins < 1) return "Just now";
            if (mins < 60) return mins + "m ago";
            const hrs = Math.floor(mins / 60);
            if (hrs < 24) return hrs + "h ago";
            const days = Math.floor(hrs / 24);
            return days + "d ago";
        }

        function formatTime(isoStr) {
            if (!isoStr) return "";
            const d = new Date(isoStr);
            return d.toLocaleString('en-IN', {
                day: 'numeric', month: 'short',
                hour: '2-digit', minute: '2-digit',
                hour12: true
            });
        }

        function agentDisplayName(key) {
            return AGENTS[key] ? AGENTS[key].name : key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        }

        function eventIcon(event) {
            switch(event) {
                case 'started': return { icon: '>', cls: 'icon-started' };
                case 'completed': return { icon: '✓', cls: 'icon-completed' };
                case 'error': return { icon: '!', cls: 'icon-error' };
                case 'action': return { icon: '~', cls: 'icon-action' };
                default: return { icon: '-', cls: 'icon-action' };
            }
        }

        async function loadData() {
            try {
                const res = await fetch('/api/dashboard');
                const data = await res.json();
                render(data);
            } catch(e) {
                console.error('Failed to load dashboard data:', e);
            }
        }

        function render(data) {
            const stats = data.stats || {};
            const activity = data.recent_activity || [];
            const timeSaved = data.time_saved || {};

            // Time saved cards
            const todayH = timeSaved.today_hours || 0;
            const weekH = timeSaved.week_hours || 0;
            const lifeH = timeSaved.lifetime_hours || 0;
            document.getElementById('time-today').textContent = todayH + 'h';
            document.getElementById('time-today-sub').textContent = (timeSaved.today_minutes || 0) + ' minutes saved';
            document.getElementById('time-week').textContent = weekH + 'h';
            document.getElementById('time-week-sub').textContent = (timeSaved.week_minutes || 0) + ' minutes saved';
            document.getElementById('time-lifetime').textContent = lifeH + 'h';
            document.getElementById('time-lifetime-sub').textContent = (timeSaved.lifetime_minutes || 0) + ' minutes saved';

            // Summary cards
            let totalRuns = 0;
            let activeCount = 0;
            let lastTime = null;
            let errorCount = 0;
            const now = Date.now();
            const day = 24 * 60 * 60 * 1000;

            Object.values(stats).forEach(s => {
                totalRuns += (s.total_runs || 0);
                if (s.status === 'running') activeCount++;
                if (s.last_completed && (!lastTime || s.last_completed > lastTime)) {
                    lastTime = s.last_completed;
                }
                if (s.last_error_time && (now - new Date(s.last_error_time).getTime()) < day) {
                    errorCount++;
                }
            });

            document.getElementById('total-runs').textContent = totalRuns;
            document.getElementById('total-runs-sub').textContent = 'Since server start';
            document.getElementById('active-agents').textContent = activeCount;
            document.getElementById('last-activity').textContent = lastTime ? timeAgo(lastTime) : 'No activity yet';
            document.getElementById('last-activity-sub').textContent = lastTime ? formatTime(lastTime) : '';
            document.getElementById('error-count').textContent = errorCount;

            // Uptime
            if (data.server_start) {
                const upMins = Math.floor((now - new Date(data.server_start).getTime()) / 60000);
                let upStr = '';
                if (upMins < 60) upStr = upMins + ' min';
                else if (upMins < 1440) upStr = Math.floor(upMins/60) + 'h ' + (upMins%60) + 'm';
                else upStr = Math.floor(upMins/1440) + 'd ' + Math.floor((upMins%1440)/60) + 'h';
                document.getElementById('server-uptime').textContent = 'Up ' + upStr;
            }

            // Agent cards
            const agentGrid = document.getElementById('agent-grid');
            agentGrid.innerHTML = '';

            Object.entries(AGENTS).forEach(([key, info]) => {
                const s = stats[key] || {};
                const status = s.status || 'never';
                const card = document.createElement('div');
                card.className = 'agent-card ' + status;

                let statusBadge = '';
                switch(status) {
                    case 'running':
                        statusBadge = '<span class="agent-status status-running">Running</span>';
                        break;
                    case 'error':
                        statusBadge = '<span class="agent-status status-error">Error</span>';
                        break;
                    case 'idle':
                        statusBadge = '<span class="agent-status status-idle">Idle</span>';
                        break;
                    default:
                        statusBadge = '<span class="agent-status status-never">Never run</span>';
                }

                let meta = '';
                if (s.last_completed) {
                    meta += '<div><strong>Last run:</strong> ' + timeAgo(s.last_completed) + ' (' + formatTime(s.last_completed) + ')</div>';
                }
                if (s.total_runs) {
                    meta += '<div><strong>Total runs:</strong> ' + s.total_runs + '</div>';
                }
                if (s.last_error) {
                    meta += '<div style="color:#f85149"><strong>Last error:</strong> ' + s.last_error.substring(0, 100) + '</div>';
                }
                meta += '<div><strong>Trigger:</strong> ' + info.trigger + '</div>';

                let actions = '';
                if (info.runUrl) {
                    actions = '<div class="agent-actions"><button class="run-btn" onclick="triggerAgent(\'' + info.runUrl + '\', this)">Run Now</button></div>';
                }

                card.innerHTML = `
                    <div class="agent-name">${info.name}</div>
                    <div class="agent-desc">${info.desc}</div>
                    ${statusBadge}
                    <div class="agent-meta">${meta}</div>
                    ${actions}
                `;
                agentGrid.appendChild(card);
            });

            // Activity feed
            const feed = document.getElementById('activity-feed');
            if (activity.length === 0) {
                feed.innerHTML = '<div class="empty-state">No activity yet. Agents will appear here once they run.</div>';
                return;
            }

            feed.innerHTML = '';
            // Show newest first
            const reversed = [...activity].reverse();
            reversed.forEach(item => {
                const { icon, cls } = eventIcon(item.event);
                const div = document.createElement('div');
                div.className = 'activity-item';

                let details = '';
                if (item.event === 'error' && item.details && item.details.error) {
                    details = '<div class="activity-details" style="color:#f85149">' + item.details.error.substring(0, 120) + '</div>';
                } else if (item.event === 'action' && item.action) {
                    details = '<div class="activity-details">' + item.action + '</div>';
                } else if (item.event === 'completed' && item.details) {
                    const d = item.details;
                    const parts = [];
                    if (d.transcript_id) parts.push('Transcript: ' + d.transcript_id.substring(0, 12) + '...');
                    if (d.days_back) parts.push(d.days_back + ' day(s) processed');
                    if (d.content_ideas) parts.push(d.content_ideas + ' content ideas');
                    if (parts.length) details = '<div class="activity-details">' + parts.join(' | ') + '</div>';
                }

                div.innerHTML = `
                    <div class="activity-icon ${cls}">${icon}</div>
                    <div class="activity-content">
                        <span class="activity-agent">${agentDisplayName(item.agent)}</span>
                        <span class="activity-event"> ${item.event}</span>
                        ${details}
                    </div>
                    <div class="activity-time">${timeAgo(item.timestamp)}</div>
                `;
                feed.appendChild(div);
            });
        }

        async function triggerAgent(url, btn) {
            btn.disabled = true;
            btn.textContent = 'Starting...';
            try {
                await fetch(url);
                setTimeout(() => {
                    loadData();
                    btn.disabled = false;
                    btn.textContent = 'Run Now';
                }, 2000);
            } catch(e) {
                btn.textContent = 'Failed';
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = 'Run Now';
                }, 3000);
            }
        }

        // Initial load
        loadData();

        // Auto-refresh every 30 seconds
        setInterval(loadData, 30000);
    </script>
</body>
</html>"""
    return html


# ══════════════════════════════════════════════
# WORKFLOW LOGIN + DASHBOARD
# ══════════════════════════════════════════════

WORKFLOW_LOGIN_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MoneyIQ - Login</title>
<style>
body { font-family: -apple-system, sans-serif; background: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
.login-box { background: white; padding: 40px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); width: 340px; }
h1 { font-size: 20px; margin: 0 0 8px; color: #1e293b; }
p { font-size: 13px; color: #94a3b8; margin: 0 0 24px; }
label { font-size: 13px; color: #475569; font-weight: 500; display: block; margin-bottom: 4px; }
input { width: 100%; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; margin-bottom: 16px; box-sizing: border-box; }
input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
button { width: 100%; padding: 10px; background: #2563eb; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }
button:hover { background: #1d4ed8; }
.error { color: #dc2626; font-size: 13px; margin-bottom: 12px; }
</style></head><body>
<div class="login-box">
<h1>MoneyIQ Workflow</h1>
<p>Sign in to access your dashboard</p>
{error}
<form method="POST" action="/workflow/login">
<label>Username</label><input name="username" autofocus required>
<label>Password</label><input name="password" type="password" required>
<button type="submit">Sign In</button>
</form></div></body></html>"""


@app.route("/workflow/login", methods=["GET", "POST"])
def workflow_login():
    if request.method == "GET":
        return WORKFLOW_LOGIN_HTML.replace("{error}", "")

    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    user = WORKFLOW_USERS.get(username)
    if user and user["password"] == password:
        session["workflow_user"] = username
        return redirect("/workflow")

    return WORKFLOW_LOGIN_HTML.replace("{error}", '<div class="error">Invalid username or password</div>')


@app.route("/workflow/logout")
def workflow_logout():
    session.pop("workflow_user", None)
    return redirect("/workflow/login")


@app.route("/workflow", methods=["GET"])
def workflow_dashboard():
    """Clean workflow interface — login required, role-based filtering."""
    user = get_workflow_user()
    if not user:
        return redirect("/workflow/login")

    from workflow_dashboard import WORKFLOW_HTML

    # Inject user info into the HTML so JS can filter by role
    user_json = json.dumps({"username": user["username"], "role": user["role"]})
    injected = WORKFLOW_HTML.replace(
        "let currentTab = 'tasks';",
        f"const CURRENT_USER = {user_json};\n    let currentTab = 'tasks';"
    )
    return injected


# ══════════════════════════════════════════════
# FOLLOW-UP SYSTEM - Dashboard, Tracking Pixel, Daily Scheduler
# ══════════════════════════════════════════════

from followup_manager import (
    process_due_followups, get_dashboard_followups,
    mark_as_sent, mark_email_opened, get_followup_field,
    update_followup_status, send_whatsapp_message
)
from config import ADVISORS as ADVISOR_CONFIG

# 1x1 transparent PNG pixel (for email open tracking)
TRACKING_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@app.route("/track/open/<page_id>.png", methods=["GET"])
def tracking_pixel(page_id):
    """Serve a 1x1 transparent PNG and mark the follow-up email as opened."""
    try:
        mark_email_opened(page_id)
        print(f"  📬 Email opened — follow-up {page_id[:8]}...")
    except Exception as e:
        print(f"  ⚠️ Tracking pixel error: {e}")

    return Response(TRACKING_PIXEL, mimetype="image/png", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache"
    })


@app.route("/followups/send/<page_id>", methods=["POST", "GET"])
def followup_send(page_id):
    """Mark a follow-up as sent (advisor clicked Send on dashboard)."""
    try:
        mark_as_sent(page_id)
        return jsonify({"status": "sent", "page_id": page_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/followups/skip/<page_id>", methods=["POST", "GET"])
def followup_skip(page_id):
    """Skip a follow-up touchpoint."""
    reason = request.args.get("reason", "Manually skipped by advisor")
    try:
        update_followup_status(page_id, "Skipped", skip_reason=reason)
        return jsonify({"status": "skipped", "page_id": page_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/cron/process-followups", methods=["GET", "POST"])
def cron_process_followups():
    """Scheduled: Process due follow-ups (run daily at 9 AM IST)."""
    if not check_cron_auth():
        return jsonify({"error": "Unauthorized"}), 401

    print(f"\n  CRON: Processing due follow-ups")
    thread = threading.Thread(target=_logged_process_followups)
    thread.start()
    return jsonify({"status": "processing", "agent": "followup_manager"})


def _logged_process_followups():
    """Wrap process_due_followups with logging."""
    log_agent_start("followup_manager")
    try:
        process_due_followups()
        log_agent_complete("followup_manager", {})
    except Exception as e:
        log_agent_error("followup_manager", str(e))


@app.route("/followups", methods=["GET"])
def followup_dashboard():
    """Advisor dashboard - review and send follow-up messages."""
    # Optional password protection (same as main dashboard)
    if DASHBOARD_PASSWORD:
        pwd = request.args.get("pwd", "")
        if pwd != DASHBOARD_PASSWORD:
            return "Access denied. Add ?pwd=your_password to the URL.", 401

    advisor_filter = request.args.get("advisor", None)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoneyIQ - Follow-Up Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1117;
            color: #e1e4e8;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%);
            border-bottom: 1px solid #2d333b;
            padding: 20px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { font-size: 22px; font-weight: 600; color: #f0f3f6; }
        .header h1 span { color: #58a6ff; }
        .header-right { display: flex; align-items: center; gap: 12px; }
        .btn {
            padding: 8px 16px;
            border-radius: 6px;
            border: 1px solid #363b42;
            background: #21262d;
            color: #c9d1d9;
            cursor: pointer;
            font-size: 13px;
            text-decoration: none;
            transition: background 0.2s;
        }
        .btn:hover { background: #30363d; }
        .btn-send {
            background: #238636;
            border-color: #2ea043;
            color: #fff;
        }
        .btn-send:hover { background: #2ea043; }
        .btn-skip {
            background: #21262d;
            border-color: #363b42;
            color: #8b949e;
        }
        .btn-wa {
            background: #25d366;
            border-color: #25d366;
            color: #fff;
        }
        .btn-wa:hover { background: #1da851; }
        .container { max-width: 1000px; margin: 0 auto; padding: 24px; }
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 24px;
        }
        .stat-card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 10px;
            padding: 16px;
            text-align: center;
        }
        .stat-value { font-size: 28px; font-weight: 700; color: #f0f3f6; }
        .stat-label { font-size: 12px; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .followup-card {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 12px;
            transition: border-color 0.2s;
        }
        .followup-card:hover { border-color: #363b42; }
        .followup-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .client-name { font-size: 16px; font-weight: 600; color: #f0f3f6; }
        .channel-badge {
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .channel-whatsapp { background: rgba(37, 211, 102, 0.15); color: #25d366; }
        .channel-email { background: rgba(88, 166, 255, 0.15); color: #58a6ff; }
        .followup-meta {
            display: flex;
            gap: 16px;
            margin-bottom: 12px;
            font-size: 12px;
            color: #8b949e;
        }
        .followup-meta span { display: flex; align-items: center; gap: 4px; }
        .message-preview {
            background: #0d1117;
            border: 1px solid #21262d;
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 14px;
            font-size: 14px;
            line-height: 1.5;
            color: #c9d1d9;
            white-space: pre-wrap;
            max-height: 200px;
            overflow-y: auto;
        }
        .followup-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin: 24px 0 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #21262d;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #8b949e;
        }
        .empty-state .icon { font-size: 48px; margin-bottom: 12px; }
        .filter-bar {
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
        }
        .filter-btn {
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid #363b42;
            background: transparent;
            color: #8b949e;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .filter-btn.active {
            background: #58a6ff;
            border-color: #58a6ff;
            color: #fff;
        }
        .subject-line {
            font-size: 12px;
            color: #58a6ff;
            margin-bottom: 8px;
        }
        .replied-badge {
            background: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            padding: 2px 8px;
            border-radius: 8px;
            font-size: 11px;
        }
        .opened-badge {
            background: rgba(210, 153, 34, 0.15);
            color: #d29922;
            padding: 2px 8px;
            border-radius: 8px;
            font-size: 11px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>MoneyIQ <span>Follow-Ups</span></h1>
        <div class="header-right">
            <a href="/dashboard" class="btn">Main Dashboard</a>
            <button class="btn" onclick="loadFollowups()">Refresh</button>
        </div>
    </div>

    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value" id="stat-ready">-</div>
                <div class="stat-label">Ready to Send</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-pending">-</div>
                <div class="stat-label">Upcoming</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-sent">-</div>
                <div class="stat-label">Sent Today</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-replied">-</div>
                <div class="stat-label">Client Replies</div>
            </div>
        </div>

        <div class="filter-bar" id="filter-bar">
            <button class="filter-btn active" data-filter="all" onclick="filterCards('all', this)">All</button>
            <button class="filter-btn" data-filter="WhatsApp" onclick="filterCards('WhatsApp', this)">WhatsApp</button>
            <button class="filter-btn" data-filter="Email" onclick="filterCards('Email', this)">Email</button>
        </div>

        <div id="followup-list">
            <div class="empty-state">
                <div class="icon">Loading...</div>
            </div>
        </div>
    </div>

    <script>
        let allFollowups = [];

        async function loadFollowups() {
            try {
                const resp = await fetch('/api/followups""" + (f"?advisor={advisor_filter}" if advisor_filter else "") + """');
                const data = await resp.json();
                allFollowups = data.followups || [];

                // Update stats
                document.getElementById('stat-ready').textContent = data.stats?.ready || 0;
                document.getElementById('stat-pending').textContent = data.stats?.pending || 0;
                document.getElementById('stat-sent').textContent = data.stats?.sent_today || 0;
                document.getElementById('stat-replied').textContent = data.stats?.replied || 0;

                renderFollowups(allFollowups);
            } catch(e) {
                document.getElementById('followup-list').innerHTML =
                    '<div class="empty-state"><div class="icon">Error</div><p>Could not load follow-ups</p></div>';
            }
        }

        function renderFollowups(items) {
            const container = document.getElementById('followup-list');
            if (!items.length) {
                container.innerHTML = '<div class="empty-state"><div class="icon">All clear</div><p>No follow-ups ready to send right now. Check back tomorrow at 9 AM.</p></div>';
                return;
            }

            let html = '';
            items.forEach(fu => {
                const channelClass = fu.channel === 'WhatsApp' ? 'channel-whatsapp' : 'channel-email';
                const badges = [];
                if (fu.client_replied) badges.push('<span class="replied-badge">Replied</span>');
                if (fu.email_opened) badges.push('<span class="opened-badge">Opened</span>');

                let actions = '';
                if (fu.channel === 'WhatsApp' && fu.whatsapp_link) {
                    actions = `
                        <a href="${fu.whatsapp_link}" target="_blank" class="btn btn-wa" onclick="markSent('${fu.id}')">Open WhatsApp</a>
                        <button class="btn btn-skip" onclick="skipFollowup('${fu.id}')">Skip</button>
                    `;
                } else if (fu.channel === 'Email') {
                    actions = `
                        <button class="btn btn-send" onclick="markSent('${fu.id}')">Mark Sent (Draft in Gmail)</button>
                        <button class="btn btn-skip" onclick="skipFollowup('${fu.id}')">Skip</button>
                    `;
                } else {
                    actions = `
                        <button class="btn btn-send" onclick="markSent('${fu.id}')">Mark Sent</button>
                        <button class="btn btn-skip" onclick="skipFollowup('${fu.id}')">Skip</button>
                    `;
                }

                let subjectHtml = '';
                if (fu.email_subject) {
                    subjectHtml = `<div class="subject-line">Subject: ${fu.email_subject}</div>`;
                }

                html += `
                <div class="followup-card" data-channel="${fu.channel}" data-id="${fu.id}">
                    <div class="followup-header">
                        <span class="client-name">${fu.client_name || 'Unknown'}</span>
                        <div style="display:flex; gap:8px; align-items:center;">
                            ${badges.join('')}
                            <span class="channel-badge ${channelClass}">${fu.channel}</span>
                        </div>
                    </div>
                    <div class="followup-meta">
                        <span>Day ${fu.day_number} - ${fu.touchpoint_type || ''}</span>
                        <span>Advisor: ${fu.advisor || ''}</span>
                        <span>Scheduled: ${fu.scheduled_date || ''}</span>
                    </div>
                    ${subjectHtml}
                    <div class="message-preview">${fu.message || 'No message generated'}</div>
                    <div class="followup-actions">${actions}</div>
                </div>`;
            });
            container.innerHTML = html;
        }

        function filterCards(channel, btn) {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (channel === 'all') {
                renderFollowups(allFollowups);
            } else {
                renderFollowups(allFollowups.filter(fu => fu.channel === channel));
            }
        }

        async function markSent(pageId) {
            try {
                await fetch(`/followups/send/${pageId}`, {method: 'POST'});
                // Remove card from UI
                const card = document.querySelector(`[data-id="${pageId}"]`);
                if (card) card.style.display = 'none';
                // Update stat
                const el = document.getElementById('stat-ready');
                el.textContent = Math.max(0, parseInt(el.textContent) - 1);
            } catch(e) {
                alert('Failed to mark as sent');
            }
        }

        async function skipFollowup(pageId) {
            if (!confirm('Skip this follow-up?')) return;
            try {
                await fetch(`/followups/skip/${pageId}`);
                const card = document.querySelector(`[data-id="${pageId}"]`);
                if (card) card.style.display = 'none';
                const el = document.getElementById('stat-ready');
                el.textContent = Math.max(0, parseInt(el.textContent) - 1);
            } catch(e) {
                alert('Failed to skip');
            }
        }

        // Load on page open
        loadFollowups();
        // Auto-refresh every 60 seconds
        setInterval(loadFollowups, 60000);
    </script>
</body>
</html>"""
    return html


@app.route("/api/followups", methods=["GET"])
def api_followups():
    """API endpoint for follow-up dashboard data."""
    advisor_filter = request.args.get("advisor", None)

    try:
        # get_dashboard_followups returns pre-formatted dicts (not raw Notion pages)
        items = get_dashboard_followups(advisor_filter)

        # Stats
        ready = len(items)  # All returned items are "Ready" status
        pending = 0  # Would need a separate query for pending
        sent_today = 0  # Would need a separate query for sent today
        replied = sum(1 for i in items if i.get("client_replied"))

        return jsonify({
            "followups": items,
            "stats": {
                "ready": ready,
                "pending": pending,
                "sent_today": sent_today,
                "replied": replied
            }
        })
    except Exception as e:
        print(f"  ⚠️ Follow-up API error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"followups": [], "stats": {}, "error": str(e)}), 500


# ══════════════════════════════════════════════
# DAILY FOLLOW-UP SCHEDULER - runs at 9 AM IST
# ══════════════════════════════════════════════

FOLLOWUP_HOUR_IST = 9  # 9 AM IST

def followup_check_loop():
    """Background thread that processes due follow-ups at 9 AM IST daily."""
    time.sleep(120)  # Wait 2 min after startup
    print(f"\n  FOLLOWUP SCHEDULER: Started (runs daily at {FOLLOWUP_HOUR_IST}:00 IST)")

    last_run_date = None

    while True:
        ist_now = _get_ist_now()
        today = ist_now.date()

        # Run once per day at 9 AM IST (or later if server was down)
        if ist_now.hour >= FOLLOWUP_HOUR_IST and last_run_date != today:
            try:
                print(f"\n{'='*60}")
                print(f"  FOLLOWUP SCHEDULER: Processing due follow-ups at {ist_now.strftime('%I:%M %p IST')}")
                print(f"{'='*60}")
                process_due_followups()
                last_run_date = today
                log_agent_complete("followup_scheduler", {"date": today.isoformat()})
            except Exception as e:
                print(f"  FOLLOWUP SCHEDULER ERROR: {e}")
                log_agent_error("followup_scheduler", str(e))
                last_run_date = today  # Don't retry on error, wait for next day

        # Check every 10 minutes
        time.sleep(600)


_followup_scheduler_started = False
_followup_scheduler_lock = threading.Lock()

def start_followup_scheduler():
    """Start the daily follow-up processing scheduler."""
    global _followup_scheduler_started
    with _followup_scheduler_lock:
        if _followup_scheduler_started:
            return
        _followup_scheduler_started = True

    t = threading.Thread(target=followup_check_loop, daemon=True, name="followup-scheduler")
    t.start()
    print(f"  FOLLOWUP SCHEDULER: Daily follow-up checker enabled ({FOLLOWUP_HOUR_IST}:00 IST)")


# Start the follow-up scheduler when module loads
start_followup_scheduler()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  MoneyIQ AGENT SERVER")
    print("=" * 60)
    print()
    print("  Your agent is now listening for meetings.")
    print()
    print("  DASHBOARD:")
    print("  -------------------------------------------")
    print(f"  http://localhost:{port}/dashboard")
    print()
    print("  WEBHOOK SETUP (do this once in Fireflies):")
    print("  -------------------------------------------")
    print("  1. Go to Fireflies - Settings - Integrations - Webhooks")
    print("  2. Add a new webhook URL:")
    print()
    print("     For LOCAL testing:")
    print(f"     http://localhost:{port}/webhook/fireflies")
    print()
    print("     For DEPLOYED:")
    print("     https://your-server.com/webhook/fireflies")
    print()
    print("  3. Select event: 'Transcription complete'")
    print("  4. Save")
    print()
    print("  MANUAL TRIGGER:")
    print("  -------------------------------------------")
    print(f"  http://localhost:{port}/run")
    print(f"  http://localhost:{port}/run?days=7  (last 7 days)")
    print()
    print("=" * 60)
    print(f"  Server starting on http://localhost:{port}")
    print("=" * 60)
    print()

    app.run(host="0.0.0.0", port=port, debug=False)
