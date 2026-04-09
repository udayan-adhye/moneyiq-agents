"""
Agent 2  - Meeting Processor
=============================
The main brain of your system.

HOW TO RUN:
  python3 meeting_processor.py

REQUIREMENTS:
  pip3 install requests anthropic google-auth google-auth-oauthlib google-api-python-client
"""

import json
from datetime import datetime, date, timedelta
from anthropic import Anthropic

from config import (
    CLAUDE_API_KEY, ADVISORS, INSURANCE_TEAM_EMAIL,
    CA_CONTACT_EMAIL, CA_CONTACT_PHONE, CA_CONTACT_NAME,
    HIGH_VALUE_SIP_MONTHLY,
    HIGH_VALUE_LUMPSUM_YEARLY, HIGH_VALUE_ALERT_EMAIL
)
from fireflies_helpers import (
    get_recent_transcripts, get_full_transcript,
    format_transcript_for_claude
)
from gmail_helpers import send_email, save_draft
from notion_helpers import (
    find_contact_by_email, find_contact_by_name,
    create_contact, update_contact, get_contact_field,
    create_meeting, create_task
)
from followup_manager import create_followup_sequence

client = Anthropic(api_key=CLAUDE_API_KEY)


def analyze_meeting_with_claude(transcript_text, advisor_name, client_name, existing_profile=None):
    # Look up advisor phone for email signatures
    advisor_phone_for_prompt = ""
    for adv_info in ADVISORS.values():
        if adv_info["name"] == advisor_name:
            advisor_phone_for_prompt = adv_info.get("phone", "")
            break

    # Build merge context — pass existing profile data so Claude updates instead of overwriting
    profile_block = ""
    if existing_profile and any(existing_profile.values()):
        profile_block = (
            "\nEXISTING CLIENT PROFILE (from previous meetings — MERGE new info into this, do not discard):\n"
            f"  Family Details: {existing_profile.get('family_details', '') or '(none)'}\n"
            f"  Psychological Profile: {existing_profile.get('psychological_profile', '') or '(none)'}\n"
            f"  Personal Context: {existing_profile.get('personal_context', '') or '(none)'}\n"
            f"  Closing Phrases: {existing_profile.get('closing_phrases', '') or '(none)'}\n"
        )

    # Build CA introduction instruction with real contact details
    # Uses Udayan's exact tone: warm, short, personal, trusting
    ca_instruction = (
        f"If CA introduction needed, draft a warm introduction email. "
        f"Follow this EXACT tone and structure (this is how the advisor actually writes):\n\n"
        f"Hi Asmeet, hi [Client first name],\n\n"
        f"Connecting you both.\n\n"
        f"Asmeet, [Client first name] and I had a conversation today, and [he/she] mentioned needing help with [specific topic from meeting  - taxes, ITR filing, capital gains, HUF structuring, etc.].\n\n"
        f"[Client first name], Asmeet is my trusted CA. I work with him and have been very happy with our work. He will be able to guide you on the best approach.\n\n"
        f"Contact details for easy reference:\n\n"
        f"* CA Details: Asmeet Shah, {CA_CONTACT_EMAIL}, {CA_CONTACT_PHONE}\n\n"
        f"* [Client full name], [client email if known], [client phone if known]\n\n"
        f"Warm regards,\n"
        f"{advisor_name}\n\n"
        f"IMPORTANT: Keep it short and warm like above. Do NOT make it long or corporate-sounding. "
        f"Use the client's first name naturally. The tone should feel like a personal WhatsApp message, not a formal letter. "
        f"Always spell the CA's name as 'Asmeet Shah'  - never abbreviate or misspell. "
        f"If CA introduction is NOT needed, return empty string."
    )

    prompt = f"""You are a meeting analysis agent for a wealth management firm (MoneyIQ).
You are analyzing a meeting transcript between an advisor ({advisor_name}) and a client/prospect ({client_name}).

Analyze the following transcript and return a JSON object with these exact keys:

{{
  "summary": "A 3-5 sentence summary of what was discussed in the meeting",

  "meeting_type": "One of: discovery, recommendations, review, rescheduled_intro. See detection rules below.",

  "action_items": [
    {{"item": "Description of action item", "assigned_to": "Advisor name or Team", "priority": "High/Medium/Low", "due_in_days": 3, "task_owner": "Internal"}}
  ],

  "client_pending_items": [
    {{"item": "What the client needs to do or share", "due_in_days": 7}}
  ],

  "awaiting_from_client": "A summary of all documents, information, or actions the client needs to provide. Empty string if nothing pending.",

  "insurance_discussed": true/false,
  "insurance_details": "If insurance was discussed, describe what kind and client needs. Empty string if not discussed.",

  "ca_introduction_needed": true/false,
  "ca_introduction_context": "If a CA introduction was mentioned, describe why. Empty string if not needed.",

  "meeting_quality": {{
    "overall_score": "Excellent/Good/Needs Improvement",
    "overall_score_numeric": 1-10,
    "dimensions": {{
      "discovery_and_rapport": {{
        "score": 1-10,
        "feedback": "Did the advisor build trust? Ask open-ended questions? Show genuine interest in the client's life situation beyond just finances?"
      }},
      "needs_assessment": {{
        "score": 1-10,
        "feedback": "Were the client's financial goals, risk tolerance, time horizon, and life stage thoroughly explored? Were follow-up questions asked to deepen understanding?"
      }},
      "solution_presentation": {{
        "score": 1-10,
        "feedback": "Was the recommendation clear, tailored to the client's specific situation, and explained in simple language? Were alternatives discussed?"
      }},
      "objection_handling": {{
        "score": 1-10,
        "feedback": "Were client concerns addressed with empathy and evidence? Did the advisor acknowledge uncertainty rather than dismiss it?"
      }},
      "compliance_and_transparency": {{
        "score": 1-10,
        "feedback": "Were risks disclosed? Was the advisor transparent about fees, lock-in periods, and potential downsides? Were regulatory requirements followed?"
      }},
      "next_steps_and_commitment": {{
        "score": 1-10,
        "feedback": "Was there a clear call to action? Did the advisor set a specific next meeting or deadline? Was the client clear on what happens next?"
      }}
    }},
    "top_strength": "The single most impressive thing the advisor did in this meeting",
    "top_improvement": "The single most impactful thing the advisor could improve for next time",
    "phrases_to_review": [
      {{
        "who_said_it": "Advisor or Client",
        "original_phrase": "The exact phrase or sentence from the transcript that could have been handled differently",
        "suggestion": "How this could have been handled better - be specific and constructive. If it was something the client said, explain how the advisor should have responded differently."
      }}
    ],
    "coaching_note": "A 2-3 sentence coaching note as if you were a senior wealth management trainer giving feedback to a junior advisor. Be specific, cite moments from the conversation."
  }},

  "high_value_client": {{
    "is_high_value": true/false,
    "estimated_sip_monthly": null or number in rupees,
    "estimated_lumpsum": null or number in rupees,
    "signal": "What in the conversation indicated this is a high-value client? Empty string if not high-value.",
    "client_first_name": "The client's first name only",
    "client_phone": "Client's phone number if mentioned in the conversation. null if not mentioned.",
    "whatsapp_message": "A short, warm, personalised WhatsApp message. MUST start with: 'Hi [client first name], I am Udayan Adhye. I know you spoke to [team member first name] from my office.' Then add 1-2 sentences referencing something SPECIFIC from their conversation - a goal, concern, or life event they discussed. End with something supportive like 'Happy to help in any way' or 'You are in great hands with [team member name]'. NEVER mention 'financial plan', 'wealth plan', or any generic plan language - reference the specific topic instead (retirement goal, children's education, portfolio, SIP, etc). NEVER say 'I'd love to chat' or 'Would you have time for a call'. Keep it to 3 sentences max. Example: 'Hi Amritha, I am Udayan Adhye. I know you spoke to Rishabh from my office about your retirement goals and children's education fund. Happy to help in any way, and I trust Rishabh to take great care of you.' If not high-value, return empty string."
  }},

  "client_financial_goals": "Brief summary of financial goals discussed",
  "investment_amount_discussed": null or number in rupees,

  "follow_up_email_subject": "A short, specific email subject line based on meeting_type. For discovery: MUST start with 'Our investment call today' + specific topic. For recommendations: 'Your investment plan next steps' + specific topic. For review: 'Portfolio review update' + specific topic. NEVER use generic phrases like 'wealth plan', 'financial plan'. Keep under 60 characters.",

  "follow_up_email": "A structured follow-up email whose TONE AND STRUCTURE changes based on meeting_type:\n\n--- IF meeting_type is 'discovery' or 'rescheduled_intro' ---\nTone: Warm, exploratory, rapport-building. They are a prospect, not a client yet.\nStructure:\n1. OPENING (2-3 sentences): Warm, personal, referencing something specific from the conversation.\n2. WHAT WE DISCUSSED: Summarize key topics with actual numbers, goals, situations.\n3. KEY ACTION POINTS: What was discussed as possible next steps. Be specific.\n4. WHAT I WILL BE SENDING YOU: What the advisor committed to preparing for the next call.\n5. WHAT I WOULD NEED FROM YOU: Documents or info the prospect needs to share. If mutual fund consolidation was mentioned, ALWAYS include: 'Your consolidated mutual fund statement - you can download it here: https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement'\n6. NEXT STEPS: 'I will prepare a detailed plan for our next conversation' + timeline.\n\n--- IF meeting_type is 'recommendations' ---\nTone: Concrete, action-oriented. This is the decision point.\nStructure:\n1. OPENING (2-3 sentences): Reference the journey so far - 'Following up on our earlier conversation and the plan I shared today.'\n2. WHAT WE DISCUSSED TODAY: The specific portfolio/SIP/fund suggestions presented. Include fund names, amounts, allocation percentages where discussed.\n3. YOUR INVESTMENT PLAN: Clear summary of exactly what was recommended - SIP amounts, fund names, lumpsum allocation, timeline.\n4. HOW TO GET STARTED: Concrete next steps to begin - 'Fill the information form', 'Share KYC documents', 'Set up the SIP mandate'.\n5. WHAT I NEED FROM YOU: Specific documents/actions needed to proceed.\n6. TIMELINE: When they should ideally get started and why (market timing, SIP date, etc).\n\n--- IF meeting_type is 'review' ---\nTone: Professional, reassuring, results-focused. They are an existing client.\nStructure:\n1. OPENING: Reference the review meeting warmly.\n2. PORTFOLIO PERFORMANCE: Summarize how their investments with MoneyIQ are performing.\n3. CHANGES DISCUSSED: Any rebalancing, additions, or adjustments discussed.\n4. ACTION ITEMS: What will be executed and by when.\n5. NEXT REVIEW: When the next review is planned.\n\nSign off with:\nWarm regards,\n{advisor_name}\nMoneyIQ\n{advisor_phone_for_prompt}\n\nIMPORTANT RULES FOR ALL TYPES:\n- Use section headers (lowercase, with colon)\n- Be specific - use actual numbers, names, fund names, amounts\n- Do NOT use the word 'recommendations' - use 'action points' or 'suggestions'\n- NEVER use the word 'client' in discovery/recommendations emails - use first name\n- For review emails, 'client' is acceptable but first name is still preferred",

  "insurance_type": "If insurance was discussed, what type: term life, health, critical illness, personal accident, or other. Empty string if not discussed.",
  "insurance_details_for_team": "If insurance was discussed, describe any specific details mentioned: family size, existing coverage, budget range, specific concerns. Empty string if not discussed.",
  "insurance_recommendation": "If the person conducting the meeting suggested any specific insurance idea or recommendation, describe it here. Empty string if nothing was suggested.",

  "ca_introduction_email": "{ca_instruction}",

  "next_meeting": {{
    "discussed": true/false,
    "proposed_date": "The specific date mentioned for the next meeting in YYYY-MM-DD format. null if no specific date was discussed. If they said something like 'Thursday' or 'next week', calculate the actual date relative to the meeting date.",
    "proposed_time": "The time mentioned in HH:MM format (24-hour, IST). null if no specific time was discussed. e.g., '20:00' for 8 PM.",
    "proposed_duration_minutes": 45,
    "context": "Brief description of what the next meeting is about. e.g., 'Detailed portfolio review and SIP setup', 'Follow-up with husband to discuss tax planning'. Empty string if not discussed.",
    "additional_attendees": ["Any additional people mentioned who should join the next meeting that were NOT in this meeting. e.g., 'husband Nitin', 'wife Rishita'. Empty array if none mentioned."]
  }},

  "family_details": "Names, ages, relationships of spouse, kids, parents, siblings — anything personal about the family. If updating an existing profile, MERGE new info with the existing details (do not discard prior data). Empty string if nothing new and no prior data.",

  "psychological_profile": "A 3-5 sentence read of the client: risk tolerance, decision-making style, communication preferences, anxieties, motivations, what drives them. If updating, refine the existing profile with new observations.",

  "personal_context": "Hobbies, life events, career details, health notes, recent changes, anything personal not captured elsewhere. Merge with existing if updating.",

  "closing_phrases": "Specific words, phrases, or framings that resonated with this client during the call (or could resonate based on their personality). 2-4 short examples. Merge with existing if updating.",

  "investment_readiness": {{
    "ready_to_invest": true/false,
    "residency_status": "Resident" or "NRI" or "Unknown",
    "nri_kyc_required": true/false,
    "client_email": "Client's email if mentioned in the conversation. null if not mentioned.",
    "signal": "What in the conversation indicated readiness to invest? Empty string if not ready."
  }},

  "content_ideas": ["Any interesting questions or topics from this meeting that could make good content for YouTube or social media. 1-3 ideas, or empty array."],

  "followup_messages": {{
    "day1_whatsapp": "A warm, short WhatsApp check-in message (2-3 sentences max). Sent 1 day after the meeting. Purpose: make the client feel remembered. Reference something SPECIFIC from the meeting - a personal detail, a concern they raised, or a goal they mentioned. Example tone: 'Hi [first name], was great chatting yesterday! Just wanted to check - did you get a chance to look at the CAMS statement link I shared? No rush at all, happy to help whenever you are ready.' Do NOT use formal language. Write like a friend texting, not a corporate follow-up. Use the client's first name.",

    "day3_whatsapp": "A gentle nudge WhatsApp message (2-3 sentences max). Sent 3 days after the meeting. Purpose: remind about any pending items WITHOUT being pushy. Reference the specific pending item from the meeting (documents to share, forms to fill, decisions to make). If nothing is pending from the client, return empty string. Example tone: 'Hi [first name], just a gentle reminder about [specific pending item]. Happy to jump on a quick call if you have any questions about it.' Keep it helpful, not salesy.",

    "day7_email_subject": "A short email subject line for the Day 7 value-add email. Should reference something useful - an article, insight, or update relevant to what was discussed. Example: 'Thought you might find this useful - [topic]' or 'Quick update on [topic we discussed]'. Under 60 characters.",

    "day7_email_body": "A value-add email body (4-6 sentences). Sent 7 days after the meeting. Purpose: provide genuine value without asking for anything. Share a relevant insight, market update, article summary, or tip related to what was discussed in the meeting. For example, if they discussed SIPs, share a quick insight about SIP timing or market conditions. If they discussed tax planning, share a relevant tax-saving tip. End with a soft availability line like 'Happy to discuss if you would like to explore this further.' Sign off with: Warm regards,\\n{advisor_name}\\nMoneyIQ",

    "day14_whatsapp": "A soft re-engagement WhatsApp message (2-3 sentences max). Sent 14 days after the meeting. Purpose: reopen the conversation without pressure. Reference the original meeting context but acknowledge that life gets busy. Example tone: 'Hi [first name], hope you have been well! I was thinking about our conversation about [specific topic] and wanted to check if you had any more thoughts on it. No pressure at all - just here whenever you are ready to move forward.' Do NOT be desperate or overly eager."
  }}
}}

IMPORTANT RULES:
- Return ONLY valid JSON, no markdown formatting, no code blocks
- action_items are things YOUR TEAM needs to do (internal tasks). Set task_owner to "Internal".
- client_pending_items are things the CLIENT needs to do (share documents, fill forms, provide information). These are separate.
- awaiting_from_client should summarize everything the client owes.
- For meeting_quality: Use the 6-dimension framework rigorously. Score each dimension 1-10. Be honest and specific  - cite actual moments from the transcript. This is for internal training, not client-facing.
- For phrases_to_review: ALWAYS provide exactly 2-3 phrases. These should be ACTUAL sentences or close paraphrases from the transcript - things the advisor or client said that represent coaching opportunities. For each phrase, explain specifically how it could have been handled differently. This is the most valuable part of the feedback.
- For high_value_client: A client is high-value if they mention investing ₹1 lakh+ per month (SIP) OR ₹20 lakhs+ as lumpsum. Look for signals like salary mentions, existing portfolio size, inheritance, business income, or direct investment amount discussions.
- For the follow_up_email: Follow the structured format specified above. The email should be a comprehensive but scannable recap. Use section headers. Be specific with numbers and details from the conversation. The CAMS link (https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement) MUST be included whenever mutual fund consolidation or portfolio sharing was discussed.
- For the ca_introduction_email: This is a WARM introduction  - both the CA and client are marked (To and CC). Make it feel personal, not robotic. Include both parties' full contact details at the end.
- For next_meeting: Look carefully for ANY mention of scheduling a follow-up. This includes: "let's meet again on...", "how about Thursday?", "I'll send a calendar invite for...", "next call on 1st April", "let's schedule a follow-up", "we'll connect again next week". Extract the date and time as precisely as possible. If they say "evening" without a specific time, use 20:00 (8 PM IST). If they mention a day like "Thursday" or "1st April", calculate the actual YYYY-MM-DD date.
- For investment_readiness: Look for signals like "I'm ready to start", "let's go ahead with the SIP", "I want to invest", "let's proceed", "send me the form", or the advisor saying "I'll send you the form to fill". Also detect if the person is an NRI — look for mentions of living abroad, NRE/NRO accounts, foreign salary, US/UK/Dubai/Singapore residence, OCI/PIO status, or the advisor asking about residency status. If NRI, check if KYC was mentioned as pending.
- All monetary amounts should be in Indian Rupees (numbers, not words).
- NEVER use the word "advisor" in any client-facing email (follow_up_email, ca_introduction_email). Do not refer to anyone as an "advisor". Use the person's first name instead.
- NEVER use the word "client" in any email. These are prospects, not clients yet. Use their first name or "them/they" instead.
- NEVER use the phrase "investment advice" in any email. We do not give investment advice.
- NEVER use the phrases "financial plan", "wealth plan", "financial planning", "wealth planning", or any variation in email subjects or body text. Instead, be SPECIFIC about what was discussed - use the actual topics like "your retirement goal", "your SIP plan", "your children's education fund", "your portfolio review", "your tax planning", etc. Always reference the specific topic, never generic "plan" language.
- NEVER use em dashes in any email text. Use regular dashes (-) or commas instead.
- NEVER use the word "recommendations" in client-facing emails. Use "action points" instead.
- For meeting_type detection:
  * "discovery": Advisor is asking about goals, income, family, risk tolerance, existing holdings. First real conversation with this person. Also applies if the advisor is reviewing the client's EXTERNAL investments (Groww, ET Money, Zerodha, etc.) to assess their current situation.
  * "recommendations": Advisor is presenting SPECIFIC NEW fund names, SIP amounts, portfolio allocation, or investment strategy for the client to act on. The advisor is making concrete suggestions, not just asking questions.
  * "review": Discussing performance of investments that MoneyIQ/the advisor SET UP or RECOMMENDED previously. Key signal is ownership language like "the portfolio we built", "the SIP we started", "our recommendation". NOT reviewing external holdings — that is discovery.
  * "rescheduled_intro": Same ground as a discovery call being covered again. Client exists in the system from a prior booking but the real conversation is happening for the first time. Treat the follow-up email exactly like discovery.
- For family_details/psychological_profile/personal_context/closing_phrases: if existing profile data is provided below, MERGE the new observations into the existing data (do not discard the prior info). If no new info on a field, return the existing value unchanged.
{profile_block}
TRANSCRIPT:
{transcript_text}
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        analysis = json.loads(cleaned)

        # Check if response was truncated (stop_reason != "end_turn" means it hit token limit)
        stop_reason = message.stop_reason if hasattr(message, "stop_reason") else "unknown"
        if stop_reason == "max_tokens":
            print(f"  ⚠️  Claude response was TRUNCATED (hit max_tokens). Some fields may be missing.")
            print(f"     Missing fields check: content_ideas={'content_ideas' in analysis}, next_meeting={'next_meeting' in analysis}")

        # Log key fields presence for debugging
        has_content_ideas = bool(analysis.get("content_ideas"))
        has_follow_up = bool(analysis.get("follow_up_email"))
        has_next_meeting = bool(analysis.get("next_meeting", {}).get("discussed"))
        print(f"  ✅ Claude analysis complete (follow_up={has_follow_up}, content_ideas={has_content_ideas}, next_meeting={has_next_meeting})")
        return analysis
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse Claude's response as JSON: {e}")
        print(f"     Response length: {len(cleaned)} chars")
        print(f"     Last 200 chars: ...{cleaned[-200:]}")
        return None
    except Exception as e:
        print(f"  ❌ Claude API error: {e}")
        return None


def determine_advisor_from_transcript(transcript):
    organizer = transcript.get("organizer_email", "").lower()
    participants = [p.lower() for p in transcript.get("participants", [])]

    for advisor_key, advisor_info in ADVISORS.items():
        if advisor_info["email"].lower() in organizer:
            return advisor_info["name"]
        for p in participants:
            if advisor_info["email"].lower() in p or advisor_info["name"].lower() in p:
                return advisor_info["name"]
    return list(ADVISORS.values())[0]["name"]


def find_client_in_participants(transcript, advisor_name):
    participants = transcript.get("participants", [])
    for p in participants:
        is_advisor = False
        for advisor_info in ADVISORS.values():
            if advisor_info["name"].lower() in p.lower() or advisor_info["email"].lower() in p.lower():
                is_advisor = True
                break
        if not is_advisor and p.strip():
            return p.strip()
    return "Unknown Client"


def process_single_meeting(transcript_id, duration_hint=None):
    """
    Process a single meeting transcript.

    Args:
        transcript_id: Fireflies transcript ID
        duration_hint: Duration in minutes from the transcript list (optional, used for pre-filtering)
    """
    print(f"\n{'='*60}")
    print(f"  Processing transcript: {transcript_id}")
    print(f"{'='*60}")

    # Step 0a: Quick duration pre-filter (skip missed calls and very short meetings)
    MIN_MEETING_DURATION_MINUTES = 10
    if duration_hint is not None and duration_hint < MIN_MEETING_DURATION_MINUTES:
        print(f"  ⏭️  Skipping — too short ({duration_hint:.0f} min). Likely a missed call or reschedule.")
        return None

    # Step 0b: Check if already processed (deduplication)
    from notion_helpers import meeting_already_processed
    if meeting_already_processed(transcript_id):
        print(f"  ⏭️  Already processed. Skipping.")
        return None

    # Step 1: Fetch the full transcript
    transcript = get_full_transcript(transcript_id)
    if not transcript:
        print("  ⚠️  Could not fetch transcript. Skipping.")
        return

    # Step 1b: Verify duration from full transcript (in case duration_hint wasn't available)
    transcript_duration = transcript.get("duration", 0)
    if transcript_duration and transcript_duration < MIN_MEETING_DURATION_MINUTES:
        print(f"  ⏭️  Skipping — too short ({transcript_duration:.0f} min). Likely a missed call or reschedule.")
        return None

    # Step 1c: Check for silent/empty meetings
    sentences = transcript.get("sentences", [])
    if len(sentences) < 10:
        print(f"  ⏭️  Skipping — only {len(sentences)} sentences. Likely a missed call or test meeting.")
        return None

    # Step 2: Determine who's who
    advisor_name = determine_advisor_from_transcript(transcript)
    client_name = find_client_in_participants(transcript, advisor_name)
    print(f"  👤 Advisor: {advisor_name}")
    print(f"  👤 Client:  {client_name}")

    # Step 3: Pre-fetch existing contact (if any) to feed prior profile data into Claude
    existing_contact = None
    for p in transcript.get("participants", []):
        if "@" in p:
            is_advisor = any(a["email"].lower() == p.lower() for a in ADVISORS.values())
            if not is_advisor:
                existing_contact = find_contact_by_email(p)
                if existing_contact:
                    break
    if not existing_contact and client_name != "Unknown Client":
        existing_contact = find_contact_by_name(client_name)

    existing_profile = None
    if existing_contact:
        existing_profile = {
            "family_details": get_contact_field(existing_contact, "Family Details") or "",
            "psychological_profile": get_contact_field(existing_contact, "Psychological Profile") or "",
            "personal_context": get_contact_field(existing_contact, "Personal Context") or "",
            "closing_phrases": get_contact_field(existing_contact, "Closing Phrases") or "",
        }

    # Step 3b: Send to Claude for analysis (with existing profile for merge)
    transcript_text = format_transcript_for_claude(transcript)
    analysis = analyze_meeting_with_claude(transcript_text, advisor_name, client_name, existing_profile=existing_profile)
    if not analysis:
        print("  ⚠️  Claude analysis failed. Skipping.")
        return

    # Step 4: Find or create the contact in Notion (reuse from step 3 if found)
    contact = existing_contact
    participants = transcript.get("participants", [])

    if not contact:
        print(f"  📝 Creating new contact: {client_name}")
        contact = create_contact(
            name=client_name,
            assigned_advisor=advisor_name,
            pipeline_stage="Meeting 1 Done"
        )

    if not contact:
        print("  ❌ Could not find or create contact. Stopping.")
        return

    contact_id = contact["id"]

    # Step 4b: Update client_name from Notion if we have a proper name
    # (Fireflies often returns email addresses instead of names)
    notion_name = get_contact_field(contact, "Name")
    if notion_name and "@" not in notion_name and notion_name != "Unknown Client":
        if client_name != notion_name:
            print(f"  📛 Name updated: {client_name} → {notion_name}")
            client_name = notion_name
    elif "@" in client_name or client_name == "Unknown Client":
        # If client_name is still an email or unknown, try extracting name from transcript title
        import re
        title = transcript.get("title", "")
        if title:
            # Strip prefixes like "Meet – ", "Investment Consultation × "
            DASH = r'[\-–—\u2013\u2014]'
            title_clean = re.sub(rf'^Meet\s*{DASH}\s*', '', title).strip()
            title_clean = re.sub(rf'^Investment\s+Consultation\s*[×x]\s*', '', title_clean).strip()
            # Strip topic prefixes like "Portfolio discussion - ", "Investment discussion - "
            title_clean = re.sub(rf'^[\w\s]+(discussion|consultation|review|call)\s*{DASH}\s*', '', title_clean, flags=re.IGNORECASE).strip()
            # Split on common separators: ", ", " and ", " × ", " x ", " - ", " & "
            parts = re.split(rf'\s*(?:,|and|×|x|&|{DASH})\s+', title_clean, flags=re.IGNORECASE)
            client_names = []
            for part in parts:
                part = part.strip()
                is_advisor = False
                for adv_info in ADVISORS.values():
                    if adv_info["name"].lower() in part.lower() or adv_info["name"].split()[0].lower() == part.lower():
                        is_advisor = True
                        break
                if not is_advisor and part and "@" not in part and len(part) > 1:
                    client_names.append(part)
            if client_names:
                new_name = ", ".join(client_names)
                print(f"  📛 Name from title: {client_name} → {new_name}")
                client_name = new_name

    # Step 5: Update contact in CRM
    current_count = get_contact_field(contact, "Meeting Count") or 0
    new_count = current_count + 1
    new_stage = f"Meeting {min(new_count, 2)} Done"

    contact_updates = {
        "Pipeline Stage": new_stage,
        "Meeting Count": new_count,
        "Last Meeting Date": date.today().isoformat(),
        "Last Contact Date": date.today().isoformat()
    }

    if analysis.get("insurance_discussed"):
        contact_updates["Insurance Flagged"] = True
        contact_updates["Insurance Requirements"] = analysis.get("insurance_details", "")
    if analysis.get("ca_introduction_needed"):
        contact_updates["CA Introduction Needed"] = True
    if analysis.get("client_financial_goals"):
        contact_updates["Financial Goals"] = analysis["client_financial_goals"]
    if analysis.get("investment_amount_discussed"):
        contact_updates["Investment Amount"] = analysis["investment_amount_discussed"]

    # Family/psych/context/closing — overwrite with merged version Claude returned
    for fld_key, fld_name in [
        ("family_details", "Family Details"),
        ("psychological_profile", "Psychological Profile"),
        ("personal_context", "Personal Context"),
        ("closing_phrases", "Closing Phrases"),
    ]:
        val = analysis.get(fld_key)
        if val:
            contact_updates[fld_name] = val

    update_contact(contact_id, contact_updates)

    # Step 6: Create meeting record
    meeting_date_str = transcript.get("parsed_date", date.today().isoformat())
    if "T" in meeting_date_str:
        meeting_date_str = meeting_date_str.split("T")[0]

    meeting_record = create_meeting(
        title=transcript.get("title", f"Meeting with {client_name}"),
        contact_page_id=contact_id,
        meeting_date=meeting_date_str,
        advisor=advisor_name,
        meeting_number=new_count,
        fireflies_link=f"https://app.fireflies.ai/view/{transcript_id}",
        summary=analysis.get("summary", ""),
        action_items=json.dumps(analysis.get("action_items", []), indent=2),
        insurance_flagged=analysis.get("insurance_discussed", False),
        ca_intro_flagged=analysis.get("ca_introduction_needed", False),
        quality_score=analysis.get("meeting_quality_score"),
        meeting_type=analysis.get("meeting_type")
    )

    if not meeting_record:
        print(f"  ❌ Notion meeting record failed to create. Stopping here to prevent duplicate drafts on retry.")
        return None

    # Step 7a: Create INTERNAL tasks (for your team)
    for item in analysis.get("action_items", []):
        due_days = item.get("due_in_days", 3)
        due_date = (date.today() + timedelta(days=due_days)).isoformat()
        create_task(
            task_name=item.get("item", "Follow up"),
            contact_page_id=contact_id,
            assigned_to=item.get("assigned_to", advisor_name),
            due_date=due_date,
            priority=item.get("priority", "Medium"),
            task_type="Follow-up Call" if "call" in item.get("item", "").lower() else "Other",
            notes=f"From meeting with {client_name} on {meeting_date_str}",
            task_owner="Internal"
        )

    # Step 7b: Create CLIENT ACTION tasks (things the client needs to do)
    for item in analysis.get("client_pending_items", []):
        due_days = item.get("due_in_days", 7)
        due_date = (date.today() + timedelta(days=due_days)).isoformat()
        create_task(
            task_name=item.get("item", "Client to provide information"),
            contact_page_id=contact_id,
            assigned_to=advisor_name,
            due_date=due_date,
            priority="Medium",
            task_type="Other",
            notes=f"Client action needed  - from meeting on {meeting_date_str}",
            task_owner="Client Action"
        )

    # Step 7c: Update "Awaiting From Client" on the contact
    if analysis.get("awaiting_from_client"):
        update_contact(contact_id, {
            "Awaiting From Client": analysis["awaiting_from_client"]
        })

    # Step 8: Send emails and save drafts
    # Get advisor's email for sending
    advisor_email = None
    for advisor_info in ADVISORS.values():
        if advisor_info["name"] == advisor_name:
            advisor_email = advisor_info["email"]
            break
    if not advisor_email:
        print(f"  ⚠️  Could not match advisor '{advisor_name}' to any configured email. Defaulting to first advisor.")
        advisor_email = list(ADVISORS.values())[0]["email"]
    sender = f"{advisor_name} <{advisor_email}>"
    print(f"  📧 Using Gmail account: {advisor_email} (for {advisor_name})")

    # Find client email and phone  - prefer Notion (from Calendly) over transcript
    client_email = get_contact_field(contact, "Email") if contact else None
    client_phone_from_crm = get_contact_field(contact, "WhatsApp Number") if contact else None

    # Save to Google Contacts (name shows in WhatsApp)
    if client_phone_from_crm or client_email:
        try:
            from google_contacts_helpers import save_to_google_contacts
            save_to_google_contacts(
                name=client_name,
                phone=client_phone_from_crm,
                email=client_email,
                advisor_email=advisor_email
            )
        except Exception as e:
            print(f"  ⚠️ Google Contacts save failed: {e}")

    # Fallback: try to find email from Fireflies participants
    if not client_email:
        for p in participants:
            if "@" in p:
                is_advisor = False
                for adv in ADVISORS.values():
                    if adv["email"].lower() in p.lower():
                        is_advisor = True
                        break
                if not is_advisor:
                    client_email = p
                    break

    # --- CLIENT FOLLOW-UP → SAVE AS DRAFT ---
    if analysis.get("follow_up_email") and client_email:
        print(f"\n{'─'*60}")
        print(f"  📧 SAVING DRAFT: Follow-up to {client_name}")
        print(f"{'─'*60}")
        follow_up_subject = analysis.get("follow_up_email_subject", f"Our investment call today  - {advisor_name}")

        # CC Udayan on first meeting emails from other advisors
        udayan_name = ADVISORS["udayan"]["name"]
        udayan_email_addr = ADVISORS["udayan"]["email"]
        follow_up_cc = None
        if new_count == 1 and advisor_name != udayan_name:
            follow_up_cc = udayan_email_addr
            print(f"  📋 CC: {udayan_email_addr} (first meeting, team call)")

        save_draft(
            sender=sender,
            to=client_email,
            subject=follow_up_subject,
            body=analysis["follow_up_email"],
            cc=follow_up_cc
        )
    elif analysis.get("follow_up_email"):
        print(f"\n{'─'*60}")
        print(f"  📧 FOLLOW-UP EMAIL (no client email found  - printing instead)")
        print(f"{'─'*60}")
        print(analysis["follow_up_email"])

    # --- INSURANCE TEAM → SAVE AS DRAFT (client in CC) ---
    if analysis.get("insurance_discussed") and analysis.get("insurance_type"):
        print(f"\n{'─'*60}")
        print(f"  📧 SAVING DRAFT: Insurance referral for {client_name}")
        print(f"{'─'*60}")

        # Extract first name for natural language
        client_first_name = client_name.split()[0] if client_name and client_name != "Unknown Client" else client_name

        insurance_body = (
            f"Hi team,\n\n"
            f"{client_first_name} needs help with {analysis.get('insurance_type', 'insurance').lower()}. Details below.\n\n"
            f"Name: {client_name}\n"
            f"Email: {client_email or 'Not available'}\n"
            f"WhatsApp: {client_phone_from_crm or 'Not available'}\n\n"
            f"Type of insurance needed: {analysis.get('insurance_type', 'To be discussed')}\n\n"
        )

        ins_details = analysis.get("insurance_details_for_team", "")
        if ins_details:
            insurance_body += f"Details: {ins_details}\n\n"

        ins_reco = analysis.get("insurance_recommendation", "")
        if ins_reco:
            insurance_body += f"Notes from the call: {ins_reco}\n\n"

        # Get advisor phone for signature
        advisor_phone = ""
        for adv_info in ADVISORS.values():
            if adv_info["name"] == advisor_name:
                advisor_phone = adv_info.get("phone", "")
                break

        insurance_body += (
            f"Please get in touch with them directly.\n\n"
            f"Thanks,\n"
            f"{advisor_name}\n"
            f"MoneyIQ\n"
        )
        if advisor_phone:
            insurance_body += f"{advisor_phone}\n"

        save_draft(
            sender=sender,
            to=INSURANCE_TEAM_EMAIL,
            subject=f"Insurance Requirement - {client_name}",
            body=insurance_body,
            cc=client_email
        )

    # --- CA INTRODUCTION → SAVE AS DRAFT (only if not already introduced) ---
    ca_already_done = get_contact_field(contact, "CA Introduction Needed") if contact else False
    if analysis.get("ca_introduction_needed") and analysis.get("ca_introduction_email") and not ca_already_done:
        print(f"\n{'─'*60}")
        print(f"  📧 SAVING DRAFT: CA Introduction for {client_name}")
        print(f"{'─'*60}")

        # Inject client contact details from CRM into the CA intro email
        ca_email_body = analysis["ca_introduction_email"]
        if client_email and client_email not in ca_email_body:
            ca_email_body = ca_email_body.replace(
                "[client email if known]", client_email
            )
        else:
            ca_email_body = ca_email_body.replace("[client email if known]", "")
        if client_phone_from_crm and client_phone_from_crm not in ca_email_body:
            ca_email_body = ca_email_body.replace(
                "[client phone if known]", client_phone_from_crm
            )
        else:
            ca_email_body = ca_email_body.replace("[client phone if known]", "")

        save_draft(
            sender=sender,
            to=CA_CONTACT_EMAIL,
            subject=f"Introduction  - {client_name} (CA consultation needed)",
            body=ca_email_body,
            cc=client_email
        )
    elif analysis.get("ca_introduction_needed") and ca_already_done:
        print(f"  ⏭️  CA introduction already sent for {client_name}. Skipping duplicate.")

    # --- MEETING QUALITY FEEDBACK → AUTO-SEND to advisor ---
    quality = analysis.get("meeting_quality", {})
    if quality:
        print(f"\n{'─'*60}")
        print(f"  📊 AUTO-SENDING meeting quality report to {advisor_name}")
        print(f"{'─'*60}")

        dimensions = quality.get("dimensions", {})
        feedback_body = (
            f"MEETING QUALITY REPORT\n"
            f"{'='*40}\n"
            f"Client: {client_name}\n"
            f"Date: {meeting_date_str}\n"
            f"Overall Score: {quality.get('overall_score', 'N/A')} ({quality.get('overall_score_numeric', 'N/A')}/10)\n\n"
            f"DIMENSION SCORES\n"
            f"{'─'*40}\n"
        )

        dimension_labels = {
            "discovery_and_rapport": "Discovery & Rapport",
            "needs_assessment": "Needs Assessment",
            "solution_presentation": "Solution Presentation",
            "objection_handling": "Objection Handling",
            "compliance_and_transparency": "Compliance & Transparency",
            "next_steps_and_commitment": "Next Steps & Commitment"
        }

        for key, label in dimension_labels.items():
            dim = dimensions.get(key, {})
            score = dim.get("score", "N/A")
            feedback = dim.get("feedback", "")
            feedback_body += f"\n{label}: {score}/10\n{feedback}\n"

        feedback_body += (
            f"\n{'─'*40}\n"
            f"TOP STRENGTH: {quality.get('top_strength', 'N/A')}\n\n"
            f"TOP IMPROVEMENT: {quality.get('top_improvement', 'N/A')}\n\n"
        )

        # Add phrases to review section
        phrases = quality.get("phrases_to_review", [])
        if phrases:
            feedback_body += (
                f"PHRASES TO REVIEW\n"
                f"{'─'*40}\n"
            )
            for i, phrase in enumerate(phrases, 1):
                who = phrase.get("who_said_it", "Unknown")
                original = phrase.get("original_phrase", "")
                suggestion = phrase.get("suggestion", "")
                feedback_body += (
                    f"\n{i}. {who} said: \"{original}\"\n"
                    f"   → {suggestion}\n"
                )
            feedback_body += "\n"

        feedback_body += (
            f"{'─'*40}\n"
            f"COACHING NOTE:\n{quality.get('coaching_note', 'N/A')}\n"
        )

        send_email(
            sender=sender,
            to=advisor_email,
            subject=f"Meeting Quality Report  - {client_name} ({quality.get('overall_score_numeric', '?')}/10)",
            body=feedback_body
        )

    # --- HIGH-VALUE CLIENT ALERT → SEND TO UDAYAN (only for team-taken calls) ---
    hv = analysis.get("high_value_client", {})
    udayan_name = ADVISORS["udayan"]["name"]
    udayan_email_addr = ADVISORS["udayan"]["email"]
    is_team_call = (advisor_name != udayan_name)

    if hv.get("is_high_value") and is_team_call:
        print(f"\n{'─'*60}")
        print(f"  🔔 HIGH-VALUE CLIENT (team call by {advisor_name})  - Alerting Udayan")
        print(f"{'─'*60}")

        client_first_name = hv.get("client_first_name", client_name.split()[0] if client_name else "there")
        client_phone = client_phone_from_crm or hv.get("client_phone", "")

        # Build WhatsApp link (Indian numbers: +91)
        whatsapp_link = ""
        if client_phone:
            clean_phone = client_phone.replace(" ", "").replace("-", "").replace("+91", "").replace("+", "")
            if clean_phone.startswith("91") and len(clean_phone) > 10:
                clean_phone = clean_phone[2:]
            whatsapp_link = f"https://wa.me/91{clean_phone}"

        # Estimated amounts
        sip_str = f"₹{hv.get('estimated_sip_monthly', 0):,.0f}/month" if hv.get("estimated_sip_monthly") else "Not discussed"
        lumpsum_str = f"₹{hv.get('estimated_lumpsum', 0):,.0f}" if hv.get("estimated_lumpsum") else "Not discussed"

        # Topics discussed
        topics = analysis.get("client_financial_goals", "your financial goals")

        # Use Claude's personalised WhatsApp message, fallback to template
        whatsapp_message = hv.get("whatsapp_message", "")
        if not whatsapp_message:
            advisor_first = advisor_name.split()[0]
            whatsapp_message = (
                f"Hi {client_first_name}, I am Udayan Adhye. "
                f"I know you spoke to {advisor_first} from my office today. "
                f"Happy to help in any way, and I trust {advisor_first} to take great care of you."
            )

        # WhatsApp link with pre-filled message
        import urllib.parse
        whatsapp_link_with_msg = ""
        if whatsapp_link:
            encoded_msg = urllib.parse.quote(whatsapp_message)
            whatsapp_link_with_msg = f"{whatsapp_link}?text={encoded_msg}"

        alert_body = (
            f"HIGH-VALUE CLIENT ALERT\n"
            f"{'='*40}\n\n"
            f"{client_name}\n"
            f"Email: {client_email or 'Not captured'}\n"
            f"WhatsApp: {client_phone or 'Not captured'}\n"
            f"Call taken by: {advisor_name}\n"
            f"Date: {meeting_date_str}\n\n"
            f"ESTIMATED INVESTMENT\n"
            f"{'─'*40}\n"
            f"Monthly SIP: {sip_str}\n"
            f"Lumpsum: {lumpsum_str}\n\n"
            f"WHAT WAS DISCUSSED\n"
            f"{'─'*40}\n"
            f"{analysis.get('summary', 'No summary available')}\n\n"
            f"Financial Goals: {topics}\n\n"
        )

        # WhatsApp one-click section - most prominent
        alert_body += (
            f"{'='*40}\n"
            f"MESSAGE FOR {client_first_name.upper()}\n"
            f"{'='*40}\n\n"
            f"{whatsapp_message}\n\n"
        )

        if whatsapp_link_with_msg:
            alert_body += (
                f"👉 TAP TO SEND ON WHATSAPP:\n"
                f"{whatsapp_link_with_msg}\n\n"
            )
        elif whatsapp_link:
            alert_body += (
                f"👉 TAP TO OPEN WHATSAPP:\n"
                f"{whatsapp_link}\n\n"
                f"(Copy the message above and paste in chat)\n\n"
            )
        else:
            alert_body += (
                f"(No phone number captured - copy the message above and send manually)\n\n"
            )

        if client_email:
            alert_body += f"Or email them: {client_email}\n\n"

        alert_body += (
            f"{'─'*40}\n"
            f"Fireflies recording: https://app.fireflies.ai/view/{transcript_id}\n"
        )

        send_email(
            sender=f"MoneyIQ Agent <{udayan_email_addr}>",
            to=udayan_email_addr,
            subject=f"High Value Client Alert - {client_name}",
            body=alert_body
        )

    elif hv.get("is_high_value") and not is_team_call:
        # Udayan took the call himself  - just log it
        print(f"\n{'─'*60}")
        print(f"  🔔 HIGH-VALUE CLIENT (your call)  - {client_name}")
        sip_str = f"₹{hv.get('estimated_sip_monthly', 0):,.0f}/month" if hv.get("estimated_sip_monthly") else "N/A"
        lumpsum_str = f"₹{hv.get('estimated_lumpsum', 0):,.0f}" if hv.get("estimated_lumpsum") else "N/A"
        print(f"     SIP: {sip_str} | Lumpsum: {lumpsum_str}")
        print(f"{'─'*60}")

    # --- NEXT MEETING → Create pending calendar invite ---
    next_meeting = analysis.get("next_meeting", {})
    if next_meeting and next_meeting.get("discussed") and next_meeting.get("proposed_date"):
        try:
            from calendar_helpers import create_pending_meeting
            from config import SERVER_URL

            nm_date = next_meeting["proposed_date"]
            nm_time = next_meeting.get("proposed_time") or "20:00"  # default 8 PM IST
            nm_duration = next_meeting.get("proposed_duration_minutes") or 45
            nm_context = next_meeting.get("context", "Follow-up discussion")

            # Build start and end datetime strings
            start_dt = f"{nm_date}T{nm_time}:00"
            # Calculate end time
            from datetime import datetime as dt_cls
            start_obj = dt_cls.strptime(f"{nm_date} {nm_time}", "%Y-%m-%d %H:%M")
            end_obj = start_obj + timedelta(minutes=nm_duration)
            end_dt = end_obj.strftime("%Y-%m-%dT%H:%M:%S")

            # Attendees: advisor + client + any additional people mentioned
            attendee_emails = [advisor_email]
            if client_email:
                attendee_emails.append(client_email)
            # Note: additional attendees from transcript usually don't have emails

            # Title format: "Portfolio Discussion - Client Name, Advisor Name"
            meeting_title = f"Portfolio Discussion - {client_name}, {advisor_name}"

            result = create_pending_meeting(
                advisor_email=advisor_email,
                summary=meeting_title,
                description=f"Follow-up meeting: {nm_context}\n\nAuto-scheduled by MoneyIQ based on your previous call.",
                start_datetime=start_dt,
                end_datetime=end_dt,
                attendee_emails=attendee_emails,
            )

            if result:
                event_id = result["event_id"]
                meet_link = result.get("meet_link", "")
                cal_link = result.get("html_link", "")

                # Format date for display
                display_date = start_obj.strftime("%A, %d %B %Y")
                display_time = start_obj.strftime("%I:%M %p IST")

                # Build approval email to advisor
                approve_url = f"{SERVER_URL}/approve-meeting/{event_id}?advisor={advisor_email}"
                reject_url = f"{SERVER_URL}/reject-meeting/{event_id}?advisor={advisor_email}"

                approval_body = (
                    f"FOLLOW-UP MEETING SCHEDULED (PENDING YOUR APPROVAL)\n"
                    f"{'='*50}\n\n"
                    f"Client: {client_name}\n"
                    f"Date: {display_date}\n"
                    f"Time: {display_time}\n"
                    f"Duration: {nm_duration} minutes\n"
                    f"Context: {nm_context}\n"
                )

                if next_meeting.get("additional_attendees"):
                    additional = ", ".join(next_meeting["additional_attendees"])
                    approval_body += f"Additional attendees mentioned: {additional}\n"

                if meet_link:
                    approval_body += f"\nGoogle Meet link: {meet_link}\n"

                approval_body += (
                    f"\n{'─'*50}\n\n"
                    f"APPROVE THIS MEETING:\n"
                    f"{approve_url}\n\n"
                    f"(Clicking approve will send calendar invites to {client_name} and all attendees)\n\n"
                    f"REJECT THIS MEETING:\n"
                    f"{reject_url}\n\n"
                    f"(Clicking reject will delete the calendar event)\n\n"
                    f"{'─'*50}\n"
                    f"You can also edit the event directly in your calendar:\n"
                    f"{cal_link}\n\n"
                    f"— MoneyIQ Agent"
                )

                send_email(
                    sender=f"MoneyIQ Agent <{advisor_email}>",
                    to=advisor_email,
                    subject=f"Approve Meeting: {client_name} - {display_date} at {display_time}",
                    body=approval_body
                )

                print(f"\n{'─'*60}")
                print(f"  📅 NEXT MEETING DETECTED")
                print(f"     Date: {display_date} at {display_time}")
                print(f"     Context: {nm_context}")
                print(f"     Approval email sent to {advisor_name}")
                print(f"{'─'*60}")

        except Exception as e:
            print(f"  ⚠️ Calendar invite creation failed: {e}")
            import traceback
            traceback.print_exc()

    # --- INVESTMENT READINESS → Create onboarding sheet + send draft ---
    inv = analysis.get("investment_readiness", {})
    if inv.get("ready_to_invest"):
        try:
            onboarding_email_to = client_email or inv.get("client_email")
            residency = inv.get("residency_status", "Unknown")
            is_nri = residency == "NRI"

            if onboarding_email_to:
                OPS_EMAIL = "ops@withmoneyiq.com"

                # Create a per-client copy of the onboarding sheet
                from sheets_helpers import create_client_onboarding_sheet
                sheet_result = create_client_onboarding_sheet(
                    client_name=client_name,
                    client_email=onboarding_email_to,
                    advisor_email=advisor_email,
                    ops_email=OPS_EMAIL
                )

                sheet_line = ""
                if sheet_result:
                    sheet_line = (
                        f"I have shared a Google Sheet with you that has all the fields we need. "
                        f"Please fill it in directly:\n"
                        f"{sheet_result['sheet_url']}\n"
                    )
                else:
                    sheet_line = "I will share the information form with you separately.\n"

                client_first = client_name.split()[0] if client_name else "there"
                body = (
                    f"Hi {client_first},\n\n"
                    f"Great speaking with you today! As discussed, sharing what we need to get started.\n\n"
                    f"{sheet_line}"
                )

                if is_nri:
                    body += (
                        f"\nSince you are based outside India, we would also need the following:\n"
                        f"  - A cancelled cheque (NRE/NRO account)\n"
                    )
                    if inv.get("nri_kyc_required"):
                        body += (
                            f"  - NRI KYC documents (we will share the detailed list separately)\n"
                        )

                body += (
                    f"\nIf you have any questions while filling this out, feel free to reach out.\n\n"
                    f"Warm regards,\n"
                    f"{advisor_name}\n"
                    f"MoneyIQ"
                )

                subject = "Getting started - Information form"
                if is_nri:
                    subject = "Getting started - Information form + NRI documents needed"

                save_draft(
                    sender=f"{advisor_name} <{advisor_email}>",
                    to=onboarding_email_to,
                    subject=subject,
                    body=body,
                    cc=OPS_EMAIL,
                    advisor_email=advisor_email
                )

                print(f"\n{'─'*60}")
                print(f"  📋 INVESTMENT READINESS DETECTED ({residency})")
                print(f"     Onboarding sheet created for {client_name}")
                print(f"     Draft saved → {onboarding_email_to} (CC: {OPS_EMAIL})")
                if is_nri:
                    print(f"     NRI docs requested: cancelled cheque" +
                          (" + KYC" if inv.get("nri_kyc_required") else ""))
                print(f"{'─'*60}")
            else:
                print(f"  ⚠️ Investment readiness detected but no client email found")

        except Exception as e:
            print(f"  ⚠️ Investment onboarding email failed: {e}")

    # --- CONTENT IDEAS → Collect and return ---
    content_ideas = []
    if analysis.get("content_ideas"):
        print(f"\n{'─'*60}")
        print(f"  💡 CONTENT IDEAS FROM THIS MEETING")
        print(f"{'─'*60}")
        for i, idea in enumerate(analysis["content_ideas"], 1):
            print(f"  {i}. {idea}")
            content_ideas.append({
                "idea": idea,
                "client_name": client_name,
                "advisor": advisor_name,
                "meeting_date": meeting_date_str,
                "context": analysis.get("summary", "")
            })

    # --- FOLLOW-UP SEQUENCE → Create contextual post-meeting touchpoints ---
    try:
        followup_msgs = analysis.get("followup_messages", {})
        if followup_msgs and any(v for v in followup_msgs.values() if v):
            meeting_id = meeting_record["id"] if meeting_record else None

            # Transform Claude's flat dict into the list format followup_manager expects
            sequence_items = []

            # Day 1 — WhatsApp warm check-in
            if followup_msgs.get("day1_whatsapp"):
                sequence_items.append({
                    "day": 1, "channel": "WhatsApp", "type": "warm_checkin",
                    "message": followup_msgs["day1_whatsapp"], "subject": ""
                })

            # Day 3 — WhatsApp action nudge (conditional)
            if followup_msgs.get("day3_whatsapp"):
                sequence_items.append({
                    "day": 3, "channel": "WhatsApp", "type": "action_nudge",
                    "message": followup_msgs["day3_whatsapp"], "subject": ""
                })

            # Day 7 — Email value-add
            if followup_msgs.get("day7_email_body"):
                sequence_items.append({
                    "day": 7, "channel": "Email", "type": "value_add",
                    "message": followup_msgs["day7_email_body"],
                    "subject": followup_msgs.get("day7_email_subject", "Following up")
                })

            # Day 14 — WhatsApp soft re-engagement
            if followup_msgs.get("day14_whatsapp"):
                sequence_items.append({
                    "day": 14, "channel": "WhatsApp", "type": "soft_reengage",
                    "message": followup_msgs["day14_whatsapp"], "subject": ""
                })

            if sequence_items:
                create_followup_sequence(
                    contact_id=contact_id,
                    contact_name=client_name,
                    client_email=client_email or "",
                    client_phone=client_phone_from_crm or "",
                    advisor_name=advisor_name,
                    meeting_id=meeting_id,
                    meeting_date_str=meeting_date_str,
                    followup_messages=sequence_items
                )
            print(f"\n{'─'*60}")
            print(f"  📅 FOLLOW-UP SEQUENCE CREATED")
            print(f"     4 touchpoints scheduled (Day 1, 3, 7, 14)")
            print(f"     Dashboard: /followups")
            print(f"{'─'*60}")
        else:
            print(f"  ⚠️ No follow-up messages generated by Claude — skipping sequence")
    except Exception as e:
        print(f"  ⚠️ Follow-up sequence creation failed: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  ✅ Meeting processing complete!")
    print(f"{'='*60}")

    return content_ideas


def run_meeting_processor(days_back=1):
    print("\n" + "=" * 60)
    print("  🧠 MEETING PROCESSOR AGENT  - Starting")
    print(f"  Checking for meetings in the last {days_back} day(s)")
    print("=" * 60)

    transcripts = get_recent_transcripts(days_back=days_back)
    if not transcripts:
        print("\n  No new meetings found. Nothing to process.")
        return

    # Collect content ideas across ALL meetings
    all_content_ideas = []

    for t in transcripts:
        duration = t.get("duration", None)
        ideas = process_single_meeting(t["id"], duration_hint=duration)
        if ideas:
            all_content_ideas.extend(ideas)

    # Send one consolidated content ideas email if there are any
    if all_content_ideas:
        send_content_ideas_email(all_content_ideas, len(transcripts))

    print(f"\n  🎉 All done! Processed {len(transcripts)} meeting(s).")


def send_content_ideas_email(all_ideas, meeting_count):
    """Send one consolidated email with all content ideas from today's meetings."""
    udayan_email = ADVISORS["udayan"]["email"]
    today_str = date.today().strftime("%d %b %Y")

    body = (
        f"Content ideas from {meeting_count} meeting(s) today.\n"
        f"These came up naturally in client conversations  - real questions and topics your audience cares about.\n\n"
    )

    # Group ideas by meeting/client
    current_client = None
    idea_num = 1
    for item in all_ideas:
        client = item.get("client_name", "Unknown")
        if client != current_client:
            current_client = client
            body += f"{'─'*40}\n"
            body += f"From call with {client} ({item.get('meeting_date', 'today')}):\n\n"

        body += f"  {idea_num}. {item['idea']}\n"
        idea_num += 1

    body += (
        f"\n{'─'*40}\n"
        f"Total ideas: {len(all_ideas)}\n"
    )

    send_email(
        sender=f"MoneyIQ Agent <{udayan_email}>",
        to=udayan_email,
        subject=f"Content Ideas from Today's Calls  - {len(all_ideas)} ideas ({today_str})",
        body=body
    )

    print(f"\n{'─'*60}")
    print(f"  📧 Content ideas email sent  - {len(all_ideas)} idea(s) from {meeting_count} meeting(s)")
    print(f"{'─'*60}")


# ══════════════════════════════════════════════
# RUN  - change days_back to 7 to catch up on a week
# ══════════════════════════════════════════════
if __name__ == "__main__":
    run_meeting_processor(days_back=7)
