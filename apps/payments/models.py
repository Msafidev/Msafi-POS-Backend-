import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.businesses.models import Business
from apps.sales.models import Sale


class PaymentProvider(models.Model):
    """
    A tenant's own connection to a bank/gateway/mobile-money channel —
    this is the "each business plugs in its own PDQ/bank/M-Pesa" piece.
    One Business can have several rows here (e.g. a Co-op PDQ terminal
    AND their own M-Pesa till both active at once); the Payment Engine
    picks the right adapter per-transaction from `provider`.

    Credential fields are intentionally generic (api_key/api_secret/
    shortcode/passkey/terminal_id/merchant_id) rather than one column per
    bank, because every adapter below only reads the subset it needs —
    see each adapter's docstring for which fields it expects.
    """

    class Provider(models.TextChoices):
        COOP = "coop", "Co-operative Bank"
        KCB = "kcb", "KCB Bank"
        EQUITY = "equity", "Equity Bank"
        ABSA = "absa", "Absa Bank"
        OTHER_BANK = "other_bank", "Other Bank (PDQ Terminal)"
        PESAPAL = "pesapal", "PesaPal"
        VISA_MASTERCARD = "visa_mastercard", "Visa / Mastercard"
        MPESA_STK = "mpesa_stk", "M-Pesa STK Push"

    # Providers routed through the bank-terminal ("semi-integrated PDQ")
    # adapter — see adapters/bank_terminal.py for why this is one adapter
    # shared by all banks rather than a subclass per bank.
    BANK_TERMINAL_PROVIDERS = {Provider.COOP, Provider.KCB, Provider.EQUITY, Provider.ABSA, Provider.OTHER_BANK}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="payment_providers")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    display_name = models.CharField(
        max_length=100, blank=True, help_text="e.g. 'Co-op PDQ - Main Till'. Shown to cashiers at checkout."
    )

    # Generic credential slots — which ones matter depends on `provider`,
    # see the matching adapter's docstring.
    api_key = models.CharField(max_length=255, blank=True, help_text="Consumer key / API key")
    api_secret = models.CharField(max_length=255, blank=True, help_text="Consumer secret / API secret")
    shortcode = models.CharField(max_length=32, blank=True, help_text="M-Pesa till/paybill number")
    passkey = models.CharField(max_length=255, blank=True, help_text="M-Pesa Daraja Lipa Na M-Pesa passkey")
    terminal_id = models.CharField(max_length=100, blank=True, help_text="Physical PDQ terminal ID")
    merchant_id = models.CharField(max_length=100, blank=True)
    account_reference = models.CharField(max_length=100, blank=True)

    sandbox = models.BooleanField(default=True, help_text="Use the provider's sandbox/test environment.")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider"]
        indexes = [models.Index(fields=["business", "provider", "active"])]

    def __str__(self):
        return self.display_name or f"{self.business.name} — {self.get_provider_display()}"

    @property
    def is_bank_terminal(self):
        return self.provider in self.BANK_TERMINAL_PROVIDERS


class PaymentTransaction(models.Model):
    """
    One attempt to collect money through a PaymentProvider adapter. This
    sits alongside sales.Payment rather than replacing it: a
    PaymentTransaction tracks the gateway-side attempt (pending →
    success/failed, with the provider's own reference numbers); once it
    succeeds, the POS checkout flow records the matching sales.Payment
    against the Sale the normal way. Kept separate so a failed/abandoned
    STK push or terminal swipe never has to pretend to be a completed
    sale payment.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        AWAITING_TERMINAL = "awaiting_terminal", "Awaiting Terminal Confirmation"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="payment_transactions")
    provider = models.ForeignKey(PaymentProvider, on_delete=models.PROTECT, related_name="transactions")
    sale = models.ForeignKey(
        Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_transactions"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=8, default="KES")
    phone_number = models.CharField(max_length=32, blank=True, help_text="For M-Pesa STK Push")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    merchant_request_id = models.CharField(max_length=128, blank=True)
    checkout_request_id = models.CharField(max_length=128, blank=True, db_index=True)
    provider_reference = models.CharField(
        max_length=128, blank=True, help_text="Final confirmation code — M-Pesa receipt no. / terminal ref, etc."
    )
    failure_reason = models.CharField(max_length=255, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    initiated_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True, related_name="payment_transactions_initiated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "status", "created_at"]),
            models.Index(fields=["checkout_request_id"]),
        ]

    def __str__(self):
        return f"{self.provider.get_provider_display()} · {self.amount} · {self.status}"
