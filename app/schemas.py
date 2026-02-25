from pydantic import BaseModel
from typing import Optional


class ServiceRequestCreate(BaseModel):
    user_id: int
    service_id: int
    notes: Optional[str] = None