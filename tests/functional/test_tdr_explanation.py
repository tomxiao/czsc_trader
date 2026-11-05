"""Recorded strategy explanations survive public backtest and chart projection."""
import ast
import json
import shutil
from datetime import date
from dataclasses import replace

import pytest
from strategy_runtime import implementation_sha256, ObservationUnavailable
from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import research_context, chart_payload, render_output
from test_backtest import execution_flows
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


def frozen_observation_revision(current_frozen, author):
    """Use the actual observation-only upgrade transaction on a private frozen copy."""
    from strategy_manager import StrategyRegistry, freeze_contracts as f
    from strategy_runtime import StrategyCandidate
    from czsc_trader.application import validate_release_package, runtime_migration as m
    from test_frozen_runtime_upgrade import _audit_ref
    repository, stored = current_frozen
    manifest, _, source = validate_release_package(repository, stored.release_id)
    original = f.FrozenVersionReference(stored.strategy_id, stored.version, stored.release_hash, manifest['package_hash'])
    target = repository.root / '.tmp/observation-revision-source/strategy_runtime'
    shutil.copytree(source, target)
    payload = json.loads(json.dumps(dict(stored.strategy_payload), default=dict))
    author((payload, target))
    candidate = StrategyCandidate(stored.strategy_id, 'C9877', payload, target)
    authorization = _audit_ref(repository, {'authorization':'Synthetic observation-only frozen revision'})
    request = m.FrozenRuntimeUpgradeRequest(original, candidate, authorization,
        'Synthetic chart observation contract', 'synthetic-researcher', (), repository.root / '.tmp/observation-revision')
    prepared = m.prepare_frozen_runtime_upgrade(repository, request)
    assert m.apply_frozen_runtime_upgrade(repository, prepared).status.value == 'COMMITTED'
    return repository, StrategyRegistry(repository.strategy_root).get_version(stored.strategy_id, stored.version)


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
def test_recorded_explanation_and_failure_survive_backtest(current_frozen, monkeypatch, failure):
    repository, version = frozen_observation_revision(current_frozen, _author_explanation)
    context = research_context(repository, execution_flows(repository.root))
    if failure:
        import czsc_trader.backtesting.observation as recorder
        original = recorder.observe_execution_plan
        def unavailable(definition, plan):
            original(definition, plan)  # preserve real identity validation
            return ObservationUnavailable('Injected observation-only failure', 'strategy_observation.v4')
        monkeypatch.setattr(recorder, 'observe_execution_plan', unavailable)
    result = run_backtest(context, version, BacktestRequest(
        '588080.SH', 'etf', date(2026,9,15), date(2026,9,21), 100000, 100))
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
