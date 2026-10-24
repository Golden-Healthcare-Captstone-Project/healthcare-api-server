"""Account types, permissions, and ownership rules.

Who is calling comes from `get_current_user` (currently the X-User-Id
placeholder in app/auth.py). Everything here builds on that one dependency, so
replacing it with real authentication does not touch these rules.
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .models import CaregiverLink, User


class Role:
    OLDER_ADULT = "older_adult"
    CAREGIVER = "caregiver"
    PROVIDER = "provider"
    ADMIN = "admin"


class Permission:
    CREATE_REQUEST = "create_request"
    VIEW_OWN_REQUESTS = "view_own_requests"
    VIEW_ALL_REQUESTS = "view_all_requests"
    UPDATE_REQUEST_STATUS = "update_request_status"
    MAKE_PAYMENT = "make_payment"
    VIEW_PAYMENT = "view_payment"
    VIEW_ALL_PAYMENTS = "view_all_payments"
    MANAGE_SERVICES = "manage_services"
    MANAGE_USERS = "manage_users"
    MANAGE_LINKS = "manage_links"


_CLIENT = frozenset(
    {
        Permission.CREATE_REQUEST,
        Permission.VIEW_OWN_REQUESTS,
        Permission.MAKE_PAYMENT,
        Permission.VIEW_PAYMENT,
    }
)

# The single place that says what each account type may do.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.OLDER_ADULT: _CLIENT,
    Role.CAREGIVER: _CLIENT,
    Role.PROVIDER: frozenset({Permission.VIEW_ALL_REQUESTS, Permission.UPDATE_REQUEST_STATUS}),
    Role.ADMIN: frozenset(
        {
            Permission.VIEW_ALL_REQUESTS,
            Permission.UPDATE_REQUEST_STATUS,
            Permission.VIEW_PAYMENT,
            Permission.VIEW_ALL_PAYMENTS,
            Permission.MANAGE_SERVICES,
            Permission.MANAGE_USERS,
            Permission.MANAGE_LINKS,
        }
    ),
}


def permissions_for(role: str | None) -> frozenset[str]:
    """Unknown or legacy role values get nothing (deny by default)."""
    return ROLE_PERMISSIONS.get(role or "", frozenset())


def has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for(user.role)


def require_permission(permission: str):
    """Dependency: the caller must hold `permission`; returns the caller."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail="You do not have permission to do that")
        return user

    return dependency


def linked_client_ids(db: Session, caregiver_id: int) -> set[int]:
    rows = db.query(CaregiverLink.older_adult_id).filter(CaregiverLink.caregiver_id == caregiver_id).all()
    return {row[0] for row in rows}


def can_access_owner(db: Session, user: User, owner_id: int) -> bool:
    """True when `user` is the owner, or a caregiver linked to the owner."""
    if user.id == owner_id:
        return True
    if user.role != Role.CAREGIVER:
        return False
    return (
        db.query(CaregiverLink.id)
        .filter(CaregiverLink.caregiver_id == user.id, CaregiverLink.older_adult_id == owner_id)
        .first()
        is not None
    )
