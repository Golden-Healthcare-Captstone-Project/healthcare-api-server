from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # older_adult, caregiver, admin, provider
    created_at = Column(DateTime, default=datetime.utcnow)

    service_requests = relationship("ServiceRequest", back_populates="user")
    payments = relationship("Payment", back_populates="user")


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String)
    price = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    service_requests = relationship("ServiceRequest", back_populates="service")


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    status = Column(String, default="pending")  # pending, approved, rejected, completed
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="service_requests")
    service = relationship("Service", back_populates="service_requests")
    payment = relationship("Payment", back_populates="service_request", uselist=False)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="pending")  # pending, paid, failed
    transaction_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments")
    service_request = relationship("ServiceRequest", back_populates="payment")