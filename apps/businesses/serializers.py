from rest_framework import serializers
from apps.businesses.models import Business, Branch


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "business", "name", "code", "address", "phone", "is_main", "is_active", "created_at"]
        read_only_fields = ["id", "business", "created_at"]


class BusinessSerializer(serializers.ModelSerializer):
    branches = BranchSerializer(many=True, read_only=True)

    class Meta:
        model = Business
        fields = [
            "id", "name", "slug", "logo", "email", "phone", "address", "tax_number", "vat_percent",
            "currency", "timezone", "is_active", "branches",
            "receipt_footer_text", "theme", "enabled_payment_methods",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]
