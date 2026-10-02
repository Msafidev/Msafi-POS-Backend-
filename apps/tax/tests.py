from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addons.models import AddOnSubscription
from apps.businesses.models import Business
from apps.inventory.models import Product
from apps.sales.models import Sale, SaleItem
from apps.tax import services
from apps.tax.etims import ETIMSAdapter
from apps.tax.models import ETIMSInvoice, TaxProfile, TaxRecord


def _register_and_login(client, name, username):
    client.post(
        "/api/v1/auth/register-business/",
        {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
        format="json",
    )
    login = client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return Business.objects.get(name=name)


def _activate_tax_addon(business):
    AddOnSubscription.objects.create(
        business=business, feature="tax", expires_at=timezone.now() + timezone.timedelta(days=30)
    )


def _make_completed_sale(business, *, price=Decimal("1000.00"), cost=Decimal("400.00"), tax_percent=Decimal("16.00")):
    product = Product.objects.create(
        business=business, sku=f"SKU-{Sale.objects.count()}-{price}", name="Widget",
        buying_price=cost, selling_price=price, tax_percent=tax_percent, current_stock=100,
    )
    sale = Sale.objects.create(business=business, sequence_no=_next_seq(business))
    item = SaleItem.objects.create(
        sale=sale, product=product, quantity=Decimal("1"), unit_price=price, unit_cost=cost, tax_percent=tax_percent
    )
    item.line_total = item.compute_line_total()
    item.save()
    sale.subtotal = price
    sale.tax_amount = item.line_total - price
    sale.total_amount = item.line_total
    sale.status = Sale.Status.COMPLETED
    sale.save()
    return sale


def _next_seq(business):
    last = Sale.objects.filter(business=business).order_by("-sequence_no").first()
    return (last.sequence_no + 1) if last else 1


class TaxServicesTests(APITestCase):
    """Pure calculation tests — no addon/permission layer involved."""

    def setUp(self):
        self.business = _register_and_login(self.client, "Calc Co", "calcadmin")

    def test_turnover_sums_completed_sales_total(self):
        _make_completed_sale(self.business, price=Decimal("1000.00"))
        _make_completed_sale(self.business, price=Decimal("500.00"))
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        self.assertGreater(services.turnover(self.business, start, end), Decimal("1400.00"))

    def test_gross_profit_is_revenue_minus_cost_of_goods(self):
        sale = _make_completed_sale(self.business, price=Decimal("1000.00"), cost=Decimal("400.00"), tax_percent=Decimal("0"))
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        # revenue (1000, no tax) - cost of goods (400) = 600
        self.assertEqual(services.gross_profit(self.business, start, end), Decimal("600.00"))

    def test_estimate_turnover_tax_applies_rate_to_turnover(self):
        _make_completed_sale(self.business, price=Decimal("1000.00"), tax_percent=Decimal("0"))
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        amount = services.estimate_tax("turnover_tax", self.business, start, end, Decimal("1.00"))
        self.assertEqual(amount, Decimal("10.00"))

    def test_estimate_returns_none_for_non_estimatable_type(self):
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        self.assertIsNone(services.estimate_tax("withholding_tax", self.business, start, end, Decimal("5.00")))

    def test_estimate_returns_none_when_rate_missing(self):
        start = timezone.localdate().replace(day=1)
        end = timezone.localdate()
        self.assertIsNone(services.estimate_tax("turnover_tax", self.business, start, end, None))


class TaxAddonGatingTests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Gated Tax Co", "gatedtaxadmin")

    def test_tax_profile_blocked_without_addon(self):
        response = self.client.get("/api/v1/tax/profile/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tax_summary_blocked_without_addon(self):
        response = self.client.get("/api/v1/tax/summary/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tax_profile_accessible_once_addon_active(self):
        _activate_tax_addon(self.business)
        response = self.client.get("/api/v1/tax/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TaxProfileAPITests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Profile Tax Co", "profiletaxadmin")
        _activate_tax_addon(self.business)

    def test_patch_sets_rates_and_etims_config(self):
        response = self.client.patch(
            "/api/v1/tax/profile/",
            {
                "turnover_tax_rate": "1.00",
                "corporation_tax_rate": "30.00",
                "etims_enabled": True,
                "etims_branch_code": "00",
                "etims_device_serial": "DEV123",
                "etims_communication_key": "secret-key",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["turnover_tax_rate"], "1.00")
        self.assertNotIn("etims_communication_key", response.data)

        profile = TaxProfile.objects.get(business=self.business)
        self.assertEqual(profile.etims_communication_key, "secret-key")


class TaxRecordAPITests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Record Tax Co", "recordtaxadmin")
        _activate_tax_addon(self.business)

    def test_manual_entry_for_withholding_tax(self):
        response = self.client.post(
            "/api/v1/tax/records/",
            {
                "tax_type": "withholding_tax",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "amount": "4500.00",
                "note": "Per accountant's WHT certificate summary",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["is_estimated"])

    def test_estimate_rejects_non_estimatable_tax_type(self):
        response = self.client.post(
            "/api/v1/tax/records/estimate/",
            {"tax_type": "capital_gains_tax", "period_start": "2026-07-01", "period_end": "2026-07-31"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_estimate_requires_rate_configured_first(self):
        response = self.client.post(
            "/api/v1/tax/records/estimate/",
            {"tax_type": "turnover_tax", "period_start": "2026-07-01", "period_end": "2026-07-31"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_estimate_computes_and_stores_turnover_tax(self):
        self.client.patch("/api/v1/tax/profile/", {"turnover_tax_rate": "1.00"}, format="json")
        _make_completed_sale(self.business, price=Decimal("2000.00"), tax_percent=Decimal("0"))
        response = self.client.post(
            "/api/v1/tax/records/estimate/",
            {
                "tax_type": "turnover_tax",
                "period_start": str(timezone.localdate().replace(day=1)),
                "period_end": str(timezone.localdate()),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["is_estimated"])
        self.assertEqual(Decimal(response.data["amount"]), Decimal("20.00"))


class TaxSummaryAPITests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Summary Tax Co", "summarytaxadmin")
        _activate_tax_addon(self.business)

    def test_summary_lists_manual_entry_required_types(self):
        response = self.client.get("/api/v1/tax/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("withholding_tax", response.data["manual_entry_required"])
        self.assertNotIn("turnover_tax", response.data["manual_entry_required"])


class ETIMSInvoiceTests(APITestCase):
    def setUp(self):
        self.business = _register_and_login(self.client, "Etims Co", "etimsadmin")
        _activate_tax_addon(self.business)
        self.sale = _make_completed_sale(self.business)

    def test_submit_without_etims_enabled_returns_not_configured(self):
        response = self.client.post("/api/v1/tax/etims-invoices/submit/", {"sale_id": str(self.sale.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "not_configured")

    @patch("apps.tax.etims.requests.post")
    def test_submit_success_stores_kra_invoice_number(self, mock_post):
        self.client.patch(
            "/api/v1/tax/profile/",
            {
                "etims_enabled": True, "etims_environment": "sandbox",
                "etims_branch_code": "00", "etims_device_serial": "DEV1", "etims_communication_key": "key",
            },
            format="json",
        )
        with self.settings(ETIMS_SANDBOX_BASE_URL="https://sandbox.example/etims"):
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: {"invcNo": "KRA-INV-001", "qrCode": "https://etims.kra.go.ke/verify/xyz"}
            )
            response = self.client.post(
                "/api/v1/tax/etims-invoices/submit/", {"sale_id": str(self.sale.id)}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "submitted")
        self.assertEqual(response.data["kra_invoice_number"], "KRA-INV-001")

    def test_submit_unknown_sale_returns_404(self):
        response = self.client.post(
            "/api/v1/tax/etims-invoices/submit/",
            {"sale_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ETIMSAdapterUnitTests(APITestCase):
    def test_missing_base_url_raises_clear_error(self):
        profile = TaxProfile(etims_environment="sandbox")
        adapter = ETIMSAdapter(profile)
        with self.assertRaises(Exception):
            adapter._base_url()
