from __future__ import annotations

from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation

from czsc_trader.backtesting.strategy_source import resolve_registered_strategy


def test_registered_strategy_snapshot_does_not_require_tdr_rule_resolution(
    current_frozen,
) -> None:
    context, version = current_frozen
    registered = resolve_registered_strategy(context, "S900", "v1")
    assert registered.identity.kind == "REGISTERED"
    assert registered.identity.reference == "S900-v1"
    assert registered.source_hash == version.release_hash
    assert registered.content_hash
    assert registered.strategy_payload
