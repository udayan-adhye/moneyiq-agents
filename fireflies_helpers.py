"""
Fireflies Helper Functions
===========================
Fetches meeting transcripts from Fireflies.ai via their GraphQL API.
"""

import requests
import json
from datetime import datetime, timedelta
from config import FIREFLIES_API_KEY

FIREFLIES_URL = "https://api.fireflies.ai/graphql"

HEADERS = {
    "Authorization": f"Bearer {FIREFLIES_API_KEY}",
    "Content-Type": "application/json"
}


def get_recent_transcripts(days_back=1):
    query = """
    query {
        transcripts {
            id
            title
            date
            duration
            participants
            organizer_email
        }
    }
    """
    response = requests.post(FIREFLIES_URL, headers=HEADERS, json={"query": query})

    if response.status_code == 200:
        data = response.json().get("data", {})
        all_transcripts = data.get("transcripts", [])
        recent = []
        for t in all_transcripts:
            if t.get("date"):
                try:
                    t_date = datetime.fromtimestamp(int(t["date"]) / 1000)
                    if t_date >= datetime.now() - timedelta(days=days_back):
                        t["parsed_date"] = t_date.isoformat()
                        recent.append(t)
                except (ValueError, TypeError):
                    recent.append(t)
        print(f"  📋 Found {len(recent)} transcript(s) from the last {days_back} day(s)")
        return recent
    else:
        print(f"  ❌ Fireflies API error: {response.status_code} — {response.text}")
        return []


def get_full_transcript(transcript_id):
    query = """
    query Transcript($transcriptId: String!) {
        transcript(id: $transcriptId) {
            id
            title
            date
            duration
            participants
            organizer_email
            sentences {
                text
                speaker_name
                start_time
                end_time
            }
            summary {
                overview
                shorthand_bullet
                action_items
                keywords
            }
        }
    }
    """
    response = requests.post(
        FIREFLIES_URL,
        headers=HEADERS,
        json={"query": query, "variables": {"transcriptId": transcript_id}}
    )

    if response.status_code == 200:
        data = response.json().get("data", {})
        transcript = data.get("transcript")
        if transcript:
            print(f"  ✅ Fetched transcript: {transcript.get('title', 'Unknown')}")
            return transcript
        else:
            print(f"  ⚠️  No transcript found for ID: {transcript_id}")
            return None
    else:
        print(f"  ❌ Fireflies API error: {response.status_code} — {response.text}")
        return None


def format_transcript_for_claude(transcript):
    if not transcript:
        return ""

    lines = []
    lines.append(f"MEETING: {transcript.get('title', 'Unknown Meeting')}")
    lines.append(f"DATE: {transcript.get('parsed_date', transcript.get('date', 'Unknown'))}")
    lines.append(f"PARTICIPANTS: {', '.join(transcript.get('participants', []))}")
    lines.append("")

    summary = transcript.get("summary", {})
    if summary:
        if summary.get("overview"):
            lines.append("--- MEETING OVERVIEW ---")
            lines.append(summary["overview"])
            lines.append("")
        if summary.get("action_items"):
            lines.append("--- ACTION ITEMS (from Fireflies) ---")
            lines.append(summary["action_items"])
            lines.append("")

    lines.append("--- FULL TRANSCRIPT ---")
    sentences = transcript.get("sentences", [])
    for s in sentences:
        speaker = s.get("speaker_name", "Unknown")
        text = s.get("text", "")
        lines.append(f"{speaker}: {text}")

    return "\n".join(lines)
