# File: models.py
# This file defines structure and validation rules for the database

from pydantic import BaseModel, Field, EmailStr, field_validator
from datetime import date
import re
#class with fields to represent a potential database schema
class ServiceRequest(BaseModel):
    patient_name : str = Field(..., min_length=2, max_length=100, description="Full name of the patient")
    patient_email : EmailStr
    patient_phone : str = Field(..., pattern=r"^\+?1?\d{9,15}$", description="Phone number of the patient")
    service_type : str = Field(..., description="Type of service requested")
    requested_date : date
    description : str = Field(..., max_length=500, description="Description of the request")

    @field_validator('requested_date')
    def must_be_future_date(cls, value):
        #Makes sure date is in the future
        if value < date.today():
            raise ValueError('Requested date must be in the future')
        return value
    
    @field_validator('description')
    @classmethod
    def sanitize_description(cls, value):
        # Preventing some XSS through HTML tag stripping
        cleaned_text = re.sub(r'<[^>]*?>', '', value)
        return cleaned_text.strip()
    