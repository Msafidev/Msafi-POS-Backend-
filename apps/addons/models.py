import uuid

from django.db import models
from django.utils import timezone

from apps.businesses.models import Business
from apps.authentication.models import User
from apps.addons.plans import ADDON_FEATURE_CHOICES


class AddOnSubscription(models.Model):
    """
    One row per (business, feature) — whether that business currently has
    the "payments" or "tax" add-on switched on, and until when. Mirrors
    Business.subscription_expires_at's "is_active" shape but per-feature
    instead of for the whole account, since a shop might buy Payments
    without Tax or vice versa.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="addon_subscriptions")
    feature = models.CharField(max_length=32, choices=ADDON_FEATURE_CHOICES)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("business", "feature")

    def __str__(self):
        return f"{self.business.name} — {self.feature}"

    @property
    def is_active(self):
        return self.expires_at is not None and self.expires_at > timezone.now()


class AddOnPayment(models.Model):
    """
    A shop's payment for a feature add-on. Auto-verified end to end via
    M-Pesa STK Push (see apps.addons.mpesa) — the shop enters their phone
    number, gets a prompt, and once Safaricom's callback confirms payment
    the matching AddOnSubscription is extended automatically, with no
    Super Admin step in the normal path. `verify`/`reject` stay available
    as a manual fallback for edge cases (e.g. callback delivery issues).
    """

    class Method(models.TextChoices):
        STK_PUSH = "stk_push", "M-Pesa STK Push"
        POCHI_LA_BIASHARA = "pochi_la_biashara", "Pochi la Biashara"
        TILL_NUMBER = "till_number", "Till Number"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"  # STK prompt sent, waiting on the customer/M-Pesa
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="addon_payments")
    feature = models.CharField(max_length=32, choices=ADDON_FEATURE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=32, choices=Method.choices, default=Method.STK_PUSH)
    transaction_code = models.CharField(
        max_length=64, blank=True, default="",
        help_text="The M-Pesa confirmation code. Filled in automatically once M-Pesa confirms the STK push.",
    )
    payer_phone = models.CharField(max_length=32, blank=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    merchant_request_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="submitted_addon_payments")
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_addon_payments"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "status"])]

    def __str__(self):
        return f"{self.business.name} — {self.feature} ({self.status})"
