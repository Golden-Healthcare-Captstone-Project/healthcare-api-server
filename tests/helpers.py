"""Small builders shared by the account/permission tests."""
from app.models import CaregiverLink, Service, ServiceRequest, User

ROLES = ("older_adult", "caregiver", "provider", "admin")


def add_user(Session, role, name=None):
    db = Session()
    try:
        label = name or role
        user = User(
            first_name=label.title(),
            last_name="Test",
            email=f"{label}-{db.query(User).count()}@example.com",
            password_hash="x",
            role=role,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def add_service(Session, price=25.0):
    db = Session()
    try:
        service = Service(name="Rides", description="Rides", price=price)
        db.add(service)
        db.commit()
        return service.id
    finally:
        db.close()


def add_request(Session, user_id, service_id):
    db = Session()
    try:
        request = ServiceRequest(user_id=user_id, service_id=service_id, notes="n")
        db.add(request)
        db.commit()
        return request.id
    finally:
        db.close()


def link(Session, caregiver_id, older_adult_id):
    db = Session()
    try:
        row = CaregiverLink(caregiver_id=caregiver_id, older_adult_id=older_adult_id)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def hdr(user_id):
    return {"X-User-Id": str(user_id)}
