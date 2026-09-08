from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import requests

from ..database import SessionLocal
from ..models import MetaConnection

router = APIRouter()


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
        response = requests.get(url, params=params)
        return response.json()
    except Exception as e:
        return {"error": str(e)}
