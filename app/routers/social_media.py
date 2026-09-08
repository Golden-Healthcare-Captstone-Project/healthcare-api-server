import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..meta_client import graph_get, MetaGraphAPIError, MetaRateLimitedError
from ..models import MetaConnection

router = APIRouter()

logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/social-feed")
def get_social_feed(db: Session = Depends(get_db)):
    conn = db.query(MetaConnection).first()
    if not conn or not conn.page_id or not conn.page_access_token:
        return {
            "status": "blocked",
            "message": "Meta account not connected"
        }

    url = f"https://graph.facebook.com/v19.0/{conn.page_id}/posts"
    params = {"access_token": conn.page_access_token}

    try:
        return graph_get(url, params)
    except MetaRateLimitedError:
        logger.warning("Social feed fetch rate-limited for page_id=%s", conn.page_id)
        raise HTTPException(status_code=429, detail="Meta is rate-limiting requests, try again shortly")
    except MetaGraphAPIError as e:
        logger.error("Social feed fetch failed: status=%s error_code=%s", e.status_code, e.meta_error_code)
        raise HTTPException(status_code=502, detail="Failed to fetch social feed from Meta")
