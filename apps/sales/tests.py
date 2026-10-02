from decimal import Decimal

from rest_framework.test import APITestCase
from rest_framework import status

from apps.inventory.models import Product
from apps.sales.models import Sale


class SalesFlowTestCase(APITestCase):
    """Shared setup: a logged-in admin with one stocked product."""

    def setUp(self):
        reg = self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "Sales Test Co", "username": "salesadmin", "email": "s@test.com", "password": "StrongPass123"},
            format="json",
        )
        login = self.client.post(
            "/api/v1/auth/login/", {"username": "salesadmin", "password": "StrongPass123"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        product_resp = self.client.post(
            "/api/v1/products/",
            {"sku": "TEST-1", "name": "Test Widget", "buying_price": "30.00", "selling_price": "50.00",
             "tax_percent": "16", "minimum_stock": "5"},
            format="json",
        )
        self.product_id = product_resp.data["id"]
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product_id, "movement_type": "stock_in", "quantity": "100"},
            format="json",
        )

    def current_stock(self):
        return Decimal(self.client.get(f"/api/v1/products/{self.product_id}/").data["current_stock"])


class HoldAndCheckoutTests(SalesFlowTestCase):
    def test_held_sale_does_not_touch_stock(self):
        response = self.client.post(
            "/api/v1/sales/",
            {"status": "held", "items": [{"product": self.product_id, "quantity": "3"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "held")
        self.assertEqual(self.current_stock(), Decimal("100.00"))

    def test_completed_checkout_deducts_stock_and_computes_totals(self):
        response = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product": self.product_id, "quantity": "2"}],
                "payments": [{"method": "cash", "amount": "150"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # 2 * 50 = 100 subtotal, 16% tax = 16, total = 116
        self.assertEqual(Decimal(response.data["total_amount"]), Decimal("116.00"))
        self.assertEqual(Decimal(response.data["change_due"]), Decimal("34.00"))
        self.assertEqual(Decimal(response.data["balance_due"]), Decimal("0.00"))
        self.assertEqual(self.current_stock(), Decimal("98.00"))

    def test_checkout_rejected_when_insufficient_stock(self):
        response = self.client.post(
            "/api/v1/sales/",
            {"items": [{"product": self.product_id, "quantity": "9999"}], "payments": [{"method": "cash", "amount": "1"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.current_stock(), Decimal("100.00"))

    def test_split_payment_partial_leaves_balance_due(self):
        response = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product": self.product_id, "quantity": "2"}],
                "payments": [{"method": "cash", "amount": "50"}, {"method": "mobile_money", "amount": "30"}],
            },
            format="json",
        )
        # total is 116, paid 80 -> balance 36
        self.assertEqual(Decimal(response.data["amount_paid"]), Decimal("80.00"))
        self.assertEqual(Decimal(response.data["balance_due"]), Decimal("36.00"))
        self.assertEqual(Decimal(response.data["change_due"]), Decimal("0.00"))

    def test_resume_held_sale_then_completes_and_deducts_stock(self):
        held = self.client.post(
            "/api/v1/sales/",
            {"status": "held", "items": [{"product": self.product_id, "quantity": "4"}]},
            format="json",
        )
        sale_id = held.data["id"]
        self.assertEqual(self.current_stock(), Decimal("100.00"))

        completed = self.client.post(
            f"/api/v1/sales/{sale_id}/complete/", {"payments": [{"method": "cash", "amount": "500"}]}, format="json"
        )
        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        self.assertEqual(completed.data["status"], "completed")
        self.assertEqual(self.current_stock(), Decimal("96.00"))


class RefundTests(SalesFlowTestCase):
    """
    Regression coverage for the stale-prefetch-cache bug: refunding a sale
    across two separate calls must correctly flip status all the way to
    `refunded` once every unit is accounted for, not get stuck on
    `partially_refunded`.
    """

    def setUp(self):
        super().setUp()
        sale = self.client.post(
            "/api/v1/sales/",
            {"items": [{"product": self.product_id, "quantity": "5"}], "payments": [{"method": "cash", "amount": "500"}]},
            format="json",
        )
        self.sale_id = sale.data["id"]
        self.item_id = sale.data["items"][0]["id"]

    def test_partial_refund_restores_stock_and_sets_partial_status(self):
        stock_after_sale = self.current_stock()
        response = self.client.post(
            f"/api/v1/sales/{self.sale_id}/refund/",
            {"refund_method": "cash", "items": [{"sale_item": self.item_id, "quantity": "2"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.current_stock(), stock_after_sale + 2)

        sale = self.client.get(f"/api/v1/sales/{self.sale_id}/")
        self.assertEqual(sale.data["status"], "partially_refunded")

    def test_refunding_every_unit_across_two_calls_reaches_fully_refunded(self):
        self.client.post(
            f"/api/v1/sales/{self.sale_id}/refund/",
            {"refund_method": "cash", "items": [{"sale_item": self.item_id, "quantity": "2"}]},
            format="json",
        )
        second = self.client.post(
            f"/api/v1/sales/{self.sale_id}/refund/",
            {"refund_method": "cash", "items": [{"sale_item": self.item_id, "quantity": "3"}]},
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        sale = self.client.get(f"/api/v1/sales/{self.sale_id}/")
        self.assertEqual(sale.data["status"], "refunded")

    def test_over_refund_is_rejected(self):
        self.client.post(
            f"/api/v1/sales/{self.sale_id}/refund/",
            {"refund_method": "cash", "items": [{"sale_item": self.item_id, "quantity": "5"}]},
            format="json",
        )
        response = self.client.post(
            f"/api/v1/sales/{self.sale_id}/refund/",
            {"refund_method": "cash", "items": [{"sale_item": self.item_id, "quantity": "1"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SaleTenantIsolationTests(APITestCase):
    def test_business_a_cannot_see_business_bs_sales(self):
        def register_and_login(name, username):
            self.client.post(
                "/api/v1/auth/register-business/",
                {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
                format="json",
            )
            login = self.client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
            return login.data["access"]

        token_a = register_and_login("Tenant A", "tenant_a")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")
        product = self.client.post(
            "/api/v1/products/",
            {"sku": "A-1", "name": "A Product", "buying_price": "10", "selling_price": "20"},
            format="json",
        )
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": product.data["id"], "movement_type": "stock_in", "quantity": "10"},
            format="json",
        )
        self.client.post(
            "/api/v1/sales/",
            {"items": [{"product": product.data["id"], "quantity": "1"}], "payments": [{"method": "cash", "amount": "20"}]},
            format="json",
        )

        token_b = register_and_login("Tenant B", "tenant_b")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_b}")
        response = self.client.get("/api/v1/sales/")
        self.assertEqual(response.data["count"], 0)

        # Products are tenant-scoped too — Tenant B shouldn't even be able to
        # reference Tenant A's product id in a sale.
        response = self.client.post(
            "/api/v1/sales/",
            {"items": [{"product": product.data["id"], "quantity": "1"}], "payments": [{"method": "cash", "amount": "20"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_attach_another_tenants_branch_to_a_sale(self):
        def register_and_login(name, username):
            reg = self.client.post(
                "/api/v1/auth/register-business/",
                {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
                format="json",
            )
            login = self.client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
            return login.data["access"], reg.data["user"]["business"]["id"]

        token_a, biz_a_id = register_and_login("Branch Tenant A", "branch_a")
        token_b, _ = register_and_login("Branch Tenant B", "branch_b")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")
        branches = self.client.get("/api/v1/branches/")
        foreign_branch_id = branches.data["results"][0]["id"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_b}")
        product = self.client.post(
            "/api/v1/products/", {"sku": "B-1", "name": "B Product", "buying_price": "10", "selling_price": "20"}, format="json"
        )
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": product.data["id"], "movement_type": "stock_in", "quantity": "10"},
            format="json",
        )
        response = self.client.post(
            "/api/v1/sales/",
            {
                "branch": foreign_branch_id,
                "items": [{"product": product.data["id"], "quantity": "1"}],
                "payments": [{"method": "cash", "amount": "20"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
