"""
Platform-level M-Pesa STK Push for add-on purchases.

Distinct from apps.payments.adapters.mpesa_stk.MpesaSTKAdapter, which is
per-tenant (each business's own till/paybill). This one always charges
into Msafi Labs' own shortcode (settings.PLATFORM_MPESA_*), because
add-on fees are paid to the platform, not to the shop's own account.

Kept deliberately small and dependency-free (no PaymentTransaction model
needed) since add-on purchases don't go through the payment engine.
"""
import base64
from datetime import datetime

import requests
from django.conf import settings
import json


DARAJA_BASE = {
    True: "https://sandbox.safaricom.co.ke",
    False: "https://api.safaricom.co.ke",
}


class STKError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _base_url():
    return DARAJA_BASE[settings.PLATFORM_MPESA_SANDBOX]


def _get_access_token():
    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"

    print("\nGetting Daraja Access Token...")
    print("URL:", url)

    response = requests.get(
        url,
        auth=(
            settings.PLATFORM_MPESA_CONSUMER_KEY,
            settings.PLATFORM_MPESA_CONSUMER_SECRET,
        ),
        timeout=30,
    )

    print("Token Status:", response.status_code)
    print("Token Response:", response.text)

    response.raise_for_status()

    return response.json()["access_token"]


def _password(timestamp):
    raw = f"{settings.PLATFORM_MPESA_SHORTCODE}{settings.PLATFORM_MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def stk_push(*, phone_number, amount, account_reference, transaction_desc, callback_url):
    """
    Initiates an M-Pesa STK Push.

    Returns:
        (merchant_request_id, checkout_request_id)

    Raises:
        STKError
    """

    # Get access token
    try:
        token = _get_access_token()
    except requests.RequestException as exc:
        raise STKError(f"Could not get M-Pesa access token: {exc}") from exc

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    payload = {
        "BusinessShortCode": settings.PLATFORM_MPESA_SHORTCODE,
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(round(amount)),
        "PartyA": phone_number,
        "PartyB": settings.PLATFORM_MPESA_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": account_reference,
        "TransactionDesc": transaction_desc,
    }

    url = f"{_base_url()}/mpesa/stkpush/v1/processrequest"

    print("\n" + "=" * 80)
    print("M-PESA STK PUSH REQUEST")
    print("=" * 80)
    print("URL:", url)
    print("Callback URL:", callback_url)
    print("Phone:", phone_number)
    print("Amount:", amount)
    print("Shortcode:", settings.PLATFORM_MPESA_SHORTCODE)
    print("Timestamp:", timestamp)
    print("Payload:")
    print(json.dumps(payload, indent=4))
    print("=" * 80)

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    except requests.RequestException as exc:
        raise STKError(f"Network error contacting Daraja: {exc}") from exc

    print("\n" + "=" * 80)
    print("M-PESA RESPONSE")
    print("=" * 80)
    print("HTTP Status:", response.status_code)
    print("Raw Body:")
    print(response.text)
    print("=" * 80)

    try:
        data = response.json()
    except ValueError:
        raise STKError(
            f"Daraja returned a non-JSON response.\n"
            f"HTTP {response.status_code}\n"
            f"{response.text}"
        )

    if response.status_code == 200 and data.get("ResponseCode") == "0":
        print("✅ STK Push Accepted")
        print("MerchantRequestID:", data.get("MerchantRequestID"))
        print("CheckoutRequestID:", data.get("CheckoutRequestID"))

        return (
            data.get("MerchantRequestID"),
            data.get("CheckoutRequestID"),
        )

    print("\n❌ STK PUSH FAILED")
    print(json.dumps(data, indent=4))

    error_message = (
        data.get("errorMessage")
        or data.get("ResponseDescription")
        or data.get("CustomerMessage")
        or json.dumps(data)
    )

    raise STKError(error_message)

def query_status(checkout_request_id):
    """Returns 'success' | 'processing' | 'failed', plus a human-readable message."""
    try:
        token = _get_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        payload = {
            "BusinessShortCode": settings.PLATFORM_MPESA_SHORTCODE,
            "Password": _password(timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        resp = requests.post(
            f"{_base_url()}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        data = resp.json()
    except requests.RequestException as exc:
        return "processing", f"Network error contacting M-Pesa: {exc}"

    result_code = str(data.get("ResultCode", ""))
    if result_code == "0":
        return "success", data.get("ResultDesc", "Payment received")
    if result_code == "":
        return "processing", "Waiting for the customer to complete the prompt"
    return "failed", data.get("ResultDesc", "Payment failed or was cancelled")


def parse_callback(payload: dict):
    """
    Daraja's async callback shape:
    {"Body": {"stkCallback": {"MerchantRequestID", "CheckoutRequestID",
    "ResultCode", "ResultDesc", "CallbackMetadata": {"Item": [...]}}}}

    Returns dict: {status, checkout_request_id, merchant_request_id,
    receipt_number, message}
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
        return {
            "status": "success",
            "checkout_request_id": checkout_request_id,
            "merchant_request_id": merchant_request_id,
            "receipt_number": str(items.get("MpesaReceiptNumber", "")),
            "message": "Payment received",
        }
    return {
        "status": "cancelled" if result_code == 1032 else "failed",
        "checkout_request_id": checkout_request_id,
        "merchant_request_id": merchant_request_id,
        "receipt_number": "",
        "message": stk.get("ResultDesc", "Payment failed or was cancelled"),
    }
