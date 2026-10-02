import requests
from django.conf import settings

from apps.payments.adapters.base import AdapterResult, PaymentAdapter

PESAPAL_BASE = {
    True: "https://cybqa.pesapal.com/pesapalv3",
    False: "https://pay.pesapal.com/v3",
}


class PesapalAdapter(PaymentAdapter):
    """
    PesaPal API v3 — a Kenyan payment aggregator that itself accepts
    Visa/Mastercard and mobile money, which is why
    PaymentProvider.Provider.VISA_MASTERCARD is also routed here (see
    registry.py): card acquiring needs a PCI-DSS compliant gateway, and
    PesaPal is the one most Kenyan SMEs can actually onboard with
    directly, rather than MsafiPOS holding raw card numbers itself.

    Reads from PaymentProvider: api_key (consumer key), api_secret
    (consumer secret), account_reference (optional order description
    prefix). `merchant_id`/`terminal_id` aren't used by this adapter.
    """

    def _base_url(self):
        return PESAPAL_BASE[self.provider.sandbox]

    def _get_token(self):
        resp = requests.post(
            f"{self._base_url()}/api/Auth/RequestToken",
            json={"consumer_key": self.provider.api_key, "consumer_secret": self.provider.api_secret},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["token"]

    def _ipn_id(self, token):
        callback_base = getattr(settings, "PUBLIC_API_BASE_URL", "").rstrip("/")
        resp = requests.post(
            f"{self._base_url()}/api/URLSetup/RegisterIPN",
            json={
                "url": f"{callback_base}/api/v1/payments/pesapal/callback/",
                "ipn_notification_type": "GET",
            },
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["ipn_id"]

    def initiate(self, transaction) -> AdapterResult:
        try:
            token = self._get_token()
            ipn_id = self._ipn_id(token)
            callback_base = getattr(settings, "PUBLIC_APP_BASE_URL", "").rstrip("/")
            payload = {
                "id": str(transaction.id),
                "currency": transaction.currency,
                "amount": float(transaction.amount),
                "description": self.provider.account_reference or "MsafiPOS sale payment",
                "callback_url": f"{callback_base}/pos/payment-status/{transaction.id}/",
                "notification_id": ipn_id,
                "billing_address": {"phone_number": transaction.phone_number or ""},
            }
            resp = requests.post(
                f"{self._base_url()}/api/Transactions/SubmitOrderRequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=20,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("order_tracking_id"):
                return AdapterResult(
                    status="processing",
                    merchant_request_id=data["order_tracking_id"],
                    checkout_request_id=data["order_tracking_id"],
                    raw=data,
                )
            return AdapterResult(
                status="failed", failure_reason=data.get("message", "PesaPal order rejected"), raw=data
            )
        except requests.RequestException as exc:
            return AdapterResult(status="failed", failure_reason=f"Network error contacting PesaPal: {exc}")

    def check_status(self, transaction) -> AdapterResult:
        try:
            token = self._get_token()
            resp = requests.get(
                f"{self._base_url()}/api/Transactions/GetTransactionStatus",
                params={"orderTrackingId": transaction.checkout_request_id},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15,
            )
            data = resp.json()
            status_map = {1: "success", 2: "failed", 3: "cancelled"}
            mapped = status_map.get(data.get("status_code"), "processing")
            return AdapterResult(
                status=mapped,
                provider_reference=data.get("confirmation_code", ""),
                failure_reason="" if mapped == "success" else data.get("description", ""),
                raw=data,
            )
        except requests.RequestException as exc:
            return AdapterResult(status="failed", failure_reason=f"Network error contacting PesaPal: {exc}")

    def parse_callback(self, payload: dict) -> AdapterResult:
        # PesaPal's IPN is a simple GET with query params (OrderTrackingId,
        # OrderMerchantReference, OrderNotificationType) — the view is
        # expected to re-check status via check_status() rather than trust
        # the callback body, since IPN carries no result code itself.
        tracking_id = payload.get("OrderTrackingId", "")
        return AdapterResult(status="processing", checkout_request_id=tracking_id, raw=payload)
