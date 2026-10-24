import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import add_request, add_service, add_user, hdr, link

client = TestClient(app)


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


def test_client_creates_request_for_self(db_factory):
    w = _world(db_factory)
    res = client.post("/requests/", json={"user_id": w["client"], "service_id": w["service"]}, headers=hdr(w["client"]))
    assert res.status_code == 201
    assert res.json()["user_id"] == w["client"]


def test_missing_identity_is_401(db_factory):
    w = _world(db_factory)
    assert client.post("/requests/", json={"user_id": w["client"], "service_id": w["service"]}).status_code == 401
    assert client.post(
        "/requests/", json={"user_id": 1, "service_id": 1}, headers={"X-User-Id": "9999"}
    ).status_code == 401


def test_cannot_create_request_for_someone_else(db_factory):
    w = _world(db_factory)
    res = client.post("/requests/", json={"user_id": w["other"], "service_id": w["service"]}, headers=hdr(w["client"]))
    assert res.status_code == 403


def test_linked_caregiver_can_create_for_client_but_unlinked_cannot(db_factory):
    w = _world(db_factory)
    link(db_factory, w["caregiver"], w["client"])
    body = {"user_id": w["client"], "service_id": w["service"]}

    assert client.post("/requests/", json=body, headers=hdr(w["caregiver"])).status_code == 201
    assert client.post("/requests/", json=body, headers=hdr(w["stranger"])).status_code == 403


def test_staff_roles_cannot_create_requests(db_factory):
    w = _world(db_factory)
    for role in ("provider", "admin"):
        res = client.post("/requests/", json={"user_id": w[role], "service_id": w["service"]}, headers=hdr(w[role]))
        assert res.status_code == 403, role


def test_unknown_service_is_404(db_factory):
    w = _world(db_factory)
    res = client.post("/requests/", json={"user_id": w["client"], "service_id": 999}, headers=hdr(w["client"]))
    assert res.status_code == 404


def test_list_is_scoped_by_role(db_factory):
    w = _world(db_factory)
    link(db_factory, w["caregiver"], w["client"])
    mine = add_request(db_factory, w["client"], w["service"])
    theirs = add_request(db_factory, w["other"], w["service"])

    def ids(user):
        res = client.get("/requests/", headers=hdr(w[user]))
        assert res.status_code == 200, user
        return {r["id"] for r in res.json()}

    assert ids("client") == {mine}
    assert ids("other") == {theirs}
    assert ids("caregiver") == {mine}  # linked to client only
    assert ids("stranger") == set()
    assert ids("provider") == {mine, theirs}
    assert ids("admin") == {mine, theirs}
    assert client.get("/requests/").status_code == 401


def test_status_update_is_staff_only(db_factory):
    w = _world(db_factory)
    request_id = add_request(db_factory, w["client"], w["service"])
    url = f"/requests/{request_id}/status"

    assert client.patch(url, json={"status": "approved"}, headers=hdr(w["client"])).status_code == 403
    assert client.patch(url, json={"status": "approved"}, headers=hdr(w["caregiver"])).status_code == 403
    ok = client.patch(url, json={"status": "approved"}, headers=hdr(w["provider"]))
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert client.patch(url, json={"status": "completed"}, headers=hdr(w["admin"])).status_code == 200
    assert client.patch(url, json={"status": "bogus"}, headers=hdr(w["admin"])).status_code == 422
    assert client.patch("/requests/999/status", json={"status": "approved"}, headers=hdr(w["admin"])).status_code == 404
