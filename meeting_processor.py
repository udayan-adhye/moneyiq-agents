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

client = Anthropic(api_key=CLAUDE_API_KEY)


def analyze_meeting_with_claude(transcript_text, advisor_name, client_name):
    # Look up advisor phone for email signatures
    advisor_phone_for_prompt = ""
    for adv_info in ADVISORS.values():
        if adv_info["name"] == advisor_name:
            advisor_phone_for_prompt = adv_info.get("phone", "")
            break

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
    "client_phone": "Client's phone number if mentioned in the conversation. null if not mentioned."
  }},

  "client_financial_goals": "Brief summary of financial goals discussed",
  "investment_amount_discussed": null or number in rupees,

  "follow_up_email_subject": "A short, specific email subject line. MUST start with 'Our investment call today' followed by a dash and something specific from the meeting (e.g., 'Our investment call today  - your SIP plan' or 'Our investment call today  - retirement portfolio'). Keep it under 60 characters total.",

  "follow_up_email": "A warm, structured follow-up email. Use this EXACT structure:\n\n1. OPENING (2-3 sentences): A warm, personal opening referencing something specific from the conversation. Keep the current natural tone - make the person feel heard and valued.\n\n2. WHAT WE DISCUSSED: A paragraph summarizing the key topics covered in the meeting. Be specific - mention actual numbers, goals, and situations discussed.\n\n3. KEY ACTION POINTS: Bullet points of the main recommendations and action items discussed. Be specific and practical.\n\n4. WHAT I WILL BE SENDING YOU: List what the advisor committed to sending or doing for them.\n\n5. WHAT I WOULD NEED FROM YOU: List what the prospect needs to share or do. IMPORTANT: If at ANY point in the conversation there was a mention of wanting to see/review/consolidate the prospect's mutual funds across PAN cards or folios, or if the prospect needs to share their mutual fund portfolio, ALWAYS include this line: 'Your consolidated mutual fund statement - you can download it here: https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement'\n\n6. NEXT STEPS: What happens next - follow-up meeting, timeline, etc.\n\nSign off with:\nWarm regards,\n{advisor_name}\nMoneyIQ\n{advisor_phone_for_prompt}\n\nIMPORTANT RULES FOR THIS EMAIL:\n- Use section headers like 'What we discussed:', 'Key action points:', etc. (lowercase, with colon)\n- The opening should feel personal and warm, NOT corporate\n- Be specific throughout - use actual numbers, names, and details from the conversation\n- This email should serve as a complete recap that makes the prospect's life easier\n- Do NOT use the word 'recommendations' - use 'action points' instead\n- NEVER use the word 'client' - these are prospects, not clients yet",

  "insurance_type": "If insurance was discussed, what type: term life, health, critical illness, personal accident, or other. Empty string if not discussed.",
  "insurance_details_for_team": "If insurance was discussed, describe any specific details mentioned: family size, existing coverage, budget range, specific concerns. Empty string if not discussed.",
  "insurance_recommendation": "If the person conducting the meeting suggested any specific insurance idea or recommendation, describe it here. Empty string if nothing was suggested.",

  "ca_introduction_email": "{ca_instruction}",

  "content_ideas": ["Any interesting questions or topics from this meeting that could make good content for YouTube or social media. 1-3 ideas, or empty array."]
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
- All monetary amounts should be in Indian Rupees (numbers, not words).
- NEVER use the word "advisor" in any client-facing email (follow_up_email, ca_introduction_email). Do not refer to anyone as an "advisor". Use the person's first name instead.
- NEVER use the word "client" in any email. These are prospects, not clients yet. Use their first name or "them/they" instead.
- NEVER use the phrase "investment advice" in any email. We do not give investment advice. Use phrases like "financial planning", "your goals", "your plan" instead.
- NEVER use em dashes in any email text. Use regular dashes (-) or commas instead.
- NEVER use the word "recommendations" in client-facing emails. Use "action points" instead.

TRANSCRIPT:
{transcript_text}
"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
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
        print("  ✅ Claude analysis complete")
        return analysis
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse Claude's response as JSON: {e}")
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


def process_single_meeting(transcript_id):
    print(f"\n{'='*60}")
    print(f"  Processing transcript: {transcript_id}")
    print(f"{'='*60}")

    # Step 1: Fetch the full transcript
    transcript = get_full_transcript(transcript_id)
    if not transcript:
        print("  ⚠️  Could not fetch transcript. Skipping.")
        return

    # Step 2: Determine who's who
    advisor_name = determine_advisor_from_transcript(transcript)
    client_name = find_client_in_participants(transcript, advisor_name)
    print(f"  👤 Advisor: {advisor_name}")
    print(f"  👤 Client:  {client_name}")

    # Step 3: Send to Claude for analysis
    transcript_text = format_transcript_for_claude(transcript)
    analysis = analyze_meeting_with_claude(transcript_text, advisor_name, client_name)
    if not analysis:
        print("  ⚠️  Claude analysis failed. Skipping.")
        return

    # Step 4: Find or create the contact in Notion
    contact = None
    participants = transcript.get("participants", [])
    for p in participants:
        if "@" in p:
            for advisor_info in ADVISORS.values():
                if advisor_info["email"].lower() != p.lower():
                    contact = find_contact_by_email(p)
                    break

    if not contact and client_name != "Unknown Client":
        contact = find_contact_by_name(client_name)

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

    update_contact(contact_id, contact_updates)

    # Step 6: Create meeting record
    meeting_date_str = transcript.get("parsed_date", date.today().isoformat())
    if "T" in meeting_date_str:
        meeting_date_str = meeting_date_str.split("T")[0]

    create_meeting(
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
        quality_score=analysis.get("meeting_quality_score")
    )

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
    advisor_email = advisor_email or list(ADVISORS.values())[0]["email"]
    sender = f"{advisor_name} <{advisor_email}>"

    # Find client email and phone  - prefer Notion (from Calendly) over transcript
    client_email = get_contact_field(contact, "Email") if contact else None
    client_phone_from_crm = get_contact_field(contact, "WhatsApp Number") if contact else None

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
        save_draft(
            sender=sender,
            to=client_email,
            subject=follow_up_subject,
            body=analysis["follow_up_email"]
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

    # --- CA INTRODUCTION → SAVE AS DRAFT ---
    if analysis.get("ca_introduction_needed") and analysis.get("ca_introduction_email"):
        print(f"\n{'─'*60}")
        print(f"  📧 SAVING DRAFT: CA Introduction for {client_name}")
        print(f"{'─'*60}")
        save_draft(
            sender=sender,
            to=CA_CONTACT_EMAIL,
            subject=f"Introduction  - {client_name} (CA consultation needed)",
            body=analysis["ca_introduction_email"],
            cc=client_email
        )

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

        # Topics discussed (for WhatsApp message)
        topics = analysis.get("client_financial_goals", "your financial goals")

        # WhatsApp template  - mentions team member by first name
        advisor_first = advisor_name.split()[0]
        whatsapp_message = (
            f"Hi {client_first_name}, this is Udayan from MoneyIQ. "
            f"I know you spoke to {advisor_first} from my team today and I hope it was helpful. "
            f"I'd love to help you further with {topics}. "
            f"Would you have a few minutes for a quick chat?"
        )

        # WhatsApp link with pre-filled message
        whatsapp_link_with_msg = ""
        if whatsapp_link:
            import urllib.parse
            encoded_msg = urllib.parse.quote(whatsapp_message)
            whatsapp_link_with_msg = f"{whatsapp_link}?text={encoded_msg}"

        alert_body = (
            f"Client: {client_name}\n"
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

        if whatsapp_link_with_msg:
            alert_body += (
                f"{'─'*40}\n"
                f"TAP TO MESSAGE ON WHATSAPP\n"
                f"{whatsapp_link_with_msg}\n\n"
                f"Suggested message:\n"
                f"\"{whatsapp_message}\"\n\n"
            )
        elif whatsapp_link:
            alert_body += (
                f"{'─'*40}\n"
                f"TAP TO OPEN WHATSAPP CHAT\n"
                f"{whatsapp_link}\n\n"
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
        ideas = process_single_meeting(t["id"])
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
