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