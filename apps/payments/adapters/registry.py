from apps.payments.adapters.bank_terminal import BankTerminalAdapter
from apps.payments.adapters.mpesa_stk import MpesaSTKAdapter
from apps.payments.adapters.pesapal import PesapalAdapter
from apps.payments.models import PaymentProvider

ADAPTER_REGISTRY = {
    PaymentProvider.Provider.COOP: BankTerminalAdapter,
    PaymentProvider.Provider.KCB: BankTerminalAdapter,
    PaymentProvider.Provider.EQUITY: BankTerminalAdapter,
    PaymentProvider.Provider.ABSA: BankTerminalAdapter,
    PaymentProvider.Provider.OTHER_BANK: BankTerminalAdapter,
    PaymentProvider.Provider.PESAPAL: PesapalAdapter,
    # Visa/Mastercard is routed through PesaPal's card-acquiring channel —
    # see PesapalAdapter's docstring for why.
    PaymentProvider.Provider.VISA_MASTERCARD: PesapalAdapter,
    PaymentProvider.Provider.MPESA_STK: MpesaSTKAdapter,
}


def get_adapter(provider_config):
    """provider_config: a PaymentProvider instance. Returns an instantiated adapter."""
    adapter_cls = ADAPTER_REGISTRY.get(provider_config.provider)
    if adapter_cls is None:
        raise ValueError(f"No adapter registered for provider '{provider_config.provider}'")
    return adapter_cls(provider_config)
