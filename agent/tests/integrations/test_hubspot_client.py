"""Integration tests for the HubSpot CRM client.

Mocked tests patch BasicApi at the class level — the SDK's basic_api property
returns a new instance each call, so instance-level patches don't intercept it.
Live tests (--m integration) create a real contact in the HubSpot Developer Sandbox.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

import agent.integrations.hubspot_client as hs
from hubspot.crm.contacts import BasicApi


def _mock_contact(id_: str = "12345", email: str = "test@example.com") -> MagicMock:
    c = MagicMock()
    c.id = id_
    c.properties = {"email": email, "firstname": "Test", "company": "Acme"}
    return c


class TestHubSpotClientMocked:
    def test_create_contact_returns_id(self):
        mock_result = _mock_contact("hs-001", "prospect@acme.com")

        with patch.object(BasicApi, "create", return_value=mock_result):
            result = hs.create_contact(
                email="prospect@acme.com",
                properties={"firstname": "Ada", "company": "Acme"},
            )

        assert result["id"] == "hs-001"
        assert result["email"] == "prospect@acme.com"

    def test_create_contact_handles_409_conflict(self):
        from hubspot.crm.contacts.exceptions import ApiException
        conflict = ApiException(status=409)

        with patch.object(BasicApi, "create", side_effect=conflict):
            result = hs.create_contact("existing@acme.com", {})

        assert result["conflict"] is True
        assert result["id"] is None

    def test_get_contact_returns_none_for_404(self):
        from hubspot.crm.contacts.exceptions import ApiException
        not_found = ApiException(status=404)

        with patch.object(BasicApi, "get_by_id", side_effect=not_found):
            result = hs.get_contact_by_email("nobody@nowhere.com")

        assert result is None

    def test_get_contact_returns_properties(self):
        mock_result = _mock_contact("hs-002", "found@acme.com")

        with patch.object(BasicApi, "get_by_id", return_value=mock_result):
            result = hs.get_contact_by_email("found@acme.com")

        assert result["id"] == "hs-002"
        assert result["properties"]["email"] == "found@acme.com"


@pytest.mark.integration
class TestHubSpotLive:
    def test_create_and_retrieve_contact(self):
        assert os.getenv("HUBSPOT_ACCESS_TOKEN"), "HUBSPOT_ACCESS_TOKEN must be set in .env"

        test_email = "integration-test@conversion-engine.dev"
        created = hs.create_contact(
            email=test_email,
            properties={"firstname": "Integration", "lastname": "Test", "company": "CE-Test"},
        )
        assert created.get("id") or created.get("conflict"), \
            f"Unexpected response: {created}"

        retrieved = hs.get_contact_by_email(test_email)
        assert retrieved is not None, "Should find the contact we just created"
        assert retrieved["properties"]["email"] == test_email
