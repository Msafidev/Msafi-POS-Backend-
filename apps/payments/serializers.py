from decimal import Decimal

from rest_framework import serializers

from apps.payments.models import PaymentProvider, PaymentTransaction


class PaymentProviderPublicSerializer(serializers.ModelSerializer):
    """
    What a cashier at checkout is allowed to see: which providers are
    active and what to call them, never any credential field. Used by
    ActivePaymentProvidersView, which — unlike PaymentProviderViewSet —
    isn't admin-only, because every cashier needs this list to take a
    card/mobile-money payment.
    """

    provider_label = serializers.CharField(source="get_provider_display", read_only=True)
    is_bank_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentProvider
        fields = ["id", "provider", "provider_label", "display_name", "is_bank_terminal"]


class PaymentProviderSerializer(serializers.ModelSerializer):
    """
    Credentials (api_key/api_secret/passkey) are write-only — a business
    admin can set or replace them, but the API never echoes them back
    once saved, the same way a password field would behave.
    """

    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = PaymentProvider
        fields = [
            "id",
            "provider",
            "display_name",
            "api_key",
            "api_secret",
            "shortcode",
            "passkey",
            "terminal_id",
            "merchant_id",
            "account_reference",
            "sandbox",
            "active",
            "has_credentials",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "api_key": {"write_only": True, "required": False},
            "api_secret": {"write_only": True, "required": False},
            "passkey": {"write_only": True, "required": False},
        }

    def get_has_credentials(self, obj):
        return bool(obj.api_key or obj.shortcode or obj.terminal_id)

    def create(self, validated_data):
        validated_data["business"] = self.context["request"].user.business
        return super().create(validated_data)


class PaymentTransactionSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.get_provider_display", read_only=True)
    provider_code = serializers.CharField(source="provider.provider", read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "provider",
            "provider_name",
            "provider_code",
            "sale",
            "amount",
            "currency",
            "phone_number",
            "status",
            "provider_reference",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ChargeRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=PaymentProvider.Provider.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    sale_id = serializers.UUIDField(required=False, allow_null=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=32)

    def validate(self, attrs):
        if attrs["provider"] == PaymentProvider.Provider.MPESA_STK and not attrs.get("phone_number"):
            raise serializers.ValidationError({"phone_number": "Required for M-Pesa STK Push."})
        return attrs


class ConfirmTerminalSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(max_length=128)
