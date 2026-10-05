"""Public backtest HTML safety and observation-to-ledger identity."""
from dataclasses import replace
from pathlib import Path
import re
import pandas as pd
import pytest
from strategy_runtime import implementation_sha256
from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from public_backtest_support import request_for_prices, assert_public_charts, chart_payload


def test_backtest_chart_escapes_permitted_observation_text(candidate_payload, tmp_path, monkeypatch):
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    text = path.read_text(encoding="utf-8")
    untrusted = "</script><script>alert(1)</script>"
    text, count = re.subn(r'ObservationSeries\("fixture", "[^"]+", "fixture_signal"\)',
                         f'ObservationSeries("fixture", {untrusted!r}, "fixture_signal")', text)
    assert count == 1
    assert untrusted in text
    path.write_text(text, encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(payload["runtime"]["source_files"], source_root=source)
    days = pd.bdate_range("2026-08-17", periods=23)
    prices = pd.DataFrame({"dt": days, "open": 1., "close": 1.})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20)
    result = run_backtest(context, request.strategy, BacktestRequest(
        "588080.SH", "etf", days[20].date(), days[-1].date(), 100000, 100,
    ))
    assert result.status == "PASS"
    output = Path(result.artifacts["output_dir"])
    html = (output / "chart.html").read_text(encoding="utf-8")
    assert untrusted not in html
    assert chart_payload(html)["observations"][0]["observation"]["series"][0]["label"] == untrusted
    assert_public_charts(output)


@pytest.mark.parametrize("mismatch", ["strategy", "target"])
def test_backtest_rejects_observations_that_differ_from_audited_decisions(candidate_payload, tmp_path, monkeypatch, mismatch):
    from czsc_trader.backtesting.service import replay_srt_account
    days = pd.bdate_range("2026-08-17", periods=23)
    prices = pd.DataFrame({"dt": days, "open": 1., "close": 1.})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20)
    def altered(**kwargs):
        replay = replay_srt_account(**kwargs)
        first = replay.observations[0]
        if mismatch == "strategy":
            first = replace(first, strategy=replace(first.strategy, release_hash="f" * 64))
        else:
            first = replace(first, target_position=1. - first.target_position)
        return replace(replay, observations=(first, *replay.observations[1:]))
    monkeypatch.setattr("czsc_trader.backtesting.service.replay_srt_account", altered)
    with pytest.raises(ExecutionError, match="chart observation"):
        run_backtest(context, request.strategy, BacktestRequest(
            "588080.SH", "etf", days[20].date(), days[-1].date(), 100000, 100,
        ))
    assert not list(context.outputs_root.glob("*/manifest.json"))
