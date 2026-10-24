import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("META_ADMIN_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import Base, get_db
from app.main import app
from app.models import Payment, Service, ServiceRequest, User
from app.payment_providers import PROVIDERS
from app.payment_providers.base import (
    PaymentProvider,
    ProviderError,
    ProviderEvent,
    ProviderIntent,
    WebhookVerificationError,
)

client = TestClient(app, headers={"X-User-Id": "1"})  # user 1 is the seeded older_adult


class RedirectProvider(PaymentProvider):
    """A deliberately non-Stripe processor: hosted redirect flow, its own
    status words and header-token webhook. Guards against Stripe-isms leaking
    into the router."""

    name = "redirectpay"
    orders: dict = {}
    WORDS = {"OPEN": "pending", "APPROVED": "paid", "DECLINED": "failed", "VOID": "canceled"}

    def ensure_configured(self):
        pass

    def _intent(self, order_id):
        return ProviderIntent(
            transaction_id=order_id,
            status=self.WORDS[self.orders[order_id]],
            next_action="redirect",
            redirect_url=f"https://pay.example/checkout/{order_id}",
        )

    def create_intent(self, *, amount_cents, currency, metadata, idempotency_key):
        order_id = f"ord_{len(self.orders) + 1}"
        self.orders[order_id] = "OPEN"
        return self._intent(order_id)

    def retrieve(self, transaction_id):
        if transaction_id not in self.orders:
            raise ProviderError("missing")
        return self._intent(transaction_id)

    def parse_webhook(self, body, headers):
        if headers.get("x-redirect-token") != "tok":
            raise WebhookVerificationError("bad token")
        data = json.loads(body)
        self.orders[data["order"]] = data["state"]
        return ProviderEvent(data["order"], self.WORDS[data["state"]])


@pytest.fixture()
def db_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    RedirectProvider.orders = {}
    monkeypatch.setitem(PROVIDERS, "redirectpay", RedirectProvider)
    yield Session
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _seed(Session, price=25.0):
    db = Session()
    user = User(first_name="Ada", last_name="Care", email="a@example.com", password_hash="h", role="older_adult")
    service = Service(name="Rides", description="Rides", price=price)
    db.add_all([user, service])
    db.commit()
    request = ServiceRequest(user_id=user.id, service_id=service.id)
    db.add(request)
    db.commit()
    request_id = request.id
    db.close()
    return request_id


def _txn(Session, payment_id):
    db = Session()
    try:
        return db.query(Payment).filter(Payment.id == payment_id).one().transaction_id
    finally:
        db.close()


def _use(monkeypatch, provider):
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", provider)


def _mock_hook(transaction_id, status, secret="mock-secret", provider="mock"):
    return client.post(
        f"/payments/webhook/{provider}",
        content=json.dumps({"transaction_id": transaction_id, "status": status}),
        headers={"x-mock-signature": secret},
    )


# --- mock provider -------------------------------------------------------

def test_mock_intent_pay_flow(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)

    created = client.post("/payments/intent", json={"service_request_id": request_id})
    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "mock"
    assert body["status"] == "pending"
    assert body["client_secret"]

    payment_id = body["payment_id"]
    assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"

    txn = _txn(db_factory, payment_id)
    assert _mock_hook(txn, "paid").status_code == 200
    assert client.get(f"/payments/{payment_id}").json()["status"] == "paid"


def test_mock_failure_then_new_attempt(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    first = client.post("/payments/intent", json={"service_request_id": request_id}).json()
    txn = _txn(db_factory, first["payment_id"])
    _mock_hook(txn, "failed")

    assert client.get(f"/payments/{first['payment_id']}").json()["status"] == "failed"
    retry = client.post("/payments/intent", json={"service_request_id": request_id})
    assert retry.status_code == 201
    assert retry.json()["payment_id"] != first["payment_id"]


def test_mock_disabled_unless_selected(db_factory, monkeypatch):
    _use(monkeypatch, "stripe")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", None)
    assert _mock_hook("mock_x", "paid").status_code == 503
    request_id = _seed(db_factory)
    assert client.post("/payments/intent", json={"service_request_id": request_id}).status_code == 503


def test_webhook_bad_signature_rejected(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    assert _mock_hook("mock_x", "paid", secret="wrong").status_code == 400


def test_webhook_unknown_provider_404(db_factory):
    assert client.post("/payments/webhook/nope", content=b"{}").status_code == 404


def test_webhook_unknown_transaction_acknowledged(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    assert _mock_hook("mock_unknown", "paid").status_code == 200


def test_settled_payment_not_reopened_by_replay(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]
    txn = _txn(db_factory, pid)
    _mock_hook(txn, "paid")
    _mock_hook(txn, "paid")
    _mock_hook(txn, "failed")
    assert client.get(f"/payments/{pid}").json()["status"] == "paid"


def test_get_payment_missing(db_factory):
    _seed(db_factory)
    assert client.get("/payments/999").status_code == 404


# --- seam check: a non-Stripe-shaped processor ---------------------------

def test_redirect_provider_full_flow(db_factory, monkeypatch):
    _use(monkeypatch, "redirectpay")
    request_id = _seed(db_factory)

    body = client.post("/payments/intent", json={"service_request_id": request_id}).json()
    assert body["provider"] == "redirectpay"
    assert body["next_action"] == "redirect"
    assert body["redirect_url"].startswith("https://pay.example/")
    assert body["client_secret"] is None

    # open intent is reused instead of creating a second order
    again = client.post("/payments/intent", json={"service_request_id": request_id}).json()
    assert again["payment_id"] == body["payment_id"]
    assert len(RedirectProvider.orders) == 1

    txn = _txn(db_factory, body["payment_id"])
    hook = client.post(
        "/payments/webhook/redirectpay",
        content=json.dumps({"order": txn, "state": "APPROVED"}),
        headers={"x-redirect-token": "tok"},
    )
    assert hook.status_code == 200
    assert client.get(f"/payments/{body['payment_id']}").json()["status"] == "paid"


def test_redirect_provider_complete_reconciles(db_factory, monkeypatch):
    _use(monkeypatch, "redirectpay")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]
    RedirectProvider.orders["ord_1"] = "DECLINED"

    res = client.post(f"/payments/{pid}/complete")

    assert res.status_code == 200
    assert res.json()["status"] == "failed"


def test_switching_provider_does_not_reuse_old_intent(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    first = client.post("/payments/intent", json={"service_request_id": request_id}).json()

    _use(monkeypatch, "redirectpay")
    second = client.post("/payments/intent", json={"service_request_id": request_id}).json()

    assert second["payment_id"] != first["payment_id"]
    assert second["provider"] == "redirectpay"
    db = db_factory()
    assert {p.provider for p in db.query(Payment).all()} == {"mock", "redirectpay"}
    db.close()


def test_payment_keeps_its_original_provider_after_switch(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]
    txn = _txn(db_factory, pid)

    _use(monkeypatch, "redirectpay")
    # mock is disabled now, so GET falls back to the stored status
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"
    assert client.get(f"/payments/{pid}").json()["provider"] == "mock"
    assert txn.startswith("mock_")


# --- stripe webhook ------------------------------------------------------

def test_stripe_webhook_marks_paid(db_factory, monkeypatch):
    import stripe

    _use(monkeypatch, "stripe")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk")
    monkeypatch.setattr(config, "STRIPE_PUBLISHABLE_KEY", "pk")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec")

    class Intent:
        id, client_secret, status = "pi_1", "sec", "requires_payment_method"

    monkeypatch.setattr(stripe.PaymentIntent, "create", lambda **kw: Intent())
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]

    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda body, sig, secret: {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_1"}}},
    )
    assert client.post("/payments/webhook/stripe", content=b"{}", headers={"stripe-signature": "x"}).status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "paid"


def test_stripe_webhook_bad_signature(db_factory, monkeypatch):
    _use(monkeypatch, "stripe")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec")
    res = client.post("/payments/webhook/stripe", content=b"{}", headers={"stripe-signature": "bad"})
    assert res.status_code == 400


def test_stripe_webhook_requires_secret(db_factory, monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", None)
    assert client.post("/payments/webhook/stripe", content=b"{}").status_code == 503


# --- security regressions ------------------------------------------------

def _stripe_setup(db_factory, monkeypatch):
    import stripe

    _use(monkeypatch, "stripe")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk")
    monkeypatch.setattr(config, "STRIPE_PUBLISHABLE_KEY", "pk")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec")

    class Intent:
        id, client_secret, status = "pi_1", "sec", "requires_payment_method"

    monkeypatch.setattr(stripe.PaymentIntent, "create", lambda **kw: Intent())
    request_id = _seed(db_factory)
    return client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]


def _stripe_event(monkeypatch, event_type, **obj):
    import stripe

    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda body, sig, secret: {"type": event_type, "data": {"object": {"id": "pi_1", **obj}}},
    )
    return client.post("/payments/webhook/stripe", content=b"{}", headers={"stripe-signature": "x"})


def test_declined_attempt_then_success_ends_paid(db_factory, monkeypatch):
    pid = _stripe_setup(db_factory, monkeypatch)

    _stripe_event(monkeypatch, "payment_intent.payment_failed")
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"

    _stripe_event(monkeypatch, "payment_intent.succeeded", amount_received=2500)
    assert client.get(f"/payments/{pid}").json()["status"] == "paid"


def test_canceled_intent_fails_payment(db_factory, monkeypatch):
    pid = _stripe_setup(db_factory, monkeypatch)
    _stripe_event(monkeypatch, "payment_intent.canceled")
    assert client.get(f"/payments/{pid}").json()["status"] == "failed"


def test_paid_overrides_recorded_failure(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]
    txn = _txn(db_factory, pid)

    _mock_hook(txn, "failed")
    assert client.get(f"/payments/{pid}").json()["status"] == "failed"
    _mock_hook(txn, "paid")
    assert client.get(f"/payments/{pid}").json()["status"] == "paid"


def test_paid_event_with_wrong_amount_is_not_settled(db_factory, monkeypatch):
    pid = _stripe_setup(db_factory, monkeypatch)

    res = _stripe_event(monkeypatch, "payment_intent.succeeded", amount_received=1)

    assert res.status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"


def test_mock_paid_event_amount_must_match(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]
    txn = _txn(db_factory, pid)

    bad = client.post(
        "/payments/webhook/mock",
        content=json.dumps({"transaction_id": txn, "status": "paid", "amount_cents": 5}),
        headers={"x-mock-signature": "mock-secret"},
    )
    assert bad.status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"

    good = client.post(
        "/payments/webhook/mock",
        content=json.dumps({"transaction_id": txn, "status": "paid", "amount_cents": 2500}),
        headers={"x-mock-signature": "mock-secret"},
    )
    assert good.status_code == 200
    assert client.get(f"/payments/{pid}").json()["status"] == "paid"


def test_oversized_webhook_rejected(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    res = client.post(
        "/payments/webhook/mock",
        content=b"x" * 1_000_001,
        headers={"x-mock-signature": "mock-secret"},
    )
    assert res.status_code == 413


def test_mock_provider_refuses_to_run_in_production(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    monkeypatch.setattr(config, "APP_ENV", "production")
    request_id = _seed(db_factory)

    assert client.post("/payments/intent", json={"service_request_id": request_id}).status_code == 503
    assert _mock_hook("mock_x", "paid").status_code == 503


def test_payment_status_does_not_leak_internal_ids(db_factory, monkeypatch):
    _use(monkeypatch, "mock")
    request_id = _seed(db_factory)
    pid = client.post("/payments/intent", json={"service_request_id": request_id}).json()["payment_id"]

    body = client.get(f"/payments/{pid}").json()

    assert set(body) == {"payment_id", "provider", "status", "amount", "currency"}
    assert set(client.post(f"/payments/{pid}/complete").json()) == set(body)
