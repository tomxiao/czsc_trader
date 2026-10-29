"""Focused tests for same-capital differences, controls and influence diagnostics."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
import multiprocessing as mp
import sys
from study import (WORK, HORIZONS, METRICS, previous, context, concentration, analyze_task,
                   metric_rows, save, digest)


def main():
    search_path = sys.path.copy()
    context()
    assert sys.path == search_path
    days = [str(date(2020, 1, 1)+timedelta(days=i)) for i in range(75)]
    rows = [{'i': i, 'n': 13, 'date': d, 'month': d[:7], 'stratum': d[:7]+'|10:00',
             'price_net_return': (i-30)/1000, 'status': 'COMPLETE'} for i, d in enumerate(days)]
    lookup = {n: {r['i']: dict(r, n=n, price_net_return=r['price_net_return']+n/10000) for r in rows} for n in HORIZONS}
    complete = set(range(75))
    metrics = metric_rows(lookup, complete)
    assert tuple(metrics) == METRICS
    assert all(abs(r['price_net_return']-.0039) < 1e-14 for r in metrics['26-65'])
    weights = {b: previous.block_weights(len(days), replicates=10, block=b)[0] for b in (20, 60)}
    members = [0, 15, 30, 50, 74]
    control_ids = {'ordinary': complete, 'B': complete, 'C': set(range(31))}
    args = ('nonoverlap130', members, metrics, control_ids, days, weights)
    result = analyze_task(args)
    item = result[1]['metrics']['65']['comparisons']['C']
    assert item['matched']['unmatched_indices'] == [50, 74]
    assert item['matched']['support']['self_in_control_events'] == 3
    stress = result[1]['stress']['65']
    removed = stress['drop_positive_events']['1']['removed']
    assert removed[0]['i'] == 74
    original_groups = {}
    for r in metrics['65']:
        original_groups.setdefault(r['stratum'], []).append(r['price_net_return'])
    kept = [r for r in metrics['65'] if r['i'] in members and r['i'] != 74]
    expected_control = sum(sum(original_groups[r['stratum']])/len(original_groups[r['stratum']]) for r in kept)/len(kept)
    actual = stress['drop_positive_events']['1']['comparisons']['ordinary']['matched']['control']['mean']
    assert abs(actual-expected_control) < 1e-13
    assert stress['leave_year_out']['2020']['ordinary']['summary']['price']['count'] == 0
    x = concentration([dict(rows[0], price_net_return=1.), dict(rows[1], price_net_return=1.), dict(rows[2], price_net_return=-.5)])
    assert x['largest_positive']['i'] == 0 and x['positive_sum'] == 2 and x['net_sum'] == 1.5
    assert concentration([])['largest_positive'] is None
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(analyze_task, [args, args])) == [result, result]
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    assert 'verify.py' in sources
    save(WORK/'others/checks.json', {'status': 'PASS', 'sources': sources,
        'checks': ['import_path_restoration', 'same_capital_differences', 'missing_C_support',
            'original_controls_retained_on_target_removal', 'empty_year_diagnostic',
            'positive_concentration_and_tie_order', 'two_spawn_full_task_equivalence'],
        'workers': 2, 'native_threads': 1})
    print('FOCUSED_CHECKS_PASS', flush=True)


if __name__ == '__main__':
    main()
