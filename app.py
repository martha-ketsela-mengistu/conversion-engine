"""FastAPI application — mounts all webhook routes and exposes a health check.

Run locally:
    uv run uvicorn app:app --reload --port 8000

Expose with ngrok for Resend / Africa's Talking webhook registration:
    ngrok http 8000
"""

from fastapi import FastAPI
from agent.webhooks.email_webhook import router as email_router
from agent.webhooks.sms_webhook import router as sms_router

app = FastAPI(
    title="Tenacious Conversion Engine",
    version="0.1.0",
    description="AI-powered outreach pipeline: enrich → personalise → send → track.",
)

app.include_router(email_router)
app.include_router(sms_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "conversion-engine"}
