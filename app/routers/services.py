import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Service
from ..schemas import ServiceCreate

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/services")
def get_services(db: Session = Depends(get_db)):
    return db.query(Service).all()


@router.post("/services", status_code=201)
def create_service(service: ServiceCreate, db: Session = Depends(get_db)):
    new_service = Service(
        name=service.name,
        description=service.description,
        price=service.price
    )
    try:
        db.add(new_service)
        db.commit()
        db.refresh(new_service)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to create service")
        raise HTTPException(status_code=500, detail="Failed to create service")
    return new_service
