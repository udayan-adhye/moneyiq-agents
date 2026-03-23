"""
Activity Logger - Tracks all agent activity for the dashboard.
================================================================
Every agent logs its actions here. The dashboard reads from the log file.
"""

import json
import os
from datetime import datetime, date, timedelta

LOG_FILE = os.path.join(os.path.dirname(__file__), "agent_activity.json")
MAX_LOG_ENTRIES = 500  # Keep last 500 entries to prevent file from growing too large

# Estimated time saved per agent run (in minutes)
# These are conservative estimates of how long a human would take to do the same work
TIME_SAVED_MINUTES = {
    "meeting_processor": 25,      # Transcript review + CRM update + drafting 3-4 emails + creating tasks
    "calendly_intake": 10,        # Manually checking Calendly + entering data into Notion
    "daily_lead_checker": 10,     # Reviewing leads + checking overdue tasks + drafting nudge emails
    "call_review": 10,            # Reviewing calls + writing coaching notes + building report
    "webhook": 0                  # Internal event, no time saved
}


def _read_log():
    """Read the current log file."""
    if not os.path.exists(LOG_FILE):
        return {"runs": [], "stats": {}}
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"runs": [], "stats": {}}


def _write_log(data):
    """Write to the log file."""
    # Trim to max entries
    if len(data.get("runs", [])) > MAX_LOG_ENTRIES:
        data["runs"] = data["runs"][-MAX_LOG_ENTRIES:]
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def log_agent_start(agent_name):
    """Log when an agent starts running."""
    data = _read_log()
    entry = {
        "agent": agent_name,
        "event": "started",
        "timestamp": datetime.now().isoformat(),
        "details": {}
    }
    data["runs"].append(entry)

    # Update last run time
    if "stats" not in data:
        data["stats"] = {}
    if agent_name not in data["stats"]:
        data["stats"][agent_name] = {}
    data["stats"][agent_name]["last_started"] = datetime.now().isoformat()
    data["stats"][agent_name]["status"] = "running"

    _write_log(data)


def log_agent_complete(agent_name, details=None):
    """Log when an agent finishes successfully."""
    data = _read_log()
    entry = {
        "agent": agent_name,
        "event": "completed",
        "timestamp": datetime.now().isoformat(),
        "details": details or {}
    }
    data["runs"].append(entry)

    if "stats" not in data:
        data["stats"] = {}
    if agent_name not in data["stats"]:
        data["stats"][agent_name] = {}
    data["stats"][agent_name]["last_completed"] = datetime.now().isoformat()
    data["stats"][agent_name]["status"] = "idle"
    data["stats"][agent_name]["last_result"] = details or {}

    # Increment run count
    count = data["stats"][agent_name].get("total_runs", 0)
    data["stats"][agent_name]["total_runs"] = count + 1

    _write_log(data)


def log_agent_error(agent_name, error_message):
    """Log when an agent encounters an error."""
    data = _read_log()
    entry = {
        "agent": agent_name,
        "event": "error",
        "timestamp": datetime.now().isoformat(),
        "details": {"error": str(error_message)}
    }
    data["runs"].append(entry)

    if "stats" not in data:
        data["stats"] = {}
    if agent_name not in data["stats"]:
        data["stats"][agent_name] = {}
    data["stats"][agent_name]["status"] = "error"
    data["stats"][agent_name]["last_error"] = str(error_message)
    data["stats"][agent_name]["last_error_time"] = datetime.now().isoformat()

    _write_log(data)


def log_action(agent_name, action, details=None):
    """Log a specific action within an agent run."""
    data = _read_log()
    entry = {
        "agent": agent_name,
        "event": "action",
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "details": details or {}
    }
    data["runs"].append(entry)
    _write_log(data)


def get_dashboard_data():
    """Get all data needed for the dashboard."""
    data = _read_log()
    runs = data.get("runs", [])

    # Calculate time saved
    time_saved = calculate_time_saved(runs)

    return {
        "stats": data.get("stats", {}),
        "recent_activity": runs[-50:],  # Last 50 events
        "time_saved": time_saved
    }


def calculate_time_saved(runs):
    """Calculate estimated time saved by agents - today, this week, and lifetime."""
    now = datetime.now()
    today_start = datetime.combine(date.today(), datetime.min.time())
    week_start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())

    today_mins = 0
    week_mins = 0
    lifetime_mins = 0

    for run in runs:
        if run.get("event") != "completed":
            continue

        agent = run.get("agent", "")
        saved = TIME_SAVED_MINUTES.get(agent, 0)
        if saved == 0:
            continue

        try:
            ts = datetime.fromisoformat(run["timestamp"])
        except (ValueError, KeyError):
            continue

        lifetime_mins += saved
        if ts >= week_start:
            week_mins += saved
        if ts >= today_start:
            today_mins += saved

    return {
        "today_minutes": today_mins,
        "today_hours": round(today_mins / 60, 1),
        "week_minutes": week_mins,
        "week_hours": round(week_mins / 60, 1),
        "lifetime_minutes": lifetime_mins,
        "lifetime_hours": round(lifetime_mins / 60, 1)
    }
