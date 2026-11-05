"""Reports are published explicitly through the research evidence API."""
import re
from pathlib import Path
from datetime import date

from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import research_context, publish_reports
from test_backtest import execution_flows
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


def test_explicit_report_publication_keeps_hash_links_and_is_reusable(current_frozen):
    repository, version = current_frozen
    context = research_context(repository, execution_flows(repository.root))
    result = run_backtest(context, version, BacktestRequest(
        '588080.SH', 'etf', date(2026,9,15), date(2026,9,21), 100000, 100))
    assert not list((repository.root / "research/S900").glob("assets/evidence/*/*"))
    references = publish_reports(context, result)
    report = references["report.md"].resolve(repository.root)
    links = re.findall(r"\]\(([^)]+)\)", report.read_text(encoding="utf-8"))
    assert links == [references["chart.html"].evidence_id, references["ma_chart.html"].evidence_id]
    assert all((report.parent / link).is_file() for link in links)
    hashes = {name: ref.sha256 for name, ref in references.items()}
    again = publish_reports(context, result)
    assert {name: ref.sha256 for name, ref in again.items()} == hashes
    assert references["report.md"].resolve(repository.root).read_bytes() == report.read_bytes()
    assert Path(report).is_relative_to(repository.root / "research/S900/assets/evidence")
