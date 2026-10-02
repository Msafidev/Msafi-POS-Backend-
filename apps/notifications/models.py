import uuid
from django.db import models

from apps.businesses.models import Business


class Notification(models.Model):
    class Type(models.TextChoices):
        LOW_STOCK = "low_stock", "Low Stock"
        OUT_OF_STOCK = "out_of_stock", "Out of Stock"
        EXPIRING_PRODUCT = "expiring_product", "Expiring Product"
        NEW_ORDER = "new_order", "New Order"
        SYSTEM_ALERT = "system_alert", "System Alert"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=32, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.CharField(max_length=500, blank=True)
    # Loosely-typed pointer back to whatever triggered this (a Product, a
    # PurchaseOrder, …) — kept as a plain UUID rather than a GenericForeignKey
    # so this app doesn't need a hard dependency on every other app's models.
    related_object_id = models.UUIDField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "is_read", "created_at"])]

    def __str__(self):
        return f"{self.type}: {self.title}"
