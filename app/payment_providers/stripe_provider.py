import stripe

from .. import config
from .base import (
    CANCELED,
    NEXT_CLIENT_CONFIRM,
    PAID,
    PENDING,
    REQUIRES_ACTION,
    PaymentProvider,
    ProviderError,
    ProviderEvent,
    ProviderIntent,
    ProviderNotConfigured,
    WebhookVerificationError,
)

_INTENT_STATUS = {
    "succeeded": PAID,
    "canceled": CANCELED,
    "requires_confirmation": REQUIRES_ACTION,
    "requires_action": REQUIRES_ACTION,
}

# A declined attempt fires payment_failed but the intent stays usable for a retry,
# so it must not settle the payment; only cancellation does.
_EVENT_STATUS = {
    "payment_intent.succeeded": PAID,
    "payment_intent.payment_failed": PENDING,
    "payment_intent.canceled": CANCELED,
}


class StripeProvider(PaymentProvider):
    name = "stripe"

    def ensure_configured(self) -> None:
        if not config.STRIPE_SECRET_KEY or not config.STRIPE_PUBLISHABLE_KEY:
            raise ProviderNotConfigured("Stripe keys are not set")
        stripe.api_key = config.STRIPE_SECRET_KEY

    def _to_intent(self, intent) -> ProviderIntent:
        return ProviderIntent(
            transaction_id=intent.id,
            status=_INTENT_STATUS.get(intent.status, PENDING),
            client_secret=intent.client_secret,
            client_config={"publishable_key": config.STRIPE_PUBLISHABLE_KEY},
            next_action=NEXT_CLIENT_CONFIRM,
        )

    def create_intent(self, *, amount_cents, currency, metadata, idempotency_key) -> ProviderIntent:
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                payment_method_types=["card"],
                metadata=metadata,
                idempotency_key=idempotency_key,
            )
        except stripe.StripeError as exc:
            raise ProviderError(str(exc)) from exc
        return self._to_intent(intent)

    def retrieve(self, transaction_id: str) -> ProviderIntent:
        try:
            intent = stripe.PaymentIntent.retrieve(transaction_id)
        except stripe.StripeError as exc:
            raise ProviderError(str(exc)) from exc
        return self._to_intent(intent)

    def parse_webhook(self, body: bytes, headers: dict) -> ProviderEvent | None:
        if not config.STRIPE_WEBHOOK_SECRET:
            raise ProviderNotConfigured("Stripe webhook secret is not set")
        try:
            event = stripe.Webhook.construct_event(
                body, headers.get("stripe-signature", ""), config.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WebhookVerificationError(str(exc)) from exc
        status = _EVENT_STATUS.get(event["type"])
        if status is None:
            return None
        obj = event["data"]["object"]
        amount = obj.get("amount_received") if status == PAID else None
        return ProviderEvent(transaction_id=obj["id"], status=status, amount_cents=amount)
