from rest_framework import viewsets, permissions

from apps.businesses.models import Business, Branch
from apps.businesses.serializers import BusinessSerializer, BranchSerializer
from apps.authentication.models import Role
from apps.authentication.permissions import IsSuperAdmin, IsBusinessAdmin


class BusinessViewSet(viewsets.ModelViewSet):
    """
    Super Admins see/manage every tenant. Everyone else only ever sees
    their own business (read-only view of their own settings record).
    """

    serializer_class = BusinessSerializer

    def get_permissions(self):
        if self.action in ("create", "destroy", "list"):
            return [IsSuperAdmin()]
        if self.action in ("update", "partial_update"):
            return [IsBusinessAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.SUPER_ADMIN:
            return Business.objects.all()
        return Business.objects.filter(id=user.business_id)


class BranchViewSet(viewsets.ModelViewSet):
    serializer_class = BranchSerializer
    permission_classes = [IsBusinessAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.SUPER_ADMIN:
            return Branch.objects.all()
        return Branch.objects.filter(business_id=user.business_id)

    def perform_create(self, serializer):
        serializer.save(business_id=self.request.user.business_id)
