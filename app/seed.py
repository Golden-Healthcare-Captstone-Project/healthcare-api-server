from app.database import SessionLocal
from app import models

def seed():
    db = SessionLocal()

    services_to_add = [
        {
            "name": "Transportation Assistance",
            "description": "Help getting to medical appointments"
        },
        {
            "name": "Respite Care",
            "description": "Temporary caregiver relief"
        },
        {
            "name": "Home Support",
            "description": "In-home assistance services"
        }
    ]

    existing_names = {service.name for service in db.query(models.Service).all()}

    for service_data in services_to_add:
        if service_data["name"] not in existing_names:
            new_service = models.Service(**service_data)
            db.add(new_service)

    db.commit()
    db.close()

    print("Seeding complete.")

def create_admin(email: str, first_name: str = "Admin", last_name: str = "User") -> None:
    """Create the first admin, or promote an existing account. No other way exists yet."""
    email = email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user is None:
            user = models.User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                password_hash="!",  # sign-in is not built yet; this can never match
                role="admin",
            )
            db.add(user)
            action = "Created"
        else:
            user.role = "admin"
            action = "Promoted"
        db.commit()
        print(f"{action} admin account: {email} (id {user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed services, or create the first admin account.")
    parser.add_argument("--admin", metavar="EMAIL", help="create (or promote) an admin account with this email")
    parser.add_argument("--first-name", default="Admin")
    parser.add_argument("--last-name", default="User")
    args = parser.parse_args()
    if args.admin:
        create_admin(args.admin, args.first_name, args.last_name)
    else:
        seed()