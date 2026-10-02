from django.db import transaction, models
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.models import (
    Category, Brand, Product, ProductVariant, ProductSerialNumber,
    StockMovement, PurchaseOrder, PurchaseOrderItem,
)
from apps.inventory.serializers import (
    CategorySerializer, BrandSerializer, ProductSerializer, ProductVariantSerializer,
    ProductSerialNumberSerializer, StockMovementSerializer, PurchaseOrderSerializer,
)
from apps.mixins import BusinessScopedQuerysetMixin
from apps.authentication.permissions import HasRole, IsBusinessAdmin
from apps.authentication.models import Role, ActivityLog


class CategoryViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.filter(parent__isnull=True)  # top-level; children nest via serializer
    permission_classes = [IsBusinessAdmin]

    def get_queryset(self):
        # Override to keep "only top-level in the list, nested children in the payload"
        # while still respecting tenant scoping from the mixin.
        qs = Category.objects.filter(parent__isnull=True)
        user = self.request.user
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(business_id=user.business_id)


class BrandViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    queryset = Brand.objects.all()
    permission_classes = [IsBusinessAdmin]
    search_fields = ["name"]


class ProductViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    queryset = Product.objects.select_related("category", "brand", "supplier").prefetch_related("variants")
    permission_classes = [HasRole.any_of(Role.MANAGER, Role.STORE_KEEPER, Role.ADMIN, Role.CASHIER)]
    filterset_fields = ["category", "brand", "supplier", "status"]
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "current_stock", "selling_price", "created_at"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        qs = self.filter_queryset(self.get_queryset()).filter(current_stock__lte=models.F("minimum_stock"))
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)


class ProductVariantViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = ProductVariant.objects.select_related("product")
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(product__business_id=user.business_id)


class ProductSerialNumberViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerialNumberSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = ProductSerialNumber.objects.select_related("product")
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(product__business_id=user.business_id)


class StockMovementViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = StockMovementSerializer
    queryset = StockMovement.objects.select_related("product", "performed_by")
    permission_classes = [HasRole.any_of(Role.MANAGER, Role.STORE_KEEPER, Role.ADMIN)]
    filterset_fields = ["movement_type", "product"]
    ordering_fields = ["created_at"]

    def perform_create(self, serializer):
        instance = serializer.save()
        ActivityLog.objects.create(
            user=self.request.user,
            business_id=self.request.user.business_id,
            action=f"inventory.{instance.movement_type}",
            description=f"{instance.product.name}: {instance.quantity}",
        )


class PurchaseOrderViewSet(BusinessScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = PurchaseOrderSerializer
    queryset = PurchaseOrder.objects.select_related("supplier").prefetch_related("items")
    permission_classes = [HasRole.any_of(Role.MANAGER, Role.STORE_KEEPER, Role.ADMIN)]
    filterset_fields = ["status", "supplier"]

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """
        Mark a PO (fully or partially) received: for each item, bumps
        quantity_received up to quantity_ordered, creates a matching
        StockMovement, and updates the product's current_stock — all in
        one transaction so a partial failure can't leave stock half-updated.
        """
        po = self.get_object()
        with transaction.atomic():
            for item in po.items.select_related("product").all():
                remaining = item.quantity_ordered - item.quantity_received
                if remaining <= 0:
                    continue
                item.quantity_received = item.quantity_ordered
                item.save(update_fields=["quantity_received"])

                item.product.current_stock += remaining
                item.product.save(update_fields=["current_stock", "updated_at"])

                StockMovement.objects.create(
                    business_id=po.business_id,
                    product=item.product,
                    movement_type=StockMovement.MovementType.STOCK_IN,
                    quantity=remaining,
                    reason=f"Received against PO {po.reference}",
                    performed_by=request.user,
                )
            po.status = PurchaseOrder.Status.RECEIVED
            po.save(update_fields=["status", "updated_at"])

        # Prefetched `items` on `po` are cached from before the updates above;
        # re-fetch so the response reflects the new quantity_received values.
        po = self.get_queryset().get(pk=po.pk)
        return Response(self.get_serializer(po).data)
