import hmac
import json
import logging
import uuid

from .. import config
from .base import (
    NEXT_CLIENT_CONFIRM,
    NORMALIZED_STATUSES,
    PENDING,
    PaymentProvider,
    ProviderError,
    ProviderEvent,
    ProviderIntent,
    ProviderNotConfigured,
    WebhookVerificationError,
)


logger = logging.getLogger(__name__)


class MockProvider(PaymentProvider):
    """Dev/test processor. Outcomes are driven through its webhook.

    Only usable when PAYMENT_PROVIDER=mock, so it can never be reached in a
    deployment that is configured for a real processor.
    """

    name = "mock"
    _intents: dict[str, str] = {}
    _amounts: dict[str, int] = {}

    _warned = False

    def _require_enabled(self) -> None:
        if config.PAYMENT_PROVIDER != "mock":
            raise ProviderNotConfigured("Mock provider is disabled")
        # Fail closed: the mock settles payments for anyone who knows its secret.
        if config.APP_ENV == "production":
            raise ProviderNotConfigured("Mock provider cannot run in production")
        if not MockProvider._warned:
            MockProvider._warned = True
            logger.warning("Mock payment provider is ENABLED. Development use only.")

    def ensure_configured(self) -> None:
        self._require_enabled()

    def _to_intent(self, transaction_id: str) -> ProviderIntent:
        return ProviderIntent(
            transaction_id=transaction_id,
            status=self._intents[transaction_id],
            client_secret=f"mock_secret_{transaction_id}",
            client_config={"mock": True},
            next_action=NEXT_CLIENT_CONFIRM,
        )

    def create_intent(self, *, amount_cents, currency, metadata, idempotency_key) -> ProviderIntent:
        transaction_id = f"mock_{uuid.uuid4().hex[:16]}"
        self._intents[transaction_id] = PENDING
        self._amounts[transaction_id] = amount_cents
        return self._to_intent(transaction_id)

    def retrieve(self, transaction_id: str) -> ProviderIntent:
        if transaction_id not in self._intents:
            raise ProviderError("Unknown mock intent")
        return self._to_intent(transaction_id)

    def parse_webhook(self, body: bytes, headers: dict) -> ProviderEvent | None:
        self._require_enabled()
        if not hmac.compare_digest(headers.get("x-mock-signature", ""), config.MOCK_WEBHOOK_SECRET):
            raise WebhookVerificationError("Bad mock signature")
        try:
            data = json.loads(body)
            transaction_id, status = data["transaction_id"], data["status"]
            amount_cents = data.get("amount_cents")
        except (ValueError, KeyError, TypeError) as exc:
            raise WebhookVerificationError("Malformed mock payload") from exc
        if status not in NORMALIZED_STATUSES:
            raise WebhookVerificationError("Unknown status")
        # Like a real processor, only record a payment for the amount it was created with.
        if amount_cents is None or amount_cents == self._amounts.get(transaction_id):
            self._intents[transaction_id] = status
        return ProviderEvent(transaction_id=transaction_id, status=status, amount_cents=amount_cents)
