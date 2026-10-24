import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import CaregiverLink, User
from ..permissions import Permission, Role, linked_client_ids, permissions_for, require_permission
from ..rate_limit import limiter
from ..schemas import CaregiverLinkCreate, RoleUpdate, UserCreate

router = APIRouter(tags=["Accounts"])

logger = logging.getLogger(__name__)

# Sign-in is not built yet; this value can never match a real password hash.
UNUSABLE_PASSWORD_HASH = "!"


def _account(user: User) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "permissions": sorted(permissions_for(user.role)),
    }


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception(detail)
        raise HTTPException(status_code=500, detail=detail)


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return _account(user)


@router.get("/me/linked-clients")
def get_linked_clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Older adults a caregiver may act for. Empty for every other account type."""
    if user.role != Role.CAREGIVER:
        return []
    ids = linked_client_ids(db, user.id)
    if not ids:
        return []
    clients = db.query(User).filter(User.id.in_(ids)).order_by(User.first_name, User.last_name).all()
    return [{"id": c.id, "first_name": c.first_name, "last_name": c.last_name} for c in clients]


@router.get("/users")
def list_users(_admin: User = Depends(require_permission(Permission.MANAGE_USERS)), db: Session = Depends(get_db)):
    return [_account(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", status_code=201)
@limiter.limit("20/minute")
def create_user(
    request: Request,
    payload: UserCreate,
    _admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    user = User(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=payload.email.lower(),
        password_hash=UNUSABLE_PASSWORD_HASH,
        role=payload.role,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to create user")
        raise HTTPException(status_code=500, detail="Failed to create account")
    return _account(user)


@router.patch("/users/{user_id}/role")
@limiter.limit("20/minute")
def change_role(
    request: Request,
    user_id: int,
    payload: RoleUpdate,
    _admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role == Role.ADMIN and payload.role != Role.ADMIN:
        admins = db.query(User).filter(User.role == Role.ADMIN).count()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last admin")

    user.role = payload.role
    _commit(db, "Failed to change role")
    db.refresh(user)
    return _account(user)


@router.get("/caregiver-links")
def list_links(_admin: User = Depends(require_permission(Permission.MANAGE_LINKS)), db: Session = Depends(get_db)):
    return [
        {
            "id": link.id,
            "caregiver_id": link.caregiver_id,
            "older_adult_id": link.older_adult_id,
            "relationship_note": link.relationship_note,
        }
        for link in db.query(CaregiverLink).order_by(CaregiverLink.id).all()
    ]


@router.post("/caregiver-links", status_code=201)
@limiter.limit("20/minute")
def create_link(
    request: Request,
    payload: CaregiverLinkCreate,
    _admin: User = Depends(require_permission(Permission.MANAGE_LINKS)),
    db: Session = Depends(get_db),
):
    caregiver = db.query(User).filter(User.id == payload.caregiver_id).first()
    older_adult = db.query(User).filter(User.id == payload.older_adult_id).first()
    if caregiver is None or older_adult is None:
        raise HTTPException(status_code=404, detail="User not found")
    if caregiver.role != Role.CAREGIVER:
        raise HTTPException(status_code=400, detail="The caregiver account must have the caregiver role")
    if older_adult.role != Role.OLDER_ADULT:
        raise HTTPException(status_code=400, detail="The linked account must have the older_adult role")

    link = CaregiverLink(
        caregiver_id=caregiver.id,
        older_adult_id=older_adult.id,
        relationship_note=payload.relationship_note,
    )
    try:
        db.add(link)
        db.commit()
        db.refresh(link)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="These accounts are already linked")
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to create caregiver link")
        raise HTTPException(status_code=500, detail="Failed to create link")
    return {
        "id": link.id,
        "caregiver_id": link.caregiver_id,
        "older_adult_id": link.older_adult_id,
        "relationship_note": link.relationship_note,
    }


@router.delete("/caregiver-links/{link_id}", status_code=204)
def delete_link(
    link_id: int,
    _admin: User = Depends(require_permission(Permission.MANAGE_LINKS)),
    db: Session = Depends(get_db),
):
    link = db.query(CaregiverLink).filter(CaregiverLink.id == link_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    _commit(db, "Failed to delete link")
