import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .. import config

router = APIRouter(tags=["Meta Webhook"])

logger = logging.getLogger(__name__)


def _valid_verify_token(token: str | None) -> bool:
    expected = config.META_VERIFY_TOKEN
    if not token or not expected:
        return False
    return hmac.compare_digest(token, expected)


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = config.META_APP_SECRET
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False

    received = signature_header.removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, received)
    except (TypeError, ValueError):
        return False


@router.get("/webhooks/meta")
def verify_meta_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and _valid_verify_token(token) and challenge is not None:
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("Meta webhook verification failed")
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhooks/meta")
async def receive_meta_webhook(request: Request):
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256")

    if not verify_meta_signature(raw_body, signature_header):
        logger.warning("Meta webhook rejected: invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    object_type = payload.get("object")
    entries = payload.get("entry") or []
    entry_count = len(entries) if isinstance(entries, list) else 0
    logger.info("Meta webhook received: object=%s entries=%s", object_type, entry_count)
    return {"status": "ok"}
