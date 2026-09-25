from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import shutil

from dataflows import DataRequest, Dataflows
import pandas as pd
import pytest
from strategy_runtime import StrategyCandidate

from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentInput,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResources,
    ExperimentResult,
    ExperimentStage,
    ExperimentWorkspace,
    ResearchExperiment,
    experiment_source_sha256,
    load_experiment,
    load_experiment_input,
)
from czsc_trader.research_tools import (
    EvaluationCost,
    EvaluationRequest,
    EvaluationResult,
    EvaluationWindow,
    create_experiment_context,
    create_formal_experiment_context,
    execute_experiment,
    preflight_experiment,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "s008_research_cases" / "20260924_S008_EX99"
)


def _write_v3_experiment(root: Path, *, explicit_precheck: bool = True) -> Path:
    root.mkdir(parents=True)
    precheck = (
        "    def synthetic_precheck(self):\n        assert 1 + 1 == 2\n\n"
        if explicit_precheck
        else ""
    )
    source = root / "experiment.py"
    source.write_text(
        """from datetime import date
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=1,
            experiment_id='20260925_S009_EX99',
            strategy_id='S009',
            mode=ExperimentMode.DISCOVERY,
            research_question='Can preflight block technical friction?',
            hypothesis='All static and synthetic checks pass before execution.',
            falsification_conditions=('A preflight check fails',),
            development_cutoff=date(2026, 9, 24),
            random_seed=99,
            allowed_datasets=('etf.ohlcv',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=('Preflight precedes formal execution',),
                information_paths=('Source binding -> synthetic check',),
                stage_objectives=('Reject technical failures early',),
                observation_metrics=('preflight status',),
                methodology=('Run deterministic checks',),
            ),
            subjects=('518880.SH',),
            capabilities=ExperimentCapabilities(),
        )

"""
        + precheck
        + """    def execute(self, context):
        del context
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={'executed': True},
            diagnostics={},
        )
""",
        encoding="utf-8",
    )
    binding = {
        "schema_version": 3,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py",)),
        "dependencies": [],
    }
    (root / "experiment_binding.json").write_text(json.dumps(binding), encoding="utf-8")
    return root


def test_v3_preflight_requires_and_runs_explicit_synthetic_check(
    functional_repo: Path,
) -> None:
    passing_root = _write_v3_experiment(functional_repo / ".tmp" / "S009" / "20260925_S009_EX99")
    passing = load_experiment(passing_root)
    resources = ExperimentResources(max_workers=1, random_seed=99)

    report = preflight_experiment(passing, resources=resources)

    assert report.passed
    assert report.to_dict()["passed"] is True
    assert {item.code for item in report.checks} >= {
        "SOURCE_BOUND",
        "ARCHIVE_IDENTITY",
        "SYNTHETIC_PRECHECK",
        "PREFLIGHT_ENFORCEMENT",
    }

    failing_root = _write_v3_experiment(
        functional_repo / ".tmp" / "missing-precheck" / "20260925_S009_EX99",
        explicit_precheck=False,
    )
    failing = preflight_experiment(load_experiment(failing_root), resources=resources)
    assert not failing.passed
    with pytest.raises(ValueError, match="SYNTHETIC_PRECHECK"):
        failing.require_pass()

    failing_loaded = load_experiment(failing_root)
    failing_context = create_experiment_context(
        failing_loaded.definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "v3-preflight-blocked"),
        resources=resources,
    )
    with pytest.raises(ValueError, match="SYNTHETIC_PRECHECK"):
        execute_experiment(failing_loaded, failing_context)
    assert not failing_context.workspace.path("execution_envelope.json").exists()


def _definition(
    *,
    capabilities: ExperimentCapabilities = ExperimentCapabilities(),
    mode: ExperimentMode = ExperimentMode.DISCOVERY,
    protocol: ExperimentProtocol | None = None,
    validation_cutoff: date | None = None,
) -> ExperimentDefinition:
    return ExperimentDefinition(
        schema_version=1,
        experiment_id="20260924_S008_EX98",
        strategy_id="S008",
        mode=mode,
        research_question="Does the public experiment boundary reject undeclared behavior?",
        hypothesis="Every sensitive operation is checked before execution.",
        falsification_conditions=("An undeclared operation reaches its provider",),
        development_cutoff=date(2026, 9, 2),
        random_seed=98,
        allowed_datasets=("etf.ohlcv",),
        protocol=protocol
        or ExperimentProtocol(
            stage=ExperimentStage.PROTOTYPE,
            first_principles=("Sensitive research actions require platform boundaries",),
            information_paths=("Declared input -> platform adapter -> immutable result",),
            stage_objectives=("Exercise the experiment execution boundary",),
            observation_metrics=("execution outcome",),
            methodology=("Run one synthetic deterministic experiment",),
        ),
        validation_cutoff=validation_cutoff,
        capabilities=capabilities,
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "Open": [10.0, 10.2],
            "High": [10.3, 10.4],
            "Low": [9.9, 10.1],
            "Close": [10.2, 10.3],
            "Volume": [100.0, 110.0],
            "Amount": [1_020.0, 1_133.0],
        }
    )


def _flows(calls: list[DataRequest] | None = None) -> Dataflows:
    def provider(request: DataRequest):
        if calls is not None:
            calls.append(request)
        return _frame(), {
            "vendor": "synthetic-test",
            "vendor_symbol": request.symbol,
            "asset_type": "etf",
            "period": "daily",
            "adjustment": "hfq",
        }

    return Dataflows({"etf.ohlcv": provider})


def _workspace(functional_repo: Path, name: str) -> ExperimentWorkspace:
    return ExperimentWorkspace(functional_repo / ".tmp" / name, functional_repo)


def _candidate() -> StrategyCandidate:
    return StrategyCandidate(
        strategy_family_id="S008",
        candidate_id="synthetic",
        payload={"runtime": {}, "parameters": {}},
    )


def _execute_fixture(functional_repo: Path, workspace_name: str):
    experiment = load_experiment(FIXTURE_ROOT)
    context = create_experiment_context(
        experiment.definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, workspace_name),
        resources=ExperimentResources(
            max_workers=4,
            max_evaluations=8,
            random_seed=experiment.definition.random_seed,
        ),
    )
    return experiment, context, execute_experiment(experiment, context)


def test_s008_fixture_loads_and_executes_through_public_context(
    functional_repo: Path,
) -> None:
    experiment, context, result = _execute_fixture(functional_repo, "experiment-fixture")

    assert result.outcome is ExperimentOutcome.PASS
    assert result.facts == {"rows": 2, "mean_close": 10.25, "max_workers": 4}
    assert result.artifacts[0].kind == "research-summary"
    assert json.loads(context.workspace.path("summary.json").read_text(encoding="utf-8")) == {
        "max_workers": 4,
        "mean_close": 10.25,
        "rows": 2,
    }
    assert context.trace.capabilities == (ExperimentCapability.SEARCH_PARAMETERS,)
    assert context.trace.operations == ("data.fetch",)
    assert context.trace.data_requests[0]["identity"]["dataset"] == "etf.ohlcv"
    assert context.trace.data_requests[0]["identity"]["temporal_contract"] == {
        "source_time_field": "Date",
        "availability_time_field": "Date",
        "source_calendar": "SOURCE_NATIVE",
        "available_at": "SOURCE_PERIOD_CLOSE",
        "request_range_policy": "EXACT",
    }
    assert context.trace.data_requests[0]["coverage"] is None
    assert result.receipt is not None
    assert result.receipt.experiment_id == experiment.definition.experiment_id
    receipt_payload = json.loads(
        context.workspace.path("execution_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt_payload["receipt_sha256"] == result.receipt.sha256
    restored = load_experiment_input(
        context.workspace.root,
        expected_receipt_sha256=result.receipt.sha256,
    )
    assert restored.experiment_id == experiment.definition.experiment_id
    assert restored.receipt_sha256 == result.receipt.sha256
    assert restored.outcome is result.outcome
    assert restored.facts == result.facts
    assert restored.artifacts == result.artifacts
    with pytest.raises(TypeError):
        result.receipt.artifact_sha256["changed"] = "0" * 64


def test_execution_envelope_rejects_result_and_artifact_tampering(
    functional_repo: Path,
) -> None:
    _, context, result = _execute_fixture(functional_repo, "tampered-envelope")
    envelope_path = context.workspace.path("execution_envelope.json")
    original = envelope_path.read_text(encoding="utf-8")
    envelope = json.loads(original)
    envelope["result"]["facts"]["rows"] = 99
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="result hash differs"):
        load_experiment_input(
            context.workspace.root,
            expected_receipt_sha256=result.receipt.sha256,
        )

    envelope_path.write_text(original, encoding="utf-8")
    context.workspace.path(result.artifacts[0].path).write_text(
        '{"tampered":true}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="artifact hash differs"):
        load_experiment_input(
            context.workspace.root,
            expected_receipt_sha256=result.receipt.sha256,
        )


def test_execution_envelope_requires_expected_receipt_identity(
    functional_repo: Path,
) -> None:
    _, context, _ = _execute_fixture(functional_repo, "unexpected-receipt")

    with pytest.raises(ValueError, match="differs from expected identity"):
        load_experiment_input(
            context.workspace.root,
            expected_receipt_sha256="0" * 64,
        )


def test_loader_rejects_source_tampering(functional_repo: Path) -> None:
    target = functional_repo / ".tmp" / "tampered" / FIXTURE_ROOT.name
    target.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, target)
    source = target / "experiment.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source SHA-256 differs"):
        load_experiment(target)


def test_executor_rechecks_source_after_loading(functional_repo: Path) -> None:
    target = functional_repo / ".tmp" / "post-load-tampered" / FIXTURE_ROOT.name
    target.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, target)
    experiment = load_experiment(target)
    context = create_experiment_context(
        experiment.definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "post-load-tampered"),
        resources=ExperimentResources(
            max_workers=1,
            random_seed=experiment.definition.random_seed,
            max_evaluations=1,
        ),
    )
    source = target / "experiment.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source SHA-256 differs"):
        execute_experiment(experiment, context)


def test_executor_rejects_non_platform_context() -> None:
    experiment = load_experiment(FIXTURE_ROOT)

    with pytest.raises(TypeError, match="platform experiment context factory"):
        execute_experiment(experiment, object())


def test_formal_mode_requires_platform_owned_context(functional_repo: Path) -> None:
    definition = _definition(
        mode=ExperimentMode.FORMAL,
        validation_cutoff=date(2026, 9, 18),
        capabilities=ExperimentCapabilities(
            reads_real_returns=True,
            reads_sealed_validation=True,
        ),
    )
    resources = ExperimentResources(max_workers=1, random_seed=98)

    with pytest.raises(ValueError, match="create_formal_experiment_context"):
        create_experiment_context(
            definition,
            repository_root=functional_repo,
            dataflows=_flows(),
            workspace=_workspace(functional_repo, "fake-formal"),
            resources=resources,
            evaluator=lambda request: EvaluationResult(runs=()),
        )

    context = create_formal_experiment_context(
        definition,
        repository_root=functional_repo,
        workspace=_workspace(functional_repo, "formal"),
        resources=resources,
    )
    assert context.definition.mode is ExperimentMode.FORMAL


def test_formal_definition_rejects_parameter_search() -> None:
    with pytest.raises(ValueError, match="cannot search or select parameters"):
        _definition(
            mode=ExperimentMode.FORMAL,
            validation_cutoff=date(2026, 9, 18),
            capabilities=ExperimentCapabilities(
                reads_real_returns=True,
                reads_sealed_validation=True,
                searches_parameters=True,
            ),
        )


def test_context_requires_exact_receipted_predecessors(functional_repo: Path) -> None:
    predecessor = load_experiment(FIXTURE_ROOT)
    predecessor_context = create_experiment_context(
        predecessor.definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "predecessor"),
        resources=ExperimentResources(
            max_workers=1,
            max_evaluations=1,
            random_seed=predecessor.definition.random_seed,
        ),
    )
    predecessor_result = execute_experiment(predecessor, predecessor_context)
    predecessor_input = ExperimentInput.from_result(predecessor_result)
    successor_protocol = ExperimentProtocol(
        stage=ExperimentStage.ROBUSTNESS,
        first_principles=("Successor evidence must reference immutable prior evidence",),
        information_paths=("Predecessor receipt -> successor robustness test",),
        stage_objectives=("Consume one verified predecessor",),
        observation_metrics=("predecessor receipt identity",),
        methodology=("Bind the exact predecessor receipt before execution",),
        predecessor_experiment_ids=(predecessor.definition.experiment_id,),
    )
    successor = _definition(protocol=successor_protocol)

    with pytest.raises(ValueError, match="predecessor inputs differ"):
        create_experiment_context(
            successor,
            repository_root=functional_repo,
            dataflows=_flows(),
            workspace=_workspace(functional_repo, "missing-predecessor"),
            resources=ExperimentResources(max_workers=1, random_seed=98),
        )

    context = create_experiment_context(
        successor,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "with-predecessor"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
        predecessors=(predecessor_input,),
    )
    assert context.predecessors[predecessor.definition.experiment_id].receipt_sha256 == (
        predecessor_result.receipt.sha256
    )
    with pytest.raises(TypeError, match="receipted result"):
        ExperimentInput()


def test_data_adapter_blocks_undeclared_dataset_before_provider(
    functional_repo: Path,
) -> None:
    calls: list[DataRequest] = []
    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(calls),
        workspace=_workspace(functional_repo, "undeclared-dataset"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    with pytest.raises(PermissionError, match="dataset was not declared"):
        context.data.fetch(
            DataRequest(
                dataset="fx.fxcm_daily",
                symbol="XAU/USD",
                start="2026-09-01",
                end="2026-09-02",
                required_cutoff="2026-09-02",
            )
        )

    assert calls == []


def test_data_adapter_blocks_future_data_before_provider(functional_repo: Path) -> None:
    calls: list[DataRequest] = []
    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(calls),
        workspace=_workspace(functional_repo, "future-data"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    with pytest.raises(PermissionError, match="development cutoff"):
        context.data.fetch(
            DataRequest(
                dataset="etf.ohlcv",
                symbol="518880.SH",
                start="2026-09-01",
                end="2026-09-03",
                required_cutoff="2026-09-03",
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    ("real_returns", "sealed_validation", "missing"),
    [
        (True, False, "reads_real_returns"),
        (False, True, "reads_sealed_validation"),
    ],
)
def test_data_adapter_blocks_undeclared_sensitive_access_before_provider(
    functional_repo: Path,
    real_returns: bool,
    sealed_validation: bool,
    missing: str,
) -> None:
    calls: list[DataRequest] = []
    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(calls),
        workspace=_workspace(functional_repo, f"missing-{missing}"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
        real_returns=real_returns,
        sealed_validation=sealed_validation,
    )

    with pytest.raises(PermissionError, match=missing):
        context.data.fetch(
            DataRequest(
                dataset="etf.ohlcv",
                symbol="518880.SH",
                start="2026-09-01",
                end="2026-09-02",
                required_cutoff="2026-09-02",
            )
        )

    assert calls == []


def test_context_tracks_runtime_and_evaluation_public_adapters(
    functional_repo: Path,
) -> None:
    candidate = _candidate()
    runtime_calls: list[str] = []
    evaluation_calls: list[str] = []

    class FakeRuntime:
        def describe(self, source, **kwargs):
            del source, kwargs
            runtime_calls.append("describe")
            return "runtime-definition"

    def evaluator(request: EvaluationRequest) -> EvaluationResult:
        evaluation_calls.append(request.experiment_id)
        return EvaluationResult(runs=())

    definition = _definition(capabilities=ExperimentCapabilities(reads_real_returns=True))
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "platform-adapters"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
        runtime=FakeRuntime(),
        evaluator=evaluator,
        real_returns=True,
    )
    request = EvaluationRequest(
        repository_root=functional_repo,
        experiment_id=definition.experiment_id,
        strategy=candidate,
        runtime_binding={},
        symbol="518880.SH",
        asset_type="etf",
        windows=(EvaluationWindow("full", date(2026, 9, 1), date(2026, 9, 2)),),
        development_cutoff=definition.development_cutoff,
        initial_cash=1_000_000.0,
        costs=(EvaluationCost("main", 0.001),),
        execution_data=object(),
    )

    assert context.runtime.describe(candidate) == "runtime-definition"
    assert context.evaluation.evaluate(request).runs == ()
    assert runtime_calls == ["describe"]
    assert evaluation_calls == [definition.experiment_id]
    assert context.trace.capabilities == (ExperimentCapability.READ_REAL_RETURNS,)
    assert context.trace.operations == ("runtime.describe", "evaluation.evaluate")


def test_evaluation_adapter_enforces_worker_and_evaluation_budgets(
    functional_repo: Path,
) -> None:
    calls: list[str] = []

    def evaluator(request: EvaluationRequest) -> EvaluationResult:
        calls.append(request.experiment_id)
        return EvaluationResult(runs=())

    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "resource-budget"),
        resources=ExperimentResources(
            max_workers=1,
            max_evaluations=1,
            random_seed=98,
        ),
        evaluator=evaluator,
    )
    request = EvaluationRequest(
        repository_root=functional_repo,
        experiment_id=definition.experiment_id,
        strategy=_candidate(),
        runtime_binding={},
        symbol="518880.SH",
        asset_type="etf",
        windows=(EvaluationWindow("full", date(2026, 9, 1), date(2026, 9, 2)),),
        development_cutoff=definition.development_cutoff,
        initial_cash=1_000_000.0,
        costs=(EvaluationCost("standard", 0.001),),
        execution_data=object(),
    )

    with pytest.raises(PermissionError, match="workers exceed"):
        context.evaluation.evaluate(replace(request, workers=2))
    assert context.evaluation.evaluate(request).runs == ()
    with pytest.raises(PermissionError, match="evaluation count exceeds"):
        context.evaluation.evaluate(request)
    assert calls == [definition.experiment_id]


class _CandidateExperiment(ResearchExperiment):
    def __init__(self, definition: ExperimentDefinition) -> None:
        self._definition = definition

    @property
    def definition(self) -> ExperimentDefinition:
        return self._definition

    def execute(self, context) -> ExperimentResult:
        del context
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"candidate": True},
            diagnostics={},
            candidate=_candidate(),
        )


def test_execute_rejects_unbound_experiment(functional_repo: Path) -> None:
    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "unbound-experiment"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    with pytest.raises(TypeError, match="loaded by load_experiment"):
        execute_experiment(_CandidateExperiment(definition), context)


def test_bound_candidate_result_requires_declared_capability(
    functional_repo: Path,
) -> None:
    root = functional_repo / ".tmp" / "bound-candidate" / "S008" / "20260924_S008_EX98"
    root.mkdir(parents=True)
    source = root / "experiment.py"
    source.write_text(
        """from datetime import date
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=1,
            experiment_id='20260924_S008_EX98',
            strategy_id='S008',
            mode=ExperimentMode.DISCOVERY,
            research_question='Does candidate creation require a declared capability?',
            hypothesis='The platform rejects undeclared candidate creation.',
            falsification_conditions=('An undeclared candidate is accepted',),
            development_cutoff=date(2026, 9, 2),
            random_seed=98,
            allowed_datasets=('etf.ohlcv',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.CANDIDATE,
                first_principles=('Candidate creation is a governed action',),
                information_paths=('Experiment result -> candidate boundary',),
                stage_objectives=('Verify candidate capability enforcement',),
                observation_metrics=('permission outcome',),
                methodology=('Return one synthetic candidate',),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context):
        del context
        candidate = StrategyCandidate(
            strategy_family_id='S008',
            candidate_id='synthetic',
            payload={'runtime': {}, 'parameters': {}},
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={'candidate': True},
            diagnostics={},
            candidate=candidate,
        )
""",
        encoding="utf-8",
    )
    binding = {
        "schema_version": 2,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py",)),
        "dependencies": [],
    }
    (root / "experiment_binding.json").write_text(json.dumps(binding), encoding="utf-8")
    experiment = load_experiment(root)
    context = create_experiment_context(
        experiment.definition,
        repository_root=functional_repo,
        dataflows=_flows(),
        workspace=_workspace(functional_repo, "candidate-capability"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    with pytest.raises(PermissionError, match="creates_candidate"):
        execute_experiment(experiment, context)


def test_workspace_rejects_escape_and_detects_artifact_change(
    functional_repo: Path,
) -> None:
    workspace = _workspace(functional_repo, "workspace-boundary")
    with pytest.raises(ValueError, match="experiment workspace"):
        workspace.path("../outside.json")
    target = workspace.path("facts/result.json")
    target.write_text("{}", encoding="utf-8")
    artifact = workspace.register_artifact("facts/result.json", "facts")
    target.write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash differs"):
        workspace.validate_artifact(artifact)


def test_definition_and_result_freeze_json_payloads() -> None:
    definition = _definition()
    result = ExperimentResult(
        outcome=ExperimentOutcome.INCONCLUSIVE,
        facts={"nested": {"values": [1, 2]}},
        diagnostics={},
    )

    assert len(definition.sha256) == 64
    assert result.facts["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        result.facts["new"] = True
    with pytest.raises(ValueError, match="finite JSON"):
        ExperimentResult(
            outcome=ExperimentOutcome.FAIL,
            facts={"bad": float("nan")},
            diagnostics={},
        )
    with pytest.raises(ValueError, match="must be exact"):
        ExperimentDependency("optuna", ">=4.0")
