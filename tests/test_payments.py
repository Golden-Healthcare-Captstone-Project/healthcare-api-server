import os
from unittest.mock import Mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("META_ADMIN_SECRET", "test-secret")

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import Base, get_db
from app.main import app
from app.models import Payment, Service, ServiceRequest, User

client = TestClient(app)


class FakeIntent:
    def __init__(self, intent_id="pi_test", client_secret="sec_test", status="requires_payment_method"):
        self.id = intent_id
        self.client_secret = client_secret
        self.status = status


@pytest.fixture()
def db_factory(monkeypatch):
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

    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(config, "STRIPE_PUBLISHABLE_KEY", "pk_test")
    app.dependency_overrides[get_db] = _override_get_db
    yield TestingSessionLocal
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _seed(session_factory, price=25.0):
    db = session_factory()
    user = User(
        first_name="Ada",
        last_name="Care",
        email="ada@example.com",
        password_hash="hash",
        role="older_adult",
    )
    service = Service(name="Transportation", description="Rides", price=price)
    db.add_all([user, service])
    db.commit()
    request = ServiceRequest(user_id=user.id, service_id=service.id, notes="Need a ride")
    db.add(request)
    db.commit()
    request_id = request.id
    db.close()
    return request_id


def test_create_intent_charges_service_price(db_factory, monkeypatch):
    request_id = _seed(db_factory)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeIntent()

    monkeypatch.setattr(stripe.PaymentIntent, "create", fake_create)

    response = client.post("/payments/intent", json={"service_request_id": request_id})

    assert response.status_code == 201
    body = response.json()
    assert body["client_secret"] == "sec_test"
    assert body["publishable_key"] == "pk_test"
    assert body["amount"] == 25.0
    assert body["currency"] == "usd"
    assert captured["amount"] == 2500
    assert captured["currency"] == "usd"
    assert captured["payment_method_types"] == ["card"]

    db = db_factory()
    payment = db.query(Payment).one()
    assert payment.status == "pending"
    assert payment.transaction_id == "pi_test"
    assert payment.service_request_id == request_id
    db.close()


def test_create_intent_missing_request(db_factory):
    response = client.post("/payments/intent", json={"service_request_id": 99})
    assert response.status_code == 404


def test_create_intent_rejects_small_price(db_factory, monkeypatch):
    request_id = _seed(db_factory, price=0)
    monkeypatch.setattr(stripe.PaymentIntent, "create", Mock(side_effect=AssertionError("should not charge")))

    response = client.post("/payments/intent", json={"service_request_id": request_id})

    assert response.status_code == 400


def test_create_intent_requires_stripe_config(db_factory, monkeypatch):
    request_id = _seed(db_factory)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", None)

    response = client.post("/payments/intent", json={"service_request_id": request_id})

    assert response.status_code == 503


def test_create_intent_reuses_pending_payment(db_factory, monkeypatch):
    request_id = _seed(db_factory)
    monkeypatch.setattr(stripe.PaymentIntent, "create", lambda **kwargs: FakeIntent())
    first = client.post("/payments/intent", json={"service_request_id": request_id})
    assert first.status_code == 201

    monkeypatch.setattr(
        stripe.PaymentIntent,
        "retrieve",
        lambda intent_id: FakeIntent(intent_id, "sec_test", "requires_payment_method"),
    )
    monkeypatch.setattr(stripe.PaymentIntent, "create", Mock(side_effect=AssertionError("should reuse")))

    second = client.post("/payments/intent", json={"service_request_id": request_id})

    assert second.status_code == 201
    assert second.json()["payment_id"] == first.json()["payment_id"]


def test_create_intent_rejects_already_paid(db_factory):
    request_id = _seed(db_factory)
    db = db_factory()
    request = db.query(ServiceRequest).one()
    db.add(
        Payment(
            user_id=request.user_id,
            service_request_id=request.id,
            amount=25.0,
            status="paid",
            transaction_id="pi_paid",
        )
    )
    db.commit()
    db.close()

    response = client.post("/payments/intent", json={"service_request_id": request_id})

    assert response.status_code == 409


def test_complete_marks_payment_paid(db_factory, monkeypatch):
    request_id = _seed(db_factory)
    monkeypatch.setattr(stripe.PaymentIntent, "create", lambda **kwargs: FakeIntent())
    created = client.post("/payments/intent", json={"service_request_id": request_id})
    payment_id = created.json()["payment_id"]
    monkeypatch.setattr(
        stripe.PaymentIntent,
        "retrieve",
        lambda intent_id: FakeIntent(intent_id, "sec_test", "succeeded"),
    )

    response = client.post(f"/payments/{payment_id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "paid"


def test_complete_missing_payment(db_factory):
    response = client.post("/payments/999/complete")
    assert response.status_code == 404
