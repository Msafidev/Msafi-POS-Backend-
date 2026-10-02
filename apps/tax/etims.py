import requests
from django.conf import settings


class ETIMSAdapterError(Exception):
    pass


class ETIMSAdapter:
    """
    KRA eTIMS OSCU/VSCU system-to-system integration — see
    https://www.kra.go.ke/business/etims-electronic-tax-invoice-management-system.

    What's confirmed from KRA's own published material: a business
    self-registers (or uses a KRA-verified integrator) for OSCU (always
    online) or VSCU (batch/offline-tolerant), gets a device serial +
    branch code + communication key issued after KRA approves the
    device, then the flow is: initialize the device once, then submit
    each invoice's sales/tax/buyer details and receive back a KRA
    invoice number + digital signature used to build the compliance QR
    code on the receipt.

    What is NOT guessed here: the exact request/response JSON schema.
    KRA publishes a full OSCU/VSCU Specification Document (PDF) with the
    exact field names, and the base API URLs are only handed out inside
    the eTIMS taxpayer sandbox portal after signup — neither is
    something this adapter fabricates. `initialize_device` and
    `submit_invoice` are shaped to match the documented flow and are the
    two calls a real implementation needs, but MUST be checked against
    that spec document (and the sandbox base URL filled into
    settings.ETIMS_SANDBOX_BASE_URL) before this is used for a live
    business's actual tax filing.
    """

    def __init__(self, tax_profile):
        self.tax_profile = tax_profile

    def _base_url(self):
        base = {
            "sandbox": getattr(settings, "ETIMS_SANDBOX_BASE_URL", ""),
            "production": getattr(settings, "ETIMS_PRODUCTION_BASE_URL", ""),
        }[self.tax_profile.etims_environment]
        if not base:
            raise ETIMSAdapterError(
                "eTIMS base URL isn't configured yet — set ETIMS_SANDBOX_BASE_URL / "
                "ETIMS_PRODUCTION_BASE_URL once you have KRA sandbox/production access."
            )
        return base

    def initialize_device(self):
        """One-time device registration confirmation with KRA, using the
        PIN + branch code + device serial issued after KRA approves the
        eTIMS device request."""
        payload = {
            "tin": self.tax_profile.business.tax_number,
            "bhfId": self.tax_profile.etims_branch_code,
            "dvcSrlNo": self.tax_profile.etims_device_serial,
        }
        resp = requests.post(
            f"{self._base_url()}/initializer/selectInitInfo",
            json=payload,
            headers={"Authorization": f"Bearer {self.tax_profile.etims_communication_key}"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def check_connection(self):
        """
        Lightweight "is this device actually reachable and approved right
        now" check for the Tax settings screen's Connected/Not Connected
        badge — re-runs device init (the one KRA call that doesn't
        require a real sale) but never raises; every failure mode
        collapses to a plain not-connected result with a human reason.
        """
        if not self.tax_profile.etims_enabled:
            return {"connected": False, "reason": "eTIMS is turned off for this business."}
        missing = [
            field for field in ("etims_branch_code", "etims_device_serial", "etims_communication_key")
            if not getattr(self.tax_profile, field)
        ]
        if missing:
            return {"connected": False, "reason": "Missing " + ", ".join(missing) + " from KRA."}
        try:
            self.initialize_device()
        except ETIMSAdapterError as exc:
            return {"connected": False, "reason": str(exc)}
        except requests.RequestException as exc:
            return {"connected": False, "reason": f"Could not reach KRA eTIMS: {exc}"}
        except Exception as exc:  # noqa: BLE001 — any other adapter/response-shape failure is still "not connected", not a 500
            return {"connected": False, "reason": str(exc)}
        return {"connected": True, "reason": "Device is registered and reachable."}

    def submit_invoice(self, sale):
        """Submit one completed Sale as a tax invoice. Returns the raw
        KRA response — the caller (apps.tax.views) is responsible for
        turning this into an ETIMSInvoice row."""
        payload = {
            "tin": self.tax_profile.business.tax_number,
            "bhfId": self.tax_profile.etims_branch_code,
            "invcNo": sale.sale_number,
            "totAmt": str(sale.total_amount),
            "taxAmt": str(sale.tax_amount),
            "items": [
                {
                    "itemNm": item.product.name,
                    "qty": str(item.quantity),
                    "prc": str(item.unit_price),
                    "taxRt": str(item.tax_percent),
                    "totAmt": str(item.line_total),
                }
                for item in sale.items.all()
            ],
        }
        resp = requests.post(
            f"{self._base_url()}/trnsSales/saveSales",
            json=payload,
            headers={"Authorization": f"Bearer {self.tax_profile.etims_communication_key}"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
