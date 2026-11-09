# Risk ownership: TDR-25
from dataclasses import replace
from datetime import date

import pytest

from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from public_backtest_support import research_context
from dataflows import Dataflows, DataSpace, ProviderConfig
from pathlib import Path
from frozen_contract_support import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


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


def test_backtest_rejects_tampered_version_before_data_access(current_frozen, monkeypatch):

    repository, version = current_frozen
    context = research_context(repository, Dataflows(base_dir=repository.root, space=DataSpace(Path("research/S900/assets/data")), providers=ProviderConfig(bindings={})))
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)

    def forbidden(*args, **kwargs):
        pytest.fail("tampered version must fail before preparing any data")

    monkeypatch.setattr(Dataflows, "prepare", forbidden)
    with pytest.raises(ExecutionError, match="differs from the frozen registry"):
        run_backtest(context, replace(version, change_summary="changed"), request)
    assert not (context.repository.root / "outputs").exists()


@pytest.mark.parametrize('kwargs', [pytest.param({'end': date(2026, 9, 1)}, id='TDR-25-C03'), pytest.param({'initial_cash': float('inf')}, id='TDR-25-C02')])
def test_backtest_request_rejects_invalid_market_window_and_capital(kwargs):
    values = dict(symbol="588080.SH", asset_type="etf", start=date(2026, 9, 15),
                  end=date(2026, 9, 21), initial_cash=100_000, lot_size=100)
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        BacktestRequest(**values)


def test_backtest_rejects_another_batch_before_data_access(current_frozen, monkeypatch):
    repository, version = current_frozen
    context = research_context(repository, Dataflows(base_dir=repository.root,
        space=DataSpace(Path("research/S901/assets/data")), providers=ProviderConfig(bindings={})), strategy_id='S901')
    def forbidden(*args, **kwargs):
        pytest.fail("foreign batch must fail before data preparation")
    monkeypatch.setattr(Dataflows, "prepare", forbidden)
    with pytest.raises(ExecutionError, match="another research batch"):
        run_backtest(context, version,
            BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100_000, 100))
