from rest_framework import serializers

from apps.tax.models import ETIMSInvoice, TaxProfile, TaxRecord
from apps.tax.services import ESTIMATABLE_TAX_TYPES


class TaxProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxProfile
        fields = [
            "id",
            "corporation_tax_rate",
            "turnover_tax_rate",
            "withholding_tax_rate",
            "capital_gains_tax_rate",
            "excise_duty_rate",
            "digital_service_tax_rate",
            "etims_enabled",
            "etims_environment",
            "etims_branch_code",
            "etims_device_serial",
            "etims_communication_key",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]
        extra_kwargs = {"etims_communication_key": {"write_only": True, "required": False}}


class TaxRecordSerializer(serializers.ModelSerializer):
    tax_type_display = serializers.CharField(source="get_tax_type_display", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.username", read_only=True, default=None)

    class Meta:
        model = TaxRecord
        fields = [
            "id", "tax_type", "tax_type_display", "period_start", "period_end",
            "rate_used", "is_estimated", "amount", "note", "recorded_by_name", "created_at",
        ]
        read_only_fields = ["id", "is_estimated", "recorded_by_name", "created_at"]

    def create(self, validated_data):
        request = self.context["request"]
        return TaxRecord.objects.create(
            business=request.user.business,
            recorded_by=request.user,
            is_estimated=False,  # manual entries only — see TaxRecordViewSet.estimate for computed ones
            **validated_data,
        )


class EstimateTaxSerializer(serializers.Serializer):
    tax_type = serializers.ChoiceField(choices=TaxRecord.TaxType.choices)
    period_start = serializers.DateField()
    period_end = serializers.DateField()

    def validate_tax_type(self, value):
        if value not in ESTIMATABLE_TAX_TYPES:
            raise serializers.ValidationError(
                "MsafiPOS can't compute this tax type from sales data — add it as a manual entry instead."
            )
        return value


class ETIMSInvoiceSerializer(serializers.ModelSerializer):
    sale_number = serializers.CharField(source="sale.sale_number", read_only=True)

    class Meta:
        model = ETIMSInvoice
        fields = [
            "id", "sale", "sale_number", "status", "kra_invoice_number",
            "qr_code_data", "failure_reason", "submitted_at", "created_at",
        ]
        read_only_fields = fields
