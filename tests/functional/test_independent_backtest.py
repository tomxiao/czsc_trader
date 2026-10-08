"""Independent CLI uses authenticated subjects and preserves research storage."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd
import pytest
from dataflows import DataSpace
from strategy_manager import CandidateKey

from czsc_trader.application import BacktestRequest, load_candidate, run_backtest
from czsc_trader.cli.main import main
from public_backtest_support import assert_public_charts, research_context
from test_backtest import execution_flows
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    completed as completed, managed_evaluation as managed_evaluation,
)


def _arguments(selector):
    return ["backtest", "run", "--strategy", "S900", *selector,
            "--symbol", "588080.SH", "--asset", "etf", "--start", "2026-09-15",
            "--end", "2026-09-21", "--init-cash", "100000", "--lot-size", "100"]


def _research_files(root):
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in (root / "research").rglob("*") if path.is_file()}


@pytest.mark.parametrize("kind", ["candidate", "frozen"])
def test_cli_accounts_match_research_api_and_keep_historical_output_layout(
    kind, request, monkeypatch, capsys,
):
    if kind == "candidate":
        repository = request.getfixturevalue("inspection")[0]
        strategy = load_candidate(repository, CandidateKey("S900", "C0001"))
        selector, reference = ["--candidate-id", "C0001"], "S900-C0001"
    else:
        repository, strategy = request.getfixturevalue("current_frozen")
        selector, reference = ["--strategy-version", "v1"], "S900-v1"
    flows = execution_flows(repository.root, space=DataSpace(Path("data/backtest")))
    monkeypatch.setattr("czsc_trader.cli.backtest._independent_data", lambda _: flows)
    monkeypatch.chdir(repository.root)
    before = _research_files(repository.root)
    day = date.today().strftime("%m%d")
    historical = repository.root / "outputs" / f"{day}_09_S999-v1"
    historical.mkdir(parents=True)
    (historical / "keep.txt").write_text("preserve historical output", encoding="utf-8")

    assert main(_arguments(selector)) == 0
    result = json.loads(capsys.readouterr().out)
    output = repository.root / result["result"]["output_dir"]
    assert output.name == f"{day}_10_{reference}"
    assert result["status"] == "PASS" and "experiment" not in result["result"]
    expected_files = {
        "account_daily.csv", "audit.json", "buyhold_account_daily.csv", "chart.html",
        "decisions.csv", "fills.csv", "ma_account_daily.csv", "ma_chart.html", "ma_orders.csv",
        "ma_signals.csv", "ma_trades.csv", "manifest.json", "metrics.json", "observations.json",
        "orders.csv", "report.md", "trades.csv",
    }
    assert set(result["artifacts"]) == {path.name for path in output.iterdir()} == expected_files
    assert all((repository.root / path).is_file() for path in result["artifacts"].values())
    links = re.findall(r"\]\(([^)]+\.html)\)", (output / "report.md").read_text(encoding="utf-8"))
    assert links == ["chart.html", "ma_chart.html"]
    assert_public_charts(output)
    assert _research_files(repository.root) == before
    assert (historical / "keep.txt").read_text(encoding="utf-8") == "preserve historical output"
    saved = {path.name: path.read_bytes() for path in output.iterdir()}
    assert main(_arguments(selector)) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["result"]["output_dir"] == f"outputs/{day}_11_{reference}"
    assert {path.name: path.read_bytes() for path in output.iterdir()} == saved
    assert _research_files(repository.root) == before

    api = run_backtest(research_context(repository, execution_flows(repository.root)), strategy,
                       BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100))
    assert result["result"]["metrics"] == api.metrics
    pd.testing.assert_frame_equal(pd.read_csv(output / "account_daily.csv", parse_dates=["date", "signal_date"]), api.result.account_daily,
                                  check_dtype=False)
    assert main([*_arguments(selector), "--outputs-root", "custom-output"]) == 0
    custom = json.loads(capsys.readouterr().out)
    assert custom["result"]["output_dir"] == f"custom-output/{day}_01_{reference}"


@pytest.mark.parametrize("selector", [[], ["--candidate-id", "C0001", "--strategy-version", "v1"],
                                       ["--candidate-id", "invalid"]])
def test_cli_rejects_missing_ambiguous_or_invalid_subject_without_output(
    selector, minimal_repo, monkeypatch, capsys,
):
    monkeypatch.chdir(minimal_repo)
    assert main(_arguments(selector)) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL" and result["artifacts"] == {}
    assert not (minimal_repo / "outputs").exists()
    assert not (minimal_repo / "data").exists()


def test_failed_output_write_preserves_existing_runs(minimal_repo, monkeypatch):
    from czsc_trader.cli.backtest import _save_reports
    from czsc_trader.application import RepositoryContext

    repository = RepositoryContext.discover(minimal_repo)
    output_root = minimal_repo / "outputs"
    day = date.today().strftime("%m%d")
    historical = output_root / f"{day}_01_S900-v1"
    historical.mkdir(parents=True)
    keep = historical / "metrics.json"
    keep.write_bytes(b"original")
    write_bytes = Path.write_bytes

    def reject_report(path, content):
        if path.name == "report.md":
            raise OSError("injected disk failure")
        return write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", reject_report)
    with pytest.raises(OSError, match="disk failure"):
        _save_reports(repository, output_root, "S900-v1", {"metrics.json": b"new", "report.md": b"report"})
    assert list(output_root.iterdir()) == [historical]
    assert keep.read_bytes() == b"original"


@pytest.mark.parametrize("failure", ["data", "write"])
def test_cli_calculation_and_output_failures_return_fail_without_partial_reports(
    failure, current_frozen, monkeypatch, capsys,
):
    repository, _ = current_frozen
    flows = execution_flows(repository.root, space=DataSpace(Path("data/backtest")))
    monkeypatch.setattr("czsc_trader.cli.backtest._independent_data", lambda _: flows)
    monkeypatch.chdir(repository.root)
    arguments = _arguments(["--strategy-version", "v1"])
    if failure == "data":
        arguments[arguments.index("--end") + 1] = "2026-09-22"
    else:
        write_bytes = Path.write_bytes

        def reject_report(path, content):
            if path.name == "report.md" and path.is_relative_to(repository.root / "outputs"):
                raise OSError("injected disk failure")
            return write_bytes(path, content)

        monkeypatch.setattr(Path, "write_bytes", reject_report)
    assert main(arguments) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL" and result["artifacts"] == {}
    assert result["error"]["code"] == ("backtest_failed" if failure == "data" else "backtest_output_failed")
    assert not list((repository.root / "outputs").glob("*"))
    assert not (repository.root / "research").exists()


@pytest.mark.parametrize(("option", "value"), [("--init-cash", "0"), ("--init-cash", "nan"),
                                               ("--end", "2026-09-14")])
def test_cli_invalid_request_is_rejected_before_strategy_and_data_access(
    option, value, minimal_repo, monkeypatch, capsys,
):
    monkeypatch.chdir(minimal_repo)
    arguments = _arguments(["--strategy-version", "v1"])
    arguments[arguments.index(option) + 1] = value
    assert main(arguments) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL" and result["error"]["code"] == "backtest_request_invalid"
    assert not (minimal_repo / "outputs").exists()
    assert not (minimal_repo / "data").exists()
