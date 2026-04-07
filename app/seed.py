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

if __name__ == "__main__":
    seed()