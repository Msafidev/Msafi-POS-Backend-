from django.db import transaction
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.sales.models import Sale, Refund
from apps.sales.serializers import (
    SaleSerializer, SaleCreateSerializer, SaleCompleteSerializer,
    RefundCreateSerializer, RefundSerializer,
)
from apps.authentication.models import Role
from apps.authentication.permissions import HasRole


class SaleViewSet(viewsets.ModelViewSet):
    """
    Deliberately not using BusinessScopedQuerysetMixin's perform_create
    (checkout needs a lot more than `business_id=...` set on save), but the
    get_queryset tenant-scoping is the same pattern as everywhere else.
    """

    queryset = Sale.objects.select_related("customer", "cashier").prefetch_related("items", "payments")
    permission_classes = [HasRole.any_of(Role.CASHIER, Role.MANAGER, Role.ADMIN)]
    filterset_fields = ["status", "customer"]
    ordering_fields = ["created_at", "total_amount"]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(business_id=user.business_id)

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        return SaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = serializer.save()
        return Response(SaleSerializer(sale).data, status=201)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Resume a held sale: attach payment(s), deduct stock, mark completed."""
        sale = self.get_object()
        if sale.status != Sale.Status.HELD:
            return Response({"detail": "Only held sales can be completed."}, status=400)

        serializer = SaleCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Reuse the exact same stock/payment/loyalty logic as a normal
        # checkout by replaying this held sale's items through the create
        # path's completion branch, rather than duplicating it here.
        from decimal import Decimal
        from django.utils import timezone
        from apps.inventory.models import StockMovement
        from apps.sales.models import Payment

        with transaction.atomic():
            for sale_item in sale.items.select_related("product"):
                product = sale_item.product
                if sale_item.quantity > product.current_stock:
                    return Response(
                        {"detail": f"Only {product.current_stock} {product.unit} of {product.name} in stock."},
                        status=400,
                    )
            for sale_item in sale.items.select_related("product"):
                product = sale_item.product
                product.current_stock -= sale_item.quantity
                product.save(update_fields=["current_stock", "updated_at"])
                StockMovement.objects.create(
                    business_id=sale.business_id,
                    product=product,
                    movement_type=StockMovement.MovementType.STOCK_OUT,
                    quantity=sale_item.quantity,
                    reason=f"Sold on {sale.sale_number} (resumed)",
                    performed_by=request.user,
                )

            amount_paid = Decimal("0")
            for p in serializer.validated_data["payments"]:
                Payment.objects.create(sale=sale, **p)
                amount_paid += p["amount"]
                if p["method"] == "store_credit" and sale.customer:
                    sale.customer.credit_balance -= p["amount"]
                    sale.customer.save(update_fields=["credit_balance", "updated_at"])

            sale.amount_paid = amount_paid
            if amount_paid > sale.total_amount:
                sale.change_due = amount_paid - sale.total_amount
                sale.balance_due = Decimal("0")
            else:
                sale.change_due = Decimal("0")
                sale.balance_due = sale.total_amount - amount_paid
            sale.status = Sale.Status.COMPLETED
            sale.completed_at = timezone.now()
            sale.save()

        # `sale` was fetched via get_object() with items/payments prefetched
        # *before* the Payment rows above were created — that cached
        # queryset is now stale, so re-fetch before serializing (same fix
        # as PurchaseOrderViewSet.receive() in the inventory app).
        sale = self.get_queryset().get(pk=sale.pk)
        return Response(SaleSerializer(sale).data)

    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        sale = self.get_object()
        if sale.status not in (Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED):
            return Response({"detail": "Only completed sales can be refunded."}, status=400)

        serializer = RefundCreateSerializer(data=request.data, context={"request": request, "sale": sale})
        serializer.is_valid(raise_exception=True)
        refund = serializer.save()
        return Response(RefundSerializer(refund).data, status=201)

    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        """Same data as the sale detail view — a distinct URL so the
        frontend's printable-receipt view has an obvious, stable endpoint
        to point at, independent of how the sale detail shape evolves."""
        return Response(SaleSerializer(self.get_object()).data)


class RefundViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RefundSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Refund.objects.select_related("sale").prefetch_related("items")
        if user.role == Role.SUPER_ADMIN:
            return qs
        return qs.filter(sale__business_id=user.business_id)
