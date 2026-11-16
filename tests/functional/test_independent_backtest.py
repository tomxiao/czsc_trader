# Risk ownership: TDR-25 TDR-26
"""Independent CLI uses authenticated subjects and preserves research storage."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd
import pytest
from dataflows import DataSpace, EquityProduct, MarketId, ProviderBinding, ProviderKey

from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.cli.main import main
from public_backtest_support import assert_public_charts, research_context
from test_backtest import execution_flows
from frozen_contract_support import (
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


REPORT_FILES = {
    "account_daily.csv", "audit.json", "buyhold_account_daily.csv", "chart.html",
    "decisions.csv", "fills.csv", "ma_account_daily.csv", "ma_chart.html", "ma_orders.csv",
    "ma_signals.csv", "ma_trades.csv", "manifest.json", "metrics.json", "observations.json",
    "orders.csv", "report.md", "trades.csv",
    "buyhold_attempts.csv", "buyhold_fills.csv", "ma_attempts.csv", "ma_fills.csv",
}


def assert_v5_cli_backtest(context, request, package, monkeypatch, capsys):
    root = context.repository.root
    (root / "src/czsc_trader").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").touch()
    config_path = root / "inputs.json"
    config_path.write_text(json.dumps({
        "data_space": context.data.binding.space.path.as_posix(),
        "prepared": {"space_id": str(request.prepared.space_id),
                     "preparation_id": str(request.prepared.preparation_id),
                     "manifest_sha256": request.prepared.manifest_sha256},
        "history_start": request.history_start.isoformat(),
        "fee_rate": request.fee_rate,
        "sources": {role: {"provider": source.provider, "revision": source.revision}
                    for role in ("bars", "sessions", "trading_facts")
                    for source in (getattr(request.sources, role),)},
        "step_data_windows": [grant.to_dict() for grant in request.step_data_windows],
    }), encoding="utf-8")
    instrument = request.candidate.instrument
    monkeypatch.chdir(root)
    research_before = _research_files(root)
    capsys.readouterr()
    symbol = instrument.symbol + ".US" if instrument.market is MarketId.US else instrument.symbol
    args = ["backtest", "run", "--strategy", "S999", "--strategy-version", "v1",
            "--symbol", symbol, "--asset", "stock",
            "--start", request.window.start.date().isoformat(), "--end", request.window.end.date().isoformat(),
            "--init-cash", str(request.initial_cash), "--lot-size", str(context.execution_spec.quantity_step),
            "--input-binding", str(config_path), "--data-space", context.data.binding.space.path.as_posix(),
            "--fee-rate", str(request.fee_rate)]
    code = main(args)
    response = json.loads(capsys.readouterr().out)
    assert code == 0 and response["status"] == "PASS", response
    artifacts = {name: root / path for name, path in response["artifacts"].items()}
    assert all(path.is_file() for path in artifacts.values())
    manifest = json.loads(artifacts["manifest.json"].read_bytes())
    assert manifest["release_hash"] == package.release.release_hash
    assert manifest["package_sha256"] == package.package_sha256
    assert manifest["strategy"]["reference"] == "S999-v1"
    assert manifest["prepared"]["manifest_sha256"] == request.prepared.manifest_sha256
    for name, reference in manifest["artifacts"].items():
        assert sha256(artifacts[name].read_bytes()).hexdigest() == reference["sha256"]
    account = json.loads(artifacts["account.json"].read_bytes())["run"]
    assert account["decisions"] and account["fills"]
    assert account["account_daily"][0]["session"][:10] == request.window.start.date().isoformat()
    assert account["account_daily"][-1]["session"][:10] == request.window.end.date().isoformat()
    assert set(response["result"]["metrics"]["benchmarks"]) == {"buyhold", "ma5_ma20"}
    assert response["result"]["metrics"]["strategy"]["metrics"]["return"] == account["metrics"]["total_return"]
    assert json.loads(artifacts["audit.json"].read_bytes())["status"] == "PASS"
    assert set(artifacts) == REPORT_FILES | {"account.json", "inputs.json"}
    assert pd.read_csv(artifacts["account_daily.csv"]).equity.tolist() == pytest.approx(
        [row["equity"] for row in account["account_daily"]])
    reads = [read for decision in account["strategy_data_reads"] for read in decision["reads"]]
    assert reads and all(read["window"]["name"] == "seed" and read["rows"] == 2 for read in reads)
    assert "S999-v1" in artifacts["report.md"].read_text(encoding="utf-8")
    assert _research_files(root) == research_before

    before = list((root / "outputs").iterdir())
    invalid = json.loads(config_path.read_bytes())
    invalid["prepared"]["manifest_sha256"] = "0" * 64
    config_path.write_text(json.dumps(invalid), encoding="utf-8")
    assert main(args) == 5
    failure = json.loads(capsys.readouterr().out)
    assert failure["error"]["code"] == "backtest_failed" and failure["artifacts"] == {}
    assert list((root / "outputs").iterdir()) == before
    if instrument.market is MarketId.CN:
        def synthetic_catalog(*, source, env_file):
            return {ProviderKey(product, instrument.market, source): ProviderBinding(source.provider, source.revision,
                context.data._equity_providers[ProviderKey(product, instrument.market, getattr(request.sources, product.name.lower()))].fetch)
                    for product in EquityProduct}

        monkeypatch.setattr("czsc_trader.cli.equity_backtest.tushare_historical_equity_bindings", synthetic_catalog)
        assert main(args[:-6] + ["--fee-rate", str(request.fee_rate)]) == 0
        automatic = json.loads(capsys.readouterr().out)
        assert set(automatic["artifacts"]) == set(artifacts)
        assert automatic["result"]["metrics"] == response["result"]["metrics"]


def test_cli_accounts_match_research_api_and_keep_historical_output_layout(
    current_frozen, monkeypatch, capsys,
):
    repository, strategy = current_frozen
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
    assert set(result["artifacts"]) == {path.name for path in output.iterdir()} == REPORT_FILES
    assert all((repository.root / path).is_file() for path in result["artifacts"].values())
    links = re.findall(r"\]\(([^)]+\.html)\)", (output / "report.md").read_text(encoding="utf-8"))
    assert links == ["chart.html", "ma_chart.html"]
    assert_public_charts(output)
    assert _research_files(repository.root) == before
    assert (historical / "keep.txt").read_text(encoding="utf-8") == "preserve historical output"
    api = run_backtest(research_context(repository, execution_flows(repository.root)), strategy,
                       BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100))
    assert result["result"]["metrics"] == api.metrics
    saved_account = pd.read_csv(output / "account_daily.csv", parse_dates=["date", "signal_date", "valuation_source_date"])
    saved_account["trading_status"] = saved_account.trading_status.astype(object).where(saved_account.trading_status.notna(), None)
    pd.testing.assert_frame_equal(saved_account, api.result.account_daily, check_dtype=False)


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


@pytest.mark.parametrize('data_context', [pytest.param({'actual_cutoff': '2026-09-18'}, id='valid-cutoff'), pytest.param({'missing_dates': ['2026-09-16']}, id='internal-gap'), pytest.param({'actual_cutoff': 'invalid'}, id='invalid-cutoff')])
def test_execution_data_failure_classification_preserves_source_context(data_context):
    from dataflows import DataError, DataResult, DataStatus
    from czsc_trader.backtesting.execution_data import (
        BacktestExecutionDataNotReadyError, BacktestExecutionDataPreparationError, _require_ready,
    )

    error = DataError('INCOMPLETE_DATA', 'injected incomplete daily observations',
                      context=data_context)
    result = DataResult(status=DataStatus.INCOMPLETE, error=error)
    expected = (BacktestExecutionDataNotReadyError
                if data_context == {'actual_cutoff': '2026-09-18'}
                else BacktestExecutionDataPreparationError)
    # This matrix owns classification of source facts. It does not need to
    # initialize a database, prepare unrelated assets or authenticate a strategy.
    with pytest.raises(expected) as caught:
        _require_ready(result, 'adjusted_daily', pd.bdate_range('2026-09-15', '2026-09-21'),
                       date(2026, 9, 21))
    if expected is BacktestExecutionDataNotReadyError:
        assert caught.value.requested_cutoff == date(2026, 9, 21)
        assert caught.value.published_cutoff == date(2026, 9, 18)
        assert caught.value.first_unpublished_session == date(2026, 9, 21)
    else:
        assert caught.value.error == error
        assert caught.value.input_name == 'adjusted_daily'
        assert 'injected incomplete daily observations' in str(caught.value)
        if 'missing_dates' in data_context:
            assert '2026-09-16' in str(caught.value)


def test_TDR_26_C02_repeated_output_allocates_new_directory_without_overwrite(minimal_repo):
    from czsc_trader.application import RepositoryContext
    from czsc_trader.cli.backtest import _save_reports
    repository = RepositoryContext.discover(minimal_repo)
    files = {'report.md': b'completed account', 'metrics.json': b'{"return":0.1}'}
    root = repository.root / 'outputs'
    first = _save_reports(repository, root, 'S900-v1', files)
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    second = _save_reports(repository, root, 'S900-v1', files)
    assert first != second
    assert {p.name: p.read_bytes() for p in first.iterdir()} == before == files
    assert {p.name: p.read_bytes() for p in second.iterdir()} == files
