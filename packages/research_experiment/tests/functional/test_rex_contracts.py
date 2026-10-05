"""REX package boundary tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest
import research_experiment
from research_experiment import (
    ExperimentDataScope, ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentReceipt,
    ExperimentResources,
    ExperimentResult,
    ExperimentStage,
    ExperimentTrace,
    LoadedExperiment,
    experiment_source_sha256,
    load_experiment,
    load_experiment_input,
)


def _definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        schema_version=2, data_scope=ExperimentDataScope.DEVELOPMENT,
        experiment_id="20260924_S008_EX99",
        strategy_id="S008",
        mode=ExperimentMode.DISCOVERY,
        research_question="Can REX load a standalone experiment?",
        hypothesis="The declared source closure is sufficient.",
        falsification_conditions=("The implementation cannot be loaded",),
        development_cutoff=date(2026, 9, 2),
        random_seed=99,
        allowed_datasets=("etf.ohlcv",),
        protocol=ExperimentProtocol(
            stage=ExperimentStage.PROTOTYPE,
            first_principles=("Synthetic prices are sufficient for a contract test",),
            information_paths=("Published prices -> deterministic summary",),
            stage_objectives=("Exercise the standalone REX contract",),
            observation_metrics=("rows",),
            methodology=("Load and execute one deterministic implementation",),
        ),
        capabilities=ExperimentCapabilities(searches_parameters=True),
    )


def test_rex_public_contracts_import_without_tdr() -> None:
    source_root = Path(research_experiment.__file__).resolve().parent.parent
    script = """
import importlib.abc
import sys

class NoTdrImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'czsc_trader':
            raise AssertionError('REX loaded TDR: ' + fullname)

sys.meta_path.insert(0, NoTdrImports())
sys.path.insert(0, sys.argv[1])
import research_experiment
for name in research_experiment.__all__:
    getattr(research_experiment, name)
assert not any(name.split('.')[0] == 'czsc_trader' for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source_root)],
        check=True, timeout=30,
    )


@pytest.mark.parametrize("changes", [{"schema_version": 1}, {"schema_version": True}, {"data_scope": None}])
def test_definition_rejects_retired_or_implicit_scope(changes):
    with pytest.raises((TypeError, ValueError)):
        replace(_definition(), **changes)


def test_definition_records_research_declarations_without_authorizing_actions(tmp_path: Path) -> None:
    formal = replace(
        _definition(), mode=ExperimentMode.FORMAL, capabilities=ExperimentCapabilities()
    )
    sealed = replace(
        formal,
        data_scope=ExperimentDataScope.SEALED_VALIDATION,
        validation_cutoff=date(2026, 9, 3),
        capabilities=ExperimentCapabilities(searches_parameters=True, selects_parameters=True),
    )
    declared = replace(
        formal, capabilities=ExperimentCapabilities(reads_sealed_validation=True)
    )

    assert not sealed.capabilities.reads_real_returns
    assert not sealed.capabilities.reads_sealed_validation
    assert len({formal.sha256, sealed.sha256, declared.sha256}) == 3

    # Capability names are a serialized boundary, including undeclared actions.
    names = [
        "reads_real_returns", "searches_parameters", "selects_parameters",
        "creates_candidate", "reads_sealed_validation",
    ]
    trace = ExperimentTrace(
        capabilities=tuple(ExperimentCapability), operations=(), data_requests=(),
        data_scope=ExperimentDataScope.DEVELOPMENT,
    )
    assert trace.to_dict()["capabilities"] == names
    result = ExperimentResult(ExperimentOutcome.PASS, {"names": names}, {}).to_dict()

    def digest(value):
        return sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")).hexdigest()

    receipt = {
        "schema_version": 2, "experiment_id": formal.experiment_id,
        "definition_sha256": formal.sha256, "source_sha256": "a" * 64,
        "resources_sha256": ExperimentResources(1, 99).sha256,
        "predecessor_receipts": {}, "result_sha256": digest(result),
        "artifact_sha256": {}, "trace": trace.to_dict(),
    }
    receipt_sha256 = digest(receipt)
    (tmp_path / "execution_envelope.json").write_text(json.dumps({
        "schema_version": 1, "receipt": receipt,
        "receipt_sha256": receipt_sha256, "result": result,
    }), encoding="utf-8")
    (tmp_path / "execution_receipt.json").write_text(json.dumps({
        **receipt, "receipt_sha256": receipt_sha256,
    }), encoding="utf-8")
    verified = load_experiment_input(tmp_path, expected_receipt_sha256=receipt_sha256)
    assert verified.receipt_sha256 == receipt_sha256
    assert verified.facts["names"] == tuple(names)
    with pytest.raises(ValueError, match="validation_cutoff after development_cutoff"):
        replace(sealed, validation_cutoff=sealed.development_cutoff)
    with pytest.raises(ValueError, match="DEVELOPMENT cannot declare validation_cutoff"):
        replace(formal, validation_cutoff=date(2026, 9, 3))
    with pytest.raises(ValueError, match="must be boolean"):
        ExperimentCapabilities(reads_real_returns="yes")
    with pytest.raises(ValueError, match="unique"):
        replace(formal, allowed_datasets=("etf.ohlcv", "etf.ohlcv"))


def test_loaded_experiment_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="only be created by load_experiment"):
        LoadedExperiment()

    with pytest.raises(TypeError, match="platform executor"):
        ExperimentReceipt()


def test_result_freezes_nested_payloads_without_aliasing() -> None:
    facts = {"nested": {"values": [1, 2]}}
    result = ExperimentResult(
        outcome=ExperimentOutcome.INCONCLUSIVE,
        facts=facts,
        diagnostics={},
    )
    facts["nested"]["values"].append(3)
    assert result.facts["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        result.facts["changed"] = True
    with pytest.raises(TypeError):
        result.facts["nested"]["changed"] = True
    payload = result.to_dict()
    payload["facts"]["nested"]["values"].append(4)
    assert result.facts["nested"]["values"] == (1, 2)


def test_resources_and_dependencies_require_explicit_execution_configuration() -> None:
    assert len(ExperimentResources(max_workers=1, random_seed=99).sha256) == 64
    with pytest.raises(ValueError, match="positive integer"):
        ExperimentResources(max_workers=0, random_seed=99)
    with pytest.raises(ValueError, match="must be exact"):
        ExperimentDependency("optuna", ">=4.0")


def test_loader_rejects_undeclared_relative_source(tmp_path: Path) -> None:
    root = tmp_path / "S008" / "20260924_S008_EX99"
    root.mkdir(parents=True)
    source = root / "experiment.py"
    source.write_text(
        """from datetime import date
from research_experiment import (
    ExperimentDataScope, ExperimentCapabilities, ExperimentDefinition, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)
from .helper import VALUE

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, data_scope=ExperimentDataScope.DEVELOPMENT,
            experiment_id='20260924_S008_EX99',
            strategy_id='S008',
            mode=ExperimentMode.DISCOVERY,
            research_question='Can undeclared source enter the closure?',
            hypothesis='REX rejects the undeclared helper.',
            falsification_conditions=('The helper is accepted',),
            development_cutoff=date(2026, 9, 2),
            random_seed=99,
            allowed_datasets=('etf.ohlcv',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=('Synthetic source closure is observable',),
                information_paths=('Helper import -> returned value',),
                stage_objectives=('Reject undeclared source imports',),
                observation_metrics=('load outcome',),
                methodology=('Load a module with an undeclared helper',),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context):
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={'value': VALUE},
            diagnostics={},
        )
""",
        encoding="utf-8",
    )
    (root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    binding = {
        "schema_version": 3,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py",)),
        "dependencies": [],
    }
    (root / "experiment_binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="undeclared source files"):
        load_experiment(root)


def test_loader_checks_dependencies_before_importing_experiment(tmp_path: Path) -> None:
    root = tmp_path / "S008" / "20260924_S008_EX96"
    root.mkdir(parents=True)
    source = root / "experiment.py"
    marker = root / "imported.txt"
    source.write_text(
        "from pathlib import Path\nPath(__file__).with_name('imported.txt').write_text('yes')\n",
        encoding="utf-8",
    )
    binding = {
        "schema_version": 3,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py",)),
        "dependencies": [
            {"name": "czsc-definitely-missing-rex-test", "version": "1.0.0"}
        ],
    }
    (root / "experiment_binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="dependency is not installed"):
        load_experiment(root)

    assert not marker.exists()


def test_loader_isolates_same_named_modules_and_repeated_loads(tmp_path: Path) -> None:
    root = tmp_path / "S008" / "20260924_S008_EX95"
    root.mkdir(parents=True)
    source = root / "experiment.py"
    source.write_text(
        """from datetime import date
from research_experiment import (
    ExperimentDataScope, ExperimentCapabilities, ExperimentDefinition, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult,
    ExperimentStage, ResearchExperiment,
)
from .helper import VALUE

CALLS = 0

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, data_scope=ExperimentDataScope.DEVELOPMENT,
            experiment_id='20260924_S008_EX95',
            strategy_id='S008',
            mode=ExperimentMode.DISCOVERY,
            research_question='Does the loader isolate same-named source modules?',
            hypothesis='Each load owns its module state and declared helper.',
            falsification_conditions=('The returned helper value or counter leaks',),
            development_cutoff=date(2026, 9, 2),
            random_seed=95,
            allowed_datasets=('etf.ohlcv',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=('Module state must not leak between loads',),
                information_paths=('Import namespace -> implementation instance',),
                stage_objectives=('Verify loader isolation',),
                observation_metrics=('returned helper value and invocation count',),
                methodology=('Execute two same-named modules and reload the first',),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context):
        del context
        global CALLS
        CALLS += 1
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={'value': VALUE, 'calls': CALLS}, diagnostics={}
        )
""",
        encoding="utf-8",
    )
    (root / "helper.py").write_text("VALUE = 'first'\n", encoding="utf-8")
    binding = {
        "schema_version": 3,
        "module": "experiment",
        "qualname": "Experiment",
        "source_files": ["experiment.py", "helper.py"],
        "source_sha256": experiment_source_sha256(root, ("experiment.py", "helper.py")),
        "dependencies": [],
    }
    (root / "experiment_binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )

    loaded = load_experiment(root)
    assert loaded.definition.experiment_id == root.name
    assert dict(loaded.implementation.execute(None).facts) == {"value": "first", "calls": 1}

    # A distinct research root deliberately uses identical module and class names.
    other_root = tmp_path / "S008" / "20260924_S008_EX94"
    other_root.mkdir()
    (other_root / "experiment.py").write_text(
        source.read_text(encoding="utf-8").replace(root.name, other_root.name),
        encoding="utf-8",
    )
    (other_root / "helper.py").write_text("VALUE = 'second'\n", encoding="utf-8")
    other_binding = {
        **binding,
        "source_sha256": experiment_source_sha256(other_root, ("experiment.py", "helper.py")),
    }
    (other_root / "experiment_binding.json").write_text(
        json.dumps(other_binding), encoding="utf-8"
    )
    other = load_experiment(other_root)
    assert other.definition.experiment_id == other_root.name
    assert dict(other.implementation.execute(None).facts) == {"value": "second", "calls": 1}
    assert dict(loaded.implementation.execute(None).facts) == {"value": "first", "calls": 2}

    reloaded = load_experiment(root)
    assert dict(reloaded.implementation.execute(None).facts) == {"value": "first", "calls": 1}
    assert dict(other.implementation.execute(None).facts) == {"value": "second", "calls": 2}
    # Cache cleanup is supplemental; public execution above proves isolation.
    assert not any(
        name.startswith("_czsc_research_experiment_")
        and getattr(module, "__file__", None)
        and any(Path(module.__file__).resolve().is_relative_to(path) for path in (root, other_root))
        for name, module in sys.modules.items()
    )
