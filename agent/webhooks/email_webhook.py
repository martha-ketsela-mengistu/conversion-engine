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
from fastapi import APIRouter, Request, HTTPException

from agent.integrations.hubspot_client import get_contact_by_email
from agent.integrations.hubspot_mcp import log_email_sent, log_sms_sent, log_booking_created
from agent.integrations.resend_client import send_email
from agent.integrations.africas_talking import send_sms
from agent.integrations.cal_client import create_booking
from agent.observability.tracing import record_span

import httpx

logger = logging.getLogger(__name__)
router = APIRouter()

_CAL_LINK = "https://cal.com/tenacious/discovery"
_CAL_EVENT_TYPE_ID = int(os.getenv("CAL_EVENT_TYPE_ID", "12345"))
_SMS_KEYWORDS = {"text me", "sms", "whatsapp", "call me", "phone"}


def _attempt_programmatic_booking(text: str, email: str, name: str) -> str | None:
    """Use LLM to detect proposed time and book it via Cal.com. Returns booked time or None."""
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
                create_booking(
                    event_type_id=_CAL_EVENT_TYPE_ID,
                    start_time=start_time,
                    attendee={"email": email, "name": name},
                )
                return start_time
    except Exception as e:
        logger.error("programmatic_booking failed exc=%s", e)

    return None


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

    # Attempt programmatic booking via LLM
    prospect_name = (contact or {}).get("properties", {}).get("firstname", "Prospect")
    logger.info("email_reply.programmatic_booking_attempt from=%s name=%s", from_email, prospect_name)
    booked_time = _attempt_programmatic_booking(body_text, from_email, prospect_name)

    if booked_time:
        logger.info("email_reply.booking_confirmed from=%s booked_time=%s", from_email, booked_time)
        if contact:
            log_booking_created(from_email, booked_time)
        try:
            send_email(
                to=from_email,
                subject=f"Re: {subject}" if subject else "Re: Your reply",
                html=(
                    f"<p>Great! I have gone ahead and booked us for {booked_time}.</p>"
                    "<p>You should receive a calendar invite shortly.</p>"
                    "<p>Looking forward to connecting,<br>Martha @ Tenacious</p>"
                ),
            )
        except Exception as send_err:
            logger.error("email_reply.booking_confirm_send_failed from=%s exc=%s", from_email, send_err)
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
    )
    return {
        "status": "processed",
        "from": from_email,
        "sms_triggered": sms_sent,
    }
