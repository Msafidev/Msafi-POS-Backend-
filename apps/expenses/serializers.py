from rest_framework import serializers
from apps.expenses.models import Expense, ExpenseCategory
from apps.mixins import validate_same_tenant


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "business", "name", "is_active"]
        read_only_fields = ["id", "business"]


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.username", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "business", "branch", "category", "category_name", "title", "description",
            "amount", "expense_date", "is_recurring", "recurrence_period", "attachment",
            "recorded_by", "recorded_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "business", "recorded_by", "created_at", "updated_at"]

    def validate(self, attrs):
        validate_same_tenant(self.context["request"], category=attrs.get("category"))
        return attrs
