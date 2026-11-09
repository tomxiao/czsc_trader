# Risk ownership: TDR-19
"""Explicit inspection compares cycle facts; TXE/SE own allocation and audit correctness."""
from copy import deepcopy
import json
import pytest
from czsc_trader.application.inspection_replay import technical_ledger_differences


def cycle_ledger(prefix):
    cycle = {"cycle_id": prefix + "cycle", "opening_signal_identity": prefix + "signal",
        "allocation_fraction": "0.5", "cash_budget": "50000.0", "target_quantity": 4900,
        "buy_cost_including_fees": "49049.0", "phase": "ACTIVE"}
    return {"strategy_hash": prefix, "content_hash": prefix,
        "decisions": [{"decision_id": prefix + "decision", "signal_identity": prefix + "signal",
            "cycle_id": prefix + "cycle", "entry_cycle_after": json.dumps(cycle)}],
        "account_daily": [{"entry_cycle_id": prefix + "cycle", "entry_cycle": json.dumps(cycle),
            "cash": 50951., "quantity": 4900, "equity": 99951.}]}




@pytest.mark.parametrize('field,value', [('phase', 'EXITING')])
def test_TDR_19_C02_explicit_inspection_does_not_tolerate_changed_cycle_facts(field, value):
    original = cycle_ledger("candidate:")
    assert technical_ledger_differences(original, cycle_ledger("release:"), 0.) == []
    changed = deepcopy(original)
    state = json.loads(changed["decisions"][0]["entry_cycle_after"])
    state[field] = value
    changed["decisions"][0]["entry_cycle_after"] = json.dumps(state)
    differences = technical_ledger_differences(original, changed, 100000.)
    assert differences
    assert any(item["path"].endswith(field) and item["tolerance"] == 0 for item in differences)
