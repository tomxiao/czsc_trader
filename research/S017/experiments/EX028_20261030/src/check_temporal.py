"""Synthetic maturity, selection and cross-fold checks before looking at returns."""
from copy import deepcopy
from datetime import date, timedelta
from common import WORK, save, digest
from temporal import analyze_temporal


def main():
    days, day = [], date(2019, 1, 2)
    while len(days) < 400:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    names = ('S017-M012', 'S017-M013', 'S017-M014')
    rows = []
    for d, at in enumerate(days):
        for slot in range(2):
            flag = d % 3 == 0
            rows.append({'i': d*13+slot, 'n': 6, 'day_index': d, 'date': at, 'month': at[:7],
                'stratum': at[:7]+'|'+str(slot), 'regime': 'up|low',
                'signals': [names[0]] if flag else [], 'status': 'COMPLETE',
                'price_net_return': .02 if flag else -.01,
                'exit_at': at+'T20:00:00+00:00'})
    a = analyze_temporal(rows, days, names)
    first = a['sequential']['folds'][0]
    assert first['choice'] == names[0] and first['train_end'] == days[251]
    changed = deepcopy(rows)
    for r in changed:
        if r['day_index'] >= 252:
            r['price_net_return'] = -.99
    b = analyze_temporal(changed, days, names)
    assert first['training'] == b['sequential']['folds'][0]['training']
    assert first['choice'] == b['sequential']['folds'][0]['choice']
    late = deepcopy(rows)
    for r in late:
        if r['day_index'] < 252 and names[0] in r['signals']:
            r['exit_at'] = days[252]+'T20:00:00+00:00'
    c = analyze_temporal(late, days, names)
    assert c['sequential']['folds'][0]['choice'] is None
    indices = [r['i'] for r in a['sequential']['pooled']['events']]
    assert all(y > x+7 for x, y in zip(indices, indices[1:]))
    assert indices[0] == 252*13
    bad = deepcopy(rows)
    bad.append(bad[0])
    try:
        analyze_temporal(bad, days, names)
    except ValueError:
        pass
    else:
        raise AssertionError('Duplicate accepted')
    save(WORK/'others/temporal_checks.json', {'status': 'PASS', 'scope': 'SYNTHETIC_ONLY',
        'checks': ['future_results_do_not_change_prior_choice', 'test_day_exit_excluded_from_training',
                   'cross_fold_nonoverlap_continuous', 'zero_index_safe', 'duplicate_rejected', 'finite_json'],
        'sources': {p.name: digest(p) for p in (WORK/'src/temporal.py', WORK/'src/check_temporal.py')}})
    print('TEMPORAL_CHECKS_PASS', flush=True)


if __name__ == '__main__':
    main()
