from dataclasses import replace
from datetime import date

import pytest
from strategy_runtime import StrategyCandidate

from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from public_backtest_support import research_context
from dataflows import Dataflows, DataSpace, ProviderConfig
from pathlib import Path
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


@pytest.mark.parametrize("lot_size", [None, True, False, 1.0, 100.5, "100", 0, -1])
def test_backtest_lot_size_rejects_invalid_values(lot_size):
    with pytest.raises((TypeError, ValueError), match="lot_size"):
        BacktestRequest("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, lot_size)


def test_backtest_requires_explicit_lot_size():
    from czsc_trader.cli.main import build_parser
    from czsc_trader.application.errors import UsageError

    with pytest.raises(TypeError, match="lot_size"):
        BacktestRequest("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000)
    args = [
        "backtest", "run", "--strategy", "S001", "--strategy-version", "v1",
        "--symbol", "588080.SH", "--asset", "etf", "--start", "2026-09-14",
        "--end", "2026-09-21", "--init-cash", "100000",
    ]
    with pytest.raises(UsageError, match="lot-size"):
        build_parser().parse_args(args)
    assert build_parser().parse_args([*args, "--lot-size", "100"]).lot_size == 100
    for invalid in ("0", "-1", "1.5", "True"):
        with pytest.raises(UsageError, match="positive integer"):
            build_parser().parse_args([*args, "--lot-size", invalid])


def test_lot_size_conflict_fails_before_data_access(candidate_payload, minimal_repo, monkeypatch):
    from czsc_trader.application import RepositoryContext
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    repository = RepositoryContext.discover(minimal_repo, explicit_root=minimal_repo)
    context = research_context(repository, Dataflows(base_dir=minimal_repo, space=DataSpace(Path("research/S900/data")), providers=ProviderConfig(bindings={})))
    def forbidden(**kwargs):
        pytest.fail("conflicting lot_size must fail before fetching data")
    monkeypatch.setattr("czsc_trader.backtesting.service._prepare_backtest_execution_data", forbidden)
    with pytest.raises(ExecutionError, match="lot_size differs"):
        run_backtest(context, candidate, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, 1,
        ))
    assert not (context.repository.root / "outputs").exists()


def test_backtest_rejects_tampered_version_before_data_access(current_frozen, monkeypatch):

    repository, version = current_frozen
    context = research_context(repository, Dataflows(base_dir=repository.root, space=DataSpace(Path("research/S900/data")), providers=ProviderConfig(bindings={})))
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)

    def forbidden(*args, **kwargs):
        pytest.fail("tampered version must fail before preparing any data")

    monkeypatch.setattr(Dataflows, "prepare", forbidden)
    with pytest.raises(ExecutionError, match="differs from the frozen registry"):
        run_backtest(context, replace(version, change_summary="changed"), request)
    assert not (context.repository.root / "outputs").exists()


def test_backtest_public_api_rejects_unsupported_arguments(candidate_payload, minimal_repo, monkeypatch):
    from czsc_trader.application import RepositoryContext

    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    repository = RepositoryContext.discover(minimal_repo, explicit_root=minimal_repo)
    context = research_context(repository, Dataflows(base_dir=minimal_repo, space=DataSpace(Path("research/S900/data")), providers=ProviderConfig(bindings={})))
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid API arguments must fail before preparing data")

    monkeypatch.setattr(Dataflows, "prepare", forbidden)
    with pytest.raises(TypeError, match="dataflows"):
        run_backtest(context, candidate, request, dataflows=object())
    with pytest.raises(TypeError, match="chart_descriptor"):
        run_backtest(context, candidate, request, chart_descriptor={})
    with pytest.raises(TypeError, match="strategy"):
        run_backtest(context, "S001-v1", request)
    with pytest.raises(TypeError, match="request"):
        run_backtest(context, candidate, {})
    assert not (context.repository.root / "outputs").exists()


def test_unknown_cli_version_is_a_validation_failure(minimal_repo, monkeypatch, capsys):
    import json
    from czsc_trader.cli.main import main

    monkeypatch.chdir(minimal_repo)
    assert (
        main(
            [
                "backtest",
                "run",
                "--strategy",
                "S999",
                "--strategy-version",
                "v1",
                "--symbol",
                "588080.SH",
                "--asset",
                "etf",
                "--start",
                "2026-09-14",
                "--end",
                "2026-09-21",
                "--init-cash",
                "100000",
                "--lot-size", "100",
            ]
        )
        != 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "backtest_strategy_invalid"


@pytest.mark.parametrize("kwargs", [
    {"symbol": "../588080.SH"}, {"asset_type": "unknown"},
    {"start": "2026-09-15"}, {"end": date(2026, 9, 1)},
    {"initial_cash": float("inf")}, {"initial_cash": True},
])
def test_backtest_request_rejects_invalid_market_window_and_capital(kwargs):
    values = dict(symbol="588080.SH", asset_type="etf", start=date(2026, 9, 15),
                  end=date(2026, 9, 21), initial_cash=100_000, lot_size=100)
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        BacktestRequest(**values)


def test_backtest_rejects_another_batch_before_data_access(candidate_payload, minimal_repo, monkeypatch):
    from czsc_trader.application import RepositoryContext
    payload, source = candidate_payload
    repository = RepositoryContext.discover(minimal_repo)
    context = research_context(repository, Dataflows(base_dir=minimal_repo,
        space=DataSpace(Path("research/S900/data")), providers=ProviderConfig(bindings={})))
    def forbidden(*args, **kwargs):
        pytest.fail("foreign batch must fail before data preparation")
    monkeypatch.setattr(Dataflows, "prepare", forbidden)
    with pytest.raises(ExecutionError, match="another research batch"):
        run_backtest(context, StrategyCandidate("S901", "C0001", payload, source),
            BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100_000, 100))
