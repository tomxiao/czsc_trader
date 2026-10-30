"""Closed-cycle facts survive the formal evaluation and evidence lifecycle."""
from dataclasses import replace
from datetime import datetime

import pytest
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import equity_source_hash
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (
    CheckpointMode, EvaluationEvidenceWrite, ExecutionCheckpointRequest,
    ResearchExecutionSession,
)
from equity_test_support import setup_formal_equity


def test_closed_cycle_feedback_formal_parallel_resume_and_legacy_economics(tmp_path):
    context, request, _, _ = setup_formal_equity(tmp_path)
    root = request.candidate.source_root
    (root / "strategy.py").write_text(
        'from strategy_runtime import EquityDecision\n'
        'def decide(ctx):\n'
        '    feedback = ctx.portfolio.closed_cycle_feedback\n'
        '    last = feedback.latest if feedback is not None else None\n'
        '    facts = {"supported": feedback is not None, "closed": last is not None}\n'
        '    if last is not None:\n'
        '        facts.update(cycle_id=last.cycle_id, entry_quantity=last.entry_quantity,\n'
        '            entry_cost=last.entry_cost, entry_start=last.entry_interval.start.isoformat(),\n'
        '            entry_end=last.entry_interval.end.isoformat(),\n'
        '            exit_start=last.exit_interval.start.isoformat(), exit_end=last.exit_interval.end.isoformat(),\n'
        '            exit_observed=last.exit_observed_through.isoformat())\n'
        '    return EquityDecision.from_facts(0 if ctx.portfolio.quantity else 1,\n'
        '        "synthetic feedback lifecycle", facts=facts, next_watch="next completed bar")\n',
        encoding="utf-8",
    )
    definition = replace(request.candidate.definition,
                         source_sha256=equity_source_hash(root, ("strategy.py",)),
                         feedback_mode="CONFIRMED_CLOSED_CYCLE_V1")
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    legacy = replace(request, candidate=replace(request.candidate,
                     definition=replace(definition, feedback_mode="CONFIRMED_EXECUTION")))
    assert request.candidate.content_identity != legacy.candidate.content_identity
    context.evaluation.resources = ExecutionResources(max_workers=2, native_threads_per_worker=1)
    prepared = tuple(context.evaluation.prepare(r) for r in (request, legacy))
    serial = tuple(context.evaluation.evaluate(r) for r in prepared)
    new, old = (result.payload["runs"]["candidate"] for result in serial)
    assert new["metrics"] == old["metrics"]
    assert [{k: row[k] for k in ("interval_start", "interval_end", "side", "quantity", "price", "fees")}
            for row in new["fills"]] == [
                {k: row[k] for k in ("interval_start", "interval_end", "side", "quantity", "price", "fees")}
                for row in old["fills"]]
    for decision in old["decisions"]:
        assert {v["key"]: v["text"] for v in decision["explanation"]["basis"]}["supported"] == "False"
    seen = set()
    for decision in new["decisions"]:
        facts = {v["key"]: v["text"] for v in decision["explanation"]["basis"]}
        assert facts["supported"] == "True"
        completed = [trade for trade in new["trades"]
                     if datetime.fromisoformat(trade["exit_at"]) <= datetime.fromisoformat(decision["decision_at"])]
        assert (facts["closed"] == "True") == bool(completed)
        if not completed:
            continue
        last = completed[-1]
        assert facts["cycle_id"] == last["cycle_id"]
        fills = [fill for fill in new["fills"] if fill["cycle_id"] == last["cycle_id"]]
        entry, exit_ = fills
        assert int(facts["entry_quantity"]) == entry["quantity"]
        assert float(facts["entry_cost"]) == pytest.approx(entry["quantity"] * entry["price"] + entry["fees"])
        for prefix, fill in (("entry", entry), ("exit", exit_)):
            for bound in ("start", "end"):
                assert datetime.fromisoformat(facts[f"{prefix}_{bound}"]) == datetime.fromisoformat(fill[f"interval_{bound}"])
        exit_decision = next(row for row in new["decisions"] if row["decision_id"] == exit_["order_id"])
        assert datetime.fromisoformat(facts["exit_observed"]) == datetime.fromisoformat(exit_decision["observed_through"])
        seen.add(facts["cycle_id"])
    assert len(seen) >= 2
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("closed-feedback")) as execution:
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.status.value for o in outcomes] == ["SUCCEEDED", "SUCCEEDED"]
        assert [o.result.content for o in outcomes] == [r.content for r in serial]
        writes = tuple(EvaluationEvidenceWrite(r.experiment, f"feedback-{i}", r, o.result)
                       for i, (r, o) in enumerate(zip(prepared, outcomes)))
        published = publish_evidence_many(context, writes, execution=execution)
        assert all(x.status.value == "PUBLISHED" for x in published)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("closed-feedback", CheckpointMode.RESUME)) as execution:
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.result.content for o in restored] == [r.content for r in serial]
        assert execution.stats.reused_results == 2
        again = publish_evidence_many(context, writes, execution=execution)
        assert [x.reference for x in again] == [x.reference for x in published]
        assert execution.stats.reused_publications == 2
