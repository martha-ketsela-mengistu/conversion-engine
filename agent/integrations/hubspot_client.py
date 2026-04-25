import os
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate
from hubspot.crm.contacts.exceptions import ApiException
from dotenv import load_dotenv
from agent.observability.tracing import observe
from datetime import datetime, timezone

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
            properties=["email", "firstname", "lastname", "company", "phone"],
        )
        return {"id": result.id, "properties": result.properties}
    except ApiException as e:
        if e.status == 404:
            return None
        raise

@observe(name="hubspot.log_engagement")
def log_engagement(contact_id: str, event_type: str, body: str, subject: str = "") -> dict:
    """Log an event as a note on the contact timeline."""
    if event_type == "email":
        content = f"Email: {subject}\n\n{body}"
    elif event_type == "sms":
        content = f"SMS: {body}"
    else:
        content = f"{event_type.capitalize()}: {body}"
        
    properties = {
        "hs_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hs_note_body": content
    }
    
    try:
        from hubspot.crm.objects.notes import SimplePublicObjectInputForCreate
        note_input = SimplePublicObjectInputForCreate(properties=properties)
        result = _client.crm.objects.notes.basic_api.create(simple_public_object_input_for_create=note_input)
        
        # Associate note with contact
        _client.crm.associations.v4.basic_api.create(
            object_type="notes",
            object_id=result.id,
            to_object_type="contacts",
            to_object_id=contact_id,
            association_spec=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
        )
        return {"id": result.id, "type": "note"}
    except Exception as e:
        print(f"[HubSpot] Failed to log engagement: {e}")
        return {"error": str(e)}


@observe(name="hubspot.create_deal")
def create_deal(contact_id: str, deal_name: str, stage: str = "appointmentscheduled", amount: float | None = None) -> dict:
    """Create a deal in HubSpot and associate it with a contact."""
    from hubspot.crm.deals import SimplePublicObjectInputForCreate as DealInput
    properties: dict = {"dealname": deal_name, "dealstage": stage, "pipeline": "default"}
    if amount is not None:
        properties["amount"] = str(amount)
    try:
        body = DealInput(properties=properties, associations=[])
        result = _client.crm.deals.basic_api.create(simple_public_object_input_for_create=body)
        _client.crm.associations.v4.basic_api.create(
            object_type="deals",
            object_id=result.id,
            to_object_type="contacts",
            to_object_id=contact_id,
            association_spec=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 3}],
        )
        return {"id": result.id, "deal_name": deal_name, "stage": stage}
    except Exception as e:
        print(f"[HubSpot] Failed to create deal: {e}")
        return {"error": str(e)}


@observe(name="hubspot.search_contact_by_phone")
def search_contact_by_phone(phone: str) -> dict | None:
    try:
        from hubspot.crm.contacts import PublicObjectSearchRequest
        req = PublicObjectSearchRequest(
            filter_groups=[{
                "filters": [{"propertyName": "phone", "operator": "EQ", "value": phone}]
            }],
            properties=["email", "firstname", "lastname", "phone"],
        )
        result = _client.crm.contacts.search_api.do_search(public_object_search_request=req)
        if result.results:
            r = result.results[0]
            return {"id": r.id, "properties": r.properties}
        return None
    except Exception as e:
        print(f"[HubSpot] search_contact_by_phone failed: {e}")
        return None
