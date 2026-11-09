# Risk ownership: TDR-25
"""Historical diagnostics and tradable targets through the public SRT/TXE bridge."""
from datetime import timedelta

import pandas as pd
import pytest
from dataflows import PreparePolicy
from strategy_runtime import (implementation_sha256, StrategyInit, StrategyRuntime,
                              TradableWindow, RuntimeContractError)
from execution_channels.historical import HistoricalExecutor
from execution_channels.policy import ExecutionPolicy
from execution_channels.serialization import from_record, to_record
from czsc_trader.application.session_replay import replay_sessions
from czsc_trader.backtesting.observation import ObservationExecutor
from public_backtest_support import request_for_prices


def _evaluate(context, request):
    window, = request.windows
    strategy = StrategyRuntime(dataflows=context.data).create(StrategyInit(
        request.strategy, TradableWindow(window.start, window.end), context.repository.root / '.tmp/bridge'))
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    history = strategy.inspect_signals()
    prices = pd.DataFrame({'dt':pd.bdate_range(window.start-timedelta(days=1), window.end), 'open':1., 'close':1.})
    executor = HistoricalExecutor(strategy_reference=strategy.definition.release_id,
        symbol=strategy.identity.symbol, execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=['dt','open','high','low','close']),
        evaluation_start=pd.Timestamp(window.start), evaluation_end=pd.Timestamp(window.end),
        initial_cash=request.initial_cash, execution_policy=from_record(ExecutionPolicy, to_record(strategy.definition.execution)),
        order_types=strategy.definition.capabilities.order_types)
    return history, replay_sessions(strategy, ObservationExecutor(strategy.definition, executor))


def _history_request(candidate_payload, tmp_path, monkeypatch, *, invalid_target=False):
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    text = path.read_text(encoding="utf-8")
    if invalid_target:
        text = text.replace('        return pd.DataFrame(', '        target.iloc[-1] = float("nan")\n        return pd.DataFrame(')
    else:
        text = text.replace('"fixture_signal": target}', '"fixture_signal": target, "base_score": float("nan"), "confirmation_score": 0.1}')
    path.write_text(text, encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=source,
    )
    dates = pd.bdate_range("2026-09-14", periods=3)
    daily = pd.DataFrame({"dt": dates, "open": 1., "close": 1.})
    return request_for_prices(candidate_payload, tmp_path, monkeypatch, daily)[:2]


def test_srt_history_allows_unavailable_diagnostics_during_warmup(candidate_payload, tmp_path, monkeypatch):
    context, request = _history_request(candidate_payload, tmp_path, monkeypatch)
    history, result = _evaluate(context, request)
    assert history['base_score'].isna().all()
    assert len(result.decisions) == 2
    assert result.account_daily['equity'].eq(request.initial_cash).all()

    # Diagnostic warmup values may be absent. Turning the tradable target into
    # a missing value is a different condition in this same prepared history.
    from copy import deepcopy
    from shutil import copytree
    payload, source = candidate_payload
    payload = deepcopy(payload)
    changed_source = copytree(source, tmp_path / 'invalid-target-source/strategy_runtime')
    path = changed_source / 'strategies/candidate_fixture.py'
    path.write_text(path.read_text(encoding='utf-8').replace(
        '        return pd.DataFrame(', '        target.iloc[-1] = float("nan")\n        return pd.DataFrame('),
        encoding='utf-8', newline='\n')
    payload['runtime']['source_sha256'] = implementation_sha256(payload['runtime']['source_files'], source_root=changed_source)
    from dataclasses import replace
    changed = replace(request, strategy=replace(request.strategy, payload=payload, source_root=changed_source))
    with pytest.raises(RuntimeContractError, match='target positions'):
        _evaluate(context, changed)
