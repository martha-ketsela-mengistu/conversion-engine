"""Tests for the email reply webhook handler.

All external calls (HubSpot, Resend, Africa's Talking, Cal.com, LLM) are mocked so
tests run offline and never touch real APIs.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

_REPLY_PAYLOAD = {
    "type": "email.received",
    "data": {
        "from": "alex@startup.com",
        "text": "Thanks for reaching out, I'd love to learn more.",
        "subject": "Re: Discovery call",
    },
}


# ---------------------------------------------------------------------------
# Helper: silence record_span file writes during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_trace_write(tmp_path):
    """Redirect trace file writes to a temp path to keep tests clean."""
    import agent.observability.tracing as t
    original = t._TRACE_FILE
    t._TRACE_FILE = tmp_path / "trace_log.jsonl"
    yield
    t._TRACE_FILE = original


# ---------------------------------------------------------------------------
# Ignored / skipped events
# ---------------------------------------------------------------------------

class TestEmailWebhookIgnored:
    def test_non_reply_event_type_is_ignored(self):
        r = client.post("/webhook/email/reply", json={"type": "email.bounced", "data": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"
        assert r.json()["type"] == "email.bounced"

    def test_click_event_is_ignored(self):
        r = client.post("/webhook/email/reply", json={"type": "email.click", "data": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_missing_sender_returns_skipped(self):
        r = client.post("/webhook/email/reply", json={
            "type": "email.received",
            "data": {"from": "", "text": "Hello", "subject": "Test"},
        })
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"

    def test_invalid_json_returns_400(self):
        r = client.post(
            "/webhook/email/reply",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Auto-reply flow (no SMS keywords, no time proposed)
# ---------------------------------------------------------------------------

class TestEmailWebhookAutoReply:
    def test_auto_reply_sent_when_no_special_keywords(self):
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-1"}) as mock_send:
            r = client.post("/webhook/email/reply", json=_REPLY_PAYLOAD)

        assert r.status_code == 200
        assert r.json()["status"] == "processed"
        mock_send.assert_called_once()
        _args, _kw = mock_send.call_args
        call_html = _kw.get("html") or (_args[2] if len(_args) > 2 else "")
        assert "cal.com" in call_html.lower()

    def test_auto_reply_uses_re_subject_prefix(self):
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-2"}) as mock_send:
            r = client.post("/webhook/email/reply", json=_REPLY_PAYLOAD)

        assert r.status_code == 200
        _args, _kw = mock_send.call_args
        call_subject = _kw.get("subject") or (_args[1] if len(_args) > 1 else "")
        assert call_subject.startswith("Re:")

    def test_no_email_sent_when_body_is_empty(self):
        """Empty body and no SMS intent should not trigger any outbound action."""
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email") as mock_send:
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "x@y.com", "text": "", "subject": ""},
            })

        assert r.status_code == 200
        mock_send.assert_not_called()

    def test_legacy_inbound_event_type_is_processed(self):
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-3"}):
            r = client.post("/webhook/email/reply", json={
                "type": "inbound",
                "data": {"from": "x@y.com", "text": "Hi there", "subject": ""},
            })

        assert r.status_code == 200
        assert r.json()["status"] == "processed"


# ---------------------------------------------------------------------------
# HubSpot engagement logging
# ---------------------------------------------------------------------------

class TestEmailWebhookHubSpotLogging:
    def test_log_engagement_called_when_contact_exists(self):
        mock_contact = {"id": "c-100", "properties": {"firstname": "Alex", "phone": ""}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}") as mock_log, \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-4"}):
            r = client.post("/webhook/email/reply", json=_REPLY_PAYLOAD)

        assert r.status_code == 200
        mock_log.assert_called_once()
        args = mock_log.call_args[0]
        assert args[0] == "alex@startup.com"  # from_email passed to MCP tool

    def test_log_engagement_not_called_when_contact_missing(self):
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook.log_email_sent") as mock_log, \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-5"}):
            r = client.post("/webhook/email/reply", json=_REPLY_PAYLOAD)

        assert r.status_code == 200
        mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# SMS handoff
# ---------------------------------------------------------------------------

class TestEmailWebhookSmsHandoff:
    def test_sms_sent_when_text_me_keyword_and_phone_known(self):
        mock_contact = {"id": "c-200", "properties": {"firstname": "Sam", "phone": "+15550001111"}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook.log_sms_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_sms", return_value={"recipients": []}) as mock_sms, \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-6"}):
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "sam@corp.com", "text": "Can you text me instead?", "subject": "Re: Call"},
            })

        assert r.status_code == 200
        assert r.json()["sms_triggered"] is True
        mock_sms.assert_called_once()

    def test_sms_not_sent_when_no_phone_on_contact(self):
        mock_contact = {"id": "c-201", "properties": {"firstname": "Sam", "phone": ""}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_sms") as mock_sms, \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-7"}):
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "sam@corp.com", "text": "Can you text me instead?", "subject": ""},
            })

        assert r.status_code == 200
        assert r.json()["sms_triggered"] is False
        mock_sms.assert_not_called()

    def test_no_auto_reply_email_when_sms_was_sent(self):
        """When SMS handoff is triggered, no fallback booking-link email should go out."""
        mock_contact = {"id": "c-202", "properties": {"firstname": "Sam", "phone": "+15550001111"}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook.log_sms_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_sms", return_value={"recipients": []}), \
             patch("agent.webhooks.email_webhook.send_email") as mock_email:
            client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "sam@corp.com", "text": "text me please", "subject": ""},
            })

        mock_email.assert_not_called()

    @pytest.mark.parametrize("keyword", ["sms", "whatsapp", "call me", "phone"])
    def test_various_sms_keywords_trigger_handoff(self, keyword):
        mock_contact = {"id": "c-203", "properties": {"firstname": "Jo", "phone": "+15550002222"}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook.log_sms_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_sms", return_value={"recipients": []}) as mock_sms, \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-x"}):
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "jo@corp.com", "text": f"Please {keyword}", "subject": ""},
            })

        assert r.json()["sms_triggered"] is True
        mock_sms.assert_called_once()


# ---------------------------------------------------------------------------
# Programmatic booking
# ---------------------------------------------------------------------------

class TestEmailWebhookProgrammaticBooking:
    def test_confirmation_email_sent_when_time_proposed(self):
        mock_contact = {"id": "c-300", "properties": {"firstname": "Dana", "phone": ""}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}"), \
             patch("agent.webhooks.email_webhook.log_booking_created", return_value="{}"), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value="2026-05-05T14:00:00Z"), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-8"}) as mock_send:
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "dana@corp.com", "text": "How about Monday at 2pm?", "subject": "Re: Intro"},
            })

        assert r.status_code == 200
        mock_send.assert_called_once()
        _args, _kw = mock_send.call_args
        call_html = _kw.get("html") or (_args[2] if len(_args) > 2 else "")
        assert "2026-05-05" in call_html

    def test_booking_attempt_logs_to_hubspot(self):
        mock_contact = {"id": "c-301", "properties": {"firstname": "Dana", "phone": ""}}
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=mock_contact), \
             patch("agent.webhooks.email_webhook.log_email_sent", return_value="{}") as mock_email_log, \
             patch("agent.webhooks.email_webhook.log_booking_created", return_value="{}") as mock_meeting_log, \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value="2026-05-05T14:00:00Z"), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-9"}):
            client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "dana@corp.com", "text": "Monday 2pm works", "subject": ""},
            })

        # One MCP call for the inbound email, one for the meeting booking
        mock_email_log.assert_called_once()
        mock_meeting_log.assert_called_once()

    def test_fallback_auto_reply_when_no_booking_detected(self):
        with patch("agent.webhooks.email_webhook.get_contact_by_email", return_value=None), \
             patch("agent.webhooks.email_webhook._attempt_programmatic_booking", return_value=None), \
             patch("agent.webhooks.email_webhook.send_email", return_value={"id": "e-10"}) as mock_send:
            r = client.post("/webhook/email/reply", json={
                "type": "email.received",
                "data": {"from": "x@y.com", "text": "Looks interesting", "subject": "Re: Intro"},
            })

        assert r.status_code == 200
        mock_send.assert_called_once()
        _args, _kw = mock_send.call_args
        call_html = _kw.get("html") or (_args[2] if len(_args) > 2 else "")
        assert "cal.com" in call_html.lower()
        assert "gone ahead and booked" not in call_html
