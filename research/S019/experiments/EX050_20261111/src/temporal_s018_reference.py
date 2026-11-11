"""Fixed S018-v1 reference required by S019 mandate; existing evidence only."""
from hashlib import sha256
from pathlib import Path

import statistics_analysis as stats

import numpy as np
from strategy_evaluator import performance_metrics

WORK, ROOT = stats.WORK, stats.ROOT
REFERENCE = stats.EXPERIMENTS / 'EX003_20261110'


def runs(rows, metric):
    segments, current = [], []
    for row in rows:
        if row[metric] < 0:
            current.append(row)
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    output = [{'count': len(group), 'first_window': group[0]['window_id'],
               'last_window': group[-1]['window_id'], 'first_start': group[0]['start'],
               'last_start': group[-1]['start'], 'last_end': group[-1]['end']} for group in segments]
    return {'maximum_count': max((x['count'] for x in output), default=0), 'segments': output}


def main():
    protocol = stats.read(WORK / 'statistics_protocol.json')
    values = stats.read(WORK / 'statistics_center_returns.json')
    assert values['protocol_sha256'] == stats.digest(WORK / 'statistics_protocol.json')
    identity = stats.read(REFERENCE / 'others/reference_identity.json')
    assert identity['purpose'] == 'FIXED_S018_V1_COMPARISON_ONLY'
    assert identity['origin']['runtime_candidate_id'] == 'C9397'
    assert identity['origin']['strategy_version_hash'] == '80a7ca699f5814ad3e9162de1828d9848b5a0e7077857eb92002aec10c3f631e'
    assert identity['origin']['package_hash'] == 'c7035dc5a8bd3eee2a2dfe434e04f868e43613085036f7f3a434ce8b875a9d80'
    original, adapted = identity['original_definition'], identity['evaluation_definition']
    assert {k: v for k, v in original.items() if k != 'auxiliary_inputs'} == {
        k: v for k, v in adapted.items() if k != 'auxiliary_inputs'}
    assert len(original['auxiliary_inputs']) == len(adapted['auxiliary_inputs'])
    for a, b in zip(original['auxiliary_inputs'], adapted['auxiliary_inputs'], strict=True):
        assert {k: v for k, v in a.items() if k != 'source'} == {k: v for k, v in b.items() if k != 'source'}
        assert a['source']['provider'] == b['source']['provider'] == 'futu'
        assert b['source']['revision'] == 's019-unified-window-20261110-v2'
    reference = stats.read(REFERENCE / 'others/reference_account.json')
    projector = stats.load_projector(protocol)
    fact, header, ref = projector.fact(reference)
    assert header['request']['candidate_definition'] == adapted
    assert header['request']['candidate_id'] == 'C0001' and header['request']['fee_rate'] == .001
    sessions = [p.session for p in fact.account]
    equity = np.asarray([fact.initial_cash, *[p.equity for p in fact.account]])
    returns = equity[1:] / equity[:-1] - 1
    full = performance_metrics(returns)
    summary = stats.read(REFERENCE / 'others/reference_summary.json')['runs']['candidate']
    np.testing.assert_allclose([full.cagr, -full.max_drawdown, full.calmar],
                               [summary['nar'], summary['drawdown'], summary['calmar']], atol=1e-12, rtol=1e-12)
    candidates = []
    for cid, data in values['members'].items():
        assert data['sessions'] == sessions
        curve = np.r_[1., np.cumprod(1 + np.asarray(data['returns']))]

        def window(name, start, stop):
            left, right = performance_metrics(np.asarray(data['returns'][start:stop])), performance_metrics(returns[start:stop])
            return {'window_id': name, 'start': sessions[start], 'end': sessions[stop - 1], 'sessions': stop - start,
                    'strategy': {'period_return': float(curve[stop] / curve[start] - 1), 'nar': left.cagr,
                                 'mdd': -left.max_drawdown, 'calmar': left.calmar},
                    'reference': {'period_return': float(equity[stop] / equity[start] - 1), 'nar': right.cagr,
                                  'mdd': -right.max_drawdown, 'calmar': right.calmar},
                    'nar_excess': left.cagr - right.cagr, 'calmar_excess': left.calmar - right.calmar}

        years = []
        for year in sorted({s[:4] for s in sessions}):
            indices = [i for i, s in enumerate(sessions) if s.startswith(year)]
            years.append(window(year, indices[0], indices[-1] + 1))
        rolling = [window(f'R{i:02}', start, start + 252)
                   for i, start in enumerate(range(0, len(sessions) - 252 + 1, 21))]
        assert len(rolling) == 46
        candidates.append({'candidate_id': cid, 'source': data['reference'], 'full': window('FULL', 0, len(sessions)),
                           'years': years, 'rolling': rolling,
                           'below_reference_rolling_count': {key: sum(row[key] < 0 for row in rolling)
                                                             for key in ('nar_excess', 'calmar_excess')},
                           'consecutive_lagging_rolling_windows': {key: runs(rolling, key) for key in ('nar_excess', 'calmar_excess')},
                           'consecutive_lagging_calendar_years': {key: runs(years, key) for key in ('nar_excess', 'calmar_excess')}})
    stats.save('temporal_s018_reference.json', {
        'status': 'COMPLETE', 'new_accounts': 0, 'selected_ids': list(stats.CENTERS),
        'method': 'PUBLIC_ASSESSMENT_SESSION_RETURNS_FIXED_S018_V1',
        'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'protocol_sha256': stats.digest(WORK / 'statistics_protocol.json'),
        'reference': ref.to_dict(), 'reference_identity': identity,
        'source_bindings': {p.relative_to(ROOT).as_posix(): stats.digest(p) for p in [
            REFERENCE / 'others/reference_identity.json', REFERENCE / 'others/reference_summary.json',
            REFERENCE / 'others/reference_account.json', ROOT / 'research/S019/materials/stage1_agreement.md']},
        'reference_context_sha256': fact.context_sha256, 'reference_scenario': fact.scenario_context.to_dict(),
        'candidates': candidates, 'limitations': [
            'Fixed reference daily execution and current S019 30m execution retain their respective original rules.',
            'Same 1212 sessions, initial equity, fee and HFQ research convention; comparison is an auxiliary temporal diagnostic.',
            'No S018 candidate is added to the S019 NAR ranking or original twelve targets.',
            'Calendar/rolling slices inherit the continuous account; 2026 ends 2026-10-30; overlapping windows are dependent.',
            'Separate NAR and Calmar lag runs use strict negative differences; zero terminates a run.']})
    print('S018_REFERENCE_COMPLETE', [(x['candidate_id'], x['below_reference_rolling_count']) for x in candidates])


if __name__ == '__main__':
    main()
