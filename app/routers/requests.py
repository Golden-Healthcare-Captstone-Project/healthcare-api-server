import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Service, ServiceRequest, User
from ..schemas import ServiceRequestCreate

router = APIRouter(prefix="/requests", tags=["Service Requests"])

logger = logging.getLogger(__name__)


@router.post("/", status_code=201)
def create_service_request(request: ServiceRequestCreate, db: Session = Depends(get_db)):
    if not db.query(User).filter(User.id == request.user_id).first():
        raise HTTPException(status_code=404, detail=f"User {request.user_id} not found")
    if not db.query(Service).filter(Service.id == request.service_id).first():
        raise HTTPException(status_code=404, detail=f"Service {request.service_id} not found")

    new_request = ServiceRequest(
        user_id=request.user_id,
        service_id=request.service_id,
        notes=request.notes
    )
    try:
        db.add(new_request)
        db.commit()
        db.refresh(new_request)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to create service request")
        raise HTTPException(status_code=500, detail="Failed to create service request")
    return new_request

@router.get("/mockfeed")
def get_mock_feed():
    return [
        {
            "platform": "facebook",
            "content": "We love our community at Golden Healthcare!",
            "date": "2026-04-01"
        },
        {
            "platform": "instagram",
            "content": "Compassionate care every day ❤️",
            "date": "2026-04-02"
        },
        {
            "platform": "twitter",
            "content": "Now offering transportation assistance services!",
            "date": "2026-04-03"
        }
    ]

@router.get("/")
def get_requests(db: Session = Depends(get_db)):
    return db.query(ServiceRequest).all()
