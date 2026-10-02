from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addons.models import AddOnPayment, AddOnSubscription
from apps.addons.services import has_active_addon
from apps.authentication.models import Role, User
from apps.businesses.models import Business


def _register_and_login(client, name, username):
    client.post(
        "/api/v1/auth/register-business/",
        {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
        format="json",
    )
    login = client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return Business.objects.get(name=name)


def _login_super_admin(client):
    user = User.objects.create_user(username="rootadmin", password="StrongPass123", role=Role.SUPER_ADMIN)
    login = client.post("/api/v1/auth/login/", {"username": "rootadmin", "password": "StrongPass123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return user


class AddonGatingTests(APITestCase):
    """The core thing this phase adds: payments endpoints stay locked until the add-on is paid for."""

    def setUp(self):
        self.business = _register_and_login(self.client, "Gate Addon Co", "gateaddonadmin")

    def test_payments_endpoints_blocked_without_addon(self):
        response = self.client.get("/api/v1/payments/providers/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"].code, "addon_required")

    def test_payments_endpoints_open_once_addon_active(self):
        AddOnSubscription.objects.create(
            business=self.business, feature="payments", expires_at=timezone.now() + timedelta(days=30)
        )
        response = self.client.get("/api/v1/payments/providers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expired_addon_blocks_again(self):
        AddOnSubscription.objects.create(
            business=self.business, feature="payments", expires_at=timezone.now() - timedelta(days=1)
        )
        response = self.client.get("/api/v1/payments/providers/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_has_active_addon_service_function(self):
        self.assertFalse(has_active_addon(self.business, "payments"))
        AddOnSubscription.objects.create(
            business=self.business, feature="payments", expires_at=timezone.now() + timedelta(days=1)
        )
        self.assertTrue(has_active_addon(self.business, "payments"))

    def test_addon_is_per_feature_not_all_or_nothing(self):
        AddOnSubscription.objects.create(
            business=self.business, feature="tax", expires_at=timezone.now() + timedelta(days=30)
        )
        # "tax" addon active doesn't unlock "payments"
        response = self.client.get("/api/v1/payments/providers/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AddonPurchaseFlowTests(APITestCase):
    """
    Auto-verified purchase flow: InitiateAddOnPaymentView sends the STK
    push (mocked here — no real Daraja calls in tests), then either the
    M-Pesa callback or a status poll confirms it. verify/reject stay
    covered as the manual fallback for a payment that never got a
    callback.
    """

    def setUp(self):
        self.business = _register_and_login(self.client, "Purchase Addon Co", "purchaseaddonadmin")

    def _initiate(self, feature, phone_number="0712345678"):
        with patch("apps.addons.mpesa.stk_push", return_value=("merchant-1", "checkout-1")):
            return self.client.post(
                "/api/v1/addons/stk/initiate/",
                {"feature": feature, "phone_number": phone_number},
                format="json",
            )

    def test_initiate_sends_stk_push_and_leaves_addon_inactive_until_confirmed(self):
        response = self._initiate("payments")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(response.data["amount"]), Decimal("2000"))
        self.assertEqual(response.data["status"], "processing")
        self.assertFalse(has_active_addon(self.business, "payments"))

    def test_mpesa_callback_activates_addon_with_no_super_admin_step(self):
        payment_id = self._initiate("payments").data["id"]

        callback_result = {"checkout_request_id": "checkout-1", "status": "success", "receipt_number": "QFT1XYZ2AB", "message": ""}
        with patch("apps.addons.mpesa.parse_callback", return_value=callback_result):
            response = self.client.post("/api/v1/addons/mpesa/callback/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment = AddOnPayment.objects.get(pk=payment_id)
        self.assertEqual(payment.status, AddOnPayment.Status.VERIFIED)
        self.assertEqual(payment.transaction_code, "QFT1XYZ2AB")
        self.assertTrue(has_active_addon(self.business, "payments"))

    def test_mpesa_callback_failure_does_not_activate_addon(self):
        payment_id = self._initiate("tax").data["id"]

        callback_result = {"checkout_request_id": "checkout-1", "status": "failed", "receipt_number": "", "message": "Request cancelled by user."}
        with patch("apps.addons.mpesa.parse_callback", return_value=callback_result):
            self.client.post("/api/v1/addons/mpesa/callback/", {}, format="json")

        payment = AddOnPayment.objects.get(pk=payment_id)
        self.assertEqual(payment.status, AddOnPayment.Status.FAILED)
        self.assertFalse(has_active_addon(self.business, "tax"))

    def test_callback_is_idempotent_once_already_verified(self):
        payment_id = self._initiate("payments").data["id"]
        callback_result = {"checkout_request_id": "checkout-1", "status": "success", "receipt_number": "FIRSTCODE1", "message": ""}
        with patch("apps.addons.mpesa.parse_callback", return_value=callback_result):
            self.client.post("/api/v1/addons/mpesa/callback/", {}, format="json")

        # A second (duplicate/retried) callback with a different receipt must not overwrite the first.
        second_result = {"checkout_request_id": "checkout-1", "status": "success", "receipt_number": "SECONDCODE", "message": ""}
        with patch("apps.addons.mpesa.parse_callback", return_value=second_result):
            self.client.post("/api/v1/addons/mpesa/callback/", {}, format="json")

        payment = AddOnPayment.objects.get(pk=payment_id)
        self.assertEqual(payment.transaction_code, "FIRSTCODE1")

    def test_reject_does_not_activate_addon(self):
        payment_id = self._initiate("tax").data["id"]

        self.client.credentials()
        _login_super_admin(self.client)
        response = self.client.post(
            f"/api/v1/addons/payments/{payment_id}/reject/", {"rejection_reason": "Couldn't find it on the statement"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(has_active_addon(self.business, "tax"))

    def test_manual_verify_fallback_extends_from_existing_expiry_not_now(self):
        existing_expiry = timezone.now() + timedelta(days=10)
        AddOnSubscription.objects.create(business=self.business, feature="payments", expires_at=existing_expiry)

        payment_id = self._initiate("payments").data["id"]
        self.client.credentials()
        _login_super_admin(self.client)
        self.client.post(f"/api/v1/addons/payments/{payment_id}/verify/")

        addon = AddOnSubscription.objects.get(business=self.business, feature="payments")
        expected = existing_expiry + timedelta(days=30)
        self.assertAlmostEqual(addon.expires_at.timestamp(), expected.timestamp(), delta=10)

    def test_my_addons_endpoint_reports_status(self):
        response = self.client.get("/api/v1/addons/mine/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["payments"]["active"])
        self.assertFalse(response.data["tax"]["active"])

        AddOnSubscription.objects.create(
            business=self.business, feature="payments", expires_at=timezone.now() + timedelta(days=5)
        )
        response = self.client.get("/api/v1/addons/mine/")
        self.assertTrue(response.data["payments"]["active"])
        self.assertFalse(response.data["tax"]["active"])

    def test_business_cannot_see_or_verify_another_businesses_addon_payment(self):
        payment_id = self._initiate("payments").data["id"]

        self.client.credentials()
        _register_and_login(self.client, "Other Addon Co", "otheraddonadmin")
        response = self.client.get("/api/v1/addons/payments/")
        ids = [p["id"] for p in (response.data if isinstance(response.data, list) else response.data.get("results", []))]
        self.assertNotIn(payment_id, ids)

        response = self.client.post(f"/api/v1/addons/payments/{payment_id}/verify/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
