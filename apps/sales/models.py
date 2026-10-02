import uuid
from decimal import Decimal

from django.db import models, transaction
from django.core.validators import MinValueValidator

from apps.businesses.models import Business, Branch
from apps.customers.models import Customer
from apps.inventory.models import Product


class Sale(models.Model):
    class Status(models.TextChoices):
        HELD = "held", "Held"                        # parked cart, nothing charged/deducted yet
        COMPLETED = "completed", "Completed"          # may still have a balance_due (partial payment)
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"
        VOIDED = "voided", "Voided"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="sales")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    cashier = models.ForeignKey("authentication.User", on_delete=models.SET_NULL, null=True, related_name="sales")

    # Business-scoped, human-readable sequence (e.g. SALE-000042) — see
    # generate_sale_number() below for how this is assigned under a row lock.
    sequence_no = models.PositiveIntegerField()

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # partial-payment / layaway
    notes = models.TextField(blank=True)

    held_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("business", "sequence_no")
        indexes = [
            models.Index(fields=["business", "status", "created_at"]),
            models.Index(fields=["business", "sequence_no"]),
        ]

    def __str__(self):
        return self.sale_number

    @property
    def sale_number(self):
        return f"SALE-{self.sequence_no:06d}"

    @staticmethod
    def next_sequence_no(business_id):
        """
        Row-locks the business's existing sales while computing the next
        number, so two checkouts in the same business can't race onto the
        same sequence_no. Must be called inside an outer transaction.atomic().
        """
        last = (
            Sale.objects.select_for_update()
            .filter(business_id=business_id)
            .order_by("-sequence_no")
            .first()
        )
        return (last.sequence_no + 1) if last else 1


class SaleItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    # Snapshotted at sale time — a later price change shouldn't rewrite history.
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # for profit reporting
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def compute_line_total(self):
        gross = self.quantity * self.unit_price
        discount = gross * (self.discount_percent / Decimal(100))
        taxable = gross - discount
        tax = taxable * (self.tax_percent / Decimal(100))
        return (taxable + tax).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        GIFT_CARD = "gift_card", "Gift Card"
        STORE_CREDIT = "store_credit", "Store Credit"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=20, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=128, blank=True)  # e.g. mobile money txn code, card auth code
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.method} · {self.amount}"


class Refund(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="refunds")
    refunded_by = models.ForeignKey("authentication.User", on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_method = models.CharField(max_length=20, choices=Payment.Method.choices, default=Payment.Method.CASH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund on {self.sale.sale_number}"


class RefundItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    refund = models.ForeignKey(Refund, on_delete=models.CASCADE, related_name="items")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="refund_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.sale_item.product.name} x {self.quantity}"
