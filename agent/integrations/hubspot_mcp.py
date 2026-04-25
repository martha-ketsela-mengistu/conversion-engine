"""HubSpot MCP Server exposing timeline logging tools."""

import json
from mcp.server.fastmcp import FastMCP
from agent.integrations.hubspot_client import log_engagement, create_contact, get_contact_by_email, create_deal

# Create the MCP server
mcp = FastMCP("HubSpot")


@mcp.tool()
def create_enriched_contact(
    email: str,
    firstname: str,
    lastname: str,
    company: str,
    domain: str,
    icp_segment: str,
    enrichment_timestamp: str,
    ai_maturity_score: int,
    segment_confidence: float,
    has_recent_funding: bool,
    has_recent_layoffs: bool,
    hiring_signal_strength: str,
) -> str:
    """Create a HubSpot contact record with ICP classification and enrichment metadata.

    Writes enrichment fields (segment, AI score, funding/layoff signals, timestamp) as a
    timeline note so the data is visible without custom property creation.
    """
    properties = {
        "firstname": firstname,
        "lastname": lastname,
        "company": company,
        "website": f"https://{domain}",
        "jobtitle": f"ICP:{icp_segment or 'none'} AI:{ai_maturity_score}/3",
    }
    result = create_contact(email, properties)

    contact = get_contact_by_email(email)
    if contact:
        enrichment_note = (
            f"Signal enrichment (as of {enrichment_timestamp}):\n"
            f"- ICP Segment: {icp_segment or 'none'} (confidence: {segment_confidence:.0%})\n"
            f"- AI Maturity Score: {ai_maturity_score}/3\n"
            f"- Recent Funding (180d): {'Yes' if has_recent_funding else 'No'}\n"
            f"- Recent Layoffs (120d): {'Yes' if has_recent_layoffs else 'No'}\n"
            f"- Hiring Signal Strength: {hiring_signal_strength}\n"
        )
        log_engagement(contact["id"], "note", enrichment_note, "Signal Enrichment Data")

    return json.dumps(result)


@mcp.tool()
def log_email_sent(email: str, subject: str, body: str) -> str:
    """Log an outbound email sent to a prospect in HubSpot."""
    contact = get_contact_by_email(email)
    if not contact:
        return f"Contact not found: {email}"
    
    result = log_engagement(contact["id"], "email", body, subject)
    return json.dumps(result)

@mcp.tool()
def log_sms_sent(email: str, message: str) -> str:
    """Log an SMS sent to a prospect in HubSpot."""
    contact = get_contact_by_email(email)
    if not contact:
        return f"Contact not found: {email}"
    
    result = log_engagement(contact["id"], "sms", message)
    return json.dumps(result)

@mcp.tool()
def log_booking_created(email: str, start_time: str) -> str:
    """Log a calendar booking on the contact's timeline."""
    contact = get_contact_by_email(email)
    if not contact:
        return f"Contact not found: {email}"
    
    body = f"Discovery call booked for {start_time}"
    log_engagement(contact["id"], "meeting", body)
    deal = create_deal(
        contact_id=contact["id"],
        deal_name=f"Discovery Call – {contact['properties'].get('company', email)} ({start_time[:10]})",
        stage="appointmentscheduled",
    )
    return json.dumps({"note": "logged", "deal": deal})

if __name__ == "__main__":
    mcp.run()
