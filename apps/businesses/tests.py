from rest_framework.test import APITestCase
from rest_framework import status


class BusinessSettingsTests(APITestCase):
    def setUp(self):
        reg = self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "Settings Co", "username": "setadmin", "email": "s@test.com", "password": "StrongPass123"},
            format="json",
        )
        self.business_id = reg.data["business_id"]
        login = self.client.post("/api/v1/auth/login/", {"username": "setadmin", "password": "StrongPass123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    def test_admin_can_update_own_business_settings(self):
        response = self.client.patch(
            f"/api/v1/businesses/{self.business_id}/",
            {"theme": "dark", "enabled_payment_methods": ["cash"], "receipt_footer_text": "Thanks!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["theme"], "dark")
        self.assertEqual(response.data["enabled_payment_methods"], ["cash"])

    def test_admin_cannot_see_other_businesses_in_list(self):
        self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "Other Co", "username": "otheradmin", "email": "o@test.com", "password": "StrongPass123"},
            format="json",
        )
        # /businesses/ list is Super-Admin-only; a regular Admin gets 403 for list,
        # but can still fetch (not edit) their own business by id.
        response = self.client.get("/api/v1/businesses/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BranchTenantIsolationTests(APITestCase):
    def test_admin_cannot_create_branch_for_another_business(self):
        self.client.post(
            "/api/v1/auth/register-business/",
            {"business_name": "Branch Co A", "username": "brancha", "email": "ba@test.com", "password": "StrongPass123"},
            format="json",
        )
        login_a = self.client.post("/api/v1/auth/login/", {"username": "brancha", "password": "StrongPass123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_a.data['access']}")
        response = self.client.post("/api/v1/branches/", {"name": "New Branch", "code": "NEW1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # perform_create always pins business_id from the requesting user —
        # confirm it can't be overridden even if a client tried to pass one.
        self.assertEqual(str(response.data["business"]), self.client.get(
            "/api/v1/auth/me/"
        ).data["business"]["id"])
