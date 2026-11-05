"""Frozen replay metrics reach the report unchanged; SE owns the numeric matrix."""
from datetime import date
import json

from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import research_context, render_output, assert_public_charts
from test_backtest import execution_flows
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


def test_frozen_backtest_publishes_audited_trade_metrics_without_changing_identity(current_frozen):
    repository, version = current_frozen
    context = research_context(repository, execution_flows(repository.root))
    result = run_backtest(context, version, BacktestRequest(
        '588080.SH', 'etf', date(2026,9,15), date(2026,9,21), 100000, 100))
    assert result.manifest['audit']['status'] == 'PASS'
    output = render_output(result, repository.root)
    published = json.loads((output/'metrics.json').read_text(encoding='utf-8'))
    assert published == result.metrics
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['strategy']['kind'] == 'REGISTERED'
    assert manifest['strategy']['reference'] == result.snapshot.identity.reference == version.release_id
    assert manifest['strategy']['source_hash'] == result.snapshot.source_hash
    assert manifest['audit'] == result.manifest['audit']
    assert_public_charts(output)
