"""Focused synthetic checks, before reading new research outcomes."""
# ruff: noqa: E402
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import numpy as np
from mechanisms import flags, sparse, episodes, match, bootstrap, block_weights
from study import WORK, save, digest


def f(i, d=True, r=True):
    return {'i': i, 'facts': {'previous_close': 8 if d else 9,
        'previous_mean': 10, 'previous_atr': 1, 'close': 11 if r else 10, 'previous_high': 10}}


def row(i, day, value, stratum='2020-01|10:00'):
    return {'i': i, 'date': day, 'stratum': stratum,
            'status': 'COMPLETE' if value is not None else 'NO_ENTRY', 'price_net_return': value}


def worker(item):
    return flags(item['facts'])


def main():
    assert flags(f(0)['facts']) == {'D': True, 'R': True, 'C': True, 'D_NR': False}
    assert flags(f(0, r=False)['facts']) == {'D': True, 'R': False, 'C': False, 'D_NR': True}
    assert flags(f(0, d=False)['facts']) == {'D': False, 'R': True, 'C': False, 'D_NR': False}
    assert not any(flags(f(0, False, False)['facts']).values())
    x = f(0)['facts']
    x['previous_close'] += 1e-10
    assert not flags(x)['D']
    x = f(0, r=False)['facts']
    x['close'] += 1e-10
    assert flags(x)['R']
    facts = [f(0), f(1, False), f(2, True, False), f(3), f(4), f(5, False), f(6, True, False)]
    e = episodes(facts)
    assert e[0]['left_censored'] and e[0]['confirmations'] == [0]
    assert e[1]['members'] == [2, 3, 4] and e[1]['confirmations'] == [3, 4]
    assert e[2]['right_censored'] and not e[2]['confirmations']
    assert episodes(facts[:6])[:2] == e[:2]
    try:
        episodes([f(0), f(2)])
    except ValueError:
        pass
    else:
        raise AssertionError('A missing decision index must not join episodes')
    assert sparse([0, 14, 15, 29, 30], 13) == [0, 15, 30]
    assert sparse([0, 1, 131, 132, 260, 264], 130) == [0, 132, 264]
    # Missing future label cannot cause a replacement entry.
    ids = sparse([0, 1, 132], 130)
    complete = {1, 132}
    assert [i for i in ids if i in complete] == [132]
    days = ['a', 'b', 'c']
    control = [row(1, 'a', .1), row(2, 'b', .3)]
    target = [row(3, 'c', .4), row(4, 'c', .9, 'unsupported'), row(5, 'a', None)]
    m = match(control, target)
    assert m['unmatched_indices'] == [4] and m['supported_indices'] == [3]
    assert abs(m['control']['mean']-.2) < 1e-14 and abs(m['difference']['mean']-.2) < 1e-14
    w = np.array([[1, 1, 1], [0, 0, 3], [1, 2, 0]])
    b, d = bootstrap(control, target, days, w)
    assert b['unsupported_control_replicates'] == 1 and b['empty_target_replicates'] == 1
    assert d['difference'] == [.2, None, None]
    assert np.isclose(d['all_target_mean'][1], .65) and d['all_target_mean'][2] is None
    weights, starts = block_weights(25, 10, 20, 17)
    assert (weights.sum(axis=1) == 25).all() and starts.shape == (10, 2)
    assert np.array_equal(weights, block_weights(25, 10, 20, 17)[0])
    assert all(sum(np.bincount((s[:, None]+np.arange(20)).ravel()[:25], minlength=25)) == 25 for s in starts)
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(worker, facts)) == [worker(item) for item in facts]
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    assert 'verify.py' in sources
    save(WORK/'others/checks.json', {'status': 'PASS', 'sources': sources,
        'checks': ['threshold_inclusive_and_strict', 'disjoint_and_nested_signals', 'episode_censoring_and_gap',
                   'past_signal_prefix', 'nonoverlap_before_completeness', 'matched_support_and_denominators',
                   'undefined_bootstrap_not_zero', 'shared_block_weights', 'two_spawn_equivalence'],
        'workers': 2, 'native_threads': 1})
    print('FOCUSED_SYNTHETIC_CHECKS_PASS', flush=True)


if __name__ == '__main__':
    main()
