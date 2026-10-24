import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models import Payment, User
from app.permissions import ROLE_PERMISSIONS, Permission, has_permission, permissions_for
from tests.helpers import ROLES, add_request, add_service, add_user, hdr, link

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "mock")


def _world(Session):
    return {
        "client": add_user(Session, "older_adult", "client"),
        "other": add_user(Session, "older_adult", "other"),
        "caregiver": add_user(Session, "caregiver", "caregiver"),
        "stranger": add_user(Session, "caregiver", "stranger"),
        "provider": add_user(Session, "provider", "provider"),
        "admin": add_user(Session, "admin", "admin"),
        "service": add_service(Session),
    }


# --- the permission table itself -----------------------------------------

def test_permission_table_matches_the_agreed_matrix():
    expected = {
        "older_adult": {"create_request", "view_own_requests", "make_payment", "view_payment"},
        "caregiver": {"create_request", "view_own_requests", "make_payment", "view_payment"},
        "provider": {"view_all_requests", "update_request_status"},
        "admin": {
            "view_all_requests", "update_request_status", "view_payment", "view_all_payments",
            "manage_services", "manage_users", "manage_links",
        },
    }
    assert {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()} == expected


def test_unknown_or_missing_role_has_no_permissions():
    for role in (None, "", "superuser", "ADMIN"):
        assert permissions_for(role) == frozenset()
    assert not has_permission(User(role="legacy"), Permission.CREATE_REQUEST)


def test_user_with_unknown_role_is_denied_everywhere(db_factory):
    legacy = add_user(db_factory, "legacy_role")
    assert client.get("/requests/", headers=hdr(legacy)).status_code == 403
    assert client.post("/services", json={"name": "x", "price": 1}, headers=hdr(legacy)).status_code == 403
    assert client.get("/me", headers=hdr(legacy)).json()["permissions"] == []


# --- /me and linked clients ----------------------------------------------

def test_me_reports_role_and_permissions(db_factory):
    w = _world(db_factory)
    for role in ROLES:
        body = client.get("/me", headers=hdr(w["client" if role == "older_adult" else role])).json()
        assert body["role"] == role
        assert set(body["permissions"]) == set(ROLE_PERMISSIONS[role])
    assert client.get("/me").status_code == 401


def test_linked_clients_only_for_caregivers(db_factory):
    w = _world(db_factory)
    link(db_factory, w["caregiver"], w["client"])

    mine = client.get("/me/linked-clients", headers=hdr(w["caregiver"])).json()
    assert [c["id"] for c in mine] == [w["client"]]
    assert client.get("/me/linked-clients", headers=hdr(w["stranger"])).json() == []
    assert client.get("/me/linked-clients", headers=hdr(w["client"])).json() == []


# --- admin-only account management ---------------------------------------

@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/users", None),
        ("post", "/users", {"first_name": "A", "last_name": "B", "email": "a@b.co", "role": "provider"}),
        ("patch", "/users/1/role", {"role": "provider"}),
        ("get", "/caregiver-links", None),
        ("post", "/caregiver-links", {"caregiver_id": 1, "older_adult_id": 2}),
        ("delete", "/caregiver-links/1", None),
    ],
)
def test_account_management_is_admin_only(db_factory, method, path, body):
    w = _world(db_factory)
    for role in ("client", "caregiver", "provider"):
        res = getattr(client, method)(path, headers=hdr(w[role]), **({"json": body} if body else {}))
        assert res.status_code == 403, (role, path)
    assert getattr(client, method)(path, **({"json": body} if body else {})).status_code == 401


def test_admin_creates_users_and_rejects_duplicates_and_bad_roles(db_factory):
    w = _world(db_factory)
    body = {"first_name": "New", "last_name": "Person", "email": "New@Example.com", "role": "caregiver"}

    created = client.post("/users", json=body, headers=hdr(w["admin"]))
    assert created.status_code == 201
    assert created.json()["email"] == "new@example.com"
    assert "password" not in str(created.json()).lower()

    assert client.post("/users", json=body, headers=hdr(w["admin"])).status_code == 409
    assert client.post("/users", json={**body, "email": "x@y.co", "role": "root"}, headers=hdr(w["admin"])).status_code == 422
    listing = client.get("/users", headers=hdr(w["admin"])).json()
    assert all("password_hash" not in u for u in listing)


def test_cannot_remove_the_last_admin(db_factory):
    w = _world(db_factory)
    res = client.patch(f"/users/{w['admin']}/role", json={"role": "provider"}, headers=hdr(w["admin"]))
    assert res.status_code == 409

    second = add_user(db_factory, "admin", "second")
    ok = client.patch(f"/users/{second}/role", json={"role": "provider"}, headers=hdr(w["admin"]))
    assert ok.status_code == 200 and ok.json()["role"] == "provider"
    assert client.patch("/users/999/role", json={"role": "admin"}, headers=hdr(w["admin"])).status_code == 404


def test_link_rules(db_factory):
    w = _world(db_factory)
    body = {"caregiver_id": w["caregiver"], "older_adult_id": w["client"], "relationship_note": "daughter"}

    first = client.post("/caregiver-links", json=body, headers=hdr(w["admin"]))
    assert first.status_code == 201
    assert client.post("/caregiver-links", json=body, headers=hdr(w["admin"])).status_code == 409
    # the roles must fit: a provider is not a caregiver, a caregiver is not an older adult
    bad_caregiver = {"caregiver_id": w["provider"], "older_adult_id": w["client"]}
    assert client.post("/caregiver-links", json=bad_caregiver, headers=hdr(w["admin"])).status_code == 400
    bad_client = {"caregiver_id": w["caregiver"], "older_adult_id": w["stranger"]}
    assert client.post("/caregiver-links", json=bad_client, headers=hdr(w["admin"])).status_code == 400
    assert client.post(
        "/caregiver-links", json={"caregiver_id": 999, "older_adult_id": w["client"]}, headers=hdr(w["admin"])
    ).status_code == 404

    link_id = first.json()["id"]
    assert client.delete(f"/caregiver-links/{link_id}", headers=hdr(w["admin"])).status_code == 204
    assert client.delete(f"/caregiver-links/{link_id}", headers=hdr(w["admin"])).status_code == 404
    # once unlinked the caregiver loses access again
    res = client.post(
        "/requests/", json={"user_id": w["client"], "service_id": w["service"]}, headers=hdr(w["caregiver"])
    )
    assert res.status_code == 403


# --- payments: who may pay for and see what ------------------------------

def _intent(w, request_id, user):
    return client.post("/payments/intent", json={"service_request_id": request_id}, headers=hdr(w[user]))


def test_owner_pays_and_sees_own_payment_only(db_factory):
    w = _world(db_factory)
    request_id = add_request(db_factory, w["client"], w["service"])

    res = _intent(w, request_id, "client")
    assert res.status_code == 201
    payment_id = res.json()["payment_id"]

    assert client.get(f"/payments/{payment_id}", headers=hdr(w["client"])).status_code == 200
    # another client sees "not found", not "forbidden", so ids cannot be probed
    assert client.get(f"/payments/{payment_id}", headers=hdr(w["other"])).status_code == 404
    assert client.post(f"/payments/{payment_id}/complete", headers=hdr(w["other"])).status_code == 404
    assert _intent(w, request_id, "other").status_code == 404


def test_linked_caregiver_may_pay_unlinked_may_not(db_factory):
    w = _world(db_factory)
    link(db_factory, w["caregiver"], w["client"])
    request_id = add_request(db_factory, w["client"], w["service"])

    assert _intent(w, request_id, "stranger").status_code == 404
    res = _intent(w, request_id, "caregiver")
    assert res.status_code == 201
    payment_id = res.json()["payment_id"]
    assert client.get(f"/payments/{payment_id}", headers=hdr(w["caregiver"])).status_code == 200
    assert client.get(f"/payments/{payment_id}", headers=hdr(w["stranger"])).status_code == 404


def test_staff_cannot_pay_but_admin_can_view_any_payment(db_factory):
    w = _world(db_factory)
    request_id = add_request(db_factory, w["client"], w["service"])
    payment_id = _intent(w, request_id, "client").json()["payment_id"]

    assert _intent(w, request_id, "provider").status_code == 403
    assert _intent(w, request_id, "admin").status_code == 403
    assert client.get(f"/payments/{payment_id}", headers=hdr(w["provider"])).status_code == 403
    assert client.get(f"/payments/{payment_id}", headers=hdr(w["admin"])).status_code == 200
    assert client.post(f"/payments/{payment_id}/complete", headers=hdr(w["admin"])).status_code == 403


def test_payment_routes_need_identity_but_webhooks_do_not(db_factory):
    w = _world(db_factory)
    request_id = add_request(db_factory, w["client"], w["service"])
    assert client.post("/payments/intent", json={"service_request_id": request_id}).status_code == 401
    assert client.get("/payments/1").status_code == 401
    # webhooks authenticate by signature, not by account
    assert client.post("/payments/webhook/mock", content=b"{}").status_code == 400


# --- bootstrap ------------------------------------------------------------

def test_seed_creates_then_promotes_admin(db_factory, monkeypatch):
    from app import seed

    monkeypatch.setattr(seed, "SessionLocal", db_factory)

    seed.create_admin("Boss@Example.com", "Boss", "Person")
    db = db_factory()
    boss = db.query(User).filter(User.email == "boss@example.com").one()
    assert boss.role == "admin" and boss.password_hash == "!"
    boss.role = "provider"
    db.commit()
    db.close()

    seed.create_admin("boss@example.com")
    db = db_factory()
    assert db.query(User).filter(User.email == "boss@example.com").one().role == "admin"
    assert db.query(User).count() == 1
    db.close()
