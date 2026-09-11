import os
from unittest.mock import MagicMock, Mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Service, User
from app.routers import requests as requests_router


def _fake_db(user_exists=True, service_exists=True):
    db = MagicMock()

    def query_side_effect(model):
        query_mock = MagicMock()
        if model is User:
            query_mock.filter.return_value.first.return_value = Mock() if user_exists else None
        elif model is Service:
            query_mock.filter.return_value.first.return_value = Mock() if service_exists else None
        return query_mock

    db.query.side_effect = query_side_effect
    db.refresh.side_effect = lambda obj: setattr(obj, "id", 1)
    return db


def _override(user_exists=True, service_exists=True):
    def _fake_get_db():
        yield _fake_db(user_exists=user_exists, service_exists=service_exists)
    return _fake_get_db


client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_override():
    yield
    app.dependency_overrides.pop(requests_router.get_db, None)


def test_create_service_request_404_when_user_missing():
    app.dependency_overrides[requests_router.get_db] = _override(user_exists=False)

    response = client.post("/requests/", json={"user_id": 1, "service_id": 1})

    assert response.status_code == 404


def test_create_service_request_404_when_service_missing():
    app.dependency_overrides[requests_router.get_db] = _override(service_exists=False)

    response = client.post("/requests/", json={"user_id": 1, "service_id": 1})

    assert response.status_code == 404


def test_create_service_request_success():
    app.dependency_overrides[requests_router.get_db] = _override()

    response = client.post("/requests/", json={"user_id": 1, "service_id": 1})

    assert response.status_code == 201
