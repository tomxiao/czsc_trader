"""Focused causal-membership and conditional-control integration checks."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
import multiprocessing as mp
import sys
from check_entries import run as entry_checks
from study import WORK, NAMES, stats, context, horizon_task, contrast_task, save, digest


def main():
    checks = entry_checks()
    path = sys.path.copy()
    context()
    assert sys.path == path
    days = [str(date(2020, 1, 1)+timedelta(days=i)) for i in range(90)]
    rows = [{'i': i, 'n': 65, 'date': d, 'month': d[:7], 'stratum': d[:7]+'|10:00',
        'price_net_return': None if i == 0 else (i-30)/1000,
        'status': 'NO_ENTRY' if i == 0 else 'COMPLETE'} for i,d in enumerate(days)]
    signals = {name: set() for name in NAMES}
    signals.update({'S017-M001': set(range(45)), 'S017-M002': {15},
        'S017-M005': {0,15,70}, 'S017-M006': set(range(90)),
        'S017-M007': {0,1,15,16,70,71,89}, 'S017-M008': {0,15,30,50,70}})
    weights = stats.block_weights(len(days), replicates=10)[0]
    args = (65, rows, signals, days, weights)
    result = horizon_task(args)
    item = result[1]['signals']['S017-M005']['nonoverlap']
    assert item['indices'] == [0,70] and item['summary']['price']['count'] == 1
    assert sum(x['summary']['events'] for x in item['background_slices'].values()) == 2
    cargs = ('S017-M005','S017-M007',rows,signals,days,weights)
    contrast = contrast_task(cargs)
    x = contrast[1]['modes']['nonoverlap']['background_adjusted']
    assert x['indices'] == [0,70]
    assert x['matched']['supported_indices'] == [70]
    assert x['matched']['support']['minimum_control_count'] == 3
    assert x['matched']['support']['self_in_control_events'] == 1
    assert abs(x['matched']['control']['mean']-sum((i-30)/1000 for i in (70,71,89))/3) < 1e-12
    assert x['years']['2019']['summary']['events'] == 0
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(horizon_task,[args,args])) == [result,result]
        assert list(pool.map(contrast_task,[cargs,cargs])) == [contrast,contrast]
    checks.extend(['import_path_restored','causal_nonfill_not_replaced','background_partition',
        'parent_controls_remain_raw','state_matched_control_arithmetic','empty_year_preserved',
        'two_spawn_horizon_and_contrast_equivalence'])
    sources={p.name:digest(p) for p in (WORK/'src').glob('*.py') if p.stem!='render'}
    assert 'verify.py' in sources
    save(WORK/'others/checks.json',{'status':'PASS','sources':sources,'checks':checks,'workers':2,'native_threads':1})
    print('FOCUSED_CHECKS_PASS',len(checks),flush=True)


if __name__ == '__main__':
    main()
