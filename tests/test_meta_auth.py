import os
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("META_ADMIN_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.meta_client import MetaGraphAPIError, MetaRateLimitedError
from app.routers import meta_auth


def _connected_db():
    conn = Mock(user_access_token="old-token", user_token_expires_at=None)
    db = Mock()
    db.query.return_value.first.return_value = conn
    return db


def _fake_get_db():
    yield _connected_db()


@pytest.fixture(autouse=True)
def override_get_db(monkeypatch):
    monkeypatch.setattr(config, "META_ADMIN_SECRET", "test-secret")
    app.dependency_overrides[meta_auth.get_db] = _fake_get_db
    yield
    app.dependency_overrides.pop(meta_auth.get_db, None)


client = TestClient(app)


def test_refresh_returns_429_when_rate_limited():
    with patch(
        "app.routers.meta_auth.exchange_long_lived_token",
        side_effect=MetaRateLimitedError("rate limited"),
    ):
        response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 429


def test_refresh_returns_502_on_graph_api_error():
    with patch(
        "app.routers.meta_auth.exchange_long_lived_token",
        side_effect=MetaGraphAPIError("bad token", status_code=401, meta_error_code=190),
    ):
        response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 502
