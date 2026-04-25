"""Resend inbound email reply webhook handler (Phase 4).

Resend posts a JSON payload to this endpoint when a prospect replies to an outreach email.
We:
  1. Parse the sender and body text
  2. Detect if the prospect wants to switch to SMS
  3. Auto-reply with a Cal.com booking link
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException

from agent.integrations.hubspot_client import get_contact_by_email, create_deal
from agent.integrations.hubspot_mcp import log_email_sent, log_sms_sent, log_booking_created
from agent.integrations.resend_client import send_email
from agent.integrations.africas_talking import send_sms
from agent.integrations.cal_client import create_booking
from agent.observability.tracing import record_span
from agent.prompts import build_objection_response, build_capacity_gap_reply

import httpx

logger = logging.getLogger(__name__)
router = APIRouter()

_CAL_LINK = "https://cal.com/tenacious/discovery"
_CAL_EVENT_TYPE_ID = int(os.getenv("CAL_EVENT_TYPE_ID", "12345"))
_SMS_KEYWORDS = {"text me", "sms", "whatsapp", "call me", "phone"}

_BENCH_PATH = Path(__file__).parent.parent / "data" / "tenacious_sales_data" / "seed" / "bench_summary.json"

# In-process committed capacity ledger — persists across requests within a single server process.
_COMMITTED: dict[str, int] = {}

_STACK_KEYWORDS: dict[str, list[str]] = {
    "rust": ["rust"],
    "python": ["python", "django", "fastapi", "flask"],
    "go": ["golang", " go "],
    "data": ["data engineer", "data engineers"],
    "ml": ["machine learning", "ml engineer", "pytorch", "tensorflow"],
    "infra": ["infrastructure", "devops", "kubernetes", "terraform"],
    "frontend": ["frontend", "react engineer", "vue engineer", "angular"],
    "fullstack_nestjs": ["nestjs", "nest.js", "fullstack"],
}


def _attempt_programmatic_booking(text: str, email: str, name: str) -> dict | None:
    """Use LLM to detect proposed time and book it via Cal.com. Returns booking dict or None."""
    llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("ENRICHMENT_MODEL", "qwen/qwen3.5-flash-02-23").removeprefix("openrouter/")

    if not api_key:
        return None

    prompt = (
        f"Analyze the following email reply:\n'{text}'\n\n"
        "Does the prospect propose a specific date and time to meet? "
        "If yes, return ONLY a JSON object with 'wants_booking': true and 'start_time': 'YYYY-MM-DDTHH:MM:00Z' (assume current year is 2026). "
        "If no, return ONLY {'wants_booking': false}."
    )

    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{llm_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}]}
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # Extract JSON block if surrounded by backticks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()

            data = json.loads(content)
            if data.get("wants_booking") and data.get("start_time"):
                start_time = data["start_time"]
                logger.info("programmatic_booking detected start_time=%s email=%s", start_time, email)
                result = create_booking(
                    event_type_id=_CAL_EVENT_TYPE_ID,
                    start_time=start_time,
                    attendee={"email": email, "name": name},
                )
                return result
    except Exception as e:
        logger.error("programmatic_booking failed exc=%s", e)

    return None


def _detect_intent(text: str) -> str:
    """Use LLM to detect the intent of the email reply."""
    llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("ENRICHMENT_MODEL", "qwen/qwen3.5-flash-02-23").removeprefix("openrouter/")

    if not api_key:
        return "positive"

    prompt = (
        f"Analyze the intent of this B2B email reply:\n'{text}'\n\n"
        "Categorize as exactly one: 'positive', 'objection_price', 'objection_vendor', 'objection_poc', 'unsubscribe', or 'neutral'.\n"
        "Return ONLY the category string."
    )

    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{llm_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}]}
            )
            r.raise_for_status()
            intent = r.json()["choices"][0]["message"]["content"].lower().strip().replace("'", "").replace('"', "")
            return intent
    except Exception:
        return "neutral"


def _extract_stack_ask(text: str) -> str | None:
    """Return the first stack keyword found in the email body, or None."""
    text_lower = text.lower()
    for stack, keywords in _STACK_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return stack
    return None


def _check_bench_for_stack(stack_name: str) -> dict:
    """Return available engineers and deploy days for a stack from bench_summary.json."""
    if not _BENCH_PATH.exists():
        return {"available": 0, "deploy_days": 14}
    with open(_BENCH_PATH) as f:
        summary = json.load(f)
    stack = summary.get("stacks", {}).get(stack_name, {})
    return {
        "available": stack.get("available_engineers", 0),
        "deploy_days": stack.get("time_to_deploy_days", 14),
    }


@router.post("/webhook/email/reply")
async def handle_email_reply(request: Request) -> dict:
    """Handle an inbound email reply forwarded by Resend."""
    _t0 = time.monotonic()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type: str = payload.get("type", "")
    logger.info("email_reply.received type=%s", event_type)

    # Resend inbound event types: "email.received" or legacy "inbound"
    if not any(kw in event_type.lower() for kw in ("reply", "inbound", "received")):
        logger.debug("email_reply.ignored type=%s", event_type)
        record_span("webhook.email.reply", (time.monotonic() - _t0) * 1000, status="ignored", event_type=event_type)
        return {"status": "ignored", "type": event_type}

    data: dict = payload.get("data", {})
    from_email: str = data.get("from", "")
    body_text: str = data.get("text", "") or data.get("plain_text", "") or ""
    subject: str = data.get("subject", "")

    logger.info("email_reply.parsed from=%s subject=%r body_len=%d", from_email, subject, len(body_text))

    if not from_email:
        record_span("webhook.email.reply", (time.monotonic() - _t0) * 1000, status="skipped", reason="no_sender")
        return {"status": "skipped", "reason": "no sender"}

    # Look up prospect in HubSpot to get phone number if needed
    contact = get_contact_by_email(from_email)
    logger.info("email_reply.hubspot_lookup from=%s found=%s id=%s", from_email, contact is not None, (contact or {}).get("id"))

    # Log inbound reply to HubSpot via MCP
    if contact:
        log_email_sent(from_email, f"Re: {subject}", body_text)
        logger.info("email_reply.mcp_email_logged from=%s", from_email)

    # Detect SMS handoff intent
    body_lower = body_text.lower()
    wants_sms = any(kw in body_lower for kw in _SMS_KEYWORDS)
    sms_sent = False
    if wants_sms:
        phone = (contact or {}).get("properties", {}).get("phone", "")
        logger.info("email_reply.sms_handoff from=%s phone=%s has_phone=%s", from_email, phone, bool(phone))
        if phone:
            send_sms(
                to=phone,
                message=f"Hi! Here's your discovery call link: {_CAL_LINK}",
            )
            sms_sent = True
            if contact:
                log_sms_sent(from_email, f"Sent booking link to {phone}")
            logger.info("email_reply.sms_sent to=%s", phone)

    # Intent detection and response
    intent = _detect_intent(body_text)
    logger.info("email_reply.intent_detected from=%s intent=%s", from_email, intent)

    if intent == "unsubscribe":
        logger.info("email_reply.unsubscribe from=%s", from_email)
        # In real life, we'd unsubscribe them in HubSpot here
        return {"status": "unsubscribed", "from": from_email}

    # Bench-gated capacity check (PROBE-3-1 fix)
    # Must run before programmatic booking so capacity questions get an honest answer.
    stack_ask = _extract_stack_ask(body_text)
    if stack_ask and not sms_sent:
        bench_info = _check_bench_for_stack(stack_ask)
        committed = _COMMITTED.get(stack_ask, 0)
        effective = bench_info["available"] - committed
        capacity_html = build_capacity_gap_reply(stack_ask, effective, bench_info["deploy_days"])
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=capacity_html,
            )
            if effective > 0:
                _COMMITTED[stack_ask] = committed + 1
        except Exception as send_err:
            logger.error("email_reply.bench_reply_send_failed from=%s exc=%s", from_email, send_err)
        logger.info("email_reply.bench_reply from=%s stack=%s effective=%d", from_email, stack_ask, effective)
        record_span("webhook.email.reply", (time.monotonic() - _t0) * 1000, bench_check=True, stack=stack_ask)
        return {"status": "processed", "from": from_email, "sms_triggered": sms_sent}

    # Neutral intent: ask a soft scheduling question first rather than pushing a link (PROBE-7-1 fix)
    if intent == "neutral" and not sms_sent:
        logger.info("email_reply.neutral_soft_ask from=%s", from_email)
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=(
                    "<p>Thanks for the note — good to hear from you.</p>"
                    "<p>Would a quick 20-minute call make sense to explore whether there's a fit? "
                    "Happy to work around your schedule.</p>"
                    "<p>Best,<br>Martha @ Tenacious</p>"
                ),
            )
        except Exception as send_err:
            logger.error("email_reply.neutral_send_failed from=%s exc=%s", from_email, send_err)
        record_span("webhook.email.reply", (time.monotonic() - _t0) * 1000, from_email=from_email, intent="neutral")
        return {"status": "processed", "from": from_email, "intent": "neutral"}

    # Attempt programmatic booking via LLM (positive intent only)
    booking: dict | None = None
    if intent == "positive":
        prospect_name = (contact or {}).get("properties", {}).get("firstname", "Prospect")
        logger.info("email_reply.programmatic_booking_attempt from=%s name=%s", from_email, prospect_name)
        booking = _attempt_programmatic_booking(body_text, from_email, prospect_name)

    booked_time = booking["start"] if booking else None
    is_mock_booking = booking.get("_mock", False) if booking else False

    if booked_time:
        logger.info("email_reply.booking_confirmed from=%s booked_time=%s mock=%s", from_email, booked_time, is_mock_booking)
        if contact:
            log_booking_created(from_email, booked_time)
            # Create HubSpot deal at appointmentscheduled stage
            try:
                company = contact["properties"].get("company", from_email)
                create_deal(
                    contact_id=contact["id"],
                    deal_name=f"Discovery Call – {company} ({booked_time[:10]})",
                    stage="appointmentscheduled",
                )
            except Exception as deal_err:
                logger.error("email_reply.deal_create_failed from=%s exc=%s", from_email, deal_err)
        booking_uid = booking.get("uid", "") if booking else ""
        cal_link = f"https://cal.com/booking/{booking_uid}" if booking_uid and not is_mock_booking else _CAL_LINK
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=(
                    f"<p>Great — I've booked us in for <strong>{booked_time}</strong>.</p>"
                    f"<p>You can view or manage the booking here: <a href='{cal_link}'>{cal_link}</a></p>"
                    "<p>A calendar invite is on its way. Looking forward to connecting,<br>Martha @ Tenacious</p>"
                ),
            )
        except Exception as send_err:
            logger.error("email_reply.booking_confirm_send_failed from=%s exc=%s", from_email, send_err)
    elif "objection" in intent:
        # Handle objections
        objection_key = {
            "objection_price": "price_higher_than_india",
            "objection_vendor": "already_working_with_major_vendor",
            "objection_poc": "small_poc_only",
        }.get(intent, "neutral")
        
        reply_body = build_objection_response(objection_key)
        logger.info("email_reply.objection_reply from=%s intent=%s key=%s", from_email, intent, objection_key)
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=(
                    f"<p>{reply_body}</p>"
                    f"<p>Does a 15-minute call to compare notes make sense? "
                    f"<a href='{_CAL_LINK}'>Book here</a></p>"
                    "<p>Best,<br>Martha @ Tenacious</p>"
                ),
            )
        except Exception as send_err:
            logger.error("email_reply.objection_send_failed from=%s exc=%s", from_email, send_err)
    elif body_text and not sms_sent:
        # Fallback: Auto-reply with booking link
        logger.info("email_reply.auto_reply from=%s", from_email)
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=(
                    "<p>Thanks for replying — great to hear from you!</p>"
                    f"<p>You can book a 20-min discovery call here: "
                    f"<a href='{_CAL_LINK}'>{_CAL_LINK}</a></p>"
                    "<p>Looking forward to connecting,<br>Martha @ Tenacious</p>"
                ),
            )
        except Exception as send_err:
            logger.error("email_reply.auto_reply_send_failed from=%s exc=%s", from_email, send_err)

    logger.info(
        "email_reply.done from=%s sms_sent=%s booked_time=%s",
        from_email, sms_sent, booked_time,
    )
    record_span(
        "webhook.email.reply",
        (time.monotonic() - _t0) * 1000,
        from_email=from_email,
        sms_triggered=sms_sent,
        booked=booked_time is not None,
        mock=is_mock_booking,
    )
    return {
        "status": "processed",
        "from": from_email,
        "sms_triggered": sms_sent,
    }
