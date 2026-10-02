import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.businesses.models import Business, Branch


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Admin"
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    CASHIER = "cashier", "Cashier"
    STORE_KEEPER = "store_keeper", "Store Keeper"
    ACCOUNTANT = "accountant", "Accountant"


class User(AbstractUser):
    """
    Custom user. A Super Admin has business=null (platform-level).
    Every other role is scoped to exactly one Business, and optionally
    pinned to one Branch (cashiers/store keepers usually are; admins
    typically see all branches of their business).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="users", null=True, blank=True
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, related_name="users", null=True, blank=True
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.CASHIER)
    phone = models.CharField(max_length=32, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    is_email_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["username"]
        indexes = [models.Index(fields=["business", "role"])]

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class ActivityLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="activity_logs")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="activity_logs", null=True)
    action = models.CharField(max_length=64)  # e.g. "login", "sale.create", "product.delete"
    description = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "action", "created_at"])]

    def __str__(self):
        return f"{self.action} by {self.user}"
