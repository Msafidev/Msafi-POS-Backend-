from decimal import Decimal

from rest_framework.test import APITestCase
from rest_framework import status

from apps.authentication.models import Role, User
from apps.businesses.models import Business, Branch


class RegisterBusinessTests(APITestCase):
    """The SaaS signup flow — the seam every tenant enters through."""

    def test_register_business_creates_business_branch_and_admin(self):
        response = self.client.post(
            "/api/v1/auth/register-business/",
            {
                "business_name": "Acme Retail",
                "username": "acme_admin",
                "email": "admin@acme.test",
                "password": "StrongPass123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        business = Business.objects.get(name="Acme Retail")
        self.assertEqual(business.branches.count(), 1)
        self.assertTrue(business.branches.first().is_main)

        user = User.objects.get(username="acme_admin")
        self.assertEqual(user.role, Role.ADMIN)
        self.assertEqual(user.business_id, business.id)
        self.assertEqual(user.branch_id, business.branches.first().id)

    def test_duplicate_username_is_rejected(self):
        payload = {
            "business_name": "First Co",
            "username": "dupe",
            "email": "a@test.com",
            "password": "StrongPass123",
        }
        self.client.post("/api/v1/auth/register-business/", payload, format="json")
        response = self.client.post(
            "/api/v1/auth/register-business/",
            {**payload, "business_name": "Second Co", "email": "b@test.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # A rejected duplicate signup must not leave a second orphaned business behind.
        self.assertEqual(Business.objects.filter(name="Second Co").exists(), False)


class LoginTests(APITestCase):
    def setUp(self):
        reg = self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "LoginCo", "username": "loginuser", "email": "l@test.com", "password": "StrongPass123"},
            format="json",
        )
        self.business_id = reg.data["business_id"]

    def test_login_embeds_role_and_business_claims_in_jwt(self):
        import jwt as pyjwt

        response = self.client.post(
            "/api/v1/auth/login/", {"username": "loginuser", "password": "StrongPass123"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["user"]["role"], Role.ADMIN)

        decoded = pyjwt.decode(response.data["access"], options={"verify_signature": False})
        self.assertEqual(decoded["role"], Role.ADMIN)
        self.assertEqual(decoded["business_id"], self.business_id)

    def test_wrong_password_rejected(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"username": "loginuser", "password": "WrongPassword"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserManagementAndTenantIsolationTests(APITestCase):
    """
    The core multi-tenancy guarantee: an Admin from Business A must never be
    able to see or touch Business B's staff, even by guessing a UUID.
    """

    def setUp(self):
        self.biz_a = self._register("Business A", "admin_a")
        self.biz_b = self._register("Business B", "admin_b")

    def _register(self, name, username):
        reg = self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": name, "username": username, "email": f"{username}@test.com", "password": "StrongPass123"},
            format="json",
        )
        login = self.client.post("/api/v1/auth/login/", {"username": username, "password": "StrongPass123"}, format="json")
        return {"business_id": reg.data["business_id"], "access": login.data["access"], "username": username}

    def auth(self, ctx):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {ctx['access']}")

    def test_admin_cannot_list_other_business_users(self):
        self.auth(self.biz_a)
        response = self.client.post(
            "/api/v1/auth/users/",
            {"username": "cashier_a", "email": "ca@test.com", "password": "StrongPass123", "role": "cashier"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.auth(self.biz_b)
        response = self.client.get("/api/v1/auth/users/")
        usernames = [u["username"] for u in response.data["results"]]
        self.assertNotIn("cashier_a", usernames)
        self.assertIn("admin_b", usernames)

    def test_non_admin_cannot_create_users(self):
        self.auth(self.biz_a)
        self.client.post(
            "/api/v1/auth/users/",
            {"username": "cashier_only", "email": "co@test.com", "password": "StrongPass123", "role": "cashier"},
            format="json",
        )
        cashier_login = self.client.post(
            "/api/v1/auth/login/", {"username": "cashier_only", "password": "StrongPass123"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {cashier_login.data['access']}")
        response = self.client.post(
            "/api/v1/auth/users/",
            {"username": "should_fail", "email": "sf@test.com", "password": "StrongPass123", "role": "cashier"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_assign_super_admin_role_via_user_management(self):
        self.auth(self.biz_a)
        response = self.client.post(
            "/api/v1/auth/users/",
            {"username": "sneaky", "email": "s@test.com", "password": "StrongPass123", "role": "super_admin"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
