from fastapi import APIRouter
import requests
import os

router = APIRouter()

@router.get("/social-feed")
def get_social_feed():
    page_id = os.getenv("META_PAGE_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")

    if not page_id or not access_token:
        return {
            "status": "blocked",
            "message": "Meta credentials not configured"
        }

    url = f"https://graph.facebook.com/v19.0/{page_id}/posts"
    params = {"access_token": access_token}

    try:
        response = requests.get(url, params=params)
        return response.json()
    except Exception as e:
        return {"error": str(e)}