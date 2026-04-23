import os
import httpx
from dotenv import load_dotenv
from agent.observability.tracing import observe

load_dotenv()

_BASE_URL = os.getenv("CAL_BASE_URL", "https://api.cal.com/v2")


def _is_dev() -> bool:
    return os.getenv("PRODUCTION_MODE", "false").lower() != "true"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['CAL_API_KEY']}",
        "Content-Type": "application/json",
        "cal-api-version": "2024-08-13",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=_BASE_URL, headers=_headers(), timeout=15)


@observe(name="cal.get_available_slots")
def get_available_slots(event_type_id: int, start_time: str, end_time: str) -> list[dict]:
    """Returns available slots for the given event type within the date range.

    start_time / end_time must be ISO-8601 strings, e.g. '2026-04-22T00:00:00Z'.
    Returns a flat list of dicts with a 'time' key.
    """
    with _client() as c:
        r = c.get(
            "/slots/available",
            params={
                "eventTypeId": event_type_id,
                "startTime": start_time,
                "endTime": end_time,
            },
        )
        r.raise_for_status()
        body = r.json()
        # Cal.com v2: {"data": {"slots": {"2026-04-24": [{"time": "..."}]}}}
        # Flatten across all dates
        raw = body.get("data", body).get("slots", {})
        if isinstance(raw, list):
            return raw
        slots: list[dict] = []
        for day_slots in raw.values():
            slots.extend(day_slots)
        return slots


@observe(name="cal.create_booking")
def create_booking(event_type_id: int, start_time: str, attendee: dict) -> dict:
    """Creates a booking via Cal.com v2 API. Returns mock in dev mode."""
    if _is_dev():
        return {
            "uid": "mock-booking-uid",
            "status": "ACCEPTED",
            "start": start_time,
            "_mock": True,
        }
    full_attendee = {"timeZone": "UTC", **attendee}
    with _client() as c:
        r = c.post(
            "/bookings",
            json={
                "eventTypeId": event_type_id,
                "start": start_time,
                "attendee": full_attendee,
            },
        )
        if not r.is_success:
            raise httpx.HTTPStatusError(
                f"{r.status_code} from Cal.com: {r.text}",
                request=r.request,
                response=r,
            )
        data = r.json().get("data", r.json())
        return {"uid": data["uid"], "status": data["status"], "start": data["start"]}


@observe(name="cal.cancel_booking")
def cancel_booking(booking_uid: str, reason: str = "") -> dict:
    if _is_dev():
        return {"uid": booking_uid, "status": "CANCELLED", "_mock": True}
    with _client() as c:
        r = c.delete(
            f"/bookings/{booking_uid}",
            content=f'{{"cancellationReason": "{reason}"}}',
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return {"uid": booking_uid, "status": "CANCELLED"}
