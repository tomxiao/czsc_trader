"""Prepare S019 EX050 diagnostics; all actions read existing account evidence only.

Adaptation of EX041 statistics_analysis.py (bootstrap/selection policy) and
assess.py (public evidence projection, calendar/rolling and concentration).
Preparation reads small immutable headers. Center diagnostics are explicit;
bootstrap and full-family selection projection require separate CLI actions.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import importlib.util
from itertools import combinations
import json
import os
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'research/RSCH_AGENT.md').is_file())
SOURCE_DIRECTORY = Path(__file__).resolve().parent
WORK = SOURCE_DIRECTORY.parent / 'others' if SOURCE_DIRECTORY.name == 'src' else SOURCE_DIRECTORY
EXPERIMENTS = ROOT / 'research/S019/experiments'
PRIOR = EXPERIMENTS / 'EX041_20261110'
LATEST = EXPERIMENTS / 'EX049_20261111'
CENTERS = ('C0966', 'C1010', 'C0909')
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', TEMP=str(WORK), TMP=str(WORK))
sys.dont_write_bytecode = True

import numpy as np  # noqa: E402
import strategy_evaluator as se  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from strategy_runtime import canonical_sha256  # noqa: E402
from strategy_evaluator import equity_assessment as equity_facts  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                      allow_nan=False) + '\n', encoding='utf8')


def source(reference):
    ref = d.EvidenceRef.from_dict(reference)
    path = ref.resolve(ROOT)
    assert digest(path) == ref.sha256
    return path, read(path)


def iter_refs(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef' and value.get('schema') == 'equity_research':
            yield value
        else:
            for member in value.values():
                yield from iter_refs(member)
    elif isinstance(value, list):
        for member in value:
            yield from iter_refs(member)


def inventory():
    previous = read(PRIOR / 'others/statistics_inventory.json')
    rows = [{k: v for k, v in row.items() if k != 'aliases'}
            for item in previous['rows'] for row in [item, *item['aliases']]]
    seen = {r['reference']['sha256'] for r in rows}
    files, all_refs, origins = [], {}, defaultdict(set)
    for number in range(41, 50):
        directory, = EXPERIMENTS.glob(f'EX{number:03d}_*')
        for name in ('account_results.json', 'results.json', 'summary.json', 'stage_exact_aliases.json'):
            path = directory / 'others' / name
            if not path.is_file():
                continue
            files.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)})
            for ref in iter_refs(read(path)):
                all_refs[ref['sha256']] = ref
                origins[ref['sha256']].add(directory.name)
    excluded = []
    for fingerprint, ref in sorted(all_refs.items()):
        if fingerprint in seen:
            continue
        path, header = source(ref)
        req = header['request']
        if req['fee_rate'] != .001:
            excluded.append({'reference': ref, 'reason': 'FEE_SCENARIO', 'fee_rate': req['fee_rate']})
            continue
        assert req['measurement_tier'] == 'FORMAL'
        assert req['window']['start'].startswith('2022-01-03')
        assert req['window']['end'].startswith('2026-10-30')
        definition = req['candidate_definition']
        context = {key: req[key] for key in ('instrument', 'specification', 'window', 'history_start',
                   'initial_cash', 'benchmark_sha256', 'fee_rate', 'drawdown_basis', 'engine_sources',
                   'python_version', 'pandas_version')}
        context['data'] = header['data']
        rows.append({'candidate_id': req['candidate_id'], 'reference': ref,
                     'experiment': ref['experiment']['experiment_id'],
                     'content_sha256': req['content_sha256'],
                     'implementation_sha256': canonical_sha256(definition),
                     'source_sha256': definition['source_sha256'],
                     'parameters': json.loads(definition['parameters_json']),
                     'context_proxy': canonical_sha256(context),
                     'context_components': {k: canonical_sha256(v) for k, v in context.items()},
                     'candidate_artifact': header['candidate_ref'],
                     'candidate_bytes': path.with_name(header['candidate_ref']['sha256'] + '.json').stat().st_size,
                     'origin': sorted(origins[fingerprint])})
        seen.add(fingerprint)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['implementation_sha256']].append(row)
    inventory = {'status': 'PREPARED_HEADERS_ONLY', 'published_account_count': len(rows),
                 'unique_implementations': len(grouped),
                 'rows': [{**items[0], 'aliases': items[1:]} for items in grouped.values()],
                 'metadata_sources': files, 'excluded_scenarios': excluded,
                 'history': ['EX005-040 inventory reused with exact aliases.',
                             'EX041 reviewed neighborhoods included: later mechanism research used their failures.',
                             'EX042 has zero completed economic accounts; technical failure retained separately.',
                             'EX043-049 full standard histories included, not only 112 qualified or 3 selected.',
                             'Repeated imported references are one observed account; source/parameter repeats keep aliases.',
                             'EX050 new neighborhoods excluded from pre-selection universe.'],
                 'count_interpretation': 'Published account and exact implementation counts; independent effective choices are not asserted.'}
    save('statistics_inventory.json', inventory)
    return inventory


def prepare():
    if (WORK / 'statistics_protocol.json').exists():
        old = read(WORK / 'statistics_protocol.json')
        assert digest(WORK / 'statistics_inventory.json') == old['inventory_sha256']
        prepared_inventory = read(WORK / 'statistics_inventory.json')
        for item in prepared_inventory['metadata_sources']:
            assert digest(ROOT / item['path']) == item['sha256']
    else:
        prepared_inventory = inventory()
    fee_review = read(LATEST / 'others/fee_gate_review.json')
    centers = []
    for cid in CENTERS:
        pair, = [x for x in fee_review['pairs'] if x['candidate_id'] == cid]
        refs = {name: read(LATEST / f'others/{cid}{suffix}_account.json')
                for name, suffix in (('standard', ''), ('pressure', '_stress'))}
        headers = {name: source(ref)[1] for name, ref in refs.items()}
        a, b = (headers[name]['request'] for name in ('standard', 'pressure'))
        assert a['candidate_definition'] == b['candidate_definition']
        assert a['content_sha256'] == b['content_sha256'] == pair['content_hash']
        assert a['fee_rate'] == .001 and b['fee_rate'] == .002
        centers.append({'id': cid, 'references': refs, 'content_sha256': a['content_sha256'],
                        'definition': a['candidate_definition'],
                        'standard': pair['standard'], 'pressure': pair['pressure']})
    save('statistics_centers.json', centers)
    dependencies = [PRIOR / 'src/statistics_analysis.py', PRIOR / 'src/statistics_verification.py',
                    PRIOR / 'src/assess.py', PRIOR / 'protocols/plan.md',
                    PRIOR / 'protocols/statistics_protocol.json', PRIOR / 'others/statistics_inventory.json',
                    PRIOR / 'others/statistics_returns.json', PRIOR / 'others/statistics_incremental_projection.json',
                    LATEST / 'others/fee_gate_review.json', LATEST / 'others/stage_summary.json',
                    ROOT / 'research/S019/assets/deliveries/MANDATE/2/delivery.json']
    protocol = {'status': 'PREPARED_BEFORE_STATISTICAL_COMPUTATION', 'version': 'S019-EX050-statistics-v1',
                'centers': list(CENTERS), 'scope': '3 user-selected of 112; remaining 109 NOT_ASSESSED',
                'selection_order': 'All applicable original twelve targets, then unrounded standard NAR descending; exact ties share rank.',
                'selection_history_rule': 'Six original center gates, then unrounded NAR descending; source-specific BH and comparable contexts.',
                'new_hard_gates': [], 'sample': ['2022-01-03', '2026-10-30'],
                'bootstrap': {'repetitions': 10000, 'mean_block_length': 21, 'seed': 20261110,
                              'pairs': [[x, 'MU_BUY_HOLD'] for x in CENTERS] + [list(x) for x in combinations(CENTERS, 2)],
                              'metrics': ['NAR', 'negative_MDD', 'Calmar'], 'interval': 'percentile_95'},
                'temporal': {'rolling_days': 252, 'step_days': 21, 'expected_windows': 46,
                             'years': [2022, 2023, 2024, 2025, 2026], '2026_end': '2026-10-30'},
                'concentration': 'MAX_SINGLE: max positive closed PnL / sum positive closed PnL',
                'family_selection': {'annual_pairs': ['2022->2023', '2023->2024', '2024->2025', '2025->2026_partial'],
                                     'status': 'PENDING_INCREMENTAL_PUBLIC_PROJECTION_PREPARATION',
                                     'reuse': 'EX039 published projection + EX041 incremental projection; only later unique sources projected.'},
                'actual_adaptive_nar_gated_selection_bias': 'NOT_ESTIMATED',
                'sharpe_proxy': 'Optional auxiliary, no eligibility/ranking weight; never substitute for NAR-gated selection.',
                'limitations': ['Repeatedly seen development sample; selfcheck feedback entered subsequent optimization.',
                                'Overlapping time windows are dependent; incomplete 2026 annualization is labeled.',
                                'Bootstrap conditions on observed returns and rearranges chronology.',
                                'Selection-history counts include source identity changes; economic aliases remain explicit.'],
                'resources': {'processes': 1, 'native_threads': 1, 'new_accounts': 0},
                'inventory_sha256': digest(WORK / 'statistics_inventory.json'),
                'centers_sha256': digest(WORK / 'statistics_centers.json'),
                'source_sha256': digest(Path(__file__)),
                'dependencies': {p.relative_to(ROOT).as_posix(): digest(p) for p in dependencies}}
    save('statistics_protocol.json', protocol)
    print('PREPARED', prepared_inventory['published_account_count'],
          prepared_inventory['unique_implementations'], len(prepared_inventory['excluded_scenarios']), flush=True)


def load_projector(protocol):
    path = PRIOR / 'src/assess.py'
    assert digest(path) == protocol['dependencies'][path.relative_to(ROOT).as_posix()]
    spec = importlib.util.spec_from_file_location('s019_ex041_assessment_reuse', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCRATCH = ROOT / '.tmp/s019-ex050/assessment'
    module.SCRATCH.mkdir(exist_ok=True, parents=True)
    os.environ.update(TMP=str(WORK), TEMP=str(WORK))
    return module


def centers():
    protocol = read(WORK / 'statistics_protocol.json')
    assert digest(Path(__file__)) == protocol['source_sha256']
    assert digest(WORK / 'statistics_centers.json') == protocol['centers_sha256']
    projector = load_projector(protocol)
    values, diagnostics = {}, []
    for center in read(WORK / 'statistics_centers.json'):
        cid = center['id']
        scenarios = {}
        for label, ref in center['references'].items():
            fact, header, typed = projector.fact(ref)
            assert header['request']['content_sha256'] == center['content_sha256']
            account = np.asarray([fact.initial_cash, *[p.equity for p in fact.account]])
            bh = np.asarray([fact.initial_cash, *fact.benchmark_equity])
            returns, benchmark_returns = account[1:] / account[:-1] - 1, bh[1:] / bh[:-1] - 1
            full = se.performance_metrics(returns)
            expected = center[label]
            np.testing.assert_allclose([full.cagr, -full.max_drawdown, full.calmar],
                                       [expected['nar'], expected['drawdown'], expected['calmar']], atol=1e-12, rtol=1e-12)
            scenarios[label] = {'reference': typed.to_dict(), 'context_sha256': fact.context_sha256,
                                'scenario_context': fact.scenario_context.to_dict(),
                                'nar': full.cagr, 'mdd': -full.max_drawdown, 'calmar': full.calmar}
            if label == 'pressure':
                continue
            sessions = [p.session for p in fact.account]
            values[cid] = {'reference': ref, 'content_sha256': center['content_sha256'],
                           'sessions': sessions, 'returns': returns.tolist(),
                           'benchmark_returns': benchmark_returns.tolist(),
                           'context_sha256': fact.context_sha256, 'scenario_context': fact.scenario_context.to_dict()}

            def window(name, start, stop):
                a, b = (se.performance_metrics(r[start:stop]) for r in (returns, benchmark_returns))
                return {'window_id': name, 'start': sessions[start], 'end': sessions[stop - 1],
                        'sessions': stop - start,
                        'strategy': {'period_return': float(account[stop] / account[start] - 1),
                                     'nar': a.cagr, 'mdd': -a.max_drawdown, 'calmar': a.calmar},
                        'benchmark': {'period_return': float(bh[stop] / bh[start] - 1),
                                      'nar': b.cagr, 'mdd': -b.max_drawdown, 'calmar': b.calmar},
                        'nar_excess': a.cagr - b.cagr, 'calmar_excess': a.calmar - b.calmar}

            years = []
            for year in sorted({s[:4] for s in sessions}):
                indices = [i for i, s in enumerate(sessions) if s.startswith(year)]
                years.append(window(year, indices[0], indices[-1] + 1))
            rolling = [window(f'R{i:02}', start, start + 252)
                       for i, start in enumerate(range(0, len(sessions) - 252 + 1, 21))]
            assert len(rolling) == 46
            trades = json.loads(fact.equity.candidate_ledger)['trades']
            winners = sorted((t for t in trades if t['net_pnl'] > 0), key=lambda x: x['net_pnl'], reverse=True)
            positive_sum = sum(t['net_pnl'] for t in winners)
            concentration = equity_facts.equity_concentration(fact)
            assert fact.equity.concentration_basis == 'MAX_SINGLE'
            assert concentration == winners[0]['net_pnl'] / positive_sum
            temporal = {'years': years, 'rolling': rolling, 'concentration': concentration,
                        'concentration_basis': 'MAX_SINGLE', 'positive_closed_pnl': positive_sum,
                        'positive_closed_cycles': len(winners), 'closed_cycles': len(trades),
                        'top_five_winners': [{**t, 'positive_pnl_share': t['net_pnl'] / positive_sum} for t in winners[:5]]}
        diagnostics.append({'candidate_id': cid, 'scenarios': scenarios, **temporal})
        print('CENTER_READ', cid, flush=True)
    assert len({tuple(v['sessions']) for v in values.values()}) == 1
    assert len({tuple(v['benchmark_returns']) for v in values.values()}) == 1
    save('statistics_center_returns.json', {'members': values, 'protocol_sha256': digest(WORK / 'statistics_protocol.json')})
    save('statistics_temporal.json', {'status': 'COMPLETE', 'new_accounts': 0,
                                    'protocol_sha256': digest(WORK / 'statistics_protocol.json'),
                                    'candidates': diagnostics, 'limitations': protocol['limitations']})


def bootstrap():
    protocol = read(WORK / 'statistics_protocol.json')
    data = read(WORK / 'statistics_center_returns.json')
    assert data['protocol_sha256'] == digest(WORK / 'statistics_protocol.json')
    values, settings = data['members'], protocol['bootstrap']
    results = []
    for left, right in settings['pairs']:
        a = values[left]
        b = a['benchmark_returns'] if right == 'MU_BUY_HOLD' else values[right]['returns']
        result = se.paired_stationary_bootstrap(np.asarray(a['returns']), np.asarray(b),
                    champion_id=left, comparator_id=right, repetitions=settings['repetitions'],
                    mean_block_length=settings['mean_block_length'], seed=settings['seed'])
        results.append(result.to_dict())
    save('statistics_bootstrap.json', {'comparisons': results, 'protocol': settings,
                                      'protocol_sha256': digest(WORK / 'statistics_protocol.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'centers', 'bootstrap'))
    arguments = parser.parse_args()
    {'prepare': prepare, 'centers': centers, 'bootstrap': bootstrap}[arguments.action]()
