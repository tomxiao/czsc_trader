"""Reports are published explicitly through the research evidence API."""
import re
from pathlib import Path

from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import request_for_prices, publish_reports


def test_explicit_report_publication_keeps_hash_links_and_is_reusable(candidate_payload, tmp_path, monkeypatch):
    import pandas as pd
    dates = pd.bdate_range("2026-09-01", periods=25)
    prices = pd.DataFrame({"dt": dates, "open": 1., "close": 1.})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20)
    result = run_backtest(context, request.strategy, BacktestRequest(
        request.symbol, request.asset_type, request.windows[0].start, request.data_cutoff, request.initial_cash, 100))
    assert not list((tmp_path / "research/S900").glob("experiments/*/evidence/*"))
    references = publish_reports(context, result)
    report = references["report.md"].resolve(tmp_path)
    links = re.findall(r"\]\(([^)]+)\)", report.read_text(encoding="utf-8"))
    assert links == [references["chart.html"].evidence_id, references["ma_chart.html"].evidence_id]
    assert all((report.parent / link).is_file() for link in links)
    hashes = {name: ref.sha256 for name, ref in references.items()}
    again = publish_reports(context, result)
    assert {name: ref.sha256 for name, ref in again.items()} == hashes
    assert references["report.md"].resolve(tmp_path).read_bytes() == report.read_bytes()
    assert Path(report).is_relative_to(tmp_path / "research/S900/experiments")
