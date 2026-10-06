from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import shutil

from dataflows import (DataRequest, Dataflows, DataSpace, Dataset, ProviderConfig, ProviderBinding, PreparePolicy)
from uuid import uuid4
import pandas as pd
import pytest

from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold
from strategy_runtime import StrategyCandidate, StrategyInit, TradableWindow

from research_experiment import (
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition, ExperimentDataScope,
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
    ExperimentCapabilities, ExperimentDefinition, ExperimentDataScope, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id='20260925_S009_EX99',
            strategy_id='S009',
            mode=ExperimentMode.DISCOVERY,
            data_scope=ExperimentDataScope.DEVELOPMENT,
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
    tmp_path: Path,
) -> None:
    passing_root = _write_v3_experiment(tmp_path / ".tmp" / "S009" / "20260925_S009_EX99")
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
        tmp_path / ".tmp" / "missing-precheck" / "20260925_S009_EX99",
        explicit_precheck=False,
    )
    failing = preflight_experiment(load_experiment(failing_root), resources=resources)
    assert not failing.passed
    with pytest.raises(ValueError, match="SYNTHETIC_PRECHECK"):
        failing.require_pass()

    failing_loaded = load_experiment(failing_root)
    failing_context = create_experiment_context(
        failing_loaded.definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "v3-preflight-blocked"),
        resources=resources,
    )
    with pytest.raises(ValueError, match="SYNTHETIC_PRECHECK"):
        execute_experiment(failing_loaded, failing_context)
    assert not failing_context.workspace.path("execution_envelope.json").exists()


def _preflight_fixture(tmp_path, *, extra="", real_data=False):
    root = _write_v3_experiment(tmp_path / "S009" / "20260925_S009_EX99")
    source = root / "experiment.py"
    text = source.read_text(encoding="utf-8")
    if real_data:
        text = text.replace("capabilities=ExperimentCapabilities(),", "capabilities=ExperimentCapabilities(reads_real_returns=True),")
    source.write_text(text + extra, encoding="utf-8")
    binding_path = root / "experiment_binding.json"
    binding = json.loads(binding_path.read_text())
    binding["source_sha256"] = experiment_source_sha256(root, ("experiment.py",))
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    return load_experiment(root)


def _execution_boundary_fixture(tmp_path, *, prelude="", artifact=False, mutable_definition=False):
    root = _write_v3_experiment(tmp_path / "S009" / "20260925_S009_EX99")
    source = root / "experiment.py"
    text = source.read_text(encoding="utf-8").replace("        del context", prelude)
    if mutable_definition:
        text = text.replace("random_seed=99,", "random_seed=getattr(self, 'seed', 99),")
    if artifact:
        text = text.replace("diagnostics={},", "diagnostics={}, artifacts=(artifact,),")
    source.write_text(text, encoding="utf-8")
    binding_path = root / "experiment_binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["source_sha256"] = experiment_source_sha256(root, ("experiment.py",))
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    loaded = load_experiment(root)
    context = create_experiment_context(
        loaded.definition, repository_root=tmp_path, dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "execution-boundary"), resources=ExperimentResources(1, 99),
    )
    return loaded, context


@pytest.mark.parametrize(
    ("prelude", "artifact", "mutable_definition", "error_type", "message"),
    [
        (
            "        from pathlib import Path\n"
            "        source = Path(__file__)\n"
            "        source.write_text(source.read_text() + '\\n# changed during execution\\n')",
            False, False, ValueError, "source SHA-256 differs",
        ),
        ("        self.seed = 100", False, True, ValueError, "definition changed"),
        ("        return None", False, False, TypeError, "invalid result"),
        (
            "        path = context.workspace.path('result.txt')\n"
            "        path.write_text('original')\n"
            "        artifact = context.workspace.register_artifact('result.txt', 'result')\n"
            "        path.write_text('changed')",
            True, False, ValueError, "artifact hash differs",
        ),
    ],
)
def test_executor_records_post_execution_identity_and_result_failures(
    tmp_path, prelude, artifact, mutable_definition, error_type, message,
):
    loaded, context = _execution_boundary_fixture(
        tmp_path, prelude=prelude, artifact=artifact, mutable_definition=mutable_definition,
    )
    with pytest.raises(error_type, match=message):
        execute_experiment(loaded, context)
    failure_path = context.workspace.path("execution_failure.json")
    original = failure_path.read_bytes()
    failure = json.loads(original)
    assert failure["error_code"] == error_type.__name__
    assert failure["source_sha256"] == loaded.binding.source_sha256
    assert failure["definition_sha256"] == loaded.definition.sha256
    assert not context.workspace.path("execution_receipt.json").exists()
    assert not context.workspace.path("execution_envelope.json").exists()
    with pytest.raises(FileExistsError, match="evidence already exists"):
        execute_experiment(loaded, context)
    assert failure_path.read_bytes() == original


def test_executor_failure_is_terminal_for_execution_and_evaluation(tmp_path):
    loaded, context = _execution_boundary_fixture(
        tmp_path,
        prelude="        context.workspace.path('result.txt').write_text('retained')\n"
        "        raise RuntimeError('synthetic computation failure')",
    )
    with pytest.raises(RuntimeError, match="synthetic computation failure"):
        execute_experiment(loaded, context)
    original = context.workspace.path("execution_failure.json").read_bytes()
    with pytest.raises(FileExistsError, match="evidence already exists"):
        execute_experiment(loaded, context)
    with pytest.raises(RuntimeError, match="execution is already complete"):
        context.evaluation.evaluate(object())
    with pytest.raises(RuntimeError, match="execution is already complete"):
        context.evaluation.evaluate_many(())
    assert context.workspace.path("execution_failure.json").read_bytes() == original
    assert context.workspace.path("result.txt").read_text() == "retained"


def test_executor_preserves_partial_publication_and_records_failure(tmp_path, monkeypatch):
    from czsc_trader.research_tools import experiment as execution

    loaded, context = _execution_boundary_fixture(tmp_path)
    publish = execution._atomic_execution_document

    def interrupt_receipt(workspace, name, payload):
        if name == "execution_receipt.json":
            raise OSError("synthetic receipt publication failure")
        publish(workspace, name, payload)

    monkeypatch.setattr(execution, "_atomic_execution_document", interrupt_receipt)
    with pytest.raises(OSError, match="synthetic receipt publication failure"):
        execute_experiment(loaded, context)
    envelope_path = context.workspace.path("execution_envelope.json")
    envelope = envelope_path.read_bytes()
    assert context.workspace.path("execution_failure.json").is_file()
    assert not context.workspace.path("execution_receipt.json").exists()
    with pytest.raises(ValueError, match="failed experiment execution"):
        load_experiment_input(
            context.workspace.root,
            expected_receipt_sha256=json.loads(envelope)["receipt_sha256"],
        )
    with pytest.raises(FileExistsError, match="evidence already exists"):
        execute_experiment(loaded, context)
    assert envelope_path.read_bytes() == envelope
    assert list(context.workspace.path(".tmp/execution").glob("*.json")) == []




@pytest.mark.parametrize("status", [ExperimentPreflightStatus.PASS, ExperimentPreflightStatus.FAIL])
def test_preflight_named_checks_and_nested_result_serialization(tmp_path, monkeypatch, status):
    loaded = _preflight_fixture(tmp_path)
    sample = ExperimentResult(ExperimentOutcome.PASS, {"nested": {"rows": [1, 2]}}, {})
    result = ExperimentPrecheckResult((ExperimentPreflightCheck("LEDGER", status, "ledger test"),), sample)
    monkeypatch.setattr(type(loaded.implementation), "synthetic_precheck", lambda self: result)
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    checks = {item.code: item for item in report.checks}
    assert report.passed is (status is ExperimentPreflightStatus.PASS)
    assert checks["SYNTHETIC_LEDGER"].status is status
    assert checks["SYNTHETIC_PRECHECK"].status is status
    if report.passed:
        assert checks["RESULT_SERIALIZATION"].status is ExperimentPreflightStatus.PASS
        json.dumps(report.to_dict(), allow_nan=False)


def test_preflight_rejects_false_synthetic_success(tmp_path, monkeypatch):
    loaded = _preflight_fixture(tmp_path)
    monkeypatch.setattr(type(loaded.implementation), "synthetic_precheck", lambda self: False)
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    assert not report.passed
    assert (
        next(item for item in report.checks if item.code == "SYNTHETIC_PRECHECK").status
        is ExperimentPreflightStatus.FAIL
    )


def test_preflight_rejects_unserializable_synthetic_output(tmp_path, monkeypatch):
    loaded = _preflight_fixture(tmp_path)
    result = ExperimentPrecheckResult(
        (ExperimentPreflightCheck("OUTPUT", ExperimentPreflightStatus.PASS, "synthetic"),),
        ExperimentResult(ExperimentOutcome.PASS, {}, {}),
    )
    monkeypatch.setattr(type(loaded.implementation), "synthetic_precheck", lambda self: result)
    monkeypatch.setattr(ExperimentResult, "to_dict", lambda self: {"bad": object()})
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    assert not report.passed
    assert (
        next(item for item in report.checks if item.code == "RESULT_SERIALIZATION").status
        is ExperimentPreflightStatus.FAIL
    )


def test_preflight_detects_known_source_risks_without_executing_them(tmp_path):
    loaded = _preflight_fixture(tmp_path, extra='''
def risky(frame, result, study):
    a = frame.to_numpy()
    b = frame.join(frame)
    c = dict(result.facts)
    d = study.trials[-1]
    pool = ProcessPoolExecutor()
    return a, b, c, d, pool
''')
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    assert report.passed
    checks = {item.code: item for item in report.checks}
    for code in ("NUMPY_VIEW_MUTATION_RISK", "JOIN_COLUMN_COLLISION_RISK", "SHALLOW_RESULT_SERIALIZATION_RISK", "LAST_TRIAL_IDENTITY_RISK", "PROCESS_PAYLOAD_REVIEW"):
        assert checks[code].status is ExperimentPreflightStatus.WARNING
        assert "experiment.py:" in checks[code].message
    assert checks["DATA_READINESS"].status is ExperimentPreflightStatus.WARNING
    assert checks["SYNTHETIC_COVERAGE"].status is ExperimentPreflightStatus.WARNING


def test_preflight_blocks_changed_source_before_synthetic_or_data_access(tmp_path, monkeypatch):
    loaded = _preflight_fixture(tmp_path, real_data=True)
    monkeypatch.setattr(
        type(loaded.implementation),
        "synthetic_precheck",
        lambda self: pytest.fail("must not execute"),
    )
    path = loaded.root / "experiment.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    flows = _configured_flows(tmp_path, lambda request: pytest.fail("must not fetch"))
    report = preflight_experiment(
        loaded,
        resources=ExperimentResources(1, 99),
        dataflows=flows,
        data_requests=(
            DataRequest("etf.ohlcv", "518880.SH", "2026-09-14", "2026-09-15", "2026-09-15"),
        ),
    )
    assert not report.passed
    assert (
        next(item for item in report.checks if item.code == "SOURCE_BOUND").status
        is ExperimentPreflightStatus.FAIL
    )


def test_preflight_detects_source_mutation_during_synthetic_check(tmp_path, monkeypatch):
    loaded = _preflight_fixture(tmp_path)
    def mutate(self):
        path = loaded.root / "experiment.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    monkeypatch.setattr(type(loaded.implementation), "synthetic_precheck", mutate)
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    assert not report.passed
    assert next(item for item in report.checks if item.code == "SOURCE_UNCHANGED").status is ExperimentPreflightStatus.FAIL


def test_preflight_bare_assertion_becomes_structured_failure(tmp_path, monkeypatch):
    loaded = _preflight_fixture(tmp_path)
    def fail(self):
        raise AssertionError
    monkeypatch.setattr(type(loaded.implementation), "synthetic_precheck", fail)
    report = preflight_experiment(loaded, resources=ExperimentResources(1, 99))
    check = next(item for item in report.checks if item.code == "SYNTHETIC_PRECHECK")
    assert check.status is ExperimentPreflightStatus.FAIL
    assert check.message == "AssertionError"


@pytest.mark.parametrize(
    "real_data,end",
    [(False, "2026-09-15"), (True, "2026-09-25")],
    ids=["undeclared-real-data", "after-declared-cutoff"],
)
def test_preflight_successful_explicit_data_probe(tmp_path, real_data, end):
    loaded = _preflight_fixture(tmp_path, real_data=real_data)
    frame = pd.DataFrame(
        {
            "Date": pd.bdate_range("2026-09-14", end),
            "Open": 1.0,
            "High": 1.0,
            "Low": 1.0,
            "Close": 1.0,
            "Volume": 1.0,
            "Amount": 1.0,
        }
    )
    flows = _configured_flows(
        tmp_path, lambda request: _quality_provider_result(request, frame, {"vendor": "synthetic"})
    )
    report = preflight_experiment(
        loaded,
        resources=ExperimentResources(1, 99),
        dataflows=flows,
        data_requests=(DataRequest("etf.ohlcv", "518880.SH", "2026-09-14", end, end),),
    )
    assert report.passed
    assert (
        next(item for item in report.checks if item.code == "DATA_REQUEST_001").status
        is ExperimentPreflightStatus.PASS
    )


def test_preflight_empty_data_is_failure_without_false_readiness(tmp_path):
    real_data, end = True, "2026-09-15"
    loaded = _preflight_fixture(tmp_path, real_data=real_data)
    calls = []

    def empty(request):
        calls.append(request)
        return pd.DataFrame(), {}

    request = DataRequest("etf.ohlcv", "518880.SH", "2026-09-14", end, end)
    report = preflight_experiment(
        loaded,
        resources=ExperimentResources(1, 99),
        dataflows=_configured_flows(tmp_path, empty),
        data_requests=(request,),
    )
    assert not report.passed
    assert len(calls) == 1
    check = next(item for item in report.checks if item.code == "DATA_REQUEST_001")
    assert check.status is ExperimentPreflightStatus.FAIL
    assert "EMPTY" in check.message
    with pytest.raises(ValueError, match="configured Dataflows"):
        preflight_experiment(loaded, resources=ExperimentResources(1, 99), data_requests=(request,))


def _definition(
    *,
    capabilities: ExperimentCapabilities = ExperimentCapabilities(),
    mode: ExperimentMode = ExperimentMode.DISCOVERY,
    protocol: ExperimentProtocol | None = None,
    validation_cutoff: date | None = None,
) -> ExperimentDefinition:
    return ExperimentDefinition(
        schema_version=2,
        experiment_id="20260924_S008_EX98",
        strategy_id="S008",
        mode=mode,
        data_scope=ExperimentDataScope.SEALED_VALIDATION if validation_cutoff else ExperimentDataScope.DEVELOPMENT,
        research_question="Does the public experiment boundary track operations?",
        hypothesis="Every data operation is recorded for research review.",
        falsification_conditions=("A data operation has no trace",),
        development_cutoff=date(2026, 9, 2),
        random_seed=98,
        allowed_datasets=("etf.ohlcv",),
        protocol=protocol
        or ExperimentProtocol(
            stage=ExperimentStage.PROTOTYPE,
            first_principles=("Research decisions remain with researchers",),
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


def _configured_flows(tmp_path, provider):
    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("data") / uuid4().hex),
        providers=ProviderConfig(bindings={Dataset.ETF_OHLCV: ProviderBinding("fixture", "v1", provider)}))


def _quality_provider_result(request: DataRequest, frame: pd.DataFrame, metadata: dict):
    from dataflows.ohlcv_quality import (
        bind_quality_frame, build_quality_evidence, verify_daily_sessions,
    )

    class SyntheticCalendar:
        """This fixture declares weekday sessions and a synthetic listing date."""

        def fund_basic(self, *, ts_code, fields):
            return pd.DataFrame({
                "ts_code": [ts_code],
                "list_date": ["20260101"],
            })

        def trade_cal(self, *, exchange, start_date, end_date):
            dates = pd.date_range(start_date, end_date)
            return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                                 "is_open": (dates.weekday < 5).astype(int)})

    coverage = verify_daily_sessions(
        SyntheticCalendar(), request.symbol, frame, start=request.start, end=request.end,
    )
    evidence = build_quality_evidence(frame, expected_dates=coverage["expected_dates"])
    metadata = {**metadata, "daily_session_coverage": coverage,
                "ohlcv_quality_evidence": bind_quality_frame(
                    evidence, frame, adjustment=metadata.get("adjustment", "none"),
                )}
    frame = frame.copy()
    frame.attrs.update({key: deepcopy(metadata[key]) for key in (
        "daily_session_coverage", "ohlcv_quality_evidence",
    )})
    return frame, metadata


def _flows(tmp_path: Path, calls: list[DataRequest] | None = None) -> Dataflows:
    def provider(request: DataRequest):
        if calls is not None:
            calls.append(request)
        return _quality_provider_result(request, _frame(), {
            "vendor": "synthetic-test",
            "vendor_symbol": request.symbol,
            "asset_type": "etf",
            "period": "daily",
            "adjustment": "hfq",
        })

    return _configured_flows(tmp_path, provider)


def _workspace(tmp_path: Path, name: str) -> ExperimentWorkspace:
    return ExperimentWorkspace(tmp_path / ".tmp" / name, tmp_path)


def test_data_prepare_checks_whole_batch_before_any_source_access(tmp_path):
    calls = []
    context = create_experiment_context(
        _definition(), repository_root=tmp_path, dataflows=_flows(tmp_path, calls),
        workspace=_workspace(tmp_path, "prepare-authorization"),
        resources=ExperimentResources(1, 98),
    )
    valid = DataRequest("etf.ohlcv", "518880.SH", "2026-09-01", "2026-09-02", "2026-09-02")
    with pytest.raises(TypeError, match="DataRequest"):
        context.data.prepare((valid, object()), policy=PreparePolicy.REUSE)
    assert calls == [] and context.trace.data_requests == ()


def test_context_records_preparation_reference_and_fetch_remains_local(tmp_path):
    calls = []
    context = create_experiment_context(
        _definition(), repository_root=tmp_path, dataflows=_flows(tmp_path, calls),
        workspace=_workspace(tmp_path, "bound-read"), resources=ExperimentResources(1, 98),
    )
    request = DataRequest("etf.ohlcv", "518880.SH", "2026-09-01", "2026-09-02", "2026-09-02")
    prepared = context.data.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    assert context.data.fetch(request, prepared=prepared.reference).ready
    assert context.data.fetch(request, prepared=prepared.reference).ready
    assert len(calls) == 1
    assert all(item["prepared"]["manifest_sha256"] == prepared.reference.manifest_sha256
               for item in context.trace.data_requests)


def _candidate() -> StrategyCandidate:
    return StrategyCandidate(
        strategy_family_id="S008",
        candidate_id="C0001",
        payload={"runtime": {}, "parameters": {}},
    )


def _execute_fixture(tmp_path: Path, workspace_name: str):
    experiment = load_experiment(FIXTURE_ROOT)
    context = create_experiment_context(
        experiment.definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, workspace_name),
        resources=ExperimentResources(
            max_workers=4,

            random_seed=experiment.definition.random_seed,
        ),
    )
    return experiment, context, execute_experiment(experiment, context)


def test_s008_fixture_loads_and_executes_through_public_context(
    tmp_path: Path,
) -> None:
    experiment, context, result = _execute_fixture(tmp_path, "experiment-fixture")

    assert result.outcome is ExperimentOutcome.PASS
    assert result.facts == {"rows": 2, "mean_close": 10.25, "max_workers": 4}
    assert result.artifacts[0].kind == "research-summary"
    assert json.loads(context.workspace.path("summary.json").read_text(encoding="utf-8")) == {
        "max_workers": 4,
        "mean_close": 10.25,
        "rows": 2,
    }
    assert context.trace.capabilities == (ExperimentCapability.SEARCH_PARAMETERS,)
    assert context.trace.operations == ("data.prepare", "data.fetch")
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
    with pytest.raises(ValueError, match="differs from expected identity"):
        load_experiment_input(context.workspace.root, expected_receipt_sha256="0" * 64)
    context.workspace.path("execution_failure.json").write_text('{"error_code":"old_failure"}')
    with pytest.raises(ValueError, match="failed experiment execution"):
        load_experiment_input(context.workspace.root, expected_receipt_sha256=result.receipt.sha256)






def test_executor_rechecks_source_after_loading(tmp_path: Path) -> None:
    target = tmp_path / ".tmp" / "post-load-tampered" / FIXTURE_ROOT.name
    target.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, target)
    experiment = load_experiment(target)
    context = create_experiment_context(
        experiment.definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "post-load-tampered"),
        resources=ExperimentResources(
            max_workers=1,
            random_seed=experiment.definition.random_seed,

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


def test_formal_mode_requires_platform_owned_context(tmp_path: Path) -> None:
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
            repository_root=tmp_path,
            dataflows=_flows(tmp_path),
            workspace=_workspace(tmp_path, "fake-formal"),
            resources=resources,
            evaluator=lambda request: EvaluationResult(runs=()),
        )

    context = create_formal_experiment_context(
        definition,
        data_space=DataSpace(Path("data/research")),
        repository_root=tmp_path,
        workspace=_workspace(tmp_path, "formal"),
        resources=resources,
    )
    assert context.definition.mode is ExperimentMode.FORMAL




def test_context_requires_exact_receipted_predecessors(tmp_path: Path) -> None:
    predecessor = load_experiment(FIXTURE_ROOT)
    predecessor_context = create_experiment_context(
        predecessor.definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "predecessor"),
        resources=ExperimentResources(
            max_workers=1,

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
            repository_root=tmp_path,
            dataflows=_flows(tmp_path),
            workspace=_workspace(tmp_path, "missing-predecessor"),
            resources=ExperimentResources(max_workers=1, random_seed=98),
        )

    context = create_experiment_context(
        successor,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "with-predecessor"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
        predecessors=(predecessor_input,),
    )
    assert context.predecessors[predecessor.definition.experiment_id].receipt_sha256 == (
        predecessor_result.receipt.sha256
    )
    with pytest.raises(TypeError, match="receipted result"):
        ExperimentInput()


@pytest.mark.parametrize(
    "declared_datasets,end,real_returns,sealed_validation",
    [
        (("fx.fxcm_daily",), "2026-09-02", False, False),
        (("etf.ohlcv",), "2026-09-03", False, False),
        (("etf.ohlcv",), "2026-09-02", True, False),
        (("etf.ohlcv",), "2026-09-02", False, True),
    ],
)
def test_data_access_records_operations_without_interpreting_research_declarations(
    tmp_path, declared_datasets, end, real_returns, sealed_validation,
):
    calls = []
    def provider(request):
        calls.append(request)
        frame = _frame()
        # Keep every declared weekday when the request extends beyond the cutoff.
        frame = frame.set_index("Date").reindex(pd.bdate_range(request.start, end)).ffill()
        frame = frame.rename_axis("Date").reset_index()
        return _quality_provider_result(request, frame, {"vendor": "synthetic"})
    definition = replace(_definition(), allowed_datasets=declared_datasets)
    context = create_experiment_context(
        definition, repository_root=tmp_path,
        dataflows=_configured_flows(tmp_path, provider),
        workspace=_workspace(tmp_path, "research-declarations"),
        resources=ExperimentResources(1, 98),
        real_returns=real_returns, sealed_validation=sealed_validation,
    )
    request = DataRequest("etf.ohlcv", "518880.SH", "2026-09-01", end, end)
    prepared = context.data.prepare((request,), policy=PreparePolicy.REUSE)
    assert prepared.ready
    result = context.data.fetch(request, prepared=prepared.reference)
    assert result.ready
    assert len(calls) == 1
    assert calls[0].symbol == request.symbol and calls[0].end == request.end
    assert context.trace.operations == ("data.prepare", "data.fetch")
    assert len(context.trace.data_requests) == 2
    expected = tuple(capability for enabled, capability in (
        (real_returns, ExperimentCapability.READ_REAL_RETURNS),
        (sealed_validation, ExperimentCapability.READ_SEALED_VALIDATION),
    ) if enabled)
    assert context.trace.capabilities == expected
    # Explicit action recording has no dependency on declaration flags.
    context.record_capability(ExperimentCapability.SEARCH_PARAMETERS)
    assert ExperimentCapability.SEARCH_PARAMETERS in context.trace.capabilities
    with pytest.raises(ValueError):
        context.record_capability("not-a-capability")


def test_context_tracks_runtime_public_adapters(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    runtime_calls: list[str] = []
    evaluation_calls: list[str] = []

    class FakeRuntime:
        def describe(self, source, **kwargs):
            del source, kwargs
            runtime_calls.append("describe")
            return "runtime-definition"

        def create(self, request):
            runtime_calls.append("create")
            return request

    def evaluator(request: EvaluationRequest) -> EvaluationResult:
        evaluation_calls.append(request.experiment_id)
        return EvaluationResult(runs=())

    definition = _definition(capabilities=ExperimentCapabilities(reads_real_returns=True))
    context = create_experiment_context(
        definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "platform-adapters"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
        runtime=FakeRuntime(),
        evaluator=evaluator,
        real_returns=True,
    )
    assert context.runtime.describe(candidate) == "runtime-definition"
    runtime_request = StrategyInit(
        candidate,
        TradableWindow(date(2026, 9, 1), date(2026, 9, 3)),
        tmp_path / "runtime",
    )
    assert context.runtime.create(runtime_request) is runtime_request
    with pytest.raises(TypeError, match="StrategyInit"):
        context.runtime.create(object())
    assert runtime_calls == ["describe", "create"]
    assert evaluation_calls == []
    assert context.trace.capabilities == ()
    assert context.trace.operations == ("runtime.describe", "runtime.create")


@pytest.fixture
def rejected_evaluation_input(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def evaluator(request: EvaluationRequest) -> EvaluationResult:
        calls.append(request.experiment_id)
        return EvaluationResult(runs=())

    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "resource-budget"),
        resources=ExperimentResources(
            max_workers=1,
            random_seed=98,
        ),
        evaluator=evaluator,
    )
    request = EvaluationRequest(
        repository_root=tmp_path,
        experiment_id=definition.experiment_id,
        strategy=_candidate(),
        runtime_binding={},
        symbol="518880.SH",
        asset_type="etf",
        windows=(EvaluationWindow("full", date(2026, 9, 1), date(2026, 9, 2)),),
        data_cutoff=definition.development_cutoff,
        initial_cash=1_000_000.0,
        costs=(EvaluationCost("standard", 0.001),),
        execution_data=object(),
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    )

    return context, request, calls


def test_evaluation_rejects_workers_above_public_context_limit(rejected_evaluation_input):
    context, request, calls = rejected_evaluation_input
    with pytest.raises(PermissionError, match="workers exceed"):
        context.evaluation.evaluate(replace(request, workers=2))
    assert calls == [] and context.trace.evaluations == ()


def test_evaluation_rejects_unsourced_candidate(rejected_evaluation_input):
    context, request, calls = rejected_evaluation_input
    with pytest.raises(ValueError, match="sourced StrategyCandidate"):
        context.evaluation.evaluate(request)
    assert calls == [] and context.trace.evaluations == ()


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


def test_execute_rejects_unbound_experiment(tmp_path: Path) -> None:
    definition = _definition()
    context = create_experiment_context(
        definition,
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "unbound-experiment"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    with pytest.raises(TypeError, match="loaded by load_experiment"):
        execute_experiment(_CandidateExperiment(definition), context)


def test_bound_candidate_result_records_creation_without_permission_gate(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".tmp" / "bound-candidate" / "S008" / "20260924_S008_EX98"
    root.mkdir(parents=True)
    source = root / "experiment.py"
    source.write_text(
        """from datetime import date
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentDataScope, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id='20260924_S008_EX98',
            strategy_id='S008',
            mode=ExperimentMode.DISCOVERY,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            research_question='Does candidate creation leave a trace?',
            hypothesis='The platform records candidate creation.',
            falsification_conditions=('A candidate has no creation trace',),
            development_cutoff=date(2026, 9, 2),
            random_seed=98,
            allowed_datasets=('etf.ohlcv',),
            subjects=('518880.SH',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.CANDIDATE,
                first_principles=('Candidate creation is a research action',),
                information_paths=('Experiment result -> candidate boundary',),
                stage_objectives=('Verify candidate creation trace',),
                observation_metrics=('operation trace',),
                methodology=('Return one synthetic candidate',),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def synthetic_precheck(self):
        pass

    def execute(self, context):
        del context
        candidate = StrategyCandidate(
            strategy_family_id='S008',
            candidate_id='C0001',
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
        "schema_version": 3,
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
        repository_root=tmp_path,
        dataflows=_flows(tmp_path),
        workspace=_workspace(tmp_path, "candidate-capability"),
        resources=ExperimentResources(max_workers=1, random_seed=98),
    )

    result = execute_experiment(experiment, context)
    assert result.candidate is not None
    assert context.trace.capabilities == (ExperimentCapability.CREATE_CANDIDATE,)
    assert result.receipt.trace == context.trace
