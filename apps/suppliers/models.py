import uuid
from django.db import models

from apps.businesses.models import Business


class Supplier(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["business", "name"])]

    def __str__(self):
        return self.name

    @property
    def outstanding_balance(self):
        """Sum of unpaid supplier invoices. Populated once SupplierInvoice exists."""
        return self.invoices.filter(is_paid=False).aggregate(
            total=models.Sum("amount")
        )["total"] or 0


class SupplierInvoice(models.Model):
    """
    Minimal invoice/payment tracking so the supplier profile ("Outstanding
    Balances", "Invoices", "Payments" in the brief) has something real
    behind it, ahead of the full Purchase Order -> Goods Received ->
    Invoice flow that lands with Sales/Payments in Phase 3.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="invoices")
    reference = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.supplier.name} — {self.reference}"
