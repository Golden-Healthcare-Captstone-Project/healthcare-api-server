import logging
import secrets
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import config
from ..database import SessionLocal
from ..models import MetaConnection

router = APIRouter(prefix="/auth/meta", tags=["Meta Auth"])

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
STATE_COOKIE_NAME = "meta_oauth_state"
META_SCOPES = "pages_show_list,pages_read_engagement,instagram_basic,instagram_manage_insights,business_management"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin_secret(secret: str = None):
    if not config.META_ADMIN_SECRET or secret != config.META_ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing secret")


def get_connection(db: Session) -> MetaConnection:
    conn = db.query(MetaConnection).first()
    if conn is None:
        conn = MetaConnection(id=1)
        db.add(conn)
    return conn


def exchange_long_lived_token(short_lived_or_current_token: str) -> dict:
    response = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": config.META_APP_ID,
            "client_secret": config.META_APP_SECRET,
            "fb_exchange_token": short_lived_or_current_token,
        },
    )
    response.raise_for_status()
    return response.json()


def fetch_page_and_ig_info(user_access_token: str) -> dict:
    accounts_response = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={"access_token": user_access_token},
    )
    accounts_response.raise_for_status()
    accounts = accounts_response.json().get("data", [])
    if not accounts:
        return {}

    page = accounts[0]
    page_id = page.get("id")
    page_access_token = page.get("access_token")

    ig_business_account_id = None
    if page_id and page_access_token:
        ig_response = requests.get(
            f"{GRAPH_API_BASE}/{page_id}",
            params={"fields": "instagram_business_account", "access_token": page_access_token},
        )
        if ig_response.ok:
            ig_business_account_id = (
                ig_response.json().get("instagram_business_account", {}).get("id")
            )

    return {
        "page_id": page_id,
        "page_name": page.get("name"),
        "page_access_token": page_access_token,
        "ig_business_account_id": ig_business_account_id,
    }


@router.get("/login")
def meta_login(secret: str = None):
    require_admin_secret(secret)

    state = secrets.token_urlsafe(16)
    auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={config.META_APP_ID}"
        f"&redirect_uri={config.META_REDIRECT_URI}"
        f"&state={state}"
        f"&scope={META_SCOPES}"
    )

    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        max_age=300,
    )
    return response


@router.get("/callback")
def meta_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        raise HTTPException(status_code=400, detail="Invalid or missing state")

    short_lived_response = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "client_id": config.META_APP_ID,
            "redirect_uri": config.META_REDIRECT_URI,
            "client_secret": config.META_APP_SECRET,
            "code": code,
        },
    )
    short_lived_response.raise_for_status()
    short_lived_token = short_lived_response.json().get("access_token")

    long_lived_data = exchange_long_lived_token(short_lived_token)
    long_lived_token = long_lived_data.get("access_token")
    expires_in = long_lived_data.get("expires_in")

    page_and_ig_info = fetch_page_and_ig_info(long_lived_token)

    conn = get_connection(db)
    conn.user_access_token = long_lived_token
    if expires_in:
        conn.user_token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    conn.page_id = page_and_ig_info.get("page_id")
    conn.page_name = page_and_ig_info.get("page_name")
    conn.page_access_token = page_and_ig_info.get("page_access_token")
    conn.ig_business_account_id = page_and_ig_info.get("ig_business_account_id")

    db.commit()

    response = {
        "status": "connected",
        "page_name": conn.page_name,
        "ig_connected": bool(conn.ig_business_account_id),
    }
    return response


@router.post("/refresh")
def meta_refresh(secret: str = None, db: Session = Depends(get_db)):
    require_admin_secret(secret)

    conn = db.query(MetaConnection).first()
    if conn is None or not conn.user_access_token:
        return {"status": "not_connected"}

    if conn.user_token_expires_at and conn.user_token_expires_at - datetime.utcnow() > timedelta(days=7):
        return {"status": "not_due"}

    try:
        long_lived_data = exchange_long_lived_token(conn.user_access_token)
        new_token = long_lived_data.get("access_token")
        expires_in = long_lived_data.get("expires_in")
        if not new_token:
            raise ValueError("No access_token in refresh response")

        page_and_ig_info = fetch_page_and_ig_info(new_token)

        conn.user_access_token = new_token
        if expires_in:
            conn.user_token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        if page_and_ig_info.get("page_id"):
            conn.page_id = page_and_ig_info.get("page_id")
            conn.page_name = page_and_ig_info.get("page_name")
            conn.page_access_token = page_and_ig_info.get("page_access_token")
            conn.ig_business_account_id = page_and_ig_info.get("ig_business_account_id")

        db.commit()
        return {"status": "refreshed"}
    except Exception as e:
        db.rollback()
        logger.error("Meta token refresh failed: %s", type(e).__name__)
        return {"status": "error"}
