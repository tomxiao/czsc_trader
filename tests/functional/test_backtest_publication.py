"""Publication numbering, competition and failure via public run_backtest."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import json
import shutil
import pytest
from strategy_runtime import StrategyCandidate
from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from test_backtest import execution_flows
from public_backtest_support import assert_public_charts
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


@pytest.fixture
def publication_inputs(current_frozen, monkeypatch):
    context, version = current_frozen
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows",
                        lambda repository_root, **kwargs: execution_flows(repository_root))
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)
    return context, version, request


def _public_output(inputs, day, strategy=None):
    context, version, request = inputs
    selected = strategy or version
    result = run_backtest(context, selected, request, run_date=day)
    assert result.status == "PASS"
    path = Path(result.artifacts["output_dir"])
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["strategy"]["reference"] == result.result["strategy"]
    assert result.result["strategy"] == (
        selected.reference_id if isinstance(selected, StrategyCandidate) else selected.release_id
    )
    assert manifest["strategy"]["kind"] == ("CANDIDATE" if isinstance(selected, StrategyCandidate) else "REGISTERED")
    assert manifest["strategy"]["source_hash"] == (
        selected.runtime_identity_sha256 if isinstance(selected, StrategyCandidate) else selected.release_hash
    )
    assert result.result["runtime_engine"] == manifest["application"]["runtime_engine"] == "srt"
    assert result.result["audit_status"] == manifest["audit"]["status"] == "PASS"
    assert manifest["run_date"] == day.isoformat()
    assert (path / "chart.html").is_file() and (path / "report.md").is_file()
    return path


def test_daily_sequence_is_shared_by_candidates_and_releases(publication_inputs, candidate_payload):
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    first = _public_output(publication_inputs, date(2026, 10, 2), candidate)
    second = _public_output(publication_inputs, date(2026, 10, 2))
    third = _public_output(publication_inputs, date(2026, 10, 3))
    assert [path.name for path in (first, second, third)] == [
        "1002_01_S900-C0001", "1002_02_S900-v1", "1003_01_S900-v1",
    ]
    assert_public_charts(first)
    assert_public_charts(second)
    context, _, _ = publication_inputs
    assert not (context.strategy_root / "S900/versions/v2.json").exists()


def test_sequence_uses_maximum_and_grows_beyond_two_digits(publication_inputs):
    context, version, _ = publication_inputs
    first = _public_output(publication_inputs, date(2026, 10, 2))
    high = context.outputs_root / "1002_99_S900-v1"
    shutil.copytree(first, high)
    (context.outputs_root / "unrelated-directory").mkdir()
    result = _public_output(publication_inputs, date(2026, 10, 2))
    assert result.name == "1002_100_S900-v1"
    assert (high / "manifest.json").read_bytes() == (first / "manifest.json").read_bytes()


def test_concurrent_publishers_reserve_unique_daily_numbers(publication_inputs):
    # Prepare immutable inputs once; all contested computation and publication execute normally.
    warmup = _public_output(publication_inputs, date(2026, 10, 1))
    original = (warmup / "manifest.json").read_bytes()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: _public_output(publication_inputs, date(2026, 10, 2)), range(3)))
    assert sorted(int(path.name.split("_")[1]) for path in results) == [1, 2, 3]
    assert len(set(results)) == 3
    assert (warmup / "manifest.json").read_bytes() == original


def test_failed_publication_has_no_final_output_and_releases_reservation(publication_inputs, monkeypatch):
    from czsc_trader.reporting import publication
    original = publication.replace_directory
    def fail(*args):
        raise PermissionError("publication denied")
    monkeypatch.setattr(publication, "replace_directory", fail)
    context, version, request = publication_inputs
    with pytest.raises(ExecutionError, match="publication denied"):
        run_backtest(context, version, request, run_date=date(2026, 10, 2))
    assert not list(context.outputs_root.glob("1002_*"))
    assert not list(context.root.glob(".tmp/backtest/run-*"))
    monkeypatch.setattr(publication, "replace_directory", original)
    assert _public_output(publication_inputs, date(2026, 10, 2)).name == "1002_01_S900-v1"
