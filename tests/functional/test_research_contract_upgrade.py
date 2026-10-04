from copy import deepcopy
from pathlib import Path
from dataflows import DataSpace
from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha256
import json
import shutil

import pandas as pd
import pytest

from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDataScope,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentProtocol,
    ExperimentStage,
    ExperimentResources,
    ExperimentWorkspace,
    EvaluationAttemptStatus,
    EvaluationRecord,
    load_experiment,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateEvidence,
    CandidateRegistrationOrigin,
    CandidateIdentityConflict,
    StrategyRegistry,
    StrategyFamily,
    ResearchState,
)
from czsc_trader.application import (
    RepositoryContext,
    CandidateRegistrationRequest,
    register_candidate,
    load_candidate,
)
from czsc_trader.research_tools import (
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationExecutionError,
    create_formal_experiment_context,
    preflight_experiment,
)
from test_candidate_runtime_execution import _install_candidate_dataflows
from test_research_experiment import _write_v3_experiment


@pytest.fixture
def managed_evaluation(candidate_payload, tmp_path, monkeypatch):
    payload, package = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path, space=DataSpace(Path("data/backtest")))
    execution = _prepare_backtest_execution_data(repository_root=tmp_path, symbol="588080.SH", asset_type="etf", start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows)
    candidate = StrategyCandidate("S900", "C0001", payload, package)
    definition = ExperimentDefinition(
        schema_version=2,
        experiment_id="20261001_S900_EX01",
        strategy_id="S900",
        mode=ExperimentMode.FORMAL,
        data_scope=ExperimentDataScope.DEVELOPMENT,
        research_question="Does each independent evaluation retain identity?",
        hypothesis="Repeat evaluations have independent records and stable input identity",
        falsification_conditions=("A failure returns success",),
        development_cutoff=sessions[-1].date(),
        random_seed=1,
        subjects=("588080.SH",),
        allowed_datasets=tuple(
            item.dataset for item in StrategyRuntime().describe(candidate).inputs.requirements
        ),
        protocol=ExperimentProtocol(
            ExperimentStage.PARAMETER_SEARCH,
            ("Bound inputs",),
            ("Data to account",),
            ("Evaluate",),
            ("identity",),
            ("Synthetic replay",),
        ),
        capabilities=ExperimentCapabilities(reads_real_returns=True, searches_parameters=True),
    )
    workspace = ExperimentWorkspace(tmp_path / ".tmp" / "managed", tmp_path)
    context = create_formal_experiment_context(
        definition,
        repository_root=tmp_path,
        data_space=DataSpace(Path("data/research")),
        resources=ExperimentResources(1, 1),
        workspace=workspace,
    )
    request = EvaluationRequest(
        tmp_path,
        definition.experiment_id,
        candidate,
        {
            "candidate_id": candidate.reference_id,
            "source_files": list(payload["runtime"]["source_files"]),
            "implementation_sha256": payload["runtime"]["source_sha256"],
        },
        "588080.SH",
        "etf",
        (EvaluationWindow("full", sessions[1].date(), sessions[-1].date()),),
        sessions[-1].date(),
        100_000,
        (EvaluationCost("standard", 0.001),),
        execution,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    )
    return context, request


def test_formal_development_evaluates_without_registration_or_search_budget(managed_evaluation):
    context, request = managed_evaluation
    first = context.evaluation.evaluate(request)
    second = context.evaluation.evaluate(request)
    assert first.attempt_id != second.attempt_id
    assert first.runs[0].identity.evaluation_id == second.runs[0].identity.evaluation_id
    assert first.result_hash == second.result_hash
    assert not (request.repository_root / "research" / "registrations").exists()
    assert [item.status for item in context.trace.evaluations] == [
        EvaluationAttemptStatus.SUCCEEDED
    ] * 2
    for record in context.trace.evaluations:
        context.workspace.validate_artifact(record.result_artifact)
        assert record.completed_count == 1
    saved = EvaluationRecord.from_dict(
        json.loads(context.workspace.path(first.record.path).read_text())
    )
    assert saved.attempt_id == first.attempt_id
    with pytest.raises(TypeError, match="max_evaluations"):
        ExperimentResources(1, 1, max_evaluations=1)
    with pytest.raises(ValueError, match="different content"):
        changed = {
            "runtime": dict(request.strategy.payload["runtime"]),
            "parameters": dict(request.strategy.payload["parameters"]),
        }
        changed["parameters"]["threshold"] = 0.9
        context.evaluation.evaluate(
            replace(request, strategy=replace(request.strategy, payload=changed))
        )


@pytest.mark.parametrize("failure", [RuntimeError("provider unavailable"), KeyboardInterrupt()])
def test_failed_and_cancelled_evaluations_retain_records(managed_evaluation, failure):
    context, request = managed_evaluation
    original = context.evaluation._evaluator

    def fail(request):
        raise failure

    context.evaluation._evaluator = fail
    expected = (
        KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else EvaluationExecutionError
    )
    with pytest.raises(expected):
        context.evaluation.evaluate(request)
    record = context.trace.evaluations[-1]
    assert record.status is (
        EvaluationAttemptStatus.CANCELLED
        if expected is KeyboardInterrupt
        else EvaluationAttemptStatus.FAILED
    )
    assert record.result_hash is None and record.completed_count is None
    stored = context.workspace.path(f"evaluations/{record.attempt_id}/record.json")
    assert EvaluationRecord.from_dict(json.loads(stored.read_text())) == record
    context.evaluation._evaluator = original
    assert context.evaluation.evaluate(request).runs


def test_failed_record_publication_cannot_return_success(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools._evaluation_records import _CallEvidence

    context, request = managed_evaluation
    original = _CallEvidence.record

    def fail(self, record):
        if record.status is EvaluationAttemptStatus.SUCCEEDED:
            raise OSError("disk write failed")
        return original(self, record)

    monkeypatch.setattr(_CallEvidence, "record", fail)
    with pytest.raises(EvaluationExecutionError):
        context.evaluation.evaluate(request)
    assert context.trace.evaluations[-1].status is EvaluationAttemptStatus.FAILED


def test_research_declarations_do_not_replace_request_date_validation(managed_evaluation):
    context, request = managed_evaluation
    declaration = replace(
        context.definition,
        data_scope=ExperimentDataScope.SEALED_VALIDATION,
        validation_cutoff=date(2026, 10, 1),
        capabilities=ExperimentCapabilities(searches_parameters=True),
    )
    assert declaration.capabilities.searches_parameters
    with pytest.raises(ValueError, match="execution data identity"):
        context.evaluation.evaluate(replace(request, data_cutoff=date(2026, 10, 1)))
    with pytest.raises(TypeError, match="date"):
        replace(request, data_cutoff=datetime(2026, 9, 21))
    with pytest.raises(ValueError, match="ExperimentDataScope"):
        replace(context.definition, data_scope="DEVELOPMENT")


def test_researcher_owns_window_selection_and_platform_records_execution(managed_evaluation):
    context, request = managed_evaluation
    definition = replace(
        context.definition,
        data_scope=ExperimentDataScope.SEALED_VALIDATION,
        development_cutoff=date(2026, 9, 18),
        validation_cutoff=request.data_cutoff,
        capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
    )
    sealed = create_formal_experiment_context(
        definition,
        repository_root=request.repository_root,
        data_space=DataSpace(Path("data/research")),
        resources=ExperimentResources(1, 1),
        workspace=context.workspace,
    )
    result = sealed.evaluation.evaluate(request)
    assert result.runs
    assert sealed.trace.data_scope is ExperimentDataScope.SEALED_VALIDATION
    assert sealed.trace.evaluations[-1].status is EvaluationAttemptStatus.SUCCEEDED


def test_derivation_checks_actual_child_and_successful_parent(managed_evaluation):
    from strategy_manager import CandidateDerivation, CandidateDerivationKind
    from czsc_trader.research_tools import EvaluationLineage

    context, request = managed_evaluation
    parent = context.evaluation.evaluate(request)
    child = replace(request.strategy, candidate_id="C0002")
    identity = StrategyRuntime().identify(child, dependencies=())
    relation = CandidateDerivation(
        CandidateKey("S900", "C0001"),
        parent.runs[0].identity.content_sha256,
        CandidateKey("S900", "C0002"),
        identity.content_sha256,
        CandidateDerivationKind.PARAMETERS,
        {"threshold": {"before": 0.5, "after": 0.5}},
        "a" * 64,
        CandidateEvidence(
            context.workspace.path(parent.record.path)
            .relative_to(request.repository_root)
            .as_posix(),
            parent.record.sha256,
        ),
    )
    child_request = replace(
        request,
        strategy=child,
        runtime_binding={**request.runtime_binding, "candidate_id": child.reference_id},
        lineage=EvaluationLineage(relation),
    )
    result = context.evaluation.evaluate(child_request)
    assert result.runs[0].identity.candidate == relation.child
    with pytest.raises(ValueError, match="lineage child"):
        context.evaluation.evaluate(
            replace(
                child_request,
                lineage=EvaluationLineage(replace(relation, child_content_sha256="0" * 64)),
            )
        )


def test_historical_receipt_is_rejected_without_modifying_original(tmp_path):
    from strategy_runtime import canonical_sha256
    from research_experiment import load_experiment_input

    result = {"outcome": "PASS", "facts": {}, "diagnostics": {}, "artifacts": [], "candidate": None}
    receipt = {
        "schema_version": 1,
        "experiment_id": "20260901_S900_EX01",
        "definition_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "resources_sha256": "c" * 64,
        "predecessor_receipts": {},
        "result_sha256": canonical_sha256(result),
        "artifact_sha256": {},
        "trace": {
            "capabilities": [],
            "operations": [],
            "data_requests": [],
            "evaluations": [{"request_hash": "d" * 64}],
        },
    }
    digest = canonical_sha256(receipt)
    envelope = {"schema_version": 1, "receipt": receipt, "receipt_sha256": digest, "result": result}
    (tmp_path / "execution_envelope.json").write_text(json.dumps(envelope))
    original = (tmp_path / "execution_envelope.json").read_bytes()
    with pytest.raises(ValueError, match="schema_version must be 2"):
        load_experiment_input(tmp_path, expected_receipt_sha256=digest)
    assert (tmp_path / "execution_envelope.json").read_bytes() == original


@pytest.mark.parametrize("batch_mode", [False, True])
def test_executor_archives_typed_evaluation_and_rejects_partial_receipt(managed_evaluation, batch_mode):
    from research_experiment import experiment_source_sha256, load_experiment_input
    from czsc_trader.research_tools import execute_experiment

    context, request = managed_evaluation
    root = request.repository_root / "experiments" / "S900" / request.experiment_id
    root.mkdir(parents=True)
    # The experiment owns its input selection; TDR authenticates each supplied request.
    source = """from datetime import date
from research_experiment import (
    ExperimentDefinition, ExperimentDataScope, ExperimentMode, ExperimentProtocol,
    ExperimentStage, ExperimentCapabilities, ResearchExperiment, ExperimentResult, ExperimentOutcome,
)
class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id="20261001_S900_EX01", strategy_id="S900",
            mode=ExperimentMode.FORMAL, data_scope=ExperimentDataScope.DEVELOPMENT,
            research_question="Does each independent evaluation retain identity?",
            hypothesis="Repeat evaluations have independent records and stable input identity",
            falsification_conditions=("A failure returns success",), development_cutoff=date(2026, 9, 21),
            random_seed=1, subjects=("588080.SH",), allowed_datasets=DATASETS,
            protocol=ExperimentProtocol(ExperimentStage.PARAMETER_SEARCH, ("Bound inputs",), ("Data to account",), ("Evaluate",), ("identity",), ("Synthetic replay",)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, searches_parameters=True),
        )
    def synthetic_precheck(self):
        assert 1 + 1 == 2
    def execute(self, context):
        result = context.evaluation.evaluate(self.request)
        return ExperimentResult(ExperimentOutcome.PASS, {"result_hash": result.result_hash}, {})
""".replace("DATASETS", repr(context.definition.allowed_datasets))
    if batch_mode:
        from test_evaluation_batch import synthetic_evaluator
        context.evaluation._batch_evaluator = synthetic_evaluator
        context.resources = context.evaluation._resources = ExperimentResources(2, 1)
        source = source.replace(
            "result = context.evaluation.evaluate(self.request)",
            "outcomes = context.evaluation.evaluate_many((self.request, self.request))\n"
            "        result = outcomes[0].result",
        )
    (root / "experiment.py").write_text(source, encoding="utf-8")
    binding = {
        "schema_version": 3,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py",)),
        "dependencies": [],
    }
    (root / "experiment_binding.json").write_text(json.dumps(binding))
    loaded = load_experiment(root)
    loaded.implementation.request = request
    result = execute_experiment(loaded, context)
    assert len(result.receipt.trace.evaluations) == (2 if batch_mode else 1)
    evidence = load_experiment_input(
        context.workspace.root, expected_receipt_sha256=result.receipt.sha256
    )
    assert evidence.facts["result_hash"] == context.trace.evaluations[0].result_hash
    assert {item.kind for item in evidence.artifacts} == {"evaluation_record", "evaluation_result"}
    receipt_file = context.workspace.path("execution_receipt.json")
    receipt_file.unlink()
    with pytest.raises(ValueError, match="publication is incomplete"):
        load_experiment_input(context.workspace.root, expected_receipt_sha256=result.receipt.sha256)


def test_evaluator_cannot_report_success_with_wrong_identity(managed_evaluation):
    context, request = managed_evaluation
    original = context.evaluation._evaluator
    context.evaluation._evaluator = lambda item: replace(original(item), request_hash="0" * 64)
    with pytest.raises(EvaluationExecutionError, match="identity differs"):
        context.evaluation.evaluate(request)
    assert context.trace.evaluations[-1].status is EvaluationAttemptStatus.FAILED


def test_content_identity_is_id_and_path_independent(candidate_payload, tmp_path):
    payload, root = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, root)
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=())
    moved = tmp_path / "copy" / "strategy_runtime"
    shutil.copytree(root, moved)
    assert (
        runtime.identify(
            replace(candidate, candidate_id="C0002", source_root=moved), dependencies=()
        )
        == identity
    )
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 0.8
    assert (
        runtime.identify(replace(candidate, payload=changed), dependencies=()).content_sha256
        != identity.content_sha256
    )
    assert (
        runtime.identify(
            candidate, dependencies=(ImplementationDependency("some_pkg", "1.0"),)
        ).content_sha256
        != identity.content_sha256
    )
    with pytest.raises(ValueError):
        runtime.identify(
            candidate,
            dependencies=(
                ImplementationDependency("some_pkg", "1.0"),
                ImplementationDependency("some-pkg", "1.1"),
            ),
        )


def test_registration_is_explicit_immutable_and_uses_saved_sources(
    candidate_payload, minimal_repo
):
    payload, source = candidate_payload
    context = RepositoryContext.discover(minimal_repo)
    candidate_root = minimal_repo / "candidate" / "strategy_runtime"
    shutil.copytree(source, candidate_root)
    candidate = StrategyCandidate("S009", "C0001", payload, candidate_root)
    experiment_path = context.experiments_root / "S009" / "20260925_S009_EX99"
    _write_v3_experiment(experiment_path)
    loaded = load_experiment(experiment_path)
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    report.require_pass()
    preflight = experiment_path / "preflight.json"
    preflight.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    origin = CandidateRegistrationOrigin(
        loaded.definition.experiment_id,
        loaded.definition.sha256,
        sha256((experiment_path / "experiment_binding.json").read_bytes()).hexdigest(),
        CandidateEvidence(
            preflight.relative_to(context.root).as_posix(),
            sha256(preflight.read_bytes()).hexdigest(),
        ),
    )
    registry = StrategyRegistry(context.research_registry_root)
    family = StrategyFamily(
        2,
        "S009",
        "Synthetic candidate",
        "ETF",
        {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING,
        "2026-10-01T00:00:00+00:00",
        "test",
        "2026-10-01T00:00:00+00:00",
    )
    registry.create_family(family, actor="test", reason="candidate registration acceptance")
    request = CandidateRegistrationRequest(candidate, origin, ())
    record = register_candidate(context, request)
    assert register_candidate(context, request) == record
    assert (
        load_candidate(context, record.key).runtime_identity_sha256
        == candidate.runtime_identity_sha256
    )
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 0.8
    with pytest.raises(CandidateIdentityConflict):
        register_candidate(context, replace(request, candidate=replace(candidate, payload=changed)))
    (candidate_root / "strategies" / "candidate_fixture.py").write_text("invalid original source")
    assert load_candidate(context, record.key).candidate_id == "C0001"
    saved_source = record.source_files[0].resolve(experiment_path)
    saved_source.write_text("tampered")
    with pytest.raises(Exception, match="hash differs"):
        load_candidate(context, CandidateKey("S009", "C0001"))


def test_assessment_adapter_binds_actual_fees_for_identically_named_scenarios(managed_evaluation):
    from czsc_trader.research_tools import build_assessment_evidence

    context, request = managed_evaluation
    other = replace(request, costs=(EvaluationCost("standard", 0.002),))
    first = build_assessment_evidence(request, context.evaluation.evaluate(request))[0]
    second = build_assessment_evidence(other, context.evaluation.evaluate(other))[0]
    assert first.context_sha256 == second.context_sha256
    assert first.scenario_id == second.scenario_id == "standard"
    assert first.scenario_context.one_way_cost == 0.001
    assert second.scenario_context.one_way_cost == 0.002
    assert first.scenario_context != second.scenario_context


@pytest.mark.parametrize("tier", ["FORMAL", "SCREENING"])
def test_managed_standard_and_stress_evaluations_reach_se_ranking(
    managed_evaluation, monkeypatch, tier
):
    from strategy_evaluator import assess_candidates, compare_candidates, research_models as m
    from strategy_manager import CandidateDerivation, CandidateDerivationKind, canonical_sha256
    from czsc_trader.research_tools import build_assessment_evidence, EvaluationLineage

    old_context, request = managed_evaluation
    sessions = request.execution_data.adjusted_daily["dt"]
    daily = pd.DataFrame(
        {
            "dt": sessions,
            "open": [1.0, 1.0, 1.0, 1.05, 1.1, 1.1],
            "close": [1.0, 1.0, 1.0, 1.05, 1.1, 1.1],
        }
    )
    flow = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    request = replace(request, repository_root=request.repository_root / "stress-case")
    request.repository_root.mkdir()
    runtime_root = request.repository_root / "runtime/strategy_runtime"
    shutil.copytree(request.strategy.source_root, runtime_root)
    request = replace(request, strategy=StrategyCandidate(
        request.strategy.strategy_family_id, request.strategy.candidate_id,
        request.strategy.payload, runtime_root,
    ))
    flows = _install_candidate_dataflows(monkeypatch, flow, daily, base_dir=request.repository_root)
    context = create_formal_experiment_context(
        old_context.definition,
        repository_root=request.repository_root,
        data_space=DataSpace(Path("data/stress")),
        resources=ExperimentResources(1, 1),
        workspace=ExperimentWorkspace(
            request.repository_root / ".tmp/stress-integration", request.repository_root
        ),
    )
    request = replace(
        request,
        frequency_window_days=2,
        costs=(EvaluationCost("standard", 0.001, tier), EvaluationCost("fee_x2", 0.002, "STRESS")),
        execution_data=_prepare_backtest_execution_data(
            repository_root=request.repository_root, symbol=request.symbol, asset_type=request.asset_type,
            start=request.windows[0].start, end=request.data_cutoff, dataflows=flows),
    )
    parent = context.evaluation.evaluate(request)
    base_evidence = build_assessment_evidence(request, parent)
    child = replace(
        request.strategy,
        candidate_id="C0002",
        payload={
            **request.strategy.payload,
            "parameters": {**request.strategy.payload["parameters"], "threshold": 0.6},
        },
    )
    identity = StrategyRuntime().identify(child, dependencies=())
    relation = CandidateDerivation(
        CandidateKey("S900", "C0001"),
        parent.runs[0].identity.content_sha256,
        CandidateKey("S900", "C0002"),
        identity.content_sha256,
        CandidateDerivationKind.PARAMETERS,
        {"threshold": {"before": 0.5, "after": 0.6}},
        "a" * 64,
        CandidateEvidence(
            context.workspace.path(parent.record.path)
            .relative_to(request.repository_root)
            .as_posix(),
            parent.record.sha256,
        ),
    )
    child_request = replace(
        request,
        strategy=child,
        costs=(request.costs[0],),
        runtime_binding={**request.runtime_binding, "candidate_id": child.reference_id},
        lineage=EvaluationLineage(relation),
    )
    neighbor = build_assessment_evidence(child_request, context.evaluation.evaluate(child_request))
    center = base_evidence[0].candidate
    protocol = m.SelfCheckProtocol(
        "1",
        "full",
        "standard",
        "fee_x2",
        2,
        1,
        m.QuantileMethod.LINEAR,
        1,
        1,
        40,
        2,
        1,
        1e-7,
        pbo_blocks=2,
    )
    panel = assess_candidates(
        m.CandidateAssessmentRequest(
            (center,),
            protocol,
            (
                m.PerturbationLink(
                    center, neighbor[0].candidate, 1.0, canonical_sha256(relation.to_dict())
                ),
            ),
            (*base_evidence, *neighbor),
        )
    )
    metrics = {x.metric: x for x in panel.rows[0].diagnostics}
    stress = metrics[m.ResearchMetric.STRESS_ANNUAL_LOSS]
    assert stress.status is m.DiagnosticStatus.AVAILABLE, stress
    by_scenario = {x.scenario_id: x for x in base_evidence}
    standard, pressure = by_scenario["standard"], by_scenario["fee_x2"]
    exponent = 252 / len(standard.account)
    expected_loss = (standard.account[-1].equity / standard.initial_cash) ** exponent - (
        pressure.account[-1].equity / pressure.initial_cash
    ) ** exponent
    assert stress.value == pytest.approx(expected_loss)
    assert set(stress.evaluation_ids) == {standard.evaluation_id, pressure.evaluation_id}
    comparison = compare_candidates(
        m.CandidateComparisonRequest(
            (center,),
            m.ResearchTargets((), 2),
            panel,
            m.ComparisonPolicy(
                "1",
                tuple(
                    (m.MetricBinSpec(x, 0.01, 0.0, m.BinRounding.FLOOR) for x in m.RANKING_METRICS)
                ),
                pareto_basis=m.ParetoBasis.RAW,
                missing_evidence_policy=m.MissingEvidencePolicy.REQUIRE_COMPLETE,
            ),
        )
    )
    assert comparison.rows[0].status is m.ComparisonStatus.RANKED, comparison.rows[0].reasons


def test_unprepared_evaluation_uses_fixed_space_and_supports_assessment(managed_evaluation):
    from czsc_trader.research_tools import build_assessment_evidence
    context, request = managed_evaluation
    request = replace(request, execution_data=None)
    result = context.evaluation.evaluate(request)
    assert result.execution_data is not None
    assert result.execution_data.prepared is not None
    assert build_assessment_evidence(request, result)
    assert any(item["operation"] == "prepare" for item in context.trace.data_requests)
    assert any(item["operation"] == "fetch" for item in context.trace.data_requests)
    assert context.data._dataflows is not context._backtest_data._dataflows
    assert (request.repository_root / "data/backtest").is_dir()


def test_unprepared_evaluation_rejects_cutoff_before_preparation(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import evaluation
    context, request = managed_evaluation
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid request must fail before data preparation")
    monkeypatch.setattr(evaluation._dataflows, "create_backtest_dataflows", forbidden)
    request = replace(request, execution_data=None, windows=(
        EvaluationWindow("full", request.windows[0].start, date(2026, 9, 30)),
    ))
    with pytest.raises(ValueError, match="cutoff"):
        context.evaluation.evaluate(request)


def test_evaluation_records_inputs_without_deciding_research_authorization(managed_evaluation):
    from dataflows import Dataset
    context, request = managed_evaluation
    definition = replace(
        context.definition, allowed_datasets=(Dataset.ETF_OHLCV,),
        capabilities=ExperimentCapabilities(), development_cutoff=date(2026, 9, 1),
    )
    context = create_formal_experiment_context(
        definition, repository_root=request.repository_root,
        data_space=DataSpace(Path("data/research")), resources=context.resources,
        workspace=context.workspace,
    )
    result = context.evaluation.evaluate(replace(request, execution_data=None))
    assert result.runs
    assert any(item["dataset"] == Dataset.ETF_UNADJUSTED_DAILY
               for item in context.trace.data_requests)
    assert context.trace.evaluations[-1].status is EvaluationAttemptStatus.SUCCEEDED


def test_evaluation_rejects_foreign_repository_before_preparation(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools import evaluation
    context, request = managed_evaluation
    def forbidden(*args, **kwargs):
        raise AssertionError("foreign repository must fail before data preparation")
    monkeypatch.setattr(evaluation._dataflows, "create_backtest_dataflows", forbidden)
    with pytest.raises(ValueError, match="repository differs"):
        context.evaluation.evaluate(replace(request, repository_root=request.repository_root / "other", execution_data=None))
