from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.addons.models import AddOnPayment, AddOnSubscription
from apps.addons.plans import ADDON_FEATURES


def activate_addon(payment, verifier=None):
    """
    Shared by the auto (M-Pesa callback) and manual (Super Admin) paths:
    extends the business's AddOnSubscription for `payment.feature` and
    marks the payment VERIFIED. `verifier=None` means system-verified.
    """
    with transaction.atomic():
        days = ADDON_FEATURES[payment.feature]["days"]
        addon, _ = AddOnSubscription.objects.select_for_update().get_or_create(
            business=payment.business, feature=payment.feature
        )
        base = addon.expires_at
        if base is None or base < timezone.now():
            base = timezone.now()
        addon.expires_at = base + timedelta(days=days)
        addon.save(update_fields=["expires_at", "updated_at"])

        payment.status = AddOnPayment.Status.VERIFIED
        payment.verified_by = verifier
        payment.verified_at = timezone.now()
        payment.save(update_fields=["status", "verified_by", "verified_at", "transaction_code"])
    return payment


class InitiateSTKSerializer(serializers.Serializer):
    """Kicks off an STK push — see apps.addons.views.InitiateAddOnPaymentView."""

    feature = serializers.ChoiceField(choices=list(ADDON_FEATURES.keys()))
    phone_number = serializers.RegexField(
        r"^0\d{9}$|^2547\d{8}$|^2541\d{8}$",
        error_messages={"invalid": "Enter a valid Safaricom number, e.g. 0712345678."},
    )


class AddOnPaymentSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.username", read_only=True, default=None)
    verified_by_name = serializers.CharField(source="verified_by.username", read_only=True, default=None)

    class Meta:
        model = AddOnPayment
        fields = [
            "id", "business", "business_name", "feature", "amount", "payment_method",
            "transaction_code", "payer_phone", "status", "submitted_by", "submitted_by_name",
            "verified_by", "verified_by_name", "verified_at", "rejection_reason", "created_at",
        ]
        # Read-only history view — a payment is only ever created by
        # InitiateAddOnPaymentView (STK push), never posted directly by a client.
        read_only_fields = fields


class VerifyAddOnPaymentSerializer(serializers.Serializer):
    """Manual fallback — e.g. the STK callback never arrived but the shop can prove they paid."""

    def save(self):
        payment = self.context["payment"]
        verifier = self.context["request"].user
        return activate_addon(payment, verifier=verifier)


class RejectAddOnPaymentSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def save(self):
        payment = self.context["payment"]
        payment.status = AddOnPayment.Status.REJECTED
        payment.rejection_reason = self.validated_data["rejection_reason"]
        payment.save(update_fields=["status", "rejection_reason"])
        return payment
