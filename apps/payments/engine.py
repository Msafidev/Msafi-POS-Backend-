from apps.payments.adapters.registry import get_adapter
from apps.payments.models import PaymentProvider, PaymentTransaction


class PaymentEngine:
    """
    The one thing the rest of the app (views, and eventually the POS
    checkout flow) talks to. Given a business + a provider code, it finds
    that business's own PaymentProvider config, hands it to the matching
    adapter, and returns a PaymentTransaction row — callers never touch
    an adapter directly.

        Business A, provider="kcb"   -> KCB's PaymentProvider row -> BankTerminalAdapter
        Business B, provider="mpesa_stk" -> B's own M-Pesa config -> MpesaSTKAdapter

    Same code path for every tenant and every provider.
    """

    class PaymentEngineError(Exception):
        pass

    @staticmethod
    def charge(*, business, provider_code, amount, sale=None, phone_number="", initiated_by=None):
        try:
            provider_config = PaymentProvider.objects.get(business=business, provider=provider_code, active=True)
        except PaymentProvider.DoesNotExist:
            raise PaymentEngine.PaymentEngineError(
                f"No active '{provider_code}' payment provider configured for this business."
            )

        transaction = PaymentTransaction.objects.create(
            business=business,
            provider=provider_config,
            sale=sale,
            amount=amount,
            phone_number=phone_number,
            initiated_by=initiated_by,
        )

        adapter = get_adapter(provider_config)
        result = adapter.initiate(transaction)

        transaction.status = result.status
        transaction.merchant_request_id = result.merchant_request_id
        transaction.checkout_request_id = result.checkout_request_id
        transaction.provider_reference = result.provider_reference
        transaction.failure_reason = result.failure_reason
        transaction.raw_response = result.raw
        transaction.save()
        return transaction

    @staticmethod
    def refresh_status(transaction):
        """Actively poll the provider for a transaction still in flight."""
        adapter = get_adapter(transaction.provider)
        result = adapter.check_status(transaction)
        transaction.status = result.status
        if result.provider_reference:
            transaction.provider_reference = result.provider_reference
        if result.failure_reason:
            transaction.failure_reason = result.failure_reason
        if result.raw:
            transaction.raw_response = {**transaction.raw_response, "status_check": result.raw}
        transaction.save()
        return transaction

    @staticmethod
    def apply_callback(transaction, payload):
        """Called by the webhook view once it has matched a payload to a transaction row."""
        adapter = get_adapter(transaction.provider)
        result = adapter.parse_callback(payload)
        transaction.status = result.status
        if result.provider_reference:
            transaction.provider_reference = result.provider_reference
        if result.failure_reason:
            transaction.failure_reason = result.failure_reason
        transaction.raw_response = {**transaction.raw_response, "callback": result.raw}
        transaction.save()
        return transaction
