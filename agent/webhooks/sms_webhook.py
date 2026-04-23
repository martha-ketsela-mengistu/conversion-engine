"""Africa's Talking inbound SMS webhook handler (Phase 4).

Africa's Talking POSTs form-encoded data when an SMS is received on the shortcode.
We classify the intent, and for book_call intent we book the next available Cal.com
slot, send a confirmation SMS, and log the event to HubSpot.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from agent.integrations.africas_talking import send_sms
from agent.integrations.cal_client import create_booking, get_available_slots
from agent.integrations.hubspot_client import search_contact_by_phone
from agent.integrations.hubspot_mcp import log_booking_created
from agent.observability.tracing import record_span

logger = logging.getLogger(__name__)
router = APIRouter()

_BOOK_KEYWORDS = {"book", "schedule", "call", "meeting", "yes", "interested"}
_OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel"}
_CAL_EVENT_TYPE_ID = int(os.getenv("CAL_EVENT_TYPE_ID", "12345"))


@router.post("/webhook/sms")
async def handle_sms(request: Request) -> dict:
    """Handle an inbound SMS from Africa's Talking."""
    _t0 = time.monotonic()
    form = await request.form()
    from_ = str(form.get("from", ""))
    text = str(form.get("text", "")).strip()
    to = str(form.get("to", ""))
    date = str(form.get("date", ""))

    logger.info("sms.received from=%s to=%s text=%r", from_, to, text[:80])

    text_lower = text.lower()

    if any(kw in text_lower for kw in _OPT_OUT_KEYWORDS):
        intent = "opt_out"
    elif any(kw in text_lower for kw in _BOOK_KEYWORDS):
        intent = "book_call"
    elif any(kw in text_lower for kw in {"info", "more", "tell me", "details"}):
        intent = "wants_info"
    else:
        intent = "unknown"

    logger.info("sms.intent from=%s intent=%s", from_, intent)

    booking_uid = None
    booked_time = None

    if intent == "book_call" and from_:
        logger.info("sms.book_call.start from=%s", from_)

        # 1. Look up contact in HubSpot
        contact = search_contact_by_phone(from_)
        logger.info("sms.book_call.contact_lookup from=%s found=%s id=%s", from_, contact is not None, (contact or {}).get("id"))

        attendee_email = (
            (contact or {}).get("properties", {}).get("email")
            or f"sms_{from_.lstrip('+')[:12]}@unknown.prospect"
        )
        attendee_name = (contact or {}).get("properties", {}).get("firstname") or "Prospect"

        # 2. Fetch available Cal.com slots for the next 7 days
        now = datetime.now(timezone.utc)
        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("sms.book_call.get_slots event_type_id=%s start=%s end=%s", _CAL_EVENT_TYPE_ID, start_str, end_str)

        slots = get_available_slots(
            event_type_id=_CAL_EVENT_TYPE_ID,
            start_time=start_str,
            end_time=end_str,
        )
        logger.info("sms.book_call.slots_found count=%d", len(slots))

        booked_time = (
            slots[0]["time"]
            if slots
            else (now + timedelta(days=1))
            .replace(hour=10, minute=0, second=0, microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        )
        logger.info("sms.book_call.selected_slot booked_time=%s from_slots=%s", booked_time, bool(slots))

        # 3. Create the Cal.com booking
        logger.info("sms.book_call.create_booking attendee_email=%s booked_time=%s", attendee_email, booked_time)
        booking = create_booking(
            event_type_id=_CAL_EVENT_TYPE_ID,
            start_time=booked_time,
            attendee={"email": attendee_email, "name": attendee_name},
        )
        booking_uid = booking.get("uid")
        logger.info("sms.book_call.booking_created uid=%s status=%s", booking_uid, booking.get("status"))

        # 4. Send confirmation SMS (non-fatal failure)
        try:
            send_sms(
                to=from_,
                message=(
                    f"Booked! Your 20-min discovery call with Tenacious is set for "
                    f"{booked_time[:16].replace('T', ' ')} UTC. Ref: {booking_uid}"
                ),
            )
            logger.info("sms.book_call.confirmation_sent to=%s", from_)
        except Exception as sms_err:
            logger.warning("sms.book_call.confirmation_failed err=%s (booking still created)", sms_err)

        # 5. Log to HubSpot contact timeline via MCP
        if contact:
            log_booking_created(attendee_email, booked_time)
            logger.info("sms.book_call.mcp_booking_logged email=%s", attendee_email)

        logger.info("sms.book_call.done from=%s uid=%s booked_time=%s", from_, booking_uid, booked_time)

    record_span(
        "webhook.sms",
        (time.monotonic() - _t0) * 1000,
        from_=from_,
        intent=intent,
        booked=booking_uid is not None,
    )
    return {
        "status": "received",
        "from": from_,
        "to": to,
        "date": date,
        "intent": intent,
        "text": text,
        "booking_uid": booking_uid,
        "booked_time": booked_time,
    }
