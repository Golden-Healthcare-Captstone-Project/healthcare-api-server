import os
from unittest.mock import Mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import services


def _fake_db():
    db = Mock()
    db.refresh.side_effect = lambda obj: setattr(obj, "id", 1)
    return db


def _fake_get_db():
    yield _fake_db()


@pytest.fixture(autouse=True)
def override_get_db():
    app.dependency_overrides[services.get_db] = _fake_get_db
    yield
    app.dependency_overrides.pop(services.get_db, None)


client = TestClient(app)


def test_create_service_rejects_negative_price():
    response = client.post(
        "/services",
        json={"name": "Ride assistance", "description": "desc", "price": -5},
    )

    assert response.status_code == 422


def test_create_service_success():
    response = client.post(
        "/services",
        json={"name": "Ride assistance", "description": "desc", "price": 25.0},
    )

    assert response.status_code == 201
