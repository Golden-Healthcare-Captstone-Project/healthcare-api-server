import os
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("META_ADMIN_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.main import app
from app.database import get_db, Base
from app.meta_client import MetaGraphAPIError, MetaRateLimitedError
from app.models import MetaConnection

client = TestClient(app)


@pytest.fixture(autouse=True)
def real_test_db(monkeypatch):
    """Overrides get_db with a real, in-memory SQLite session shared across
    requests within a test, so router <-> model <-> DB behavior is actually
    exercised instead of mocked away."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(config, "META_ADMIN_SECRET", "test-secret")
    monkeypatch.setattr(config, "META_APP_ID", "test-app-id")
    monkeypatch.setattr(config, "META_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(config, "META_REDIRECT_URI", "https://example.com/auth/meta/callback")
    app.dependency_overrides[get_db] = _override_get_db
    yield TestingSessionLocal
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _get_connection(session_factory):
    db = session_factory()
    try:
        return db.query(MetaConnection).first()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# /auth/meta/login
# ---------------------------------------------------------------------------

def test_login_requires_admin_secret():
    response = client.get("/auth/meta/login", follow_redirects=False)
    assert response.status_code == 403


def test_login_rejects_wrong_secret():
    response = client.get("/auth/meta/login", params={"secret": "wrong"}, follow_redirects=False)
    assert response.status_code == 403


def test_login_redirects_to_facebook_with_state_cookie():
    response = client.get(
        "/auth/meta/login", params={"secret": "test-secret"}, follow_redirects=False
    )

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://www.facebook.com/v19.0/dialog/oauth")
    assert "client_id=test-app-id" in location
    assert "redirect_uri=https://example.com/auth/meta/callback" in location
    assert "pages_show_list" in location
    assert response.cookies.get("meta_oauth_state")


# ---------------------------------------------------------------------------
# /auth/meta/callback
# ---------------------------------------------------------------------------

def _do_callback(graph_responses, state="abc123", cookie_state="abc123"):
    client.cookies.set("meta_oauth_state", cookie_state)
    with patch("app.routers.meta_auth.graph_get", side_effect=graph_responses):
        response = client.get(
            "/auth/meta/callback", params={"code": "fake-code", "state": state}
        )
    client.cookies.clear()
    return response


def test_callback_happy_path_persists_connection(real_test_db):
    graph_responses = [
        {"access_token": "short-lived-token"},
        {"access_token": "long-lived-token", "expires_in": 5184000},
        {"data": [{"id": "page-1", "name": "My Page", "access_token": "page-token"}]},
        {"instagram_business_account": {"id": "ig-123"}},
    ]

    response = _do_callback(graph_responses)

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "page_name": "My Page",
        "ig_connected": True,
    }

    conn = _get_connection(real_test_db)
    assert conn is not None
    assert conn.user_access_token == "long-lived-token"
    assert conn.page_id == "page-1"
    assert conn.page_name == "My Page"
    assert conn.page_access_token == "page-token"
    assert conn.ig_business_account_id == "ig-123"
    assert conn.user_token_expires_at is not None
    assert conn.user_token_expires_at > datetime.utcnow() + timedelta(days=59)


def test_callback_rejects_mismatched_state(real_test_db):
    response = _do_callback([], state="abc123", cookie_state="different")

    assert response.status_code == 400
    assert _get_connection(real_test_db) is None


def test_callback_rejects_missing_state_cookie(real_test_db):
    with patch("app.routers.meta_auth.graph_get", side_effect=[]):
        response = client.get(
            "/auth/meta/callback", params={"code": "fake-code", "state": "abc123"}
        )

    assert response.status_code == 400
    assert _get_connection(real_test_db) is None


def test_callback_returns_429_when_rate_limited(real_test_db):
    response = _do_callback([MetaRateLimitedError("rate limited")])

    assert response.status_code == 429
    assert _get_connection(real_test_db) is None


def test_callback_returns_502_on_graph_api_error(real_test_db):
    response = _do_callback(
        [MetaGraphAPIError("bad code", status_code=400, meta_error_code=100)]
    )

    assert response.status_code == 502
    assert _get_connection(real_test_db) is None


def test_callback_with_no_pages_persists_connection_without_page(real_test_db):
    graph_responses = [
        {"access_token": "short-lived-token"},
        {"access_token": "long-lived-token", "expires_in": 5184000},
        {"data": []},
    ]

    response = _do_callback(graph_responses)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["page_name"] is None
    assert body["ig_connected"] is False

    conn = _get_connection(real_test_db)
    assert conn is not None
    assert conn.page_id is None
    assert conn.page_access_token is None
    assert conn.ig_business_account_id is None


def test_callback_ig_lookup_failure_still_connects_page(real_test_db):
    graph_responses = [
        {"access_token": "short-lived-token"},
        {"access_token": "long-lived-token", "expires_in": 5184000},
        {"data": [{"id": "page-1", "name": "My Page", "access_token": "page-token"}]},
        MetaGraphAPIError("ig lookup failed", status_code=400, meta_error_code=100),
    ]

    response = _do_callback(graph_responses)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["page_name"] == "My Page"
    assert body["ig_connected"] is False

    conn = _get_connection(real_test_db)
    assert conn.page_id == "page-1"
    assert conn.ig_business_account_id is None


# ---------------------------------------------------------------------------
# /auth/meta/refresh
# ---------------------------------------------------------------------------

def test_refresh_when_not_connected(real_test_db):
    response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "not_connected"}


def test_refresh_not_due_when_token_far_from_expiring(real_test_db):
    db = real_test_db()
    db.add(
        MetaConnection(
            user_access_token="current-token",
            user_token_expires_at=datetime.utcnow() + timedelta(days=30),
        )
    )
    db.commit()
    db.close()

    response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "not_due"}


def test_refresh_success_updates_connection(real_test_db):
    db = real_test_db()
    db.add(
        MetaConnection(
            user_access_token="current-token",
            user_token_expires_at=datetime.utcnow() + timedelta(days=1),
            page_id="old-page",
        )
    )
    db.commit()
    db.close()

    graph_responses = [
        {"access_token": "refreshed-token", "expires_in": 5184000},
        {"data": [{"id": "page-1", "name": "My Page", "access_token": "page-token"}]},
        {"instagram_business_account": {"id": "ig-123"}},
    ]

    with patch("app.routers.meta_auth.graph_get", side_effect=graph_responses):
        response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "refreshed"}

    conn = _get_connection(real_test_db)
    assert conn.user_access_token == "refreshed-token"
    assert conn.page_id == "page-1"


def test_refresh_returns_429_when_due_and_rate_limited(real_test_db):
    db = real_test_db()
    db.add(
        MetaConnection(
            user_access_token="current-token",
            user_token_expires_at=None,
        )
    )
    db.commit()
    db.close()

    with patch(
        "app.routers.meta_auth.graph_get",
        side_effect=MetaRateLimitedError("rate limited"),
    ):
        response = client.post("/auth/meta/refresh", params={"secret": "test-secret"})

    assert response.status_code == 429


# ---------------------------------------------------------------------------
# End-to-end: connect via callback, then fetch the social feed
# ---------------------------------------------------------------------------

def test_connect_then_fetch_social_feed_end_to_end(real_test_db):
    callback_graph_responses = [
        {"access_token": "short-lived-token"},
        {"access_token": "long-lived-token", "expires_in": 5184000},
        {"data": [{"id": "page-1", "name": "My Page", "access_token": "page-token"}]},
        {"instagram_business_account": {"id": "ig-123"}},
    ]
    callback_response = _do_callback(callback_graph_responses)
    assert callback_response.status_code == 200

    with patch(
        "app.routers.social_media.graph_get",
        return_value={"data": [{"id": "post-1", "message": "hello world"}]},
    ) as mock_graph_get:
        feed_response = client.get("/social-feed")

    assert feed_response.status_code == 200
    assert feed_response.json() == {"data": [{"id": "post-1", "message": "hello world"}]}

    called_url, called_params = mock_graph_get.call_args[0]
    assert called_url == "https://graph.facebook.com/v19.0/page-1/posts"
    assert called_params["access_token"] == "page-token"


def test_social_feed_without_connection_returns_409(real_test_db):
    response = client.get("/social-feed")

    assert response.status_code == 409
