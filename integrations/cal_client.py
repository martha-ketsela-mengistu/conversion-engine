import os
import httpx
from dotenv import load_dotenv
from observability.tracing import observe

load_dotenv()

_BASE_URL = os.getenv("CAL_BASE_URL", "https://api.cal.com/v2")


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
        return r.json().get("slots", [])


@observe(name="cal.create_booking")
def create_booking(event_type_id: int, start_time: str, attendee: dict) -> dict:
    """Creates a booking. In dev mode (PRODUCTION_MODE=False) returns a mock response."""
    if os.getenv("PRODUCTION_MODE", "false").lower() != "true":
        return {
            "uid": "mock-booking-uid",
            "status": "ACCEPTED",
            "start": start_time,
            "attendee": attendee,
            "_mock": True,
        }
    with _client() as c:
        r = c.post(
            "/bookings",
            json={
                "eventTypeId": event_type_id,
                "start": start_time,
                "attendee": attendee,
            },
        )
        r.raise_for_status()
        data = r.json()
        return {"uid": data["uid"], "status": data["status"], "start": data["start"]}


@observe(name="cal.cancel_booking")
def cancel_booking(booking_uid: str, reason: str = "") -> dict:
    if os.getenv("PRODUCTION_MODE", "false").lower() != "true":
        return {"uid": booking_uid, "status": "CANCELLED", "_mock": True}
    with _client() as c:
        r = c.delete(f"/bookings/{booking_uid}", json={"cancellationReason": reason})
        r.raise_for_status()
        return {"uid": booking_uid, "status": "CANCELLED"}
