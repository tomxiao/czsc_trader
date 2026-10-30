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
from czsc_trader.research_tools.equity_replay import materialize_equity


def test_closed_cycle_feedback_v4_parallel_resume_and_execution_economics(tmp_path):
    from equity_test_support import setup_account_research
    context, request, _, _ = setup_account_research(tmp_path)
    root = request.candidate.source_root
    (root/'strategy.py').write_text(
        'from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n'
        'def step(ctx,state):\n'
        '    last=ctx.position.latest_closed\n'
        '    facts={"closed":last is not None}\n'
        '    if last is not None:\n'
        '        facts.update(cycle_id=last.cycle_id,entry_quantity=last.buy_fills,entry_cost=last.buy_cost,\n'
        '            entry_start=last.entry_interval.start.isoformat(),entry_end=last.entry_interval.end.isoformat(),\n'
        '            exit_start=last.last_fill_interval.start.isoformat(),exit_end=last.last_fill_interval.end.isoformat())\n'
        '    return AccountStepResult(AccountDecision.from_facts(0 if ctx.account.quantity else 1,\n'
        '        "position feedback",facts=facts,next_watch="next bar"),cycle_values=StateRecord())\n',encoding='utf8')
    definition=replace(request.candidate.definition,source_sha256=equity_source_hash(root,('strategy.py',)))
    request=replace(request,candidate=replace(request.candidate,definition=definition))
    requests=(request,replace(request,candidate=replace(request.candidate,candidate_id='C0002')))
    context.evaluation.resources=ExecutionResources(2,1)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("closed-feedback")) as execution:
        prepared = tuple(context.evaluation.prepare(r, execution=execution) for r in requests)
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.status.value for o in outcomes] == ["SUCCEEDED", "SUCCEEDED"], [o.error for o in outcomes]
        results = tuple(o.result for o in outcomes)
        writes = tuple(EvaluationEvidenceWrite(r.experiment, f"feedback-{i}", r, o.result)
                       for i, (r, o) in enumerate(zip(prepared, outcomes)))
        published = publish_evidence_many(context, writes, execution=execution)
        assert all(x.status.value == "PUBLISHED" for x in published)
    new, old = (materialize_equity(result).payload["runs"]["candidate"] for result in results)
    assert new["metrics"] == old["metrics"]
    assert [{k: row[k] for k in ("interval_start", "interval_end", "side", "quantity", "price", "fees")}
            for row in new["fills"]] == [
                {k: row[k] for k in ("interval_start", "interval_end", "side", "quantity", "price", "fees")}
                for row in old["fills"]]
    seen = set()
    for decision in new["decisions"]:
        facts = {v["key"]: v["text"] for v in decision["explanation"]["basis"]}
        completed = [trade for trade in new["trades"]
                     if datetime.fromisoformat(trade["exit_at"]) <= datetime.fromisoformat(decision["decision_at"])]
        assert (facts["closed"] == "True") == bool(completed)
        if not completed:
            continue
        last = completed[-1]
        assert facts["cycle_id"] == last["cycle_id"]
        fills = [fill for fill in new["fills"] if fill["cycle_id"] == last["cycle_id"]]
        entry, exit_ = fills
        assert int(facts["entry_quantity"]) == 1
        assert float(facts["entry_cost"]) == pytest.approx(entry["quantity"] * entry["price"] + entry["fees"])
        for prefix, fill in (("entry", entry), ("exit", exit_)):
            for bound in ("start", "end"):
                assert datetime.fromisoformat(facts[f"{prefix}_{bound}"]) == datetime.fromisoformat(fill[f"interval_{bound}"])
        seen.add(facts["cycle_id"])
    assert len(seen) >= 2
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("closed-feedback", CheckpointMode.RESUME)) as execution:
        prepared = tuple(context.evaluation.prepare(r, execution=execution) for r in requests)
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [o.result.content for o in restored] == [r.content for r in results]
        assert execution.stats.reused_results == 2
        writes = tuple(EvaluationEvidenceWrite(r.experiment, f"feedback-{i}", r, o.result)
                       for i, (r, o) in enumerate(zip(prepared, restored)))
        again = publish_evidence_many(context, writes, execution=execution)
        assert [x.reference for x in again] == [x.reference for x in published]
        assert execution.stats.reused_publications == 2
