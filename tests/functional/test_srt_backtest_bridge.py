"""Historical diagnostics and tradable targets through public evaluation."""
import pandas as pd
import pytest
from strategy_runtime import RuntimeContractError, implementation_sha256
from czsc_trader.research_tools import evaluate_strategy
from public_backtest_support import request_for_prices


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
    return request_for_prices(candidate_payload, tmp_path, monkeypatch, daily)[1]


def test_srt_history_allows_unavailable_diagnostics_during_warmup(candidate_payload, tmp_path, monkeypatch):
    request = _history_request(candidate_payload, tmp_path, monkeypatch)
    result = evaluate_strategy(request)
    assert len(result.runs) == 1
    assert len(result.runs[0].signals.decisions) == 2
    assert result.runs[0].signals.decisions["factor_score"].isna().all()
    assert result.runs[0].execution.account_daily["equity"].eq(request.initial_cash).all()


def test_srt_history_rejects_unavailable_target_position(candidate_payload, tmp_path, monkeypatch):
    request = _history_request(candidate_payload, tmp_path, monkeypatch, invalid_target=True)
    with pytest.raises(RuntimeContractError, match="target positions"):
        evaluate_strategy(request)
