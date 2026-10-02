from rest_framework import serializers
from django.db import transaction

from apps.inventory.models import (
    Category, Brand, Product, ProductVariant, ProductSerialNumber,
    StockMovement, PurchaseOrder, PurchaseOrderItem,
)
from apps.mixins import validate_same_tenant


class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True)
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "business", "parent", "name", "is_active", "product_count", "children"]
        read_only_fields = ["id", "business"]

    def get_children(self, obj):
        return CategorySerializer(obj.children.all(), many=True).data


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "business", "name", "is_active"]
        read_only_fields = ["id", "business"]


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = ["id", "product", "name", "sku_suffix", "barcode", "price_override", "current_stock"]
        read_only_fields = ["id"]


class ProductSerialNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSerialNumber
        fields = ["id", "product", "serial_number", "is_sold", "received_at"]
        read_only_fields = ["id", "received_at"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    brand_name = serializers.CharField(source="brand.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    is_low_stock = serializers.BooleanField(read_only=True)
    is_offer_active = serializers.BooleanField(read_only=True)
    effective_discount_percent = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    stock_value = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "business", "branch", "sku", "barcode", "qr_code", "name", "description",
            "category", "category_name", "brand", "brand_name", "supplier", "supplier_name",
            "buying_price", "selling_price", "tax_percent",
            "discount_type", "discount_percent", "discount_amount", "is_on_offer", "offer_expires_at",
            "is_offer_active", "effective_discount_percent", "image",
            "current_stock", "minimum_stock", "maximum_stock", "unit", "status", "location",
            "expiry_date", "has_variants", "has_serial_numbers", "is_low_stock", "stock_value",
            "variants", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]

    def validate_image(self, value):
        if value and value.size > 2 * 1024 * 1024:
            raise serializers.ValidationError("Image is too large — please use one under 2MB (it will also be auto-compressed).")
        return value

    def validate_sku(self, value):
        request = self.context["request"]
        qs = Product.objects.filter(business_id=request.user.business_id, sku=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def validate(self, attrs):
        validate_same_tenant(
            self.context["request"],
            category=attrs.get("category"), brand=attrs.get("brand"), supplier=attrs.get("supplier"),
        )
        return attrs

    def create(self, validated_data):
        # New products inherit the business's default VAT % unless the
        # request explicitly set one — a zero-rated/exempt item can still
        # override this per-product, same as today.
        if "tax_percent" not in self.initial_data:
            business = self.context["request"].user.business
            if business is not None:
                validated_data["tax_percent"] = business.vat_percent
        return super().create(validated_data)


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    performed_by_name = serializers.CharField(source="performed_by.username", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "business", "product", "product_name", "movement_type", "quantity",
            "from_branch", "to_branch", "reason", "performed_by", "performed_by_name", "created_at",
        ]
        read_only_fields = ["id", "business", "performed_by", "created_at"]

    def validate(self, attrs):
        request = self.context["request"]
        product = attrs["product"]
        # SECURITY: without this, any authenticated user could pass any
        # tenant's product UUID here and directly move its stock (in, out,
        # or an absolute adjustment) — this is the most severe instance of
        # the missing-tenant-check pattern found while writing Phase 5
        # tests, since it's a direct stock-manipulation primitive rather
        # than just cross-tenant metadata linkage.
        validate_same_tenant(request, product=product)
        movement_type = attrs["movement_type"]
        quantity = attrs["quantity"]
        if movement_type in (StockMovement.MovementType.STOCK_OUT, StockMovement.MovementType.TRANSFER):
            if quantity > product.current_stock:
                raise serializers.ValidationError(
                    {"quantity": f"Only {product.current_stock} {product.unit} available."}
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        product = validated_data["product"]
        movement_type = validated_data["movement_type"]
        quantity = validated_data["quantity"]

        if movement_type == StockMovement.MovementType.STOCK_IN:
            product.current_stock += quantity
        elif movement_type in (StockMovement.MovementType.STOCK_OUT, StockMovement.MovementType.TRANSFER):
            product.current_stock -= quantity
        elif movement_type == StockMovement.MovementType.ADJUSTMENT:
            product.current_stock = quantity  # adjustment sets the absolute new count

        product.save(update_fields=["current_stock", "updated_at"])

        return StockMovement.objects.create(
            business_id=request.user.business_id,
            performed_by=request.user,
            **validated_data,
        )


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = ["id", "purchase_order", "product", "product_name", "quantity_ordered", "quantity_received", "unit_cost"]
        read_only_fields = ["id", "purchase_order", "quantity_received"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "business", "branch", "supplier", "supplier_name", "reference", "status",
            "notes", "items", "total_cost", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "business", "status", "created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context["request"]
        validate_same_tenant(request, supplier=attrs.get("supplier"))
        for item in attrs.get("items", []):
            validate_same_tenant(request, product=item.get("product"))
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context["request"]
        # business_id already lands in validated_data via the calling view's
        # perform_create -> serializer.save(business_id=...); don't set it twice.
        validated_data.setdefault("business_id", request.user.business_id)
        po = PurchaseOrder.objects.create(
            created_by=request.user,
            status=PurchaseOrder.Status.ORDERED,
            **validated_data,
        )
        PurchaseOrderItem.objects.bulk_create(
            [PurchaseOrderItem(purchase_order=po, **item) for item in items_data]
        )
        return po
