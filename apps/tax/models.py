import uuid

from django.db import models

from apps.businesses.models import Business
from apps.sales.models import Sale


class TaxProfile(models.Model):
    """
    Premium tax configuration — gated behind the 'tax' add-on (see
    apps.addons). VAT itself is NOT here: Business.vat_percent and
    Business.tax_number (KRA PIN) are free on every plan since every
    registered business needs those. Everything in this model is the
    "beyond VAT" layer: the other KRA tax types + eTIMS.

    Rates are entered manually by the business (per the brief) rather
    than looked up automatically, because several of them are legally
    dependent on facts this system has no way to know on its own (turnover
    thresholds, residency status for WHT, asset classes for CGT, etc.) —
    see apps.tax.services for which of these MsafiPOS can actually
    estimate a figure for vs. which are rate-storage only.
    """

    class ETIMSEnvironment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="tax_profile")

    corporation_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    turnover_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    withholding_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    capital_gains_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    excise_duty_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    digital_service_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # eTIMS (KRA e-invoicing) — see apps.tax.etims for the integration
    # itself. These are the identifiers KRA issues once a business
    # registers for OSCU/VSCU in the eTIMS taxpayer portal; MsafiPOS can't
    # generate them.
    etims_enabled = models.BooleanField(default=False)
    etims_environment = models.CharField(max_length=16, choices=ETIMSEnvironment.choices, default=ETIMSEnvironment.SANDBOX)
    etims_branch_code = models.CharField(max_length=16, blank=True, help_text="KRA branch code, e.g. '00'.")
    etims_device_serial = models.CharField(max_length=64, blank=True, help_text="OSCU/VSCU device serial number.")
    etims_communication_key = models.CharField(
        max_length=255, blank=True, help_text="Communication key issued by KRA when the device was approved."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Tax profile — {self.business.name}"


class TaxRecord(models.Model):
    """
    One tax type's figure for one period for one business — some are
    computed by MsafiPOS from its own sales data (turnover tax, a
    corporation-tax estimate off gross profit), the rest are entered
    manually by the business because MsafiPOS has no source of truth for
    them (see apps.tax.services.ESTIMATABLE_TAX_TYPES).
    """

    class TaxType(models.TextChoices):
        CORPORATION_TAX = "corporation_tax", "Corporation Tax"
        TURNOVER_TAX = "turnover_tax", "Turnover Tax"
        WITHHOLDING_TAX = "withholding_tax", "Withholding Tax (WHT)"
        CAPITAL_GAINS_TAX = "capital_gains_tax", "Capital Gains Tax (CGT)"
        EXCISE_DUTY = "excise_duty", "Excise Duty"
        DIGITAL_SERVICE_TAX = "digital_service_tax", "Digital Service Tax (DST)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="tax_records")
    tax_type = models.CharField(max_length=32, choices=TaxType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    rate_used = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_estimated = models.BooleanField(
        default=False, help_text="True if MsafiPOS computed this from sales data; False if entered manually."
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey("authentication.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "tax_type"]
        indexes = [models.Index(fields=["business", "tax_type", "period_end"])]

    def __str__(self):
        return f"{self.business.name} — {self.get_tax_type_display()} ({self.period_start} to {self.period_end})"


class ETIMSInvoice(models.Model):
    """
    Records MsafiPOS's attempt to register a Sale with KRA eTIMS
    (OSCU/VSCU system-to-system integration) and what KRA sent back.

    IMPORTANT: the request/response shape here follows KRA's publicly
    documented OSCU/VSCU flow (device initialization, then submit invoice
    -> receive a signed confirmation + KRA invoice number used to build
    the compliance QR code) at a high level. The exact field names and
    payload schema must be checked against KRA's own OSCU/VSCU
    Specification Document once a business has real sandbox credentials —
    see apps.tax.etims.ETIMSAdapter's docstring.
    """

    class Status(models.TextChoices):
        NOT_CONFIGURED = "not_configured", "eTIMS Not Configured"
        PENDING = "pending", "Pending Submission"
        SUBMITTED = "submitted", "Submitted"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="etims_invoices")
    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name="etims_invoice")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    kra_invoice_number = models.CharField(max_length=128, blank=True)
    kra_signature = models.CharField(max_length=255, blank=True)
    qr_code_data = models.TextField(blank=True, help_text="Verification URL/payload KRA returns for the receipt QR.")
    failure_reason = models.CharField(max_length=255, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"eTIMS invoice for {self.sale.sale_number} ({self.status})"
