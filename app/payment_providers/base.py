from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Normalized statuses every adapter must map its processor's vocabulary onto.
PENDING = "pending"
REQUIRES_ACTION = "requires_action"
PAID = "paid"
FAILED = "failed"
CANCELED = "canceled"
NORMALIZED_STATUSES = {PENDING, REQUIRES_ACTION, PAID, FAILED, CANCELED}

# How the browser must continue after an intent is created.
NEXT_CLIENT_CONFIRM = "client_confirm"  # processor SDK confirms with client_secret
NEXT_REDIRECT = "redirect"  # send the browser to redirect_url
NEXT_NONE = "none"  # nothing to do client-side


class ProviderError(Exception):
    """The processor rejected or failed a request."""


class ProviderNotConfigured(Exception):
    """The selected processor is missing credentials or is not enabled."""


class WebhookVerificationError(Exception):
    """A webhook payload failed signature or format verification."""


@dataclass
class ProviderIntent:
    transaction_id: str
    status: str
    client_secret: str | None = None
    client_config: dict = field(default_factory=dict)
    next_action: str = NEXT_CLIENT_CONFIRM
    redirect_url: str | None = None


@dataclass
class ProviderEvent:
    transaction_id: str
    status: str
    amount_cents: int | None = None  # amount the processor says it received, when known


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def ensure_configured(self) -> None:
        """Raise ProviderNotConfigured when API credentials are missing."""

    @abstractmethod
    def create_intent(
        self, *, amount_cents: int, currency: str, metadata: dict, idempotency_key: str
    ) -> ProviderIntent:
        ...

    @abstractmethod
    def retrieve(self, transaction_id: str) -> ProviderIntent:
        ...

    @abstractmethod
    def parse_webhook(self, body: bytes, headers: dict) -> ProviderEvent | None:
        """Verify and parse a webhook. Return None for events we do not act on.

        Header names are lowercased. Raise WebhookVerificationError for a bad
        signature or payload, ProviderNotConfigured if no secret is set.
        """
