"""Integration tests for the Africa's Talking SMS client.

Mocked tests patch the SMSService instance stored as `_sms` on the module —
this avoids fighting the AT SDK's module-vs-instance distinction.
Live tests (--m integration) use the AT sandbox and route to SINK_PHONE.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

import integrations.africas_talking as at


def _at_response(phone: str) -> dict:
    return {
        "SMSMessageData": {
            "Recipients": [
                {"number": phone, "status": "Success", "cost": "0", "messageId": "mock-id"}
            ]
        }
    }


class TestAfricasTalkingMocked:
    def test_routes_to_sink_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_PHONE", "+254700000000")

        mock_sms = MagicMock()
        mock_sms.send.return_value = _at_response("+254700000000")

        with patch.object(at, "_sms", mock_sms):
            result = at.send_sms("+254799999999", "Hello prospect")

        mock_sms.send.assert_called_once()
        called_recipients = mock_sms.send.call_args[0][1]
        assert called_recipients == ["+254700000000"]
        assert result["routed_to"] == "+254700000000"

    def test_routes_to_real_number_in_production_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "true")
        real_number = "+254799999999"

        mock_sms = MagicMock()
        mock_sms.send.return_value = _at_response(real_number)

        with patch.object(at, "_sms", mock_sms):
            result = at.send_sms(real_number, "Hello")

        called_recipients = mock_sms.send.call_args[0][1]
        assert called_recipients == [real_number]
        assert result["routed_to"] == real_number

    def test_returns_recipients_list(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_PHONE", "+254700000000")

        mock_sms = MagicMock()
        mock_sms.send.return_value = _at_response("+254700000000")

        with patch.object(at, "_sms", mock_sms):
            result = at.send_sms("+000", "Test")

        assert isinstance(result["recipients"], list)
        assert result["recipients"][0]["status"] == "Success"

    def test_never_sends_to_real_number_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("PRODUCTION_MODE", "false")
        monkeypatch.setenv("SINK_PHONE", "+254700000000")

        mock_sms = MagicMock()
        mock_sms.send.return_value = _at_response("+254700000000")

        with patch.object(at, "_sms", mock_sms):
            at.send_sms("+254711111111", "Secret message")

        called_recipients = mock_sms.send.call_args[0][1]
        assert "+254711111111" not in called_recipients


@pytest.mark.integration
class TestAfricasTalkingLive:
    def test_sandbox_send_to_sink(self, monkeypatch):
        assert os.getenv("PRODUCTION_MODE", "false").lower() != "true", \
            "Must be dev mode for integration tests"
        assert os.getenv("AT_API_KEY"), "AT_API_KEY must be set in .env"
        assert os.getenv("SINK_PHONE"), "SINK_PHONE must be set in .env"

        import requests
        original_request = requests.Session.request
        monkeypatch.setattr(
            requests.Session,
            "request",
            lambda self, method, url, **kwargs: original_request(self, method, url, verify=False, **kwargs),
        )

        result = at.send_sms(
            to="+254000000000",
            message="[TEST] Conversion engine integration test — ignore.",
        )
        assert result["recipients"], "Expected at least one recipient in AT response"
        assert result["routed_to"] == os.getenv("SINK_PHONE")
