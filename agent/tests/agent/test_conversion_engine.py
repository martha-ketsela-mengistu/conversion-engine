"""Tests for ConversionEngine — the main outreach orchestrator.

All external I/O (HubSpot, Resend, Africa's Talking, LLM) is mocked so tests
run fully offline.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_brief(company="TestCo", segment="segment_1", ai_score=2, has_gap=False):
    from agent.enrichment.pipeline import HiringSignalBrief
    return HiringSignalBrief(
        company_name=company,
        domain="testco.com",
        generated_at="2026-04-23T10:00:00Z",
        firmographics={"employee_count": 80, "categories": ["SaaS"], "industries": ["B2B"]},
        funding_events_180d=[{"type": "series_a", "amount_usd": 12_000_000}],
        layoff_events_120d=None,
        job_post_velocity={
            "open_engineering_roles": 4,
            "total_open_roles": 10,
            "velocity_60d": 2.1,
            "hiring_signal_strength": "strong",
            "confidence": 0.85,
        },
        leadership_changes_90d=[],
        ai_maturity={"score": ai_score, "confidence": 0.8, "evidence": ["ML Engineer role open"]},
        icp_segment=segment,
        segment_confidence=0.85,
        competitor_gap={"sector": "SaaS", "practices": ["AI ops"]} if has_gap else None,
        signal_summary="TestCo raised a Series A and is actively hiring ML engineers.",
    )


@pytest.fixture
def engine():
    """ConversionEngine with __init__ bypassed and all I/O attributes mocked."""
    from agent.conversion_engine import ConversionEngine
    e = ConversionEngine.__new__(ConversionEngine)
    e._llm_url = "https://api.openrouter.test/v1"
    e._llm_key = "test-api-key"
    e._email_model = "test-model"
    e.enrichment = MagicMock()
    e.enrichment.run.return_value = _make_brief()
    return e


@pytest.fixture(autouse=True)
def _no_trace_write(tmp_path):
    import agent.observability.tracing as t
    original = t._TRACE_FILE
    t._TRACE_FILE = tmp_path / "trace_log.jsonl"
    yield
    t._TRACE_FILE = original


def _crm_ok(id_="c-1"):
    """Return JSON string matching create_enriched_contact return type."""
    return json.dumps({"id": id_, "conflict": False})


# ---------------------------------------------------------------------------
# process_new_lead — return structure
# ---------------------------------------------------------------------------

class TestProcessNewLeadReturnValue:
    def test_returns_required_keys(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-1", "routed_to": "sink@test"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-1")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                result = engine.process_new_lead("TestCo", "testco.com", "alex@testco.com", "Alex Morgan")

        for key in ("company", "segment", "email", "crm", "brief_path"):
            assert key in result, f"Missing key: {key}"

    def test_company_name_in_result(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-2", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-2")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                result = engine.process_new_lead("Acme Corp", "acme.com", "ceo@acme.com")

        assert result["company"] == "Acme Corp"

    def test_segment_from_brief_in_result(self, engine):
        engine.enrichment.run.return_value = _make_brief(segment="segment_2")
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-3", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-3")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                result = engine.process_new_lead("TestCo", "testco.com", "cto@testco.com")

        assert result["segment"] == "segment_2"

    def test_gap_brief_path_none_when_no_competitor_gap(self, engine):
        engine.enrichment.run.return_value = _make_brief(has_gap=False)
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-4", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-4")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                result = engine.process_new_lead("TestCo", "testco.com", "x@testco.com")

        assert result["gap_brief_path"] is None


# ---------------------------------------------------------------------------
# process_new_lead — external calls
# ---------------------------------------------------------------------------

class TestProcessNewLeadExternalCalls:
    def test_send_email_called_with_prospect_email(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-5", "routed_to": "sink"}) as mock_send, \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-5")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                engine.process_new_lead("TestCo", "testco.com", "vp@testco.com", "VP Eng")

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["to"] == "vp@testco.com"

    def test_create_contact_called_with_correct_email(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-6", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-6")) as mock_crm, \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                engine.process_new_lead("TestCo", "testco.com", "cto@testco.com", "Sam Lee")

        mock_crm.assert_called_once()
        assert mock_crm.call_args[1]["email"] == "cto@testco.com"

    def test_create_contact_properties_include_company(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-7", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-7")) as mock_crm, \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                engine.process_new_lead("Acme Corp", "acme.com", "x@acme.com")

        assert mock_crm.call_args[1]["company"] == "Acme Corp"

    def test_jobtitle_encodes_segment_and_ai_score(self, engine):
        engine.enrichment.run.return_value = _make_brief(segment="segment_1", ai_score=2)
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-8", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-8")) as mock_crm, \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                engine.process_new_lead("TestCo", "testco.com", "x@testco.com")

        assert mock_crm.call_args[1]["icp_segment"] == "segment_1"
        assert mock_crm.call_args[1]["ai_maturity_score"] == 2

    def test_enrichment_run_called_with_company_and_domain(self, engine):
        with patch("agent.conversion_engine.send_email", return_value={"id": "e-9", "routed_to": "sink"}), \
             patch("agent.conversion_engine.create_enriched_contact", return_value=_crm_ok("c-9")), \
             patch("agent.conversion_engine.log_email_sent", return_value=None):
            with patch.object(engine, "_generate_email", return_value="<p>Hi</p>"):
                engine.process_new_lead("Stripe", "stripe.com", "x@stripe.com")

        engine.enrichment.run.assert_called_once_with("Stripe", "stripe.com")


# ---------------------------------------------------------------------------
# _generate_email
# ---------------------------------------------------------------------------

class TestGenerateEmail:
    def test_returns_llm_output_on_success(self, engine):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "<p>LLM-written email</p>"}}]
        }
        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response

        with patch("agent.conversion_engine.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value = mock_client_instance
            result = engine._generate_email(_make_brief(), "Alex")

        assert result == "<p>LLM-written email</p>"

    def test_falls_back_to_static_template_on_http_error(self, engine):
        with patch("agent.conversion_engine.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = Exception("timeout")
            result = engine._generate_email(_make_brief(), "Alex")

        assert "<p>" in result or "<html>" in result.lower() or "Tenacious" in result

    def test_falls_back_when_llm_returns_unexpected_shape(self, engine):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"unexpected": "shape"}

        with patch("agent.conversion_engine.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_response
            result = engine._generate_email(_make_brief(), "Alex")

        assert result  # fallback should still return something

    def test_signal_summary_prepended_to_prompt(self, engine):
        """Verify the LLM receives the signal summary in the prompt."""
        brief = _make_brief()
        brief.signal_summary = "UNIQUE_SIGNAL_MARKER_XYZ"

        captured_payload = {}

        def fake_post(url, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            raise Exception("abort after capture")

        with patch("agent.conversion_engine.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = fake_post
            engine._generate_email(brief, "Alex")

        messages_str = str(captured_payload.get("messages", ""))
        assert "UNIQUE_SIGNAL_MARKER_XYZ" in messages_str


# ---------------------------------------------------------------------------
# send_sms_followup
# ---------------------------------------------------------------------------

class TestSendSmsFollowup:
    def test_send_sms_called_with_correct_phone(self, engine):
        with patch("agent.conversion_engine.send_sms", return_value={"routed_to": "+1234"}) as mock_sms:
            engine.send_sms_followup("+15551234567", "TestCo", warm_lead=True)

        mock_sms.assert_called_once()
        assert mock_sms.call_args[1]["to"] == "+15551234567"

    def test_message_includes_company_name(self, engine):
        with patch("agent.conversion_engine.send_sms", return_value={"routed_to": "+1234"}) as mock_sms:
            engine.send_sms_followup("+15551234567", "Stripe", warm_lead=True)

        message = mock_sms.call_args[1]["message"]
        assert "Stripe" in message

    def test_message_includes_cal_link(self, engine):
        with patch("agent.conversion_engine.send_sms", return_value={"routed_to": "+1234"}) as mock_sms:
            engine.send_sms_followup("+15551234567", "TestCo", warm_lead=True)

        message = mock_sms.call_args[1]["message"]
        assert "cal.com" in message

    def test_custom_booking_url_used_when_provided(self, engine):
        with patch("agent.conversion_engine.send_sms", return_value={"routed_to": "+1234"}) as mock_sms:
            engine.send_sms_followup("+15551234567", "TestCo", warm_lead=True, booking_url="https://custom.cal/link")

        message = mock_sms.call_args[1]["message"]
        assert "https://custom.cal/link" in message

    def test_cold_sms_raises_value_error(self, engine):
        with pytest.raises(ValueError, match="warm_lead"):
            engine.send_sms_followup("+15551234567", "TestCo", warm_lead=False)


# ---------------------------------------------------------------------------
# Competitor gap brief persistence
# ---------------------------------------------------------------------------

class TestCompetitorGapBrief:
    def test_gap_brief_written_to_disk(self, engine, tmp_path):
        brief = _make_brief(has_gap=True)
        gap_path = engine._save_competitor_gap_brief(brief)
        assert gap_path is not None

    def test_no_gap_brief_when_competitor_gap_is_none(self, engine):
        brief = _make_brief(has_gap=False)
        result = engine._save_competitor_gap_brief(brief)
        assert result is None
