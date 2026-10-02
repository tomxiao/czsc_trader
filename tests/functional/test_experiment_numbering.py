from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest
from research_experiment import load_experiment, experiment_source_sha256
from strategy_manager import CandidateRegistrationOrigin, CandidateEvidence
from czsc_trader.experiment_archive import create_experiment_dir, resolve_experiment_dir
from czsc_trader.research_tools.delivery import ExperimentOwner
from test_research_experiment import _definition, _write_v3_experiment


def test_monotonic_across_dates_and_existing_archives(tmp_path):
    root = tmp_path / "experiments"
    first = create_experiment_dir(root, date(2026, 10, 3), "S011")
    assert first.name == "EX001_20261003"
    assert create_experiment_dir(root, date(2026, 10, 4), "S011").name == "EX002_20261004"
    (root / "S011/20261002_S011_EX77").mkdir()
    assert create_experiment_dir(root, date(2026, 10, 5), "S011").name == "EX078_20261005"
    assert create_experiment_dir(root, date(2026, 10, 3), "S009").name == first.name
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_experiment_dir(root, first.name)
    assert resolve_experiment_dir(root, first.name, strategy_id="S011") == first


def test_sequence_exhaustion_and_lock_release(tmp_path):
    root = tmp_path / "experiments"
    (root / "S011/EX999_20261003").mkdir(parents=True)
    with pytest.raises(ValueError, match="exhausted"):
        create_experiment_dir(root, date(2026, 10, 4), "S011")
    assert not list((tmp_path / ".tmp/experiment-allocation").glob("*.lock"))
    (root / "S009").mkdir()
    lock_root = tmp_path / ".tmp/experiment-allocation"
    key = sha256(str((root / "S009").resolve()).encode()).hexdigest()
    lock = lock_root / f"{key}.lock"
    lock.touch()
    with pytest.raises(FileExistsError):
        create_experiment_dir(root, date(2026, 10, 4), "S009")
    assert lock.exists()
    assert not list((root / "S009").iterdir())


def test_new_name_loads_through_existing_binding(tmp_path):
    import json
    root = tmp_path / "S009/EX001_20261003"
    _write_v3_experiment(root)
    source = root / "experiment.py"
    source.write_text(source.read_text().replace("20260925_S009_EX99", root.name), encoding="utf-8")
    binding_path = root / "experiment_binding.json"
    binding = json.loads(binding_path.read_text())
    binding["source_sha256"] = experiment_source_sha256(root, ("experiment.py",))
    binding_path.write_text(json.dumps(binding))
    loaded = load_experiment(root)
    assert loaded.definition.experiment_id == root.name
    assert ExperimentOwner("S009", root.name).experiment_id == root.name
    assert CandidateRegistrationOrigin(root.name, "a"*64, "b"*64, CandidateEvidence("p.json", "c"*64))


@pytest.mark.parametrize("name", ["EX000_20261003", "EX01_20261003", "EX1000_20261003", "EX００１_20261003", "../EX001_20261003"])
def test_invalid_new_names_fail_at_contract_boundaries(name):
    with pytest.raises(ValueError):
        replace(_definition(), experiment_id=name)
    with pytest.raises(ValueError):
        ExperimentOwner("S008", name)
