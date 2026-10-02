from apps.payments.adapters.base import AdapterResult, PaymentAdapter


class BankTerminalAdapter(PaymentAdapter):
    """
    Covers Co-op, KCB, Equity, Absa and any other bank's physical PDQ
    (card) terminal — deliberately ONE adapter for all of them rather
    than a subclass per bank.

    Why: a bank's PDQ terminal doesn't expose a public REST API. Real
    integration is either (a) a bank-specific proprietary SDK tied to
    that exact terminal hardware, or (b) a "semi-integrated" setup where
    the POS tells the cashier the amount, the cashier keys/taps it on
    the physical terminal, and the POS records the terminal's own
    approval code once the receipt prints. This adapter implements (b),
    which is the same pattern most SaaS POS products use for bank card
    terminals in Kenya today, and works identically regardless of which
    bank issued the terminal — the differences are all on the bank's
    side. terminal_id / merchant_id on PaymentProvider are stored so
    they can be shown to the cashier and appear on the receipt, but
    aren't used to place an API call from here.

    If a specific bank later provides a real merchant API (rather than
    just a terminal), add a dedicated adapter for that bank and route it
    in adapters/registry.py — this class stays as the default for the
    rest.
    """

    def initiate(self, transaction) -> AdapterResult:
        return AdapterResult(
            status="awaiting_terminal",
            raw={"terminal_id": self.provider.terminal_id, "merchant_id": self.provider.merchant_id},
        )

    def check_status(self, transaction) -> AdapterResult:
        # Nothing to poll — the cashier confirms manually via
        # PaymentTransactionViewSet.confirm_terminal, which is the only
        # thing that ever moves this out of AWAITING_TERMINAL.
        return AdapterResult(status=transaction.status)

    def parse_callback(self, payload: dict) -> AdapterResult:
        raise NotImplementedError("Bank PDQ terminals don't send callbacks — see confirm_terminal instead.")
