"""REX source binding, immutable payloads and serialized evidence contracts."""

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import pytest
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDataScope,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResources,
    ExperimentResult,
    ExperimentStage,
    ExperimentWorkspace,
    experiment_source_sha256,
    load_experiment,
    load_experiment_input,
)


def canonical_sha256(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


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
        data_scope=ExperimentDataScope.SEALED_VALIDATION
        if validation_cutoff
        else ExperimentDataScope.DEVELOPMENT,
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


@pytest.fixture
def execution_evidence(tmp_path):
    # Synthetic reader input has no dependency on a TDR executor or context.
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    data = b'{"rows":2}'
    (workspace / "summary.json").write_bytes(data)
    artifact = {"path": "summary.json", "kind": "summary", "sha256": sha256(data).hexdigest()}
    result = {
        "outcome": "PASS",
        "facts": {"rows": 2},
        "diagnostics": {},
        "artifacts": [artifact],
        "candidate": None,
    }
    receipt = {
        "schema_version": 2,
        "experiment_id": "EX001_20261003",
        "definition_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "resources_sha256": "c" * 64,
        "predecessor_receipts": {},
        "result_sha256": canonical_sha256(result),
        "artifact_sha256": {"summary.json": artifact["sha256"]},
        "trace": {
            "capabilities": [],
            "operations": [],
            "data_requests": [],
            "evaluations": [],
            "data_scope": "DEVELOPMENT",
        },
    }
    digest = canonical_sha256(receipt)
    envelope = {"schema_version": 1, "receipt": receipt, "receipt_sha256": digest, "result": result}
    (workspace / "execution_envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    (workspace / "execution_receipt.json").write_text(
        json.dumps({**receipt, "receipt_sha256": digest}), encoding="utf-8"
    )
    assert load_experiment_input(workspace, expected_receipt_sha256=digest).facts["rows"] == 2
    return workspace, digest


@pytest.mark.parametrize("mutation", ["result", "artifact"])
def test_reader_rejects_result_or_artifact_tampering(execution_evidence, mutation):
    workspace, digest = execution_evidence
    if mutation == "result":
        path = workspace / "execution_envelope.json"
        envelope = json.loads(path.read_text())
        envelope["result"]["facts"]["rows"] = 99
        path.write_text(json.dumps(envelope), encoding="utf-8")
    else:
        (workspace / "summary.json").write_text('{"tampered":true}', encoding="utf-8")
    with pytest.raises(
        ValueError, match="result hash differs" if mutation == "result" else "artifact hash differs"
    ):
        load_experiment_input(workspace, expected_receipt_sha256=digest)


def test_loader_rejects_source_tampering(tmp_path):
    root = _write_v3_experiment(tmp_path / "S009/20260925_S009_EX99")
    assert load_experiment(root).definition.experiment_id == root.name
    source = root / "experiment.py"
    source.write_text(source.read_text() + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source SHA-256 differs"):
        load_experiment(root)


def test_workspace_rejects_escape_and_detects_artifact_change(
    tmp_path: Path,
) -> None:
    workspace = ExperimentWorkspace(tmp_path / ".tmp/workspace-boundary", tmp_path)
    with pytest.raises(ValueError, match="experiment workspace"):
        workspace.path("../outside.json")
    target = workspace.path("facts/result.json")
    target.write_text("{}", encoding="utf-8")
    artifact = workspace.register_artifact("facts/result.json", "facts")
    workspace.validate_artifact(artifact)
    target.write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash differs"):
        workspace.validate_artifact(artifact)


def test_result_rejects_nonfinite_json():
    # Immutable tuple/hash/exact-dependency assertions remain in the REX primary
    # contract scenario. This is the unique scalar rejection previously in TDR.
    with pytest.raises(ValueError, match="finite JSON"):
        ExperimentResult(ExperimentOutcome.FAIL, {"bad": float("nan")}, {})


def test_historical_receipt_is_rejected_without_modifying_original(tmp_path):
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


def test_definition_rejects_untyped_scope_and_resources_do_not_accept_search_budget():
    # Formal declaration semantics already live in the REX primary contract test.
    with pytest.raises(ValueError, match="ExperimentDataScope"):
        replace(_definition(), data_scope="DEVELOPMENT")
    with pytest.raises(TypeError, match="max_evaluations"):
        ExperimentResources(1, 1, max_evaluations=1)


@pytest.mark.parametrize(
    "name",
    [
        "EX000_20261003",
        "EX01_20261003",
        "EX1000_20261003",
        "EX００１_20261003",
        "../EX001_20261003",
    ],
)
def test_definition_rejects_invalid_new_archive_names(name):
    with pytest.raises(ValueError):
        replace(_definition(), experiment_id=name)
