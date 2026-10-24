from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Literal, Optional

RoleName = Literal["older_adult", "caregiver", "provider", "admin"]
RequestStatus = Literal["pending", "approved", "rejected", "completed"]


class ServiceRequestCreate(BaseModel):
    user_id: int
    service_id: int
    notes: Optional[str] = None


class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    price: float = Field(..., ge=0)


class RequestStatusUpdate(BaseModel):
    status: RequestStatus


class UserCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    role: RoleName


class RoleUpdate(BaseModel):
    role: RoleName


class CaregiverLinkCreate(BaseModel):
    caregiver_id: int = Field(..., ge=1)
    older_adult_id: int = Field(..., ge=1)
    relationship_note: Optional[str] = Field(default=None, max_length=100)


class PaymentIntentCreate(BaseModel):
    service_request_id: int = Field(..., ge=1)

class PostCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Post text cannot be empty")

        return value

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Post text cannot be empty")

        return value

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