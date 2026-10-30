"""V3 public preparation, shared benchmark and independent certification."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema
from strategy_evaluator.equity_assessment import EquityCertificationScope
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, EquityBuyHold
from czsc_trader.research_tools.execution import ResearchExecutionSession
from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult, validate_equity_result
from czsc_trader.research_tools.equity_replay_v3 import (
    prepare_equity_v3, evaluate_many_equity_v3, materialize_v3, build_v3_assessment,
)
from test_equity_research import setup_equity


def setup_v3(tmp_path):
    context, legacy, products, calls = setup_equity(tmp_path)
    root = tmp_path / "fixture-source"
    root.mkdir()
    (root / "strategy.py").write_text(
        "from strategy_runtime.equity_definition import EquityDecision\n"
        "from strategy_runtime.equity_replay import StepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    target = 0 if ctx.portfolio.quantity else 1\n"
        "    return StepResult(EquityDecision.from_facts(target, 'alternate', "
        "facts={'quantity': ctx.portfolio.quantity}, next_watch='next bar'), cycle_values=StateRecord())\n", encoding="utf-8")
    definition = EquityStrategyDefinition(legacy.candidate.instrument, context.execution_spec, 1,
        "strategy:step", ("strategy.py",), equity_source_hash(root, ("strategy.py",)),
        contract_version=3, feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema())
    candidate = EquityStrategyCandidate("S999", "C0001", definition, root)
    request = replace(legacy, candidate=candidate,
        benchmark=EvaluationBenchmark(EquityBuyHold(context.execution_spec)),
        drawdown_basis="BAR_CLOSE", concentration_basis="TOP_DECILE")
    return context, request, products, calls


def test_v3_shared_snapshot_benchmark_and_certification(tmp_path, monkeypatch):
    from strategy_runtime.resources import ExecutionResources
    from czsc_trader.research_tools import equity_replay_v3
    context, request, _, calls = setup_v3(tmp_path)
    access = context.evaluation
    access.resources = ExecutionResources(max_workers=1, native_threads_per_worker=1)
    owners = []
    compute = equity_replay_v3._compute_account
    def record_owner(*args):
        owners.append(args[-1])
        return compute(*args)
    monkeypatch.setattr(equity_replay_v3, "_compute_account", record_owner)
    fetched = []
    original = access.data.fetch
    def fetch(*args, **kwargs):
        fetched.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(access.data, "fetch", fetch)
    other = replace(request, candidate=replace(request.candidate, candidate_id="C0002"))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        assert execution.equity_statistics is None
        left = access.prepare(request, execution=execution)
        right = access.prepare(other, execution=execution)
        assert access.prepare(left.request, execution=execution).snapshot is left.snapshot
        pressure = access.prepare(replace(request, fee_rate=.002), execution=execution)
        assert pressure.snapshot is left.snapshot
        assert pressure.benchmark_identity != left.benchmark_identity
        assert left.snapshot is right.snapshot
        assert left.benchmark_identity == right.benchmark_identity
        assert len(fetched) == 4 and len(calls) == 4
        outcomes = access.evaluate_many((left, right), execution=execution)
        assert all(item.status.value == "SUCCEEDED" for item in outcomes), [item.error for item in outcomes]
        a, b = (item.result for item in outcomes)
        assert a.payload["benchmark_ref"] == b.payload["benchmark_ref"]
        assert a.payload["candidate_ref"] != b.payload["candidate_ref"]
        assert set(owners) == {
            f"candidate:S999:C0001:{request.candidate.content_identity.content_sha256}",
            f"candidate:S999:C0002:{other.candidate.content_identity.content_sha256}",
            "benchmark:" + left.benchmark_identity.sha256,
        }
        statistics = execution.equity_statistics
        assert statistics.input_snapshots == 1
        assert (statistics.candidate_runs, statistics.benchmark_runs, statistics.authenticated_accounts) == (2, 1, 3)
        assert len(statistics.account_timings) == 3
        assert {item.owner for item in statistics.account_timings} == set(owners)
        assert all(0 <= item.feature_seconds <= item.replay_seconds and item.decisions == 25
                   for item in statistics.account_timings)
        assert "strategy_runtime.equity_source_runtime" in left.identity(access.execution_spec)["engine_sources"]
        validate_equity_result(access, left, a, execution=execution)
        assert execution.equity_statistics.authenticated_accounts == 3
        with pytest.raises(ValueError, match="exact certified"):
            validate_equity_result(access, left, EquityEvaluationResult(a.request_hash, a.content, a.artifacts), execution=execution)
        with pytest.raises(ValueError, match="not issued"):
            evaluate_many_equity_v3(access, (replace(left),), execution=execution)
        repeated, = access.evaluate_many((left,), execution=execution)
        assert repeated.result is not None, repeated.error
        accumulated = execution.equity_statistics
        assert (accumulated.candidate_runs, accumulated.benchmark_runs, accumulated.authenticated_accounts) == (3, 1, 3)
        assert len(accumulated.account_timings) == 3
        owner = f"candidate:S999:C0001:{request.candidate.content_identity.content_sha256}"
        assert next(item for item in accumulated.account_timings if item.owner == owner).decisions == 50
        assert accumulated.reused_authentications > statistics.reused_authentications
        assert statistics.candidate_runs == 2  # earlier public snapshot cannot change
        with pytest.raises(FrozenInstanceError):
            statistics.candidate_runs = 99
        assert len(fetched) == 4
    scope = EquityCertificationScope()
    first = build_v3_assessment(a, scope=scope)
    second = build_v3_assessment(b, scope=scope)
    assert scope.audit_count == 3
    assert first[0].result_sha256 == a.result_hash and second[0].result_sha256 == b.result_hash
    assert materialize_v3(a).payload["runs"]["candidate"]["metrics"]["closed_cycles"] == 12


def test_v3_refs_and_certification_reject_mutation(tmp_path):
    context, request, _, _ = setup_v3(tmp_path)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = prepare_equity_v3(context.evaluation, request, execution=execution)
        outcome, = evaluate_many_equity_v3(context.evaluation, (prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        result = outcome.result
    saved = {item.sha256: item.content for item in result.artifacts}
    view = materialize_v3(result.content, lambda ref: saved[ref["sha256"]])
    assert view.source_sha256 == result.result_hash
    with pytest.raises(ValueError, match="digest differs"):
        materialize_v3(result.content, lambda ref: b"{}")
    payload = result.payload
    payload["candidate_ref"]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="closure differs"):
        EquityEvaluationResult(result.request_hash, json.dumps(payload).encode(), result.artifacts)
    # Rehashing the envelope is insufficient: the independent accounting audit
    # must still reject a self-consistent content-addressed but false account.
    candidate = next(item for item in result.artifacts if item.sha256 == result.payload["candidate_ref"]["sha256"])
    document = json.loads(candidate.content)
    document["run"]["account_points"][2]["cash"] += 1
    changed = EquityArtifact(candidate.kind, json.dumps(document).encode())
    payload = result.payload
    payload["candidate_ref"] = changed.reference()
    altered = EquityEvaluationResult(result.request_hash, json.dumps(payload).encode(),
        tuple(changed if item is candidate else item for item in result.artifacts))
    with pytest.raises(ValueError, match="audit mismatch"):
        build_v3_assessment(altered)


def test_v3_requires_explicit_owned_session(tmp_path):
    context, request, _, _ = setup_v3(tmp_path)
    with pytest.raises(TypeError, match="explicit ResearchExecutionSession"):
        prepare_equity_v3(context.evaluation, request, execution=None)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        with pytest.raises(ValueError, match="not issued"):
            evaluate_many_equity_v3(context.evaluation, (request,), execution=execution)


def test_v3_auxiliary_and_sessions_use_indexed_availability(tmp_path, monkeypatch):
    from test_equity_auxiliary_context import setup_auxiliary
    from strategy_runtime import equity_context
    context, request, _, _ = setup_auxiliary(tmp_path)
    root = request.candidate.source_root
    (root / "strategy.py").write_text(
        "from strategy_runtime.equity_definition import EquityDecision\n"
        "from strategy_runtime.equity_replay import StepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    target = 0 if ctx.portfolio.quantity else 1\n"
        "    return StepResult(EquityDecision.from_facts(target, 'auxiliary', "
        "facts={'market_close': ctx.auxiliary_histories['market'].last()['Close'], "
        "'end': ctx.session.segments[-1].end.isoformat()}, next_watch='next bar'), cycle_values=StateRecord())\n",
        encoding="utf-8")
    definition = replace(request.candidate.definition, contract_version=3, entrypoint="strategy:step",
        source_sha256=equity_source_hash(root, ("strategy.py",)), feature_graph=FeatureGraph((), ()),
        state_schema=StrategyStateSchema())
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    def forbidden(*args, **kwargs):
        raise AssertionError("v3 must not rebuild full-history v2 contexts")
    monkeypatch.setattr(equity_context, "build_equity_decision_context", forbidden)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        assert execution.equity_statistics.authenticated_accounts == 2
    assert build_v3_assessment(outcome.result)


def test_v3_public_timing_rejects_invalid_units_and_owner():
    from czsc_trader.research_tools import EquityAccountTiming, EquityExecutionStatistics
    with pytest.raises(ValueError, match="owner differs"):
        EquityAccountTiming("BENCHMARK", "candidate:S999:C0001:hash", 0., 1., 1, 1)
    with pytest.raises(ValueError, match="finite"):
        EquityAccountTiming("BENCHMARK", "benchmark:hash", 0., float("nan"), 1, 1)
    with pytest.raises(ValueError, match="inclusive"):
        EquityAccountTiming("BENCHMARK", "benchmark:hash", 2., 1., 1, 1)
    valid = EquityAccountTiming("BENCHMARK", "benchmark:hash", 0., 1., 1, 1)
    with pytest.raises(ValueError, match="unique"):
        EquityExecutionStatistics(1, 0, 2, 1, 0, (valid, valid))


def test_v3_parameter_plan_uses_owned_preparation_without_refetch(tmp_path, monkeypatch):
    from strategy_evaluator import (AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep,
        RelativeChangeLimit, ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
        ParameterNeighborhoodSpace, build_parameter_neighborhood_design)
    from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite, ParameterEvaluationPlan, EvaluationLineage
    from czsc_trader.research_tools.parameter_evaluation import validate_parameter_request

    context, request, _, _ = setup_v3(tmp_path)
    root = request.candidate.source_root
    (root / "strategy.py").write_text(
        "from strategy_runtime.equity_definition import EquityDecision\n"
        "from strategy_runtime.equity_replay import StepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    active = int(ctx.history.last()['Close'] >= ctx.parameters['threshold'])\n"
        "    target = 0 if ctx.portfolio.quantity else active\n"
        "    return StepResult(EquityDecision.from_facts(target, 'threshold', "
        "facts={'threshold': ctx.parameters['threshold']}, next_watch='next bar'), cycle_values=StateRecord())\n",
        encoding="utf-8")
    definition = replace(request.candidate.definition, source_sha256=equity_source_hash(root, ("strategy.py",)),
        parameters_json='{"threshold":10.0}', parameter_schema_json='{"threshold":{"type":"number","minimum":1,"maximum":20}}')
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    fetched = []
    fetch = context.data.fetch
    def counted(*args, **kwargs):
        fetched.append(args[0])
        return fetch(*args, **kwargs)
    monkeypatch.setattr(context.data, "fetch", counted)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        center = context.evaluation.prepare(request, execution=execution)
        def material(name, content):
            return publish_evidence(context, MaterialEvidenceWrite(request.experiment, name, content,
                "application/json", "json"), execution=execution)
        mapping, feasible = material("map", b"{}"), material("feasibility", b"{}")
        design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate("S999-C0001", definition.content_identity.content_sha256), ParameterNeighborhoodProtocol(),
            ParameterNeighborhoodSpace((ParameterAxis("threshold", 10., RealDomain(1., 20.),
                BoundedLocalStep(RelativeChangeLimit(.05)), ("threshold",), "price"),),
                mapping.sha256, feasible.sha256)), feasibility=lambda _: True).design
        children = tuple(context.evaluation.prepare(replace(center.request, candidate=replace(center.candidate,
            candidate_id=f"C{index + 2:04}", definition=replace(definition,
                parameters_json=json.dumps({v.name: v.value for v in point.values})))), execution=execution)
            for index, point in enumerate(design.points))
        kwargs = dict(mapping_evidence=mapping, feasibility_evidence=feasible, dataflows=context.data)
        with pytest.raises(TypeError, match="session-owned"):
            ParameterEvaluationPlan.create(design, center.request, tuple(x.request for x in children), **kwargs)
        with pytest.raises(TypeError, match="explicit ResearchExecutionSession"):
            ParameterEvaluationPlan.create(design, center, children, **kwargs)
        with pytest.raises(ValueError, match="not issued"):
            ParameterEvaluationPlan.create(design, replace(center), children, execution=execution, **kwargs)
        plan = ParameterEvaluationPlan.create(design, center, children, execution=execution, **kwargs)
        assert plan.schema_version == 4 and ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
        ref = material("plan", json.dumps(plan.to_dict()).encode())
        bound = []
        for index, child in enumerate(children):
            derivation = CandidateDerivation(center.candidate.key, center.candidate.content_identity.content_sha256,
                child.candidate.key, child.candidate.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
                {v.name: v.value for v in design.points[index].values}, design.protocol.sha256,
                CandidateEvidence(ref.repository_path, ref.sha256))
            proposed = replace(child.request, lineage=EvaluationLineage(derivation,
                plan.bind_point(ref, index, repository_root=context.repository.root)))
            with pytest.raises(TypeError, match="session-owned"):
                validate_parameter_request(proposed, context.data)
            prepared = context.evaluation.prepare(proposed, execution=execution)
            validate_parameter_request(prepared, context.data, execution=execution)
            bound.append(prepared)
        assert len(fetched) == 4
        outcomes = context.evaluation.evaluate_many(tuple(bound), execution=execution)
        assert all(item.result is not None for item in outcomes), [item.error for item in outcomes]
        assert sorted(materialize_v3(item.result).payload["runs"]["candidate"]["metrics"]["closed_cycles"]
                      for item in outcomes) == [0, 12]
        for index, item in enumerate(outcomes):
            facts, = build_v3_assessment(item.result)
            assert facts.parameter_point == design.bind_point(index) and facts.parent == design.center
        with pytest.raises(ValueError, match="nonparameter context"):
            context.evaluation.prepare(replace(bound[0].request, initial_cash=1001., audit_inputs_sha256=None), execution=execution)
        assert len(fetched) == 4
    with ResearchExecutionSession(context, experiment=request.experiment) as other_execution:
        with pytest.raises(ValueError, match="not issued"):
            validate_parameter_request(bound[0], context.data, execution=other_execution)
