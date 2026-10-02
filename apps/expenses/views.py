from rest_framework import viewsets

from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.serializers import ExpenseSerializer, ExpenseCategorySerializer
from apps.mixins import BusinessScopedQuerysetMixin
from apps.authentication.permissions import HasRole
from apps.authentication.models import Role


class ExpenseCategoryViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ExpenseCategorySerializer
    queryset = ExpenseCategory.objects.all()
    permission_classes = [HasRole.any_of(Role.ACCOUNTANT, Role.ADMIN)]


class ExpenseViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    queryset = Expense.objects.select_related("category", "recorded_by")
    permission_classes = [HasRole.any_of(Role.ACCOUNTANT, Role.ADMIN)]
    filterset_fields = ["category", "is_recurring"]
    search_fields = ["title", "description"]
    ordering_fields = ["expense_date", "amount", "created_at"]

    def perform_create(self, serializer):
        serializer.save(business_id=self.request.user.business_id, recorded_by=self.request.user)
