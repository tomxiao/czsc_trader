"""Recorded strategy explanations survive public backtest and chart projection."""
import ast
import json
from dataclasses import replace

import pandas as pd
import pytest
from strategy_runtime import implementation_sha256, ObservationUnavailable
from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import request_for_prices, chart_payload, render_output


def _author_explanation(candidate_payload):
    payload, source = candidate_payload
    path = source / payload['runtime']['source_files'][0]
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    kw = next(n for n in ast.walk(init) if isinstance(n, ast.keyword) and n.arg == 'observation')
    original = ast.unparse(kw.value)
    kw.value = ast.parse('self.observation_definition()', mode='eval').body
    code = """
def observation_definition(self):
    from dataclasses import replace
    from strategy_runtime import (SignalPanelDefinition, SignalGroup, SignalSeriesDefinition,
        SignalStateDefinition, SignalStateOption, SignalExplanationDefinition, SignalExplanationCase,
        SignalText, SignalBasisDefinition, SeriesValueRef)
    text = lambda value: SignalText((value,))
    return replace(ORIGINAL, signal_panel=SignalPanelDefinition(
        (SignalGroup('score', 'Fixture score', 'points', 'Synthetic'),),
        (SignalSeriesDefinition('score', 'Score', 'score', 'obs_score'),),
        (SignalStateDefinition('decision', 'Decision', 'obs_decision',
            (SignalStateOption('recorded', 'Recorded'),)),),
        SignalExplanationDefinition('decision', (
            SignalExplanationCase('recorded', text('Synthetic recorded judgment'),
                (SignalBasisDefinition('score', SignalText(('Recorded score ', SeriesValueRef('score')))),),
                text('Observe the next actual condition'), text('Synthetic explanation, not investment evidence')),
        ))))

def observation_history(self, inputs, context, history):
    return pd.DataFrame({'obs_score': history['fixture_signal'], 'obs_decision': 'recorded'}, index=history.index)
""".replace('ORIGINAL', original)
    cls.body.extend(ast.parse(code).body)
    path.write_text(ast.unparse(ast.fix_missing_locations(tree)) + '\n', encoding='utf-8')
    payload['runtime']['source_sha256'] = implementation_sha256(tuple(payload['runtime']['source_files']), source_root=source)


@pytest.mark.parametrize('failure', [False, True])
def test_recorded_explanation_and_failure_survive_backtest(candidate_payload, tmp_path, monkeypatch, failure):
    _author_explanation(candidate_payload)
    days = pd.bdate_range('2026-08-17', periods=23)
    prices = pd.DataFrame({'dt': days, 'open': 1., 'close': 1.})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20)
    if failure:
        import czsc_trader.backtesting.observation as recorder
        original = recorder.observe_execution_plan
        def unavailable(definition, plan):
            original(definition, plan)  # preserve real identity validation
            return ObservationUnavailable('Injected observation-only failure', 'strategy_observation.v4')
        monkeypatch.setattr(recorder, 'observe_execution_plan', unavailable)
    result = run_backtest(context, request.strategy, BacktestRequest(
        '588080.SH', 'etf', days[20].date(), days[-1].date(), 100000, 100))
    assert result.manifest['audit']['status'] == 'PASS'
    output = render_output(result, context.repository.root)
    html = (output / 'chart.html').read_text(encoding='utf-8')
    chart = chart_payload(html)
    recorded = json.loads((output / 'observations.json').read_text(encoding='utf-8'))
    projected = [row['observation'] for row in chart['observations']]
    if failure:
        assert [row['recorded_plan'] for row in projected] == recorded
    else:
        assert projected == recorded
    assert html.index('aria-label="回测绩效指标"') < html.index('aria-label="策略运行复盘"')
    assert '<script src=' not in html
    if failure:
        assert all(row['status'] == 'UNAVAILABLE' and 'series' not in row and 'signal_panel' not in row for row in projected)
        assert all(ObservationUnavailable.from_dict(row['observation']).contract_version == 'strategy_observation.v4' for row in recorded)
    else:
        assert all(row['contract_version'] == 'strategy_observation.v4' for row in recorded)
        assert recorded[0]['signal_panel']['explanation']['judgment'] == 'Synthetic recorded judgment'
    # Corrupted recorded identity must fail even for an unavailable observation.
    first = result.result.observations[0]
    bad = replace(first, strategy=replace(first.strategy, release_hash='f' * 64))
    altered = replace(result, result=replace(result.result, observations=(bad, *result.result.observations[1:])))
    with pytest.raises(ValueError, match='chart observation'):
        render_output(altered, context.repository.root)
