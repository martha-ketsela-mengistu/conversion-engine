import os
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate
from hubspot.crm.contacts.exceptions import ApiException
from dotenv import load_dotenv
from observability.tracing import observe

load_dotenv()

_client = HubSpot(access_token=os.environ["HUBSPOT_ACCESS_TOKEN"])


@observe(name="hubspot.create_contact")
def create_contact(email: str, properties: dict) -> dict:
    props = {"email": email, **properties}
    body = SimplePublicObjectInputForCreate(properties=props, associations=[])
    try:
        result = _client.crm.contacts.basic_api.create(
            simple_public_object_input_for_create=body
        )
        return {"id": result.id, "email": email}
    except ApiException as e:
        if e.status == 409:
            # Contact already exists — return the existing id from the error body
            return {"id": None, "email": email, "conflict": True}
        raise


@observe(name="hubspot.get_contact")
def get_contact_by_email(email: str) -> dict | None:
    try:
        result = _client.crm.contacts.basic_api.get_by_id(
            contact_id=email,
            id_property="email",
            properties=["email", "firstname", "lastname", "company"],
        )
        return {"id": result.id, "properties": result.properties}
    except ApiException as e:
        if e.status == 404:
            return None
        raise
