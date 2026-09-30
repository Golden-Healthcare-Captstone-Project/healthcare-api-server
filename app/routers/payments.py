import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import Payment, Service, ServiceRequest
from ..schemas import PaymentIntentCreate

router = APIRouter(prefix="/payments", tags=["Payments"])

logger = logging.getLogger(__name__)

MIN_CHARGE_CENTS = 50
REUSABLE_INTENT_STATUSES = {
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
}


def _configure_stripe() -> None:
    if not config.STRIPE_SECRET_KEY or not config.STRIPE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Payment gateway is not configured")
    stripe.api_key = config.STRIPE_SECRET_KEY


def _amount_cents(price: float | None) -> int:
    if price is None:
        raise HTTPException(status_code=400, detail="Service has no price")
    return int(round(float(price) * 100))


def _intent_payload(payment: Payment, intent) -> dict:
    return {
        "payment_id": payment.id,
        "client_secret": intent.client_secret,
        "publishable_key": config.STRIPE_PUBLISHABLE_KEY,
        "amount": payment.amount,
        "currency": "usd",
    }


@router.post("/intent", status_code=201)
def create_payment_intent(payload: PaymentIntentCreate, db: Session = Depends(get_db)):
    service_request = db.query(ServiceRequest).filter(ServiceRequest.id == payload.service_request_id).first()
    if service_request is None:
        raise HTTPException(status_code=404, detail="Service request not found")

    service = db.query(Service).filter(Service.id == service_request.service_id).first()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    amount_cents = _amount_cents(service.price)
    if amount_cents < MIN_CHARGE_CENTS:
        raise HTTPException(status_code=400, detail="Service price must be at least $0.50")

    _configure_stripe()

    existing = (
        db.query(Payment)
        .filter(Payment.service_request_id == service_request.id)
        .order_by(Payment.id.desc())
        .first()
    )
    if existing and existing.status == "paid":
        raise HTTPException(status_code=409, detail="This request has already been paid")

    if existing and existing.status == "pending" and existing.transaction_id:
        try:
            intent = stripe.PaymentIntent.retrieve(existing.transaction_id)
        except stripe.error.StripeError:
            logger.exception("Failed to reuse payment intent payment_id=%s", existing.id)
            raise HTTPException(status_code=502, detail="Payment gateway request failed")
        if intent.status in REUSABLE_INTENT_STATUSES and intent.client_secret:
            return _intent_payload(existing, intent)

    payment = Payment(
        user_id=service_request.user_id,
        service_request_id=service_request.id,
        amount=service.price,
        status="pending",
    )
    try:
        db.add(payment)
        db.commit()
        db.refresh(payment)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to store pending payment for request_id=%s", service_request.id)
        raise HTTPException(status_code=500, detail="Failed to start payment")

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            payment_method_types=["card"],
            metadata={
                "payment_id": str(payment.id),
                "service_request_id": str(service_request.id),
            },
        )
    except stripe.error.StripeError:
        payment.status = "failed"
        db.commit()
        logger.exception("Stripe PaymentIntent.create failed payment_id=%s", payment.id)
        raise HTTPException(status_code=502, detail="Payment gateway request failed")

    payment.transaction_id = intent.id
    try:
        db.commit()
        db.refresh(payment)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to store payment intent id payment_id=%s", payment.id)
        raise HTTPException(status_code=500, detail="Failed to start payment")

    return _intent_payload(payment, intent)


@router.post("/{payment_id}/complete")
def complete_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None or not payment.transaction_id:
        raise HTTPException(status_code=404, detail="Payment not found")

    _configure_stripe()
    try:
        intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
    except stripe.error.StripeError:
        logger.exception("Failed to retrieve payment intent payment_id=%s", payment.id)
        raise HTTPException(status_code=502, detail="Payment gateway request failed")

    if intent.status == "succeeded":
        payment.status = "paid"
    elif intent.status == "canceled":
        payment.status = "failed"

    try:
        db.commit()
        db.refresh(payment)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to update payment status payment_id=%s", payment.id)
        raise HTTPException(status_code=500, detail="Failed to record payment")

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "transaction_id": payment.transaction_id,
        "amount": payment.amount,
    }
