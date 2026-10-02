"""
Premium feature add-ons. MsafiPOS itself is free to use — these are the
only thing a business ever pays for, pay-first opt-in modules on top of
the free base app:

  - "payments": everything in apps/payments (bank PDQ terminals, PesaPal,
    Visa/Mastercard, M-Pesa STK Push). A shop on the free tier can still
    take cash/manual mobile-money the normal way — this gate only covers
    the payment PROVIDER integrations.
  - "tax": every tax feature except VAT (Corporation Tax, Turnover Tax,
    WHT, CGT, Excise Duty, DST, eTIMS integration). VAT + KRA PIN stay
    free on every plan since that's the one every business legally needs.

Flat 30-day pricing for now, same renewal mechanics as the base
subscription (see apps/addons/serializers.py). Placeholder prices —
replace with real ones before going live.
"""

ADDON_FEATURES = {
    "payments": {"label": "Payment Providers (banks, cards, M-Pesa)", "days": 30, "price": 2000},
    "tax": {"label": "Advanced Tax & eTIMS", "days": 30, "price": 1500},
}

ADDON_FEATURE_CHOICES = [(key, val["label"]) for key, val in ADDON_FEATURES.items()]
