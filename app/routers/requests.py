from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import ServiceRequest
from ..schemas import ServiceRequestCreate

router = APIRouter(prefix="/requests", tags=["Service Requests"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_service_request(request: ServiceRequestCreate, db: Session = Depends(get_db)):
    new_request = ServiceRequest(
        user_id=request.user_id,
        service_id=request.service_id,
        notes=request.notes
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    return new_request


@router.get("/")
def get_requests(db: Session = Depends(get_db)):
    return db.query(ServiceRequest).all()