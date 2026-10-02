from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from czsc_trader.reporting import publication


def _stage(root, number):
    path = root / ".tmp" / f"staging-{number}"
    path.mkdir(parents=True)
    (path / "report.md").write_text(str(number), encoding="utf-8")
    return path


def test_daily_sequence_is_shared_by_candidates_and_releases(tmp_path):
    root = tmp_path / "outputs"
    names = []
    for number, (reference, day) in enumerate([
        ("S011-C0621", date(2026, 10, 2)),
        ("S007-v1", date(2026, 10, 2)),
        ("S011-C0621", date(2026, 10, 2)),
        ("S007-v1", date(2026, 10, 3)),
    ]):
        result = publication.publish_run_directory(_stage(tmp_path, number), root, reference, day)
        names.append(result.name)
        assert (result / "report.md").read_text(encoding="utf-8") == str(number)
    assert names == [
        "1002_01_S011-C0621", "1002_02_S007-v1", "1002_03_S011-C0621", "1003_01_S007-v1",
    ]


def test_sequence_uses_maximum_and_grows_beyond_two_digits(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    for name in ("1002_01_S011-C0621", "1002_99_S007-v1", "S011C0621_159326_1002_BT01"):
        (root / name).mkdir()
    result = publication.publish_run_directory(
        _stage(tmp_path, 0), root, "S011-C0621", date(2026, 10, 2),
    )
    assert result.name == "1002_100_S011-C0621"
    assert (root / "1002_99_S007-v1").is_dir()


def test_concurrent_publishers_reserve_unique_daily_numbers(tmp_path):
    root = tmp_path / "outputs"
    stages = [_stage(tmp_path, i) for i in range(12)]
    def publish(i):
        return publication.publish_run_directory(
            stages[i], root, f"S011-C{i:04d}", date(2026, 10, 2),
        )
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(publish, range(12)))
    assert sorted(int(path.name.split("_")[1]) for path in results) == list(range(1, 13))
    for i, path in enumerate(results):
        assert (path / "report.md").read_text(encoding="utf-8") == str(i)


def test_failed_publication_keeps_staging_and_releases_reservation(tmp_path, monkeypatch):
    stage = _stage(tmp_path, 0)
    root = tmp_path / "outputs"
    original = publication.replace_directory
    def fail(*args):
        raise PermissionError("publication denied")
    monkeypatch.setattr(publication, "replace_directory", fail)
    with pytest.raises(PermissionError, match="publication denied"):
        publication.publish_run_directory(stage, root, "S011-C0621", date(2026, 10, 2))
    assert stage.is_dir()
    assert not list(root.glob("1002_*"))
    monkeypatch.setattr(publication, "replace_directory", original)
    result = publication.publish_run_directory(stage, root, "S011-C0621", date(2026, 10, 2))
    assert result.name == "1002_01_S011-C0621"


@pytest.mark.parametrize("reference", ["../escape", "C0621", "S011-CFG000621R2", "S011-v01"])
def test_invalid_strategy_reference_is_rejected_before_publication(tmp_path, reference):
    stage = _stage(tmp_path, 0)
    with pytest.raises(ValueError, match="strategy reference"):
        publication.publish_run_directory(stage, tmp_path / "outputs", reference, date(2026, 10, 2))
    assert stage.is_dir()
