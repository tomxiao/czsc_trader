"""REX package boundary tests."""

from __future__ import annotations

from datetime import date
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
    ExperimentWorkspace,
    LoadedExperiment,
    experiment_source_sha256,
    load_experiment,
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
    from dataclasses import replace

    with pytest.raises((TypeError, ValueError)):
        replace(_definition(), **changes)


def test_loaded_experiment_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="only be created by load_experiment"):
        LoadedExperiment()

    with pytest.raises(TypeError, match="platform executor"):
        ExperimentReceipt()


def test_contracts_freeze_payloads_and_validate_resources(tmp_path: Path) -> None:
    result = ExperimentResult(
        outcome=ExperimentOutcome.INCONCLUSIVE,
        facts={"nested": {"values": [1, 2]}},
        diagnostics={},
    )
    repository_root = tmp_path / "repo"
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "rex-test", repository_root
    )
    artifact_path = workspace.path("facts/result.json")
    artifact_path.write_text("{}", encoding="utf-8")
    artifact = workspace.register_artifact("facts/result.json", "facts")

    assert len(_definition().sha256) == 64
    assert result.facts["nested"]["values"] == (1, 2)
    assert artifact.sha256
    workspace.validate_artifact(artifact)
    with pytest.raises(TypeError):
        result.facts["changed"] = True
    with pytest.raises(ValueError, match="positive integer"):
        ExperimentResources(max_workers=0, random_seed=99)
    with pytest.raises(ValueError, match="must be exact"):
        ExperimentDependency("optuna", ">=4.0")
    with pytest.raises(ValueError, match="experiment workspace"):
        workspace.path("../outside.json")


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


def test_loader_does_not_retain_experiment_modules(tmp_path: Path) -> None:
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

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, data_scope=ExperimentDataScope.DEVELOPMENT,
            experiment_id='20260924_S008_EX95',
            strategy_id='S008',
            mode=ExperimentMode.DISCOVERY,
            research_question='Does the loader retain isolated modules?',
            hypothesis='The namespace is removed after construction.',
            falsification_conditions=('The module remains cached',),
            development_cutoff=date(2026, 9, 2),
            random_seed=95,
            allowed_datasets=('etf.ohlcv',),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=('Module state must not leak between loads',),
                information_paths=('Import namespace -> implementation instance',),
                stage_objectives=('Verify loader isolation',),
                observation_metrics=('module cache membership',),
                methodology=('Load and inspect sys.modules',),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context):
        del context
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS, facts={'loaded': True}, diagnostics={}
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
    (root / "experiment_binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )

    loaded = load_experiment(root)

    assert loaded.definition.experiment_id == root.name
    assert not any(
        name.startswith("_czsc_research_experiment_")
        and getattr(module, "__file__", None)
        and Path(module.__file__).resolve().is_relative_to(root)
        for name, module in sys.modules.items()
    )


def test_capability_names_are_stable() -> None:
    assert tuple(item.value for item in ExperimentCapability) == (
        "reads_real_returns",
        "searches_parameters",
        "selects_parameters",
        "creates_candidate",
        "reads_sealed_validation",
    )
