import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import add_user, hdr

client = TestClient(app)
BODY = {"name": "Ride assistance", "description": "desc", "price": 25.0}


def test_listing_services_is_public(db_factory):
    assert client.get("/services").status_code == 200


def test_admin_creates_service(db_factory):
    admin = add_user(db_factory, "admin")
    res = client.post("/services", json=BODY, headers=hdr(admin))
    assert res.status_code == 201
    assert res.json()["price"] == 25.0


def test_create_service_rejects_negative_price(db_factory):
    admin = add_user(db_factory, "admin")
    res = client.post("/services", json={**BODY, "price": -5}, headers=hdr(admin))
    assert res.status_code == 422


def test_non_admins_cannot_create_services(db_factory):
    assert client.post("/services", json=BODY).status_code == 401
    for role in ("older_adult", "caregiver", "provider"):
        user = add_user(db_factory, role)
        assert client.post("/services", json=BODY, headers=hdr(user)).status_code == 403, role
