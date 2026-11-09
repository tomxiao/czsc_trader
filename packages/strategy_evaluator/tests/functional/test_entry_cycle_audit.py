"""Allocation audit rejects forged cycle facts independently of outer hashes."""
from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest
from strategy_evaluator import AuditStatus, ReplayEvidence, audit_replay
from test_champion_ledger_authentication import _replay


def cycle_replay():
    source = _replay()
    opened = {"cycle_id": "c" * 64, "opening_signal_identity": "d" * 64,
              "allocation_fraction": "1.0", "cash_budget": "100000.00",
              "target_quantity": 99900, "buy_cost_including_fees": "0", "phase": "ACTIVE"}
    held = {**opened, "buy_cost_including_fees": "99999.9"}
    exiting = {**held, "phase": "EXITING"}
    decisions, accounts = [], []
    for i, (decision, account) in enumerate(zip(source.decisions, source.account_daily)):
        before = held if i in (2, 3) else None
        after = opened if i == 1 else held if i == 2 else exiting if i == 3 else None
        settled = held if i in (1, 2) else None
        decisions.append({**decision, "signal_identity": "d" * 64,
            "cycle_target": json.dumps({"active": i in (1, 2), "entry_fraction": "1.0" if i in (1, 2) else None}),
            "entry_cycle_before": json.dumps(before), "entry_cycle_after": json.dumps(after),
            "entry_allocation_fraction": "1.0" if i in (1, 2) else None,
            "cycle_id": None if after is None else after["cycle_id"],
            "cycle_allocation_fraction": None if after is None else "1.0",
            "cycle_cash_budget": None if after is None else "100000.00",
            "cycle_target_quantity": None if after is None else 99900,
            "cycle_buy_cost_including_fees": None if after is None else "99999.9",
            "cycle_status": {1: "OPEN", 2: "HOLD", 3: "EXIT"}.get(i, "IDLE")})
        accounts.append({**account, "entry_cycle": json.dumps(settled),
            "entry_cycle_id": None if settled is None else settled["cycle_id"],
            "entry_cycle_phase": None if settled is None else "ACTIVE",
            "entry_cycle_cash_budget": None if settled is None else "100000.00",
            "entry_cycle_buy_cost_including_fees": None if settled is None else "99999.9"})
    return replace(source, execution_spec={**source.execution_spec,
        "capital_mode": "signal_cash_fraction", "target_scope": "entry_cycle"},
        decisions=tuple(decisions), account_daily=tuple(accounts),
        **{name: tuple({**row, "cycle_id": "c" * 64} for row in getattr(source, name))
           for name in ("orders", "fills", "trades")})


@pytest.mark.parametrize('difference,expected', [
    pytest.param('roundoff', AuditStatus.PASS, id='SE-26-C05'),
    pytest.param('cent', AuditStatus.FAIL, id='SE-26-C06'),
])
@pytest.mark.risk_cases('SE-26-C05', 'SE-26-C06')
def test_cycle_fee_roundoff_and_material_difference_have_distinct_results(difference, expected):
    source = cycle_replay()
    fills = tuple({**row, 'fees': math.nextafter(row['fees'], math.inf)
                   if difference == 'roundoff' else row['fees'] + .01}
                  if row['side'] == 'BUY' else row for row in source.fills)
    result = audit_replay(replace(source, fills=fills))
    assert result.status is expected, result.reason_codes
    if expected is AuditStatus.FAIL:
        assert 'ENTRY_CYCLE_ALLOCATION_MISMATCH' in result.reason_codes


@pytest.mark.parametrize('corruption', [
    pytest.param("released", id='SE-26-C03'),
    pytest.param("undeclared", id='SE-26-C04'),
])
@pytest.mark.risk_cases('SE-26-C03', 'SE-26-C04')
def test_cycle_budget_quantity_and_lifecycle_cannot_be_forged(corruption):
    source = cycle_replay()
    assert audit_replay(source).status is AuditStatus.PASS
    changed = deepcopy(source.to_dict())
    if corruption == 'released':
        changed['account_daily'][1]['entry_cycle'] = 'null'
    else:
        changed['execution_spec']['capital_mode'] = 'full_available_cash'
    result = audit_replay(ReplayEvidence.from_dict(changed))
    assert result.status is AuditStatus.FAIL
    assert ('UNDECLARED_ENTRY_CYCLE_FACTS' if corruption == 'undeclared'
            else 'ENTRY_CYCLE_ALLOCATION_MISMATCH') in result.reason_codes
