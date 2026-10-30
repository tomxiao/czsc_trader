"""Synthetic formal auxiliary data and session context integration contracts."""

from equity_test_support import setup_auxiliary, account_research, current_account_request, replay_payload
from dataclasses import replace

import pytest

from dataflows import (EquityProduct, TimeInterval)
from strategy_runtime.equity_definition import (equity_source_hash)


def test_auxiliary_preparation_evaluation_and_publication(tmp_path):
    from czsc_trader.research_tools import EvaluationEvidenceWrite
    context, request, _, calls = setup_auxiliary(tmp_path)
    assert len(current_account_request(context,request).request_items(context.execution_spec)) == 6
    with account_research(context, request) as (prepared, result, payload, execution):
        assert len(prepared.request.input_binding.expected_identities) == 6
        from czsc_trader.application import publish_evidence_many
        published, = publish_evidence_many(context, (EvaluationEvidenceWrite(request.experiment, "auxiliary", prepared, result),), execution=execution)
        assert published.reference.schema_version == 4
    assert len(calls) == 6
    assert "strategy_runtime.account_replay" in payload["request"]["engine_sources"]
    from czsc_trader.research_tools.equity_replay import build_equity_assessment
    assert build_equity_assessment(result)




def test_auxiliary_inputs_do_not_change_buy_hold(tmp_path):
    context, request, _, _ = setup_auxiliary(tmp_path)
    result = replay_payload(context, request)
    definition = replace(request.candidate.definition, auxiliary_inputs=(), session_context=False)
    candidate = replace(request.candidate, definition=definition)
    # Candidate source needs context; compare against an ordinary formal candidate.
    source = candidate.source_root / "strategy.py"
    source.write_text('from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    return EquityDecision.from_facts(ctx.parameters["enter"], "hold", facts={"enter":ctx.parameters["enter"]}, next_watch="next bar")\n', encoding="utf-8")
    candidate = replace(candidate, definition=replace(definition, source_sha256=equity_source_hash(source.parent, ("strategy.py",))))
    baseline = replay_payload(context, replace(request, candidate=candidate))
    assert result["runs"]["buy_hold"] == baseline["runs"]["buy_hold"]


def test_auxiliary_stale_input_stops_formal_evaluation(tmp_path):
    context, request, products, _ = setup_auxiliary(tmp_path)
    import pandas as pd
    bars = products["auxiliary"][EquityProduct.BARS]
    bars.loc[1:, "AvailableDate"] = bars.loc[1:, "AvailableDate"] + pd.Timedelta(days=10)
    declaration = replace(request.candidate.definition.auxiliary_inputs[0], max_age_seconds=60)
    candidate = replace(request.candidate, definition=replace(request.candidate.definition, auxiliary_inputs=(declaration,)))
    with pytest.raises(ValueError, match="AUXILIARY_INPUT_STALE"):
        replay_payload(context, replace(request, candidate=candidate))


def test_auxiliary_independent_calendar_is_allowed(tmp_path):
    context, request, products, _ = setup_auxiliary(tmp_path, auxiliary_days=(1,))
    bars = products[EquityProduct.BARS]
    start = bars.loc[bars.Date.dt.day.eq(2), "BarStart"].iloc[0].to_pydatetime()
    request = replace(request, window=TimeInterval(start, request.window.end))
    result = replay_payload(context, request)
    assert result["schema"] == "equity-research/v4"




def test_auxiliary_workers_and_checkpoint_use_all_pinned_inputs(tmp_path):
    from strategy_runtime import ExecutionResources
    from czsc_trader.research_tools import ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode
    context, request, _, calls = setup_auxiliary(tmp_path)
    context.evaluation.resources = ExecutionResources(max_workers=2, native_threads_per_worker=1)
    requests = tuple(current_account_request(context, item) for item in (request, replace(request, scenario_id="PRESSURE", measurement_tier="STRESS", fee_rate=.002)))
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("auxiliary-run")) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in requests)
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [item.status.value for item in outcomes] == ["SUCCEEDED", "SUCCEEDED"]
        expected = [item.result.content for item in outcomes]
        assert execution.equity_statistics.input_snapshots == 1
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("auxiliary-run", CheckpointMode.RESUME)) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in requests)
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert [item.result.content for item in restored] == expected
        assert execution.stats.reused_results == 2
    assert len(calls) == 6


def test_archived_primary_history_applies_declared_latency(tmp_path):
    import pandas as pd
    context, request, products, _ = setup_auxiliary(tmp_path, latency_seconds=2)
    bars = products[EquityProduct.BARS]
    start = bars.BarStart.iloc[3].to_pydatetime()
    bars.loc[0, "AvailableDate"] = pd.Timestamp(start) - pd.Timedelta(seconds=1)
    request = replace(request, window=TimeInterval(start, request.window.end))
    result = replay_payload(context, request)
    first = result["runs"]["candidate"]["decisions"][0]
    assert pd.Timestamp(first["observed_through"]) == bars.Date.iloc[1]
    assert result["schema"] == "equity-research/v4"


@pytest.mark.parametrize("half_day,exit_hour", [(False, 15), (True, 12)])
def test_session_only_exit_executes_at_last_interval_open(tmp_path, half_day, exit_hour):
    import pandas as pd
    context, request, products, _ = setup_auxiliary(tmp_path, half_day=half_day)
    source = request.candidate.source_root / "strategy.py"
    source.write_text('from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    target = int(ctx.point.execution_interval.end != ctx.session.segments[-1].end)\n'
        '    return EquityDecision.from_facts(target, "session exit", facts={"session_end":ctx.session.segments[-1].end.isoformat()}, next_watch="next session")\n', encoding="utf-8")
    definition = replace(request.candidate.definition, auxiliary_inputs=(),
        source_sha256=equity_source_hash(source.parent, ("strategy.py",)))
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    bars = products[EquityProduct.BARS]
    bars.loc[bars.index[-1], "Close"] = 10.1
    result = replay_payload(context, request)
    assert result["request"]["candidate_definition"]["session_context"] is True
    run = result["runs"]["candidate"]
    sells = [row for row in run["fills"] if row["side"] == "SELL"]
    assert len(sells) == 2
    last = pd.Timestamp(sells[-1]["interval_start"]).tz_convert("America/New_York")
    assert (last.hour, last.minute) == (exit_hour, 30)
    assert sells[-1]["price"] == 10.0
    assert run["account_points"][-1]["quantity"] == 0
    assert result["schema"] == "equity-research/v4"
