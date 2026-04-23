"""Integration tests for the Resend email client.

Mocked tests use unittest.mock and never touch the network.
Live tests (--m integration) require a valid RESEND_API_KEY in .env and
PRODUCTION_MODE=false so all emails route to SINK_EMAIL.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

import integrations.resend_client as rc


def _mock_send(response_id: str = "mock-id"):
    mock = MagicMock()
    mock.__getitem__ = lambda self, key: response_id if key == "id" else None
    return mock


class TestResendClientMocked:
    def test_routes_to_sink_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_EMAIL", "sink@test.local")

        with patch("resend.Emails.send", return_value=_mock_send()) as mock_send:
            rc.send_email("real@company.com", "Subject", "<p>Hi</p>")

        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["sink@test.local"]

    def test_routes_to_real_recipient_in_production_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "true")

        with patch("resend.Emails.send", return_value=_mock_send("prod-id")) as mock_send:
            rc.send_email("real@company.com", "Subject", "<p>Hi</p>")

        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["real@company.com"]

    def test_send_returns_id_and_routed_to(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_EMAIL", "sink@test.local")

        with patch("resend.Emails.send", return_value={"id": "abc-123"}):
            result = rc.send_email("x@y.com", "Hi", "<p>Hi</p>")

        assert result["id"] == "abc-123"
        assert result["routed_to"] == "sink@test.local"

    def test_does_not_send_to_real_address_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_EMAIL", "sink@test.local")

        with patch("resend.Emails.send", return_value={"id": "x"}) as mock_send:
            rc.send_email("ceo@bigcorp.com", "Hi", "<p>Hi</p>")

        recipients = mock_send.call_args[0][0]["to"]
        assert "ceo@bigcorp.com" not in recipients


@pytest.mark.integration
class TestResendLive:
    def test_send_to_sink_succeeds(self):
        assert os.getenv("PRODUCTION_MODE", "false").lower() != "true", \
            "PRODUCTION_MODE must be false for integration tests"
        assert os.getenv("RESEND_API_KEY"), "RESEND_API_KEY must be set in .env"
        assert os.getenv("SINK_EMAIL"), "SINK_EMAIL must be set in .env"

        result = rc.send_email(
            to="irrelevant@ignored.com",
            subject="[TEST] Conversion Engine integration test",
            html="<p>Integration test — safe to ignore.</p>",
        )
        assert result.get("id"), f"Expected non-empty id, got: {result}"
        assert result["routed_to"] == os.getenv("SINK_EMAIL")
