from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Service

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/services")
def get_services(db: Session = Depends(get_db)):
    return db.query(Service).all()

from pydantic import BaseModel

class ServiceCreate(BaseModel):
    name: str
    description: str
    price: float

@router.post("/services")
def create_service(service: ServiceCreate, db: Session = Depends(get_db)):
    new_service = Service(
        name=service.name,
        description=service.description,
        price=service.price
    )
    db.add(new_service)
    db.commit()
    db.refresh(new_service)
    return new_service