from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import User


def get_current_user(
    x_user_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if x_user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    user = db.query(User).filter(User.id == x_user_id).first()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid user",
        )

    return user