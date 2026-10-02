import base64
from datetime import datetime

import requests
from django.conf import settings

from apps.payments.adapters.base import AdapterResult, PaymentAdapter

DARAJA_BASE = {
    True: "https://sandbox.safaricom.co.ke",
    False: "https://api.safaricom.co.ke",
}


class MpesaSTKAdapter(PaymentAdapter):
    """
    Safaricom Daraja "Lipa Na M-Pesa Online" (STK Push) — used both for a
    tenant's own in-shop M-Pesa till (PaymentProvider.provider ==
    mpesa_stk) and, separately, by apps.billing for Msafi Labs' own
    platform-subscription payments (billing has its own Daraja config,
    kept out of this per-tenant table on purpose — see apps/billing/).

    Reads from PaymentProvider: api_key (consumer key), api_secret
    (consumer secret), shortcode (paybill/till number), passkey.
    `sandbox` picks the Safaricom sandbox vs. production host.
    """

    def _base_url(self):
        return DARAJA_BASE[self.provider.sandbox]

    def _get_access_token(self):
        resp = requests.get(
            f"{self._base_url()}/oauth/v1/generate?grant_type=client_credentials",
            auth=(self.provider.api_key, self.provider.api_secret),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _password(self, timestamp):
        raw = f"{self.provider.shortcode}{self.provider.passkey}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    def initiate(self, transaction) -> AdapterResult:
        try:
            token = self._get_access_token()
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            callback_base = getattr(settings, "PUBLIC_API_BASE_URL", "").rstrip("/")
            payload = {
                "BusinessShortCode": self.provider.shortcode,
                "Password": self._password(timestamp),
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": int(round(transaction.amount)),
                "PartyA": transaction.phone_number,
                "PartyB": self.provider.shortcode,
                "PhoneNumber": transaction.phone_number,
                "CallBackURL": f"{callback_base}/api/v1/addons/mpesa/callback/",
                "AccountReference": self.provider.account_reference or "MsafiPOS",
                "TransactionDesc": "MsafiPOS sale payment",
            }
            resp = requests.post(
                f"{self._base_url()}/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("ResponseCode") == "0":
                return AdapterResult(
                    status="processing",
                    merchant_request_id=data.get("MerchantRequestID", ""),
                    checkout_request_id=data.get("CheckoutRequestID", ""),
                    raw=data,
                )
            return AdapterResult(
                status="failed",
                failure_reason=data.get("errorMessage") or data.get("ResponseDescription", "STK push rejected"),
                raw=data,
            )
        except requests.RequestException as exc:
            return AdapterResult(status="failed", failure_reason=f"Network error contacting M-Pesa: {exc}")

    def check_status(self, transaction) -> AdapterResult:
        try:
            token = self._get_access_token()
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            payload = {
                "BusinessShortCode": self.provider.shortcode,
                "Password": self._password(timestamp),
                "Timestamp": timestamp,
                "CheckoutRequestID": transaction.checkout_request_id,
            }
            resp = requests.post(
                f"{self._base_url()}/mpesa/stkpushquery/v1/query",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            data = resp.json()
            result_code = str(data.get("ResultCode", ""))
            if result_code == "0":
                return AdapterResult(status="success", raw=data)
            if result_code == "":
                return AdapterResult(status="processing", raw=data)
            return AdapterResult(status="failed", failure_reason=data.get("ResultDesc", "Payment failed"), raw=data)
        except requests.RequestException as exc:
            return AdapterResult(status="failed", failure_reason=f"Network error contacting M-Pesa: {exc}")

    def parse_callback(self, payload: dict) -> AdapterResult:
        """
        Daraja's async callback shape:
        {"Body": {"stkCallback": {"MerchantRequestID", "CheckoutRequestID",
        "ResultCode", "ResultDesc", "CallbackMetadata": {"Item": [...]}}}}
        """
        stk = payload.get("Body", {}).get("stkCallback", {})
        result_code = stk.get("ResultCode")
        checkout_request_id = stk.get("CheckoutRequestID", "")
        merchant_request_id = stk.get("MerchantRequestID", "")

        if result_code == 0:
            items = {
                item.get("Name"): item.get("Value")
                for item in stk.get("CallbackMetadata", {}).get("Item", [])
            }
            return AdapterResult(
                status="success",
                provider_reference=str(items.get("MpesaReceiptNumber", "")),
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                raw=payload,
            )
        return AdapterResult(
            status="failed" if result_code != 1032 else "cancelled",
            failure_reason=stk.get("ResultDesc", "Payment failed or cancelled"),
            merchant_request_id=merchant_request_id,
            checkout_request_id=checkout_request_id,
            raw=payload,
        )
