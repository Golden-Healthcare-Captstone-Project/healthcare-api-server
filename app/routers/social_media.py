import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..meta_client import graph_get, MetaGraphAPIError, MetaRateLimitedError
from ..models import MetaConnection, Post, User
from ..schemas import PostCreate, PostResponse, FeedResponse

from ..auth import get_current_user

router = APIRouter()

logger = logging.getLogger(__name__)

def format_post(post: Post) -> PostResponse:
    return PostResponse(
        id=str(post.id),
        author={
            "id": str(post.author.id),
            "name": f"{post.author.first_name} {post.author.last_name}",
            "avatarUrl": "",
            "role": post.author.role,
        },
        text=post.text,
        createdAt=post.created_at.isoformat(),
        likeCount=0,
        commentCount=0,
        shareCount=0,
        likedByCurrentUser=False,
    )


@router.get("/social-feed")
def get_social_feed(db: Session = Depends(get_db)):
    conn = db.query(MetaConnection).first()
    if not conn or not conn.page_id or not conn.page_access_token:
        raise HTTPException(status_code=409, detail="Meta account not connected")

    url = f"https://graph.facebook.com/v19.0/{conn.page_id}/posts"
    params = {"access_token": conn.page_access_token}

    
    try:
        return graph_get(url, params)
    except MetaRateLimitedError:
        logger.warning("Social feed fetch rate-limited for page_id=%s", conn.page_id)
        raise HTTPException(
            status_code=429,
            detail="Meta is rate-limiting requests, try again shortly"
        )
    except MetaGraphAPIError as e:
        logger.error(
            "Social feed fetch failed: status=%s error_code=%s",
            e.status_code,
            e.meta_error_code
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch social feed from Meta"
        )
    
@router.get("/feed", response_model=FeedResponse)
def get_feed(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    total = db.query(Post).count()

    posts = (
        db.query(Post)
        .order_by(Post.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return FeedResponse(
        posts=[format_post(post) for post in posts],
        page=page,
        limit=limit,
        total=total,
        hasNext=page * limit < total,
    )

@router.post("/feed", response_model=PostResponse, status_code=201)
def create_post(
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = Post(
        author_id=current_user.id,
        text=post_data.text,
    )

    db.add(post)
    db.commit()
    db.refresh(post)

    return format_post(post)