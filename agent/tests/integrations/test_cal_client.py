"""Integration tests for the Cal.com cloud API client.

Mocked tests use respx to intercept httpx calls — no network required.
Live tests (--m integration) hit the real Cal.com API using CAL_API_KEY from .env.
"""

import os
import pytest
import respx
import httpx

import agent.integrations.cal_client as cal


class TestCalClientMocked:
    def test_get_available_slots_returns_list(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")

        slots_payload = {
            "data": {
                "slots": {
                    "2026-04-23": [
                        {"time": "2026-04-23T09:00:00Z"},
                        {"time": "2026-04-23T10:00:00Z"},
                    ]
                }
            }
        }

        with respx.mock(base_url="https://api.cal.com/v2") as mock:
            mock.get("/slots/available").mock(
                return_value=httpx.Response(200, json=slots_payload)
            )
            slots = cal.get_available_slots(
                event_type_id=1,
                start_time="2026-04-23T00:00:00Z",
                end_time="2026-04-24T00:00:00Z",
            )

        assert isinstance(slots, list)
        assert len(slots) == 2
        assert slots[0]["time"] == "2026-04-23T09:00:00Z"

    def test_create_booking_returns_mock_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")

        result = cal.create_booking(
            event_type_id=1,
            start_time="2026-04-23T09:00:00Z",
            attendee={"name": "Test Prospect", "email": "prospect@sink.local", "timeZone": "UTC"},
        )

        assert result["uid"] == "mock-booking-uid"
        assert result["_mock"] is True
        assert result["status"] == "ACCEPTED"

    def test_create_booking_calls_api_in_production_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "true")

        booking_response = {
            "uid": "real-uid-abc",
            "status": "ACCEPTED",
            "start": "2026-04-23T09:00:00Z",
        }

        with respx.mock(base_url="https://api.cal.com/v2") as mock:
            mock.post("/bookings").mock(
                return_value=httpx.Response(201, json=booking_response)
            )
            result = cal.create_booking(
                event_type_id=1,
                start_time="2026-04-23T09:00:00Z",
                attendee={"name": "Real Person", "email": "real@company.com", "timeZone": "UTC"},
            )

        assert result["uid"] == "real-uid-abc"
        assert "_mock" not in result

    def test_cancel_booking_returns_mock_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")

        result = cal.cancel_booking("some-uid", reason="Test")
        assert result["uid"] == "some-uid"
        assert result["status"] == "CANCELLED"
        assert result["_mock"] is True

    def test_get_slots_raises_on_api_error(self):
        with respx.mock(base_url="https://api.cal.com/v2") as mock:
            mock.get("/slots/available").mock(
                return_value=httpx.Response(401, json={"message": "Unauthorized"})
            )
            with pytest.raises(httpx.HTTPStatusError):
                cal.get_available_slots(1, "2026-04-23T00:00:00Z", "2026-04-24T00:00:00Z")


@pytest.mark.integration
class TestCalLive:
    def test_get_available_slots(self):
        assert os.getenv("CAL_API_KEY"), "CAL_API_KEY must be set in .env"
        event_type_id = int(os.getenv("CAL_EVENT_TYPE_ID", "0"))
        assert event_type_id, "CAL_EVENT_TYPE_ID must be set in .env for live tests"

        slots = cal.get_available_slots(
            event_type_id=event_type_id,
            start_time="2026-04-23T00:00:00Z",
            end_time="2026-04-30T00:00:00Z",
        )
        assert isinstance(slots, list)
