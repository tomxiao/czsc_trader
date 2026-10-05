from datetime import date

import pytest
from pathlib import Path
from czsc_trader.experiment_archive import create_experiment_dir, resolve_experiment_dir
from czsc_trader.research_tools.delivery import ExperimentOwner


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


def test_sequence_exhaustion_releases_its_allocation_lock(tmp_path):
    root = tmp_path / "experiments"
    (root / "S011/EX999_20261003").mkdir(parents=True)
    with pytest.raises(ValueError, match="exhausted"):
        create_experiment_dir(root, date(2026, 10, 4), "S011")
    assert not list((tmp_path / ".tmp/experiment-allocation").glob("*.lock"))




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
def test_invalid_new_names_fail_at_contract_boundaries(name):
    with pytest.raises(ValueError):
        ExperimentOwner("S008", name)


def test_concurrent_experiment_allocation_refuses_second_writer(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    root = tmp_path / "experiments"
    entered, release = Event(), Event()
    mkdir = Path.mkdir

    def blocked_mkdir(path, *args, **kwargs):
        if path.name == "EX001_20261003":
            entered.set()
            assert release.wait(10), "allocation barrier was not released"
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", blocked_mkdir)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(create_experiment_dir, root, date(2026, 10, 3), "S900")
        assert entered.wait(10), "first allocator did not reach publication"
        try:
            with pytest.raises(FileExistsError):
                create_experiment_dir(root, date(2026, 10, 3), "S900")
        finally:
            release.set()
        destination = first.result(timeout=10)
    assert destination.name == "EX001_20261003" and destination.is_dir()
    assert create_experiment_dir(root, date(2026, 10, 3), "S900").name == "EX002_20261003"
    assert not list((tmp_path / ".tmp/experiment-allocation").glob("*.lock"))
