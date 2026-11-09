# Risk ownership: TDR-16
"""V4 public execution, shared benchmark and auditable account facts."""

from equity_test_support import setup_account_research
from dataclasses import replace
import json

import pytest
from czsc_trader.research_tools.execution import ResearchExecutionSession
from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult
from czsc_trader.research_tools.equity_replay import (
    materialize_equity, build_equity_assessment,
)


def test_TDR_16_C02_account_refs_check_structure_without_recertifying_recorded_metrics(account_facts):
    _, result = account_facts
    saved = {item.sha256: item.content for item in result.artifacts}
    view = materialize_equity(result.content, lambda ref: saved[ref["sha256"]])
    assert view.source_sha256 == result.result_hash
    detached = view.payload
    detached["runs"]["candidate"]["account_points"].clear()
    assert view.payload["runs"]["candidate"]["account_points"]
    with pytest.raises(ValueError, match="digest differs"):
        materialize_equity(result.content, lambda ref: b"{}")
    payload = result.payload
    payload["candidate_ref"]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="closure differs"):
        EquityEvaluationResult(result.request_hash, json.dumps(payload).encode(), result.artifacts)
    # Ordinary projection consumes account observations; it does not attest to
    # independently supplied stored metrics or compare them against the journal.
    candidate = next(item for item in result.artifacts if item.sha256 == result.payload["candidate_ref"]["sha256"])
    document = json.loads(candidate.content)
    document["run"]["metrics"]["fees"] += 1
    changed = EquityArtifact(candidate.kind, json.dumps(document).encode())
    payload = result.payload
    payload["candidate_ref"] = changed.reference()
    altered = EquityEvaluationResult(result.request_hash, json.dumps(payload).encode(),
        tuple(changed if item is candidate else item for item in result.artifacts))
    projected, = build_equity_assessment(altered)
    original, = build_equity_assessment(result)
    assert projected.account == original.account and projected.fills == original.fills
    assert projected.equity == original.equity


def test_TDR_16_C01_projection_preserves_metrics_without_recomputation(account_facts, monkeypatch):
    from strategy_evaluator.equity_assessment import canonical_ledger, equity_performance, equity_concentration
    from czsc_trader.research_tools import equity_replay
    _, result = account_facts
    raw = materialize_equity(result).payload
    def forbidden(*args, **kwargs):
        raise AssertionError("fact projection must not recompute recorded metrics")
    monkeypatch.setattr(equity_replay, "summarize_equity_ledger", forbidden)
    facts, = build_equity_assessment(result)
    ledgers = {}
    economic = {name: raw["audit_inputs"][name] for name in (
        "bars", "price_basis", "quantity_basis", "constraints", "specification", "initial_cash", "fee_rate")}
    for name, run in raw["runs"].items():
        ledgers[name] = {**economic, **{field: run[field] for field in (
            "decisions", "orders", "fills", "account_entries", "account_points", "trades")}, "account_contract": 4}
    for basis in ("SESSION_CLOSE", "BAR_CLOSE"):
        compact = replace(facts, equity=replace(facts.equity, drawdown_basis=basis),
            metric_version=f"equity-assessment-v4:{basis}:{facts.equity.concentration_basis}")
        full = replace(compact, equity=replace(compact.equity,
            candidate_ledger=canonical_ledger(ledgers["candidate"]),
            benchmark_ledger=canonical_ledger(ledgers["buy_hold"])))
        assert equity_performance(compact) == equity_performance(full)
        assert equity_performance(compact, benchmark=True) == equity_performance(full, benchmark=True)
        assert equity_concentration(compact) == equity_concentration(full)
        assert len(compact.equity.candidate_ledger) < len(full.equity.candidate_ledger)




def test_TDR_04_C04_old_raw_result_cannot_be_reinterpreted(account_facts):
    from czsc_trader.research_tools.equity_replay import validate_result_structure
    _, result = account_facts
    payload = result.payload
    payload['request']['price_basis'] = 'RAW'
    with pytest.raises(ValueError, match='HFQ simulated units'):
        validate_result_structure(payload)


def test_TDR_16_C04_candidate_label_preserves_economic_facts(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    renamed = replace(request, candidate=replace(request.candidate, candidate_id='C0002'))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        original = context.evaluation.prepare(request, execution=execution)
        labelled = context.evaluation.prepare(renamed, execution=execution)
        first, second = context.evaluation.evaluate_many((original, labelled), execution=execution)
        assert first.result is not None and second.result is not None
        a, = build_equity_assessment(first.result)
        b, = build_equity_assessment(second.result)
        assert a.candidate.candidate_id != b.candidate.candidate_id
        assert a.account == b.account and a.context_sha256 == b.context_sha256
        # Candidate identity namespaces cycle IDs. Keep a one-to-one mapping,
        # then compare every economic field and its fill/trade linkage.
        assert len(a.fills) == len(b.fills)
        cycles = {}
        for left, right in zip(a.fills, b.fills, strict=True):
            assert cycles.setdefault(right.cycle_id, left.cycle_id) == left.cycle_id
            assert left == replace(right, cycle_id=cycles[right.cycle_id])
        assert len(set(cycles.values())) == len(cycles)
        assert a.closed_cycles == tuple(replace(c, cycle_id=cycles[c.cycle_id]) for c in b.closed_cycles)
        left_ledger = json.loads(a.equity.candidate_ledger)
        right_ledger = json.loads(b.equity.candidate_ledger)
        assert {t['cycle_id'] for t in right_ledger['trades']} == {c.cycle_id for c in b.closed_cycles}
        for trade in right_ledger['trades']:
            trade['cycle_id'] = cycles[trade['cycle_id']]
        assert left_ledger == right_ledger
        assert a.equity == replace(b.equity, candidate_ledger=a.equity.candidate_ledger)
