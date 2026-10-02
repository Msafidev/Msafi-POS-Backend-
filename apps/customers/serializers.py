from rest_framework import serializers
from apps.customers.models import Customer, CustomerGroup, CustomerNote
from apps.mixins import validate_same_tenant


class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = ["id", "business", "name", "default_discount_percent"]
        read_only_fields = ["id", "business"]


class CustomerNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = CustomerNote
        fields = ["id", "customer", "author", "author_name", "note", "created_at"]
        read_only_fields = ["id", "author", "author_name", "created_at"]


class CustomerSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True)
    notes_list = CustomerNoteSerializer(source="customer_notes", many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id", "business", "group", "group_name", "name", "email", "phone", "address",
            "credit_balance", "loyalty_points", "is_active", "notes_list", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "business", "credit_balance", "loyalty_points", "created_at", "updated_at"]

    def validate(self, attrs):
        validate_same_tenant(self.context["request"], group=attrs.get("group"))
        return attrs
