"""Paper trading engine public package."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import AdviceDecision, OrderSpec
    from .account_binding import (
        AccountStrategyBinding, AccountBindingUpdate, AccountBindingUpdateResult,
        AccountBindingUpdateStatus, EquityAccountBindingUpdate, EquityStateContinuation, EquityStateMigration,
    )
    from .account_maintenance import update_account_bindings
    from .equity_account_maintenance import account_binding_facts_sha256

__all__ = [
    "AdviceDecision", "OrderSpec", "AccountStrategyBinding", "AccountBindingUpdate",
    "AccountBindingUpdateResult", "AccountBindingUpdateStatus", "update_account_bindings",
    "EquityAccountBindingUpdate", "EquityStateContinuation", "EquityStateMigration", "account_binding_facts_sha256",
    "EquityAdviceClient", "prepare_equity_decision", "ExecutionReferenceBinding", "PreparedExecutionReference",
    "EquityPteInspectionProtocol", "EquityPteScenario", "inspect_equity_release",
]

_EXPORT_MODULES = {
    'ExecutionReferenceBinding': 'execution_reference', 'PreparedExecutionReference': 'execution_reference',
    'EquityAdviceClient': 'equity_advice', 'prepare_equity_decision': 'equity_advice',
    'EquityPteInspectionProtocol': 'equity_inspection',
    'EquityPteScenario': 'equity_inspection', 'inspect_equity_release': 'equity_inspection',
    'AdviceDecision': 'contracts', 'OrderSpec': 'contracts',
    'AccountStrategyBinding': 'account_binding', 'AccountBindingUpdate': 'account_binding',
    'AccountBindingUpdateResult': 'account_binding', 'AccountBindingUpdateStatus': 'account_binding',
    'update_account_bindings': 'account_maintenance',
    'EquityAccountBindingUpdate': 'account_binding', 'EquityStateContinuation': 'account_binding',
    'EquityStateMigration': 'account_binding', 'account_binding_facts_sha256': 'equity_account_maintenance',
}


def __getattr__(name: str):
    """Load trading APIs on demand, keeping the service host dependency-free."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    module = _EXPORT_MODULES[name]
    value = getattr(import_module(f'.{module}', __name__), name)
    globals()[name] = value
    return value
