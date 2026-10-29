"""Synthetic checks of numbered-entry integration and background-state matching."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
import multiprocessing as mp
import sys
from study import WORK, NAMES, NEW_NAMES, previous, context, adjusted_rows, horizon_task, save, digest
from check_entries import run as check_entries


def main():
    checks = check_entries()
    search_path = sys.path.copy()
    context()
    assert sys.path == search_path
    days = [str(date(2020, 1, 1)+timedelta(days=i)) for i in range(90)]
    rows = [{'i': i, 'n': 65, 'date': d, 'month': d[:7], 'stratum': d[:7]+'|10:00',
             'price_net_return': None if i == 0 else (i-30)/1000,
             'status': 'NO_FILL' if i == 0 else 'COMPLETE'} for i, d in enumerate(days)]
    signals = {name: {0, 1, 15, 30, 50, 70, 89} for name in NAMES}
    signals[NAMES[0]] = set(range(45))
    signals[NAMES[1]] = {1, 15, 30}
    weights = previous.block_weights(len(days), replicates=10)[0]
    args = (65, rows, signals, days, weights)
    result = horizon_task(args)
    item = result[1]['signals'][NEW_NAMES[0]]['nonoverlap']
    assert item['indices'] == [0, 70]  # Failed fill remains in causal preselection.
    assert item['summary']['price']['count'] == 1
    adjusted = adjusted_rows(rows, signals[NAMES[0]])
    assert adjusted[0]['stratum'].endswith('|M001=1') and adjusted[70]['stratum'].endswith('|M001=0')
    raw = result[1]['signals'][NEW_NAMES[0]]['raw']
    assert sum(x['summary']['events'] for x in raw['background_slices'].values()) == raw['summary']['events']
    good = [r for r in adjusted if r['i'] in signals[NEW_NAMES[0]] and r['price_net_return'] is not None]
    expected = []
    for row in good:
        group = [r['price_net_return'] for r in adjusted if r['stratum'] == row['stratum'] and r['price_net_return'] is not None]
        expected.append(row['price_net_return']-sum(group)/len(group))
    actual = raw['background_adjusted']['matched']['difference']['mean']
    assert abs(actual-sum(expected)/len(expected)) < 1e-13
    assert 'background_adjusted' not in result[1]['signals'][NAMES[0]]['raw']
    assert 'background_slices' not in result[1]['signals'][NAMES[1]]['raw']
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(horizon_task, [args, args])) == [result, result]
    checks.extend(['import_path_restoration', 'nonfill_no_replacement', 'state_adjusted_control_scalar',
        'background_slice_partition', 'reference_roles_preserved', 'two_spawn_full_task_equivalence'])
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    assert 'verify.py' in sources
    save(WORK/'others/checks.json', {'status': 'PASS', 'sources': sources, 'checks': checks,
                                   'workers': 2, 'native_threads': 1})
    print('FOCUSED_CHECKS_PASS', len(checks), flush=True)


if __name__ == '__main__':
    main()
