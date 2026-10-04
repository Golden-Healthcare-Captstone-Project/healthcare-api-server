from pydantic import BaseModel, Field
from typing import Optional


class ServiceRequestCreate(BaseModel):
    user_id: int
    service_id: int
    notes: Optional[str] = None


class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    price: float = Field(..., ge=0)


class PaymentIntentCreate(BaseModel):
    service_request_id: int = Field(..., ge=1)

class PostCreate(BaseModel):
    author_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1, max_length=2000)


class AuthorResponse(BaseModel):
    id: str
    name: str
    avatarUrl: str = ""
    role: Optional[str] = None


class PostResponse(BaseModel):
    id: str
    author: AuthorResponse
    text: str
    createdAt: str
    likeCount: int = 0
    commentCount: int = 0
    shareCount: int = 0
    likedByCurrentUser: bool = False


class FeedResponse(BaseModel):
    posts: list[PostResponse]
    page: int
    limit: int
    total: int
    hasNext: bool