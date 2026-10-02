import uuid
from django.db import models
from django.core.validators import MinValueValidator

from apps.businesses.models import Business, Branch
from apps.suppliers.models import Supplier


class Category(models.Model):
    """Nested via self-FK `parent` — supports the brief's 'Nested Categories'."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="categories")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "categories"
        unique_together = ("business", "parent", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def product_count(self):
        return self.products.count()


class Brand(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="brands")
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("business", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        KG = "kg", "Kilogram"
        LITRE = "litre", "Litre"
        BOX = "box", "Box"
        PACK = "pack", "Pack"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISCONTINUED = "discontinued", "Discontinued"

    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage (%)"
        FIXED = "fixed", "Fixed amount (KES)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="products")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    sku = models.CharField(max_length=64)
    barcode = models.CharField(max_length=64, blank=True)
    qr_code = models.CharField(max_length=128, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    buying_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Discount / offer — either a straight percentage off (discount_percent,
    # existing field) or a fixed KES amount off (discount_amount). Only one
    # applies at a time, chosen by discount_type. is_on_offer is the switch
    # cashiers/POS actually check; offer_expires_at is optional and, once
    # past, the discount stops applying without anyone remembering to
    # switch it off by hand (see is_offer_active below).
    discount_type = models.CharField(max_length=16, choices=DiscountType.choices, default=DiscountType.PERCENTAGE)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Fixed KES amount off, used when discount_type is 'fixed'.")
    is_on_offer = models.BooleanField(default=False, help_text="Switch the discount/offer on or off without clearing its values.")
    offer_expires_at = models.DateField(null=True, blank=True, help_text="Optional — offer stops applying automatically after this date.")
    image = models.ImageField(upload_to="products/", blank=True, null=True)
    current_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum_stock = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=16, choices=Unit.choices, default=Unit.PIECE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    location = models.CharField(max_length=100, blank=True)  # e.g. aisle/shelf code
    expiry_date = models.DateField(null=True, blank=True)
    has_variants = models.BooleanField(default=False)
    has_serial_numbers = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("business", "sku")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["business", "sku"]),
            models.Index(fields=["business", "barcode"]),
            models.Index(fields=["business", "status"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def save(self, *args, **kwargs):
        self._compress_image()
        super().save(*args, **kwargs)

    def _compress_image(self):
        """
        Downsizes and re-encodes any newly-attached image to a small JPEG
        (max 800px on the long edge, quality 70) so product photos stay
        in the tens-of-KBs rather than whatever multi-MB file a phone
        camera produced — matters both for page-load speed across
        thousands of products and for storage/bandwidth costs at scale.
        Skips files that are already a plain path (nothing new to
        compress) or too small to bother with.
        """
        if not self.image or not hasattr(self.image, "file"):
            return
        if not hasattr(self.image.file, "content_type"):
            return  # already-stored file being re-saved untouched, not a fresh upload
        try:
            from io import BytesIO
            from PIL import Image
            from django.core.files.base import ContentFile

            img = Image.open(self.image)
            img = img.convert("RGB")
            img.thumbnail((800, 800), Image.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=70, optimize=True)
            file_name = (self.image.name.rsplit(".", 1)[0] if self.image.name else "product") + ".jpg"
            self.image.save(file_name, ContentFile(buffer.getvalue()), save=False)
        except Exception:  # noqa: BLE001 — a bad/corrupt upload shouldn't block saving the product; it just keeps the original file
            pass

    @property
    def is_low_stock(self):
        return self.current_stock <= self.minimum_stock

    @property
    def is_offer_active(self):
        from django.utils import timezone
        if not self.is_on_offer:
            return False
        if self.offer_expires_at and self.offer_expires_at < timezone.localdate():
            return False
        return True

    @property
    def effective_discount_percent(self):
        """
        Normalizes discount_type='fixed' into an equivalent percentage so
        the POS/cart (which discounts per-line as a percentage — see
        apps.sales.SaleItem.discount_percent) can apply either kind of
        offer without special-casing fixed amounts.
        """
        if not self.is_offer_active:
            return 0
        if self.discount_type == self.DiscountType.FIXED:
            if not self.selling_price:
                return 0
            pct = (self.discount_amount / self.selling_price) * 100
            return min(pct, 100)
        return min(self.discount_percent, 100)

    @property
    def stock_value(self):
        return self.current_stock * self.buying_price


class ProductVariant(models.Model):
    """e.g. size/colour combinations. Each variant tracks its own stock and SKU suffix."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=150)  # e.g. "Red / Large"
    sku_suffix = models.CharField(max_length=32, blank=True)
    barcode = models.CharField(max_length=64, blank=True)
    price_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.product.name} — {self.name}"


class ProductSerialNumber(models.Model):
    """For serialized goods (electronics etc.) — one row per physical unit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="serial_numbers")
    serial_number = models.CharField(max_length=128)
    is_sold = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("product", "serial_number")

    def __str__(self):
        return self.serial_number


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        STOCK_IN = "stock_in", "Stock In"
        STOCK_OUT = "stock_out", "Stock Out"
        ADJUSTMENT = "adjustment", "Adjustment"
        TRANSFER = "transfer", "Transfer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="stock_movements")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    movement_type = models.CharField(max_length=16, choices=MovementType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    from_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    to_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reason = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey("authentication.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "product", "created_at"])]

    def __str__(self):
        return f"{self.movement_type} · {self.product.name} · {self.quantity}"


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ORDERED = "ordered", "Ordered"
        PARTIALLY_RECEIVED = "partially_received", "Partially Received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="purchase_orders")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, related_name="purchase_orders")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="purchase_orders")
    reference = models.CharField(max_length=64)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey("authentication.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PO {self.reference} — {self.supplier.name}"

    @property
    def total_cost(self):
        return sum((item.quantity_ordered * item.unit_cost for item in self.items.all()), start=0)


class PurchaseOrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="purchase_order_items")
    quantity_ordered = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} x {self.quantity_ordered}"
