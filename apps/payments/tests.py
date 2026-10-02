from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from apps.addons.models import AddOnSubscription
from apps.businesses.models import Business
from apps.payments.adapters.mpesa_stk import MpesaSTKAdapter
from apps.payments.engine import PaymentEngine
from apps.payments.models import PaymentProvider, PaymentTransaction


def _register_and_login(client, name, username):
    client.post(
        "/api/v1/auth/register-business/",
        {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
        format="json",
    )
    login = client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return Business.objects.get(name=name)


def _activate_payments_addon(business):
    """
    apps.payments endpoints are gated behind the "payments" add-on (see
    apps.addons) — these tests are about the payment adapters/engine
    themselves, so give every test business the add-on up front rather
    than re-testing the gate here (that's covered in apps.addons.tests).
    """
    from datetime import timedelta

    AddOnSubscription.objects.update_or_create(
        business=business, feature="payments", defaults={"expires_at": timezone.now() + timedelta(days=30)}
    )


class PaymentProviderAPITests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Provider Co", "provideradmin")
        _activate_payments_addon(self.business)

    def test_create_and_list_provider_hides_credentials(self):
        response = self.client.post(
            "/api/v1/payments/providers/",
            {
                "provider": "kcb",
                "display_name": "KCB Main Till",
                "terminal_id": "TERM123",
                "merchant_id": "MERCH456",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            "/api/v1/payments/providers/",
            {
                "provider": "mpesa_stk",
                "display_name": "Shop M-Pesa",
                "api_key": "consumer-key",
                "api_secret": "consumer-secret",
                "shortcode": "174379",
                "passkey": "somepasskey",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("api_secret", response.data)
        self.assertNotIn("passkey", response.data)
        self.assertTrue(response.data["has_credentials"])

    def test_provider_scoped_to_owning_business_only(self):
        self.client.post(
            "/api/v1/payments/providers/", {"provider": "coop", "display_name": "Co-op PDQ"}, format="json"
        )
        other_business = _register_and_login(self.client, "Other Co", "otheradmin")
        _activate_payments_addon(other_business)
        self.assertNotEqual(other_business.id, self.business.id)
        response = self.client.get("/api/v1/payments/providers/")
        self.assertEqual(len(response.data["results"]) if "results" in response.data else len(response.data), 0)


class PaymentEngineBankTerminalTests(APITestCase):
    """The Co-op/KCB/Equity/Absa "semi-integrated PDQ" flow end to end."""

    def setUp(self):
        self.business = _register_and_login(self.client, "Terminal Co", "terminaladmin")
        _activate_payments_addon(self.business)
        self.provider = PaymentProvider.objects.create(
            business=self.business, provider="kcb", display_name="KCB PDQ", terminal_id="T1", merchant_id="M1"
        )

    def test_initiate_marks_awaiting_terminal(self):
        response = self.client.post(
            "/api/v1/payments/transactions/initiate/", {"provider": "kcb", "amount": "500.00"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "awaiting_terminal")

    def test_confirm_terminal_completes_transaction(self):
        transaction = PaymentEngine.charge(business=self.business, provider_code="kcb", amount=Decimal("500.00"))
        self.assertEqual(transaction.status, "awaiting_terminal")

        response = self.client.post(
            f"/api/v1/payments/transactions/{transaction.id}/confirm-terminal/",
            {"provider_reference": "APPROVAL123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["provider_reference"], "APPROVAL123")

    def test_confirm_terminal_twice_rejected(self):
        transaction = PaymentEngine.charge(business=self.business, provider_code="kcb", amount=Decimal("500.00"))
        self.client.post(
            f"/api/v1/payments/transactions/{transaction.id}/confirm-terminal/",
            {"provider_reference": "APPROVAL123"},
            format="json",
        )
        response = self.client.post(
            f"/api/v1/payments/transactions/{transaction.id}/confirm-terminal/",
            {"provider_reference": "APPROVAL456"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_charge_fails_without_active_provider_configured(self):
        with self.assertRaises(PaymentEngine.PaymentEngineError):
            PaymentEngine.charge(business=self.business, provider_code="absa", amount=Decimal("100.00"))


class MpesaSTKAdapterTests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Mpesa Co", "mpesaadmin")
        _activate_payments_addon(self.business)
        self.provider = PaymentProvider.objects.create(
            business=self.business,
            provider="mpesa_stk",
            api_key="key",
            api_secret="secret",
            shortcode="174379",
            passkey="passkey",
            sandbox=True,
        )

    @patch("apps.payments.adapters.mpesa_stk.requests.post")
    @patch("apps.payments.adapters.mpesa_stk.requests.get")
    def test_initiate_success_sets_processing_and_checkout_id(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "tok123"})
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "MerchantRequestID": "mr-1",
                "CheckoutRequestID": "cr-1",
                "ResponseCode": "0",
                "ResponseDescription": "Success",
            },
        )
        transaction = PaymentEngine.charge(
            business=self.business, provider_code="mpesa_stk", amount=Decimal("250.00"), phone_number="254712345678"
        )
        self.assertEqual(transaction.status, "processing")
        self.assertEqual(transaction.checkout_request_id, "cr-1")

    @patch("apps.payments.adapters.mpesa_stk.requests.post")
    @patch("apps.payments.adapters.mpesa_stk.requests.get")
    def test_initiate_rejected_by_safaricom_marks_failed(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "tok123"})
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"ResponseCode": "1", "errorMessage": "Invalid shortcode"},
        )
        transaction = PaymentEngine.charge(
            business=self.business, provider_code="mpesa_stk", amount=Decimal("250.00"), phone_number="254712345678"
        )
        self.assertEqual(transaction.status, "failed")
        self.assertEqual(transaction.failure_reason, "Invalid shortcode")

    def test_missing_phone_number_rejected_before_calling_adapter(self):
        response = self.client.post(
            "/api/v1/payments/transactions/initiate/", {"provider": "mpesa_stk", "amount": "10.00"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)

    def test_callback_success_updates_transaction_and_stores_receipt(self):
        transaction = PaymentTransaction.objects.create(
            business=self.business,
            provider=self.provider,
            amount=Decimal("250.00"),
            phone_number="254712345678",
            status="processing",
            checkout_request_id="cr-99",
            merchant_request_id="mr-99",
        )
        callback_payload = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "mr-99",
                    "CheckoutRequestID": "cr-99",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 250.0},
                            {"Name": "MpesaReceiptNumber", "Value": "NLJ7RT61SV"},
                        ]
                    },
                }
            }
        }
        response = self.client.post(
            f"/api/v1/payments/mpesa/callback/{transaction.id}/", callback_payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, "success")
        self.assertEqual(transaction.provider_reference, "NLJ7RT61SV")

    def test_callback_user_cancelled_marks_cancelled_not_failed(self):
        transaction = PaymentTransaction.objects.create(
            business=self.business,
            provider=self.provider,
            amount=Decimal("250.00"),
            status="processing",
            checkout_request_id="cr-cancel",
        )
        callback_payload = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": "cr-cancel",
                    "ResultCode": 1032,
                    "ResultDesc": "Request cancelled by user",
                }
            }
        }
        self.client.post(f"/api/v1/payments/mpesa/callback/{transaction.id}/", callback_payload, format="json")
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, "cancelled")

    def test_unknown_transaction_id_returns_404(self):
        response = self.client.post(
            "/api/v1/payments/mpesa/callback/00000000-0000-0000-0000-000000000000/", {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MpesaSTKAdapterUnitTests(APITestCase):
    """Adapter-level tests that don't need the API/DB round trip."""

    def setUp(self):
        self.provider = PaymentProvider(
            provider="mpesa_stk", api_key="k", api_secret="s", shortcode="174379", passkey="p", sandbox=True
        )
        self.adapter = MpesaSTKAdapter(self.provider)

    def test_password_is_base64_of_shortcode_passkey_timestamp(self):
        password = self.adapter._password("20260723120000")
        import base64

        decoded = base64.b64decode(password).decode()
        self.assertEqual(decoded, "174379p20260723120000")

    def test_sandbox_flag_selects_sandbox_host(self):
        self.assertEqual(self.adapter._base_url(), "https://sandbox.safaricom.co.ke")
        self.provider.sandbox = False
        self.assertEqual(self.adapter._base_url(), "https://api.safaricom.co.ke")
