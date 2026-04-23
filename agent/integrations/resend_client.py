import os
import resend
from dotenv import load_dotenv
from agent.observability.tracing import observe

load_dotenv()

resend.api_key = os.environ["RESEND_API_KEY"]
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "outreach@tenacious.dev")


@observe(name="resend.send_email")
def send_email(to: str, subject: str, html: str) -> dict:
    production_mode = os.getenv("PRODUCTION_MODE", "false").lower() == "true"
    sink = os.getenv("SINK_EMAIL", "sink@localhost")
    recipient = to if production_mode else sink

    params: resend.Emails.SendParams = {
        "from": FROM_EMAIL,
        "to": [recipient],
        "subject": subject,
        "html": html,
    }
    response = resend.Emails.send(params)
    return {"id": response["id"], "routed_to": recipient}
