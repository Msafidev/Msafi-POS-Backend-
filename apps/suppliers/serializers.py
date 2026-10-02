from rest_framework import serializers
from apps.suppliers.models import Supplier, SupplierInvoice


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierInvoice
        fields = ["id", "supplier", "reference", "amount", "amount_paid", "is_paid", "due_date", "created_at"]
        read_only_fields = ["id", "created_at"]


class SupplierSerializer(serializers.ModelSerializer):
    invoices = SupplierInvoiceSerializer(many=True, read_only=True)
    outstanding_balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Supplier
        fields = [
            "id", "business", "name", "contact_person", "email", "phone", "address",
            "tax_number", "is_active", "notes", "invoices", "outstanding_balance",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]
