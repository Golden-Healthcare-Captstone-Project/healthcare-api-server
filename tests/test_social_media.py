import os
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.meta_client import MetaGraphAPIError, MetaRateLimitedError
from app.routers import social_media


def _connected_db():
    conn = Mock(page_id="123", page_access_token="token")
    db = Mock()
    db.query.return_value.first.return_value = conn
    return db


def _fake_get_db():
    yield _connected_db()


@pytest.fixture(autouse=True)
def override_get_db():
    app.dependency_overrides[social_media.get_db] = _fake_get_db
    yield
    app.dependency_overrides.pop(social_media.get_db, None)


client = TestClient(app)


def test_social_feed_returns_429_when_rate_limited():
    with patch("app.routers.social_media.graph_get", side_effect=MetaRateLimitedError("rate limited")):
        response = client.get("/social-feed")

    assert response.status_code == 429


def test_social_feed_returns_502_on_graph_api_error():
    with patch(
        "app.routers.social_media.graph_get",
        side_effect=MetaGraphAPIError("bad token", status_code=401, meta_error_code=190),
    ):
        response = client.get("/social-feed")

    assert response.status_code == 502


def test_social_feed_returns_data_on_success():
    with patch("app.routers.social_media.graph_get", return_value={"data": ["post1"]}):
        response = client.get("/social-feed")

    assert response.status_code == 200
    assert response.json() == {"data": ["post1"]}
