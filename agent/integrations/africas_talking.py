import os
import africastalking
from dotenv import load_dotenv
from observability.tracing import observe

load_dotenv()

africastalking.initialize(
    username=os.environ["AT_USERNAME"],
    api_key=os.environ["AT_API_KEY"],
)

# After initialize(), africastalking.SMS is an SMSService instance.
_sms = africastalking.SMS


@observe(name="africas_talking.send_sms")
def send_sms(to: str, message: str) -> dict:
    production_mode = os.getenv("PRODUCTION_MODE", "false").lower() == "true"
    sink = os.getenv("SINK_PHONE", "+12345678900")
    recipient = to if production_mode else sink

    response = _sms.send(message, [recipient], sender_id=os.getenv("AT_SHORTCODE"))
    return {"recipients": response["SMSMessageData"]["Recipients"], "routed_to": recipient}
