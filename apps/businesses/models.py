import uuid
from django.db import models


def _all_payment_methods():
    return ["cash", "card", "mobile_money", "gift_card", "store_credit", "bank_transfer"]


class Business(models.Model):
    """
    A tenant. Every business-owned record across the system carries a
    foreign key back to this model (directly or via Branch), which is
    how we get multi-tenancy on a shared schema without the operational
    overhead of schema-per-tenant (django-tenants). If this ever needs
    to become schema-per-tenant for scale/isolation reasons, this model
    is the natural migration seam.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    logo = models.ImageField(upload_to="business_logos/", blank=True, null=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=64, blank=True, help_text="KRA PIN.")
    vat_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Default VAT % applied at checkout and shown on receipts. Free on every plan — "
        "everything else tax-related sits behind the 'tax' add-on (see apps.addons).",
    )
    currency = models.CharField(max_length=8, default="KES")
    timezone = models.CharField(max_length=64, default="Africa/Nairobi")
    is_active = models.BooleanField(default=True)
    # Settings module (brief: "Receipt Settings", "Themes", "Payment Methods")
    receipt_footer_text = models.CharField(max_length=255, blank=True, default="Thank you for shopping with us")
    theme = models.CharField(
        max_length=16, choices=[("light", "Light"), ("dark", "Dark"), ("auto", "Auto")], default="light"
    )
    enabled_payment_methods = models.JSONField(
        default=_all_payment_methods,
        blank=True,
        help_text="Subset of cash/card/mobile_money/gift_card/store_credit/bank_transfer accepted at checkout.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Branch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_main = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("business", "code")
        ordering = ["-is_main", "name"]

    def __str__(self):
        return f"{self.business.name} — {self.name}"
