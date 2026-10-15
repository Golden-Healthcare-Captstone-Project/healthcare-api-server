import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..rate_limit import limiter
from ..models import Payment, Service, ServiceRequest
from ..payment_providers import get_provider
from ..payment_providers.base import (
    CANCELED,
    FAILED,
    PAID,
    PENDING,
    REQUIRES_ACTION,
    PaymentProvider,
    ProviderError,
    ProviderIntent,
    ProviderNotConfigured,
    WebhookVerificationError,
)
from ..schemas import PaymentIntentCreate

router = APIRouter(prefix="/payments", tags=["Payments"])

logger = logging.getLogger(__name__)

MIN_CHARGE_CENTS = 50
REUSABLE_INTENT_STATUSES = {PENDING, REQUIRES_ACTION}
MAX_WEBHOOK_BYTES = 1_000_000


def _amount_cents(price: float | None) -> int:
    if price is None:
        raise HTTPException(status_code=400, detail="Service has no price")
    return int(round(float(price) * 100))


def _configured_provider(name: str | None = None) -> PaymentProvider:
    try:
        provider = get_provider(name)
        provider.ensure_configured()
    except ProviderNotConfigured:
        logger.warning("Payment provider %s is not configured", name or config.PAYMENT_PROVIDER)
        raise HTTPException(status_code=503, detail="Payment gateway is not configured")
    return provider


def _apply_status(payment: Payment, status: str) -> None:
    """Settle a payment. Paid is final; money received wins over a recorded failure."""
    if payment.status == "paid":
        return
    if status == PAID:
        if payment.status == "failed":
            logger.warning("payment_id=%s was failed but the processor reports paid", payment.id)
        payment.status = "paid"
    elif status in (FAILED, CANCELED) and payment.status != "failed":
        payment.status = "failed"


def _commit(db: Session, payment: Payment, detail: str) -> None:
    try:
        db.commit()
        db.refresh(payment)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("%s payment_id=%s", detail, payment.id)
        raise HTTPException(status_code=500, detail=detail)


def _intent_payload(payment: Payment, intent: ProviderIntent) -> dict:
    return {
        "payment_id": payment.id,
        "provider": payment.provider,
        "status": intent.status,
        "next_action": intent.next_action,
        "client_secret": intent.client_secret,
        "redirect_url": intent.redirect_url,
        "client_config": intent.client_config,
        "amount": payment.amount,
        "currency": payment.currency,
    }


def _payment_payload(payment: Payment) -> dict:
    # Unauthenticated and keyed by a sequential id, so expose only what the UI needs.
    return {
        "payment_id": payment.id,
        "provider": payment.provider,
        "status": payment.status,
        "amount": payment.amount,
        "currency": payment.currency,
    }


@router.post("/intent", status_code=201)
@limiter.limit("10/minute")
def create_payment_intent(request: Request, payload: PaymentIntentCreate, db: Session = Depends(get_db)):
    # Row lock serializes concurrent intents for one request (no-op on SQLite),
    # so two tabs cannot both create a charge.
    service_request = (
        db.query(ServiceRequest)
        .filter(ServiceRequest.id == payload.service_request_id)
        .with_for_update()
        .first()
    )
    if service_request is None:
        raise HTTPException(status_code=404, detail="Service request not found")

    service = db.query(Service).filter(Service.id == service_request.service_id).first()
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    amount_cents = _amount_cents(service.price)
    if amount_cents < MIN_CHARGE_CENTS:
        raise HTTPException(status_code=400, detail="Service price must be at least $0.50")

    provider = _configured_provider()

    existing = (
        db.query(Payment)
        .filter(Payment.service_request_id == service_request.id)
        .order_by(Payment.id.desc())
        .first()
    )
    if existing and existing.status == "paid":
        raise HTTPException(status_code=409, detail="This request has already been paid")

    # Only reuse an open intent created by the processor that is active now.
    if (
        existing
        and existing.status == "pending"
        and existing.transaction_id
        and existing.provider == provider.name
    ):
        try:
            intent = provider.retrieve(existing.transaction_id)
        except ProviderError:
            logger.exception("Failed to reuse payment intent payment_id=%s", existing.id)
            raise HTTPException(status_code=502, detail="Payment gateway request failed")
        if intent.status in REUSABLE_INTENT_STATUSES and (intent.client_secret or intent.redirect_url):
            return _intent_payload(existing, intent)

    payment = Payment(
        user_id=service_request.user_id,
        service_request_id=service_request.id,
        amount=service.price,
        status="pending",
        provider=provider.name,
        currency=config.PAYMENT_CURRENCY,
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
        intent = provider.create_intent(
            amount_cents=amount_cents,
            currency=payment.currency,
            metadata={
                "payment_id": str(payment.id),
                "service_request_id": str(service_request.id),
            },
            idempotency_key=f"payment-{payment.id}",
        )
    except ProviderError:
        payment.status = "failed"
        db.commit()
        logger.exception("Provider %s create_intent failed payment_id=%s", provider.name, payment.id)
        raise HTTPException(status_code=502, detail="Payment gateway request failed")

    payment.transaction_id = intent.transaction_id
    _commit(db, payment, "Failed to start payment")

    return _intent_payload(payment, intent)


@router.post("/webhook/{provider_name}")
@limiter.limit("300/minute")
async def payment_webhook(request: Request, provider_name: str, db: Session = Depends(get_db)):
    try:
        provider = get_provider(provider_name)
    except ProviderNotConfigured:
        raise HTTPException(status_code=404, detail="Unknown payment provider")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    # Raw bytes: signatures are computed over the exact body.
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    try:
        event = provider.parse_webhook(body, dict(request.headers))
    except ProviderNotConfigured:
        raise HTTPException(status_code=503, detail="Payment webhook is not configured")
    except WebhookVerificationError:
        logger.warning("Rejected %s webhook: verification failed", provider.name)
        raise HTTPException(status_code=400, detail="Invalid webhook")

    if event is None:
        return {"received": True}

    payment = (
        db.query(Payment)
        .filter(Payment.provider == provider.name, Payment.transaction_id == event.transaction_id)
        .first()
    )
    if payment is None:
        # Acknowledge so the processor does not retry events we cannot match.
        logger.warning("%s webhook for unknown transaction %s", provider.name, event.transaction_id)
        return {"received": True}

    if (
        event.status == PAID
        and event.amount_cents is not None
        and event.amount_cents != _amount_cents(payment.amount)
    ):
        # Acknowledge but do not settle: the processor received a different amount.
        logger.error(
            "%s paid event amount mismatch payment_id=%s expected=%s got=%s",
            provider.name, payment.id, _amount_cents(payment.amount), event.amount_cents,
        )
        return {"received": True}

    _apply_status(payment, event.status)
    _commit(db, payment, "Failed to record payment")
    return {"received": True}


@router.get("/{payment_id}")
@limiter.limit("30/minute")
def get_payment(request: Request, payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status == "pending" and payment.transaction_id:
        _reconcile(db, payment, strict=False)

    return _payment_payload(payment)


@router.post("/{payment_id}/complete")
@limiter.limit("10/minute")
def complete_payment(request: Request, payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None or not payment.transaction_id:
        raise HTTPException(status_code=404, detail="Payment not found")

    _reconcile(db, payment, strict=True)
    return _payment_payload(payment)


def _reconcile(db: Session, payment: Payment, *, strict: bool) -> None:
    """Pull the latest status from the payment's own processor.

    strict=False (read path) falls back to the stored status if the processor
    is unreachable or unconfigured; strict=True surfaces those as HTTP errors.
    """
    try:
        provider = get_provider(payment.provider)
        provider.ensure_configured()
        intent = provider.retrieve(payment.transaction_id)
    except (ProviderNotConfigured, ProviderError) as exc:
        if not strict:
            logger.warning("Could not refresh payment_id=%s: %s", payment.id, exc)
            return
        if isinstance(exc, ProviderNotConfigured):
            raise HTTPException(status_code=503, detail="Payment gateway is not configured")
        logger.exception("Failed to retrieve payment payment_id=%s", payment.id)
        raise HTTPException(status_code=502, detail="Payment gateway request failed")

    _apply_status(payment, intent.status)
    _commit(db, payment, "Failed to record payment")
