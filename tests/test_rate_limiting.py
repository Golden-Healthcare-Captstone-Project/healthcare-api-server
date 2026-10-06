import os
from unittest.mock import MagicMock, Mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.main import app
from app.models import Service, User
from app.routers import requests as requests_router

client = TestClient(app)


def _fake_db():
    db = MagicMock()

    def query_side_effect(model):
        query_mock = MagicMock()
        if model is User:
            query_mock.filter.return_value.first.return_value = Mock()
        elif model is Service:
            query_mock.filter.return_value.first.return_value = Mock()
        return query_mock

    db.query.side_effect = query_side_effect
    db.refresh.side_effect = lambda obj: setattr(obj, "id", 1)
    return db


def test_create_service_request_returns_429_after_limit_exceeded():
    app.dependency_overrides[requests_router.get_db] = lambda: _fake_db()

    responses = [
        client.post("/requests/", json={"user_id": 1, "service_id": 1})
        for _ in range(21)
    ]

    app.dependency_overrides.pop(requests_router.get_db, None)

    assert [r.status_code for r in responses[:20]] == [201] * 20
    assert responses[20].status_code == 429
    assert responses[20].json() == {"detail": "Too many requests, please try again later"}
    assert responses[20].headers["Retry-After"] == "60"
