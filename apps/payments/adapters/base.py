from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdapterResult:
    """
    Normalized return shape every adapter method hands back, so the engine
    and views never need to know which provider they're talking to.
    """

    status: str  # matches PaymentTransaction.Status values
    provider_reference: str = ""
    merchant_request_id: str = ""
    checkout_request_id: str = ""
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentAdapter:
    """
    Base interface every provider adapter implements. The engine only ever
    calls these three methods — everything provider-specific (auth tokens,
    request shapes, callback payload formats) stays inside the adapter.
    """

    def __init__(self, provider):
        self.provider = provider  # apps.payments.models.PaymentProvider instance

    def initiate(self, transaction) -> AdapterResult:
        """Kick off collection for a PaymentTransaction. Must not raise —
        catch provider/network errors and return a FAILED AdapterResult."""
        raise NotImplementedError

    def check_status(self, transaction) -> AdapterResult:
        """Actively poll the provider for the current status of a
        transaction that's still pending/processing."""
        raise NotImplementedError

    def parse_callback(self, payload: dict) -> AdapterResult:
        """Turn a provider's webhook/callback payload into an
        AdapterResult. Does not look up the transaction — the view does
        that using whatever ID this returns in merchant_request_id/
        checkout_request_id."""
        raise NotImplementedError
