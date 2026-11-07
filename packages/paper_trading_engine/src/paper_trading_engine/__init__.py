"""Paper trading engine public package."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import AdviceDecision, OrderSpec
    from .account_binding import (
        AccountStrategyBinding, AccountBindingUpdate, AccountBindingUpdateResult,
        AccountBindingUpdateStatus, V4AccountBindingUpdate, V4StateContinuation, V4StateMigration,
    )
    from .account_maintenance import update_account_bindings
    from .v4_account_maintenance import account_binding_facts_sha256

__all__ = [
    "AdviceDecision", "OrderSpec", "AccountStrategyBinding", "AccountBindingUpdate",
    "AccountBindingUpdateResult", "AccountBindingUpdateStatus", "update_account_bindings",
    "V4AccountBindingUpdate", "V4StateContinuation", "V4StateMigration", "account_binding_facts_sha256",
    "EquityAdviceClient", "prepare_equity_decision",
    "EquityPteInspectionProtocol", "EquityPteScenario", "inspect_equity_release",
]

_EXPORT_MODULES = {
    'EquityAdviceClient': 'equity_advice', 'prepare_equity_decision': 'equity_advice',
    'EquityPteInspectionProtocol': 'equity_inspection',
    'EquityPteScenario': 'equity_inspection', 'inspect_equity_release': 'equity_inspection',
    'AdviceDecision': 'contracts', 'OrderSpec': 'contracts',
    'AccountStrategyBinding': 'account_binding', 'AccountBindingUpdate': 'account_binding',
    'AccountBindingUpdateResult': 'account_binding', 'AccountBindingUpdateStatus': 'account_binding',
    'update_account_bindings': 'account_maintenance',
    'V4AccountBindingUpdate': 'account_binding', 'V4StateContinuation': 'account_binding',
    'V4StateMigration': 'account_binding', 'account_binding_facts_sha256': 'v4_account_maintenance',
}


def __getattr__(name: str):
    """Load trading APIs on demand, keeping the service host dependency-free."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    module = _EXPORT_MODULES[name]
    value = getattr(import_module(f'.{module}', __name__), name)
    globals()[name] = value
    return value
