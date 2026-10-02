from rest_framework import viewsets

from apps.suppliers.models import Supplier, SupplierInvoice
from apps.suppliers.serializers import SupplierSerializer, SupplierInvoiceSerializer
from apps.mixins import BusinessScopedQuerysetMixin
from apps.authentication.permissions import IsBusinessAdmin


class SupplierViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    queryset = Supplier.objects.all()
    permission_classes = [IsBusinessAdmin]
    filterset_fields = ["is_active"]
    search_fields = ["name", "contact_person", "email", "phone"]
    ordering_fields = ["name", "created_at"]


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierInvoiceSerializer
    permission_classes = [IsBusinessAdmin]
    filterset_fields = ["is_paid", "supplier"]

    def get_queryset(self):
        user = self.request.user
        qs = SupplierInvoice.objects.select_related("supplier")
        if user.role == "super_admin":
            return qs
        return qs.filter(supplier__business_id=user.business_id)
