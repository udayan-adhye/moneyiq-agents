# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

MoneyIQ Wealth Management Agent System — a multi-agent backend that automates CRM workflows for a wealth advisory firm. It processes meeting transcripts, manages leads, drafts emails, and maintains a Notion CRM. Deployed on **Railway** as a Flask/Gunicorn web server.

## Commands

```bash
# Install dependencies (Python 3.14, venv at .venv)
pip install -r requirements.txt

# Run locally
python3 server.py                          # Starts Flask server on port 5000

# Run individual agents standalone
python3 meeting_processor.py               # Process recent Fireflies transcripts
python3 calendly_intake.py                 # Check last 1 day of Calendly bookings
python3 calendly_intake.py --days 7        # Catch up on last 7 days
python3 daily_lead_checker.py              # Scan CRM for leads needing attention
python3 advisor_call_review.py             # Weekly report (last 7 days)
python3 advisor_call_review.py --days 30   # Report for last 30 days

# Production (Railway uses this via Procfile)
gunicorn server:app --bind 0.0.0.0:$PORT --timeout 300
```

## Architecture

### Agents (the core processing units)

| Agent | File | Purpose |
|-------|------|---------|
| Calendly Intake | `calendly_intake.py` | Fetches Calendly bookings, creates/updates contacts in Notion CRM |
| Meeting Processor | `meeting_processor.py` | Pulls Fireflies transcripts, uses Claude to analyze meetings, updates CRM, drafts emails |
| Daily Lead Checker | `daily_lead_checker.py` | Scans Notion for stale leads, overdue tasks, missing follow-ups; drafts nudge emails |
| Call Review | `advisor_call_review.py` | Generates weekly advisor performance reports from meeting data |

### Server & Routing (`server.py`)

Flask app with these endpoint groups:
- **Webhook**: `POST /webhook/fireflies` — Fireflies sends transcript-ready events here
- **Approval flow**: `GET /approve-meeting/<event_id>`, `GET /reject-meeting/<event_id>` — email-based approval links
- **Cron endpoints**: `/cron/calendly-intake`, `/cron/daily-lead-checker`, `/cron/call-review` — protected by `CRON_SECRET`
- **Manual trigger**: `POST /run` — run meeting processor on demand
- **Dashboard**: `GET /dashboard` + `GET /api/dashboard` — live monitoring UI

A background scheduler thread (`meeting_check_loop`) polls Fireflies every 2 hours as a backup to the webhook. Uses a threading lock to prevent overlapping runs.

### Helper Modules

- `notion_helpers.py` — All Notion API calls (contacts, meetings, tasks databases)
- `fireflies_helpers.py` — Fireflies GraphQL API for transcript fetching
- `gmail_helpers.py` — Gmail API (send emails, save drafts). Per-advisor OAuth tokens (`gmail_token_udayan.json`, `gmail_token_rishabh.json`)
- `calendar_helpers.py` — Google Calendar API for follow-up scheduling
- `calendly_helpers.py` — Calendly REST API for booking/invitee data
- `config.py` — Loads all secrets from env vars (or `.env` file locally), defines team info and thresholds
- `activity_log.py` — JSON-file-based activity logger for dashboard stats

### Data Flow

1. **Trigger**: Fireflies webhook OR scheduler poll OR cron endpoint
2. **Fetch**: Transcript from Fireflies API
3. **Analyze**: Claude (Anthropic API) extracts summary, action items, client details, email drafts
4. **Persist**: Contact/meeting/task records written to Notion CRM
5. **Act**: Email drafts saved to Gmail (advisor approval required before sending)

### External Services

All configured via environment variables (see `.env.example`):
- **Anthropic (Claude)** — meeting analysis and email drafting
- **Notion** — CRM backend (Contacts, Meetings, Tasks databases)
- **Fireflies.ai** — meeting transcript source (GraphQL API)
- **Gmail API** — email sending/drafts (OAuth per advisor)
- **Google Calendar API** — follow-up scheduling
- **Calendly** — booking intake

### Key Design Decisions

- Emails are saved as **drafts** (not auto-sent) so advisors review before sending
- Meeting processor uses a **threading lock** to prevent duplicate processing
- Fireflies webhook is the primary trigger; the 2-hour polling loop is a backup to catch missed webhooks
- Two advisors (Udayan, Rishabh) each have separate Gmail OAuth tokens
- The server is stateless except for `agent_activity.json` (dashboard log, gitignored)
