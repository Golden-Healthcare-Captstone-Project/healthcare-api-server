import hashlib
import hmac
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("META_ADMIN_SECRET", "test-secret")

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers.meta_webhook import verify_meta_signature

client = TestClient(app)

VERIFY_TOKEN = "verify-token"
APP_SECRET = "app-secret"
CHALLENGE = "challenge-123"


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_returns_challenge_when_token_matches(monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", VERIFY_TOKEN)

    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": CHALLENGE,
        },
    )

    assert response.status_code == 200
    assert response.text == CHALLENGE


def test_verify_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", VERIFY_TOKEN)

    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": CHALLENGE,
        },
    )

    assert response.status_code == 403


def test_verify_rejects_missing_config(monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", None)

    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": CHALLENGE,
        },
    )

    assert response.status_code == 403


def test_receive_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", APP_SECRET)
    body = json.dumps({"object": "page", "entry": [{"id": "1"}]}).encode("utf-8")

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_receive_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", APP_SECRET)
    body = json.dumps({"object": "page", "entry": []}).encode("utf-8")

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )

    assert response.status_code == 403


def test_receive_rejects_missing_signature(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", APP_SECRET)
    body = json.dumps({"object": "page"}).encode("utf-8")

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 403


def test_verify_meta_signature_helper_matches_hmac(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", APP_SECRET)
    body = b'{"object":"page"}'
    assert verify_meta_signature(body, _sign(body)) is True
    assert verify_meta_signature(body, _sign(body, "other")) is False
    assert verify_meta_signature(body, None) is False
