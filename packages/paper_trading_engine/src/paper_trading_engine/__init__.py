"""Paper trading engine public package."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import AdviceDecision, OrderSpec
    from .account_binding import (
        AccountStrategyBinding, AccountBindingUpdate, AccountBindingUpdateResult,
        AccountBindingUpdateStatus,
    )
    from .account_maintenance import update_account_bindings
    from .account_retirement import (
        AccountRetirementRequest, AccountRetirementResult, AccountRetirementStatus,
    )

__all__ = [
    "AdviceDecision", "OrderSpec", "AccountStrategyBinding", "AccountBindingUpdate",
    "AccountBindingUpdateResult", "AccountBindingUpdateStatus", "update_account_bindings",
    "AccountRetirementRequest", "AccountRetirementResult", "AccountRetirementStatus",
]

_EXPORT_MODULES = {
    'AdviceDecision': 'contracts', 'OrderSpec': 'contracts',
    'AccountStrategyBinding': 'account_binding', 'AccountBindingUpdate': 'account_binding',
    'AccountBindingUpdateResult': 'account_binding', 'AccountBindingUpdateStatus': 'account_binding',
    'update_account_bindings': 'account_maintenance',
    'AccountRetirementRequest': 'account_retirement',
    'AccountRetirementResult': 'account_retirement',
    'AccountRetirementStatus': 'account_retirement',
}


def __getattr__(name: str):
    """Load trading APIs on demand, keeping the service host dependency-free."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(import_module(f'.{_EXPORT_MODULES[name]}', __name__), name)
    globals()[name] = value
    return value
