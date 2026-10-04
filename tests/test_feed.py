from datetime import datetime
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import Post, User


client = TestClient(app)


def _make_post(post_id=1, text="Test post"):
    author = Mock()
    author.id = 1
    author.first_name = "Juan"
    author.last_name = "Test"
    author.role = "caregiver"

    post = Mock(spec=Post)
    post.id = post_id
    post.author = author
    post.text = text
    post.created_at = datetime(2026, 10, 3, 12, 0, 0)

    return post


def test_get_feed_returns_paginated_posts():
    db = Mock()
    post = _make_post()

    count_query = Mock()
    count_query.count.return_value = 1

    post_query = Mock()
    post_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [post]

    db.query.side_effect = [count_query, post_query]

    def fake_get_db():
        yield db

    app.dependency_overrides[get_db] = fake_get_db

    response = client.get("/feed?page=1&limit=10")

    app.dependency_overrides.clear()

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 1
    assert data["page"] == 1
    assert data["limit"] == 10
    assert data["hasNext"] is False
    assert data["posts"][0]["text"] == "Test post"


def test_post_feed_requires_authentication():
    db = Mock()

    def fake_get_db():
        yield db

    app.dependency_overrides[get_db] = fake_get_db

    response = client.post(
        "/feed",
        json={"text": "Protected post"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_post_feed_creates_post_for_authenticated_user():
    db = Mock()

    user = User(
        id=1,
        first_name="Juan",
        last_name="Test",
        email="juan.test@example.com",
        password_hash="test-hash",
        role="caregiver",
    )

    def fake_get_db():
        yield db

    def fake_current_user():
        return user

    def refresh_post(post):
        post.id = 1
        post.created_at = datetime(2026, 10, 3, 12, 0, 0)
        post.author = user

    db.refresh.side_effect = refresh_post

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = fake_current_user

    response = client.post(
        "/feed",
        json={"text": "Authenticated post"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201

    data = response.json()

    assert data["text"] == "Authenticated post"
    assert data["author"]["id"] == "1"
    assert data["author"]["name"] == "Juan Test"


def test_post_feed_rejects_whitespace_only_text():
    user = Mock(spec=User)
    user.id = 1

    def fake_current_user():
        return user

    app.dependency_overrides[get_current_user] = fake_current_user

    response = client.post(
        "/feed",
        json={"text": "     "},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 422