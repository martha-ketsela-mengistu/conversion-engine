"""Tests for the inbound SMS webhook handler.

Africa's Talking POSTs form-encoded data. All external calls are mocked.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

_BOOK_FORM = {"from": "+254700000001", "text": "I want to book a call", "to": "88564", "date": "2026-04-23T10:00:00"}
_MOCK_BOOKING = {"uid": "cal-uid-abc", "status": "ACCEPTED", "start": "2026-04-25T10:00:00Z"}
_MOCK_SLOTS = [{"time": "2026-04-25T10:00:00Z"}, {"time": "2026-04-25T14:00:00Z"}]


# ---------------------------------------------------------------------------
# Helper: silence trace file writes during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_trace_write(tmp_path):
    import agent.observability.tracing as t
    original = t._TRACE_FILE
    t._TRACE_FILE = tmp_path / "trace_log.jsonl"
    yield
    t._TRACE_FILE = original


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

class TestSmsIntentClassification:
    @pytest.mark.parametrize("text,expected", [
        ("stop", "opt_out"),
        ("unsubscribe", "opt_out"),
        ("STOP please", "opt_out"),
        ("optout", "opt_out"),
        ("cancel", "opt_out"),
    ])
    def test_opt_out_keywords(self, text, expected):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": text, "to": "88564", "date": ""})
        assert r.status_code == 200
        assert r.json()["intent"] == expected

    @pytest.mark.parametrize("text,expected", [
        ("book a call", "book_call"),
        ("schedule a meeting", "book_call"),
        ("yes I'm interested", "book_call"),
        ("interested in learning more", "book_call"),
        ("Let's have a call", "book_call"),
        ("meeting this week?", "book_call"),
    ])
    def test_book_call_keywords(self, text, expected):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=[]), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": text, "to": "88564", "date": ""})
        assert r.status_code == 200
        assert r.json()["intent"] == expected

    @pytest.mark.parametrize("text,expected", [
        ("tell me more", "wants_info"),
        ("info please", "wants_info"),
        ("more details", "wants_info"),
    ])
    def test_info_keywords(self, text, expected):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": text, "to": "88564", "date": ""})
        assert r.status_code == 200
        assert r.json()["intent"] == expected

    def test_unknown_intent_for_random_text(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": "hello there", "to": "88564", "date": ""})
        assert r.status_code == 200
        assert r.json()["intent"] == "unknown"


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestSmsResponseStructure:
    def test_response_always_has_required_keys(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": "hello", "to": "88564", "date": "2026-04-23"})
        data = r.json()
        for key in ("status", "from", "to", "date", "intent", "text", "booking_uid", "booked_time"):
            assert key in data, f"Missing key: {key}"

    def test_response_echoes_form_fields(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+254700000001", "text": "hello", "to": "88564", "date": "2026-04-23"})
        data = r.json()
        assert data["from"] == "+254700000001"
        assert data["to"] == "88564"
        assert data["text"] == "hello"

    def test_no_booking_uid_for_non_book_intent(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None):
            r = client.post("/webhook/sms", data={"from": "+1234", "text": "stop", "to": "88564", "date": ""})
        assert r.json()["booking_uid"] is None
        assert r.json()["booked_time"] is None


# ---------------------------------------------------------------------------
# Book-call flow — happy path
# ---------------------------------------------------------------------------

class TestSmsBookCallFlow:
    def test_get_available_slots_called_for_book_intent(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS) as mock_slots, \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            client.post("/webhook/sms", data=_BOOK_FORM)

        mock_slots.assert_called_once()
        kwargs = mock_slots.call_args[1] if mock_slots.call_args[1] else {}
        args = mock_slots.call_args[0] if mock_slots.call_args[0] else ()
        # event_type_id should be passed
        assert "event_type_id" in kwargs or len(args) >= 1

    def test_create_booking_called_with_first_available_slot(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING) as mock_book, \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            client.post("/webhook/sms", data=_BOOK_FORM)

        mock_book.assert_called_once()
        call_kw = mock_book.call_args[1]
        assert call_kw["start_time"] == "2026-04-25T10:00:00Z"

    def test_booking_uid_returned_in_response(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            r = client.post("/webhook/sms", data=_BOOK_FORM)

        assert r.json()["booking_uid"] == "cal-uid-abc"
        assert r.json()["booked_time"] == "2026-04-25T10:00:00Z"

    def test_confirmation_sms_sent_to_sender(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}) as mock_sms:
            client.post("/webhook/sms", data=_BOOK_FORM)

        mock_sms.assert_called_once()
        assert mock_sms.call_args[1]["to"] == "+254700000001"
        assert "cal-uid-abc" in mock_sms.call_args[1]["message"]

    def test_fallback_time_used_when_no_slots_available(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=[]), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING) as mock_book, \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            r = client.post("/webhook/sms", data=_BOOK_FORM)

        # Fallback: tomorrow at 10:00 UTC
        call_start = mock_book.call_args[1]["start_time"]
        assert "T10:00:00" in call_start
        assert r.json()["booked_time"] is not None


# ---------------------------------------------------------------------------
# Book-call flow — with HubSpot contact
# ---------------------------------------------------------------------------

class TestSmsBookCallWithContact:
    _CONTACT = {"id": "c-500", "properties": {"email": "alex@startup.com", "firstname": "Alex"}}

    def test_attendee_email_from_contact(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=self._CONTACT), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING) as mock_book, \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}), \
             patch("agent.webhooks.sms_webhook.log_booking_created", return_value="{}"):
            client.post("/webhook/sms", data=_BOOK_FORM)

        attendee = mock_book.call_args[1]["attendee"]
        assert attendee["email"] == "alex@startup.com"
        assert attendee["name"] == "Alex"

    def test_hubspot_engagement_logged_when_contact_found(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=self._CONTACT), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}), \
             patch("agent.webhooks.sms_webhook.log_booking_created", return_value="{}") as mock_log:
            client.post("/webhook/sms", data=_BOOK_FORM)

        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == "alex@startup.com"   # attendee_email via MCP
        assert mock_log.call_args[0][1] == "2026-04-25T10:00:00Z"  # booked_time

    def test_hubspot_not_logged_when_no_contact(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}), \
             patch("agent.webhooks.sms_webhook.log_booking_created") as mock_log:
            client.post("/webhook/sms", data=_BOOK_FORM)

        mock_log.assert_not_called()

    def test_fallback_email_used_when_no_contact(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING) as mock_book, \
             patch("agent.webhooks.sms_webhook.send_sms", return_value={}):
            r = client.post("/webhook/sms", data={"from": "+254700000099", "text": "book", "to": "88564", "date": ""})

        attendee = mock_book.call_args[1]["attendee"]
        assert "unknown.prospect" in attendee["email"]
        assert "254700000099" in attendee["email"]


# ---------------------------------------------------------------------------
# Resilience: SMS confirmation failure should not abort the booking
# ---------------------------------------------------------------------------

class TestSmsBookCallResilience:
    def test_booking_uid_returned_even_when_sms_confirmation_fails(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", side_effect=Exception("AT sandbox down")):
            r = client.post("/webhook/sms", data=_BOOK_FORM)

        assert r.status_code == 200
        assert r.json()["booking_uid"] == "cal-uid-abc"

    def test_response_still_ok_when_sms_confirmation_fails(self):
        with patch("agent.webhooks.sms_webhook.search_contact_by_phone", return_value=None), \
             patch("agent.webhooks.sms_webhook.get_available_slots", return_value=_MOCK_SLOTS), \
             patch("agent.webhooks.sms_webhook.create_booking", return_value=_MOCK_BOOKING), \
             patch("agent.webhooks.sms_webhook.send_sms", side_effect=RuntimeError("network error")):
            r = client.post("/webhook/sms", data=_BOOK_FORM)

        assert r.status_code == 200
        assert r.json()["status"] == "received"
