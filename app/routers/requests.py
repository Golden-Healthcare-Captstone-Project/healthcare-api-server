import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..rate_limit import limiter
from ..models import Service, ServiceRequest, User
from ..permissions import (
    Permission,
    can_access_owner,
    has_permission,
    linked_client_ids,
    require_permission,
)
from ..schemas import RequestStatusUpdate, ServiceRequestCreate

router = APIRouter(prefix="/requests", tags=["Service Requests"])

logger = logging.getLogger(__name__)


@router.post("/", status_code=201)
@limiter.limit("20/minute")
def create_service_request(
    request: Request,
    payload: ServiceRequestCreate,
    current_user: User = Depends(require_permission(Permission.CREATE_REQUEST)),
    db: Session = Depends(get_db),
):
    # user_id is who the request is for: the caller, or a client they are linked to.
    if not can_access_owner(db, current_user, payload.user_id):
        raise HTTPException(status_code=403, detail="You cannot create requests for that account")
    if not db.query(User).filter(User.id == payload.user_id).first():
        raise HTTPException(status_code=404, detail=f"User {payload.user_id} not found")
    if not db.query(Service).filter(Service.id == payload.service_id).first():
        raise HTTPException(status_code=404, detail=f"Service {payload.service_id} not found")

    new_request = ServiceRequest(
        user_id=payload.user_id,
        service_id=payload.service_id,
        notes=payload.notes
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
def get_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if has_permission(current_user, Permission.VIEW_ALL_REQUESTS):
        return db.query(ServiceRequest).all()
    if not has_permission(current_user, Permission.VIEW_OWN_REQUESTS):
        raise HTTPException(status_code=403, detail="You do not have permission to do that")
    owner_ids = {current_user.id} | linked_client_ids(db, current_user.id)
    return db.query(ServiceRequest).filter(ServiceRequest.user_id.in_(owner_ids)).all()


@router.patch("/{request_id}/status")
@limiter.limit("60/minute")
def update_request_status(
    request: Request,
    request_id: int,
    payload: RequestStatusUpdate,
    _staff: User = Depends(require_permission(Permission.UPDATE_REQUEST_STATUS)),
    db: Session = Depends(get_db),
):
    service_request = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
    if service_request is None:
        raise HTTPException(status_code=404, detail="Service request not found")
    service_request.status = payload.status
    try:
        db.commit()
        db.refresh(service_request)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to update request status request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="Failed to update request")
    return service_request
