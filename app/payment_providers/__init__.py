from .. import config
from .base import PaymentProvider, ProviderNotConfigured
from .mock_provider import MockProvider
from .stripe_provider import StripeProvider

# Register a new processor here (and nowhere else on the backend).
PROVIDERS: dict[str, type[PaymentProvider]] = {
    StripeProvider.name: StripeProvider,
    MockProvider.name: MockProvider,
}


def get_provider(name: str | None = None) -> PaymentProvider:
    """Return the named adapter, defaulting to the configured PAYMENT_PROVIDER."""
    name = name or config.PAYMENT_PROVIDER
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ProviderNotConfigured(f"Unknown payment provider: {name}")
