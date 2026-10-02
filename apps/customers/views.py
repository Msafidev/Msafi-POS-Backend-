from rest_framework import viewsets, permissions

from apps.customers.models import Customer, CustomerGroup, CustomerNote
from apps.customers.serializers import CustomerSerializer, CustomerGroupSerializer, CustomerNoteSerializer
from apps.mixins import BusinessScopedQuerysetMixin
from apps.authentication.permissions import HasRole
from apps.authentication.models import Role


class CustomerViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    queryset = Customer.objects.select_related("group")
    permission_classes = [HasRole.any_of(Role.MANAGER, Role.ADMIN, Role.CASHIER)]
    filterset_fields = ["is_active", "group"]
    search_fields = ["name", "phone", "email"]
    ordering_fields = ["name", "created_at", "loyalty_points"]


class CustomerGroupViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CustomerGroupSerializer
    queryset = CustomerGroup.objects.all()
    permission_classes = [permissions.IsAuthenticated]


class CustomerNoteViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = CustomerNote.objects.select_related("customer", "author")
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(customer__business_id=user.business_id)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
