import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_service_request_returns_429_after_limit_exceeded(db_factory):
    from tests.helpers import add_service, add_user, hdr

    user = add_user(db_factory, "older_adult")
    service = add_service(db_factory)

    responses = [
        client.post("/requests/", json={"user_id": user, "service_id": service}, headers=hdr(user))
        for _ in range(21)
    ]

    assert [r.status_code for r in responses[:20]] == [201] * 20
    assert responses[20].status_code == 429
    assert responses[20].json() == {"detail": "Too many requests, please try again later"}
    assert responses[20].headers["Retry-After"] == "60"
