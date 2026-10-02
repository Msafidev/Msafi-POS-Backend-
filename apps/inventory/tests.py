from decimal import Decimal

from rest_framework.test import APITestCase
from rest_framework import status


class InventoryTestCase(APITestCase):
    def setUp(self):
        self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "Inventory Co", "username": "invadmin", "email": "i@test.com", "password": "StrongPass123"},
            format="json",
        )
        login = self.client.post("/api/v1/auth/login/", {"username": "invadmin", "password": "StrongPass123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        self.supplier = self.client.post("/api/v1/suppliers/", {"name": "Test Supplier"}, format="json").data
        self.product = self.client.post(
            "/api/v1/products/",
            {"sku": "INV-1", "name": "Inventory Widget", "buying_price": "10", "selling_price": "20", "minimum_stock": "10"},
            format="json",
        ).data


class LowStockTests(InventoryTestCase):
    def test_product_below_minimum_appears_in_low_stock(self):
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product["id"], "movement_type": "stock_in", "quantity": "5"},
            format="json",
        )
        response = self.client.get("/api/v1/products/low_stock/")
        ids = [p["id"] for p in response.data["results"]]
        self.assertIn(self.product["id"], ids)

    def test_product_above_minimum_does_not_appear_in_low_stock(self):
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product["id"], "movement_type": "stock_in", "quantity": "50"},
            format="json",
        )
        response = self.client.get("/api/v1/products/low_stock/")
        ids = [p["id"] for p in response.data["results"]]
        self.assertNotIn(self.product["id"], ids)

    def test_stock_out_beyond_available_is_rejected(self):
        self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product["id"], "movement_type": "stock_in", "quantity": "5"},
            format="json",
        )
        response = self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product["id"], "movement_type": "stock_out", "quantity": "999"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PurchaseOrderTests(InventoryTestCase):
    def test_receive_purchase_order_updates_stock_and_status(self):
        po = self.client.post(
            "/api/v1/purchase-orders/",
            {
                "supplier": self.supplier["id"],
                "reference": "PO-TEST-1",
                "items": [{"product": self.product["id"], "quantity_ordered": "20", "unit_cost": "9.00"}],
            },
            format="json",
        )
        self.assertEqual(po.status_code, status.HTTP_201_CREATED)

        response = self.client.post(f"/api/v1/purchase-orders/{po.data['id']}/receive/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "received")

        product = self.client.get(f"/api/v1/products/{self.product['id']}/").data
        self.assertEqual(Decimal(product["current_stock"]), Decimal("20.00"))


class CrossTenantFkValidationTests(APITestCase):
    """
    Regression coverage for the missing-tenant-check pattern found while
    writing this test suite: several ModelSerializers used DRF's default
    (unscoped) PrimaryKeyRelatedField for related-object FKs, meaning any
    authenticated user could reference another tenant's category, brand,
    supplier, or — most severely — directly move another tenant's product
    stock via /stock-movements/.
    """

    def setUp(self):
        self.token_a, self.category_a, self.supplier_a, self.product_a = self._setup_tenant("Tenant FK A", "fk_a")
        self.token_b, _, _, _ = self._setup_tenant("Tenant FK B", "fk_b")

    def _setup_tenant(self, name, username):
        self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
            format="json",
        )
        login = self.client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
        token = login.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        category = self.client.post("/api/v1/categories/", {"name": "Cat"}, format="json").data
        supplier = self.client.post("/api/v1/suppliers/", {"name": "Sup"}, format="json").data
        product = self.client.post(
            "/api/v1/products/",
            {"sku": f"{username}-1", "name": "Product", "buying_price": "10", "selling_price": "20"},
            format="json",
        ).data
        return token, category, supplier, product

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_cannot_assign_foreign_category_to_own_product(self):
        self.auth(self.token_b)
        response = self.client.post(
            "/api/v1/products/",
            {"sku": "B-2", "name": "Sneaky", "buying_price": "10", "selling_price": "20", "category": self.category_a["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_assign_foreign_supplier_to_own_product(self):
        self.auth(self.token_b)
        response = self.client.post(
            "/api/v1/products/",
            {"sku": "B-3", "name": "Sneaky2", "buying_price": "10", "selling_price": "20", "supplier": self.supplier_a["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_move_stock_on_another_tenants_product(self):
        """The most severe case: directly manipulating a stranger's stock."""
        self.auth(self.token_b)
        response = self.client.post(
            "/api/v1/stock-movements/",
            {"product": self.product_a["id"], "movement_type": "stock_in", "quantity": "1000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Confirm the foreign product's stock is untouched.
        self.auth(self.token_a)
        product = self.client.get(f"/api/v1/products/{self.product_a['id']}/").data
        self.assertEqual(Decimal(product["current_stock"]), Decimal("0.00"))

    def test_cannot_use_foreign_supplier_or_product_in_purchase_order(self):
        self.auth(self.token_b)
        response = self.client.post(
            "/api/v1/purchase-orders/",
            {
                "supplier": self.supplier_a["id"],
                "reference": "SNEAKY-PO",
                "items": [{"product": self.product_a["id"], "quantity_ordered": "5", "unit_cost": "1"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
