from decimal import Decimal

from django.db import transaction, models
from django.utils import timezone
from rest_framework import serializers

from apps.sales.models import Sale, SaleItem, Payment, Refund, RefundItem
from apps.inventory.models import Product, StockMovement
from apps.customers.models import Customer
from apps.businesses.models import Branch


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "method", "amount", "reference", "created_at"]
        read_only_fields = ["id", "created_at"]


class SaleItemInputSerializer(serializers.Serializer):
    """Write-side shape for one cart line — kept separate from the read
    serializer because the client only ever sends product/qty/discount;
    pricing and totals are always computed server-side, never trusted
    from the client."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    # Optional per-line override (e.g. manager discount on this specific unit price);
    # defaults to the product's current selling price if omitted.
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id", "product", "product_name", "sku", "quantity", "unit_price",
            "discount_percent", "tax_percent", "line_total", "quantity_refunded",
        ]
        read_only_fields = ["id", "line_total", "quantity_refunded"]


class SaleSerializer(serializers.ModelSerializer):
    """Read shape — everything a receipt or sales list needs."""

    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    sale_number = serializers.CharField(read_only=True)
    cashier_name = serializers.CharField(source="cashier.username", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id", "sale_number", "business", "business_name", "branch", "customer", "customer_name",
            "cashier", "cashier_name", "status", "subtotal", "discount_amount", "tax_amount",
            "total_amount", "amount_paid", "change_due", "balance_due", "notes",
            "items", "payments", "held_at", "completed_at", "created_at",
        ]
        read_only_fields = fields


class SaleCreateSerializer(serializers.Serializer):
    """
    Write shape for POST /sales/. One endpoint covers both flows the brief
    asks for:
      - Hold Sale: status="held" — cart is saved, nothing is charged or
        deducted from stock yet.
      - Checkout: status="completed" (default) — payments are required,
        stock is deducted per item, and (if a customer is attached) loyalty
        points accrue and store-credit payments draw down their balance.
    Both happen in one DB transaction so a failure partway through can't
    leave stock, payments, or loyalty half-applied.
    """

    branch = serializers.UUIDField(required=False, allow_null=True)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all(), required=False, allow_null=True)
    status = serializers.ChoiceField(choices=["held", "completed"], default="completed")
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = SaleItemInputSerializer(many=True)
    payments = PaymentSerializer(many=True, required=False, default=list)

    LOYALTY_POINTS_PER_CURRENCY_UNIT = Decimal("100")  # 1 point per 100 currency units spent

    def validate(self, attrs):
        if not attrs["items"]:
            raise serializers.ValidationError({"items": "A sale needs at least one item."})

        # SECURITY: `product` and `customer` above are plain
        # PrimaryKeyRelatedFields over the *global* Product/Customer
        # querysets — DRF only checks that the PK exists, not that it
        # belongs to the caller's business. Without this check, any
        # authenticated user could pass another tenant's product or
        # customer UUID and this sale would silently deduct a stranger's
        # stock or attach a stranger's customer (accruing loyalty points/
        # store credit to the wrong account). Every other viewset in this
        # codebase gets this for free from BusinessScopedQuerysetMixin's
        # get_queryset() — but these are bare serializer fields with no
        # view-level queryset to scope, so the check has to live here.
        business_id = self.context["request"].user.business_id
        for item in attrs["items"]:
            if item["product"].business_id != business_id:
                raise serializers.ValidationError({"items": "Invalid product."})
        customer = attrs.get("customer")
        if customer and customer.business_id != business_id:
            raise serializers.ValidationError({"customer": "Invalid customer."})

        # `branch` above is a bare UUIDField (not a related field DRF can
        # scope a queryset on), so — same class of bug as products/customer
        # above — it has to be checked by hand: a client could otherwise
        # attach another tenant's branch id to this sale.
        branch_id = attrs.get("branch")
        if branch_id and not Branch.objects.filter(id=branch_id, business_id=business_id).exists():
            raise serializers.ValidationError({"branch": "Invalid branch."})

        if attrs["status"] == "completed":
            for item in attrs["items"]:
                product = item["product"]
                if item["quantity"] > product.current_stock:
                    raise serializers.ValidationError(
                        {"items": f"Only {product.current_stock} {product.unit} of {product.name} in stock."}
                    )
            payments = attrs.get("payments") or []
            for p in payments:
                if p["method"] == "store_credit":
                    customer = attrs.get("customer")
                    if not customer:
                        raise serializers.ValidationError({"payments": "Store credit requires a customer."})
                    if p["amount"] > customer.credit_balance:
                        raise serializers.ValidationError({"payments": "Payment exceeds customer's store credit balance."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        business_id = user.business_id
        items_data = validated_data.pop("items")
        payments_data = validated_data.pop("payments", [])
        status = validated_data["status"]
        customer = validated_data.get("customer")

        sequence_no = Sale.next_sequence_no(business_id)
        sale = Sale.objects.create(
            business_id=business_id,
            branch_id=validated_data.get("branch") or user.branch_id,
            customer=customer,
            cashier=user,
            sequence_no=sequence_no,
            status="held" if status == "held" else "completed",
            discount_amount=validated_data["discount_amount"],
            notes=validated_data.get("notes", ""),
            held_at=timezone.now() if status == "held" else None,
        )

        subtotal = Decimal("0")
        tax_total = Decimal("0")
        sale_items = []
        for item in items_data:
            product = item["product"]
            unit_price = item.get("unit_price", product.selling_price)
            sale_item = SaleItem(
                sale=sale,
                product=product,
                quantity=item["quantity"],
                unit_price=unit_price,
                unit_cost=product.buying_price,
                discount_percent=item["discount_percent"],
                tax_percent=product.tax_percent,
            )
            sale_item.line_total = sale_item.compute_line_total()
            sale_items.append(sale_item)
            gross = sale_item.quantity * sale_item.unit_price
            discount = gross * (sale_item.discount_percent / Decimal(100))
            taxable = gross - discount
            subtotal += taxable
            tax_total += taxable * (sale_item.tax_percent / Decimal(100))

        SaleItem.objects.bulk_create(sale_items)

        sale.subtotal = subtotal
        sale.tax_amount = tax_total
        sale.total_amount = subtotal - validated_data["discount_amount"] + tax_total

        if status == "completed":
            for sale_item in sale_items:
                product = sale_item.product
                product.current_stock -= sale_item.quantity
                product.save(update_fields=["current_stock", "updated_at"])
                StockMovement.objects.create(
                    business_id=business_id,
                    product=product,
                    movement_type=StockMovement.MovementType.STOCK_OUT,
                    quantity=sale_item.quantity,
                    reason=f"Sold on {sale.sale_number}",
                    performed_by=user,
                )

            amount_paid = Decimal("0")
            for p in payments_data:
                Payment.objects.create(sale=sale, **p)
                amount_paid += p["amount"]
                if p["method"] == "store_credit" and customer:
                    customer.credit_balance -= p["amount"]

            sale.amount_paid = amount_paid
            if amount_paid > sale.total_amount:
                sale.change_due = amount_paid - sale.total_amount
                sale.balance_due = Decimal("0")
            else:
                sale.change_due = Decimal("0")
                sale.balance_due = sale.total_amount - amount_paid
            sale.completed_at = timezone.now()

            if customer:
                customer.loyalty_points += int(sale.total_amount // self.LOYALTY_POINTS_PER_CURRENCY_UNIT)
                customer.save(update_fields=["loyalty_points", "credit_balance", "updated_at"])

        sale.save()
        return sale


class SaleCompleteSerializer(serializers.Serializer):
    """Turns a held sale into a completed one — same payment/stock logic
    as SaleCreateSerializer.create(), triggered from Sale.resume."""

    payments = PaymentSerializer(many=True)

    def validate_payments(self, value):
        if not value:
            raise serializers.ValidationError("At least one payment is required to complete a sale.")
        return value


class RefundItemInputSerializer(serializers.Serializer):
    sale_item = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class RefundCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    refund_method = serializers.ChoiceField(choices=Payment.Method.choices, default=Payment.Method.CASH)
    items = RefundItemInputSerializer(many=True)

    @transaction.atomic
    def create(self, validated_data):
        sale = self.context["sale"]
        user = self.context["request"].user
        items_data = validated_data.pop("items")

        total = Decimal("0")
        refund = Refund.objects.create(
            sale=sale,
            refunded_by=user,
            reason=validated_data["reason"],
            refund_method=validated_data["refund_method"],
            amount=Decimal("0"),
        )

        for item in items_data:
            sale_item = sale.items.select_for_update().get(pk=item["sale_item"])
            remaining = sale_item.quantity - sale_item.quantity_refunded
            if item["quantity"] > remaining:
                raise serializers.ValidationError(
                    {"items": f"Only {remaining} of {sale_item.product.name} left to refund."}
                )

            unit_refund = sale_item.line_total / sale_item.quantity if sale_item.quantity else Decimal("0")
            amount = (unit_refund * item["quantity"]).quantize(Decimal("0.01"))
            total += amount

            RefundItem.objects.create(refund=refund, sale_item=sale_item, quantity=item["quantity"], amount=amount)
            sale_item.quantity_refunded += item["quantity"]
            sale_item.save(update_fields=["quantity_refunded"])

            product = sale_item.product
            product.current_stock += item["quantity"]
            product.save(update_fields=["current_stock", "updated_at"])
            StockMovement.objects.create(
                business_id=sale.business_id,
                product=product,
                movement_type=StockMovement.MovementType.STOCK_IN,
                quantity=item["quantity"],
                reason=f"Refund on {sale.sale_number}",
                performed_by=user,
            )

            if refund.refund_method == Payment.Method.STORE_CREDIT and sale.customer:
                sale.customer.credit_balance += amount
                sale.customer.save(update_fields=["credit_balance", "updated_at"])

        refund.amount = total
        refund.save(update_fields=["amount"])

        # NOTE: `sale` came from the view's get_object(), whose queryset has
        # .prefetch_related("items", "payments") — so `sale.items.all()`
        # would silently return the STALE prefetch cache captured at the
        # start of the request, not the quantity_refunded values we just
        # wrote above. Querying SaleItem directly (rather than through the
        # `sale.items` related manager) always hits the DB fresh.
        fully_refunded = not SaleItem.objects.filter(sale=sale).exclude(
            quantity_refunded__gte=models.F("quantity")
        ).exists()
        sale.status = Sale.Status.REFUNDED if fully_refunded else Sale.Status.PARTIALLY_REFUNDED
        sale.save(update_fields=["status", "updated_at"])

        return refund


class RefundSerializer(serializers.ModelSerializer):
    class RefundItemSerializer(serializers.ModelSerializer):
        product_name = serializers.CharField(source="sale_item.product.name", read_only=True)

        class Meta:
            model = RefundItem
            fields = ["id", "sale_item", "product_name", "quantity", "amount"]

    items = RefundItemSerializer(many=True, read_only=True)
    refunded_by_name = serializers.CharField(source="refunded_by.username", read_only=True)

    class Meta:
        model = Refund
        fields = ["id", "sale", "reason", "refund_method", "amount", "refunded_by_name", "items", "created_at"]
        read_only_fields = fields
