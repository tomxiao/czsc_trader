"""No-label scalar, calendar and feature-prefix boundary checks."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from common import WORK, account_input, digest, save
from features import at, derive, predicates


def must_fail(bars, sessions):
    try:
        derive(bars, sessions)
    except ValueError:
        return
    raise AssertionError('Invalid first/prior-session input accepted')


def main():
    assert not predicates(100., 101., 100., 102., 1.)['G0']
    a = predicates(100., 101., 100.2, 101., 1.)
    assert a['G0'] and not a['G1'] and a['G0_WITHOUT_G1']
    a = predicates(100., 101., 100.2, 102., 1.)
    assert a['G1'] and a['OLD_M025'] and not a['G1_NEW_NOT_M025']
    a = predicates(100., 100.5, 100.2, 100.7, 1.)
    assert a['G1_NEW_NOT_M025'] and not a['OLD_M025']
    # The observed subset relation is not a universal implication.
    a = predicates(100., 101., 100., 102., 1.)
    assert a['OLD_M025'] and not a['G1']
    value, _, _ = account_input()
    bars = value['products']['bars']
    sessions = value['data']['sessions']['metadata']['sessions']
    rows = derive(bars, sessions)
    changed = deepcopy(bars)
    cutoff = at('2025-06-02T00:00:00+00:00')
    for b in changed:
        if at(b['Date']) >= cutoff:
            for key in ('Open', 'High', 'Low', 'Close'):
                b[key] *= 1.7
    after = derive(changed, sessions)
    assert [r for r in rows if at(r['signal_at']) < cutoff] == [r for r in after if at(r['signal_at']) < cutoff]
    j = rows[0]['bar_index']
    must_fail(bars[:j] + bars[j + 1:], sessions)
    must_fail(bars[:j - 1] + bars[j:], sessions)
    bad = deepcopy(bars)
    bad[j]['BarStart'] = bad[j]['Date']
    must_fail(bad, sessions)
    # Prior half-day closure and both DST offsets must be present in actual rows.
    prior_hours = {at(r['prior_planned_close_at']).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).hour for r in rows}
    assert {13, 16} <= prior_hours
    ny = __import__('zoneinfo').ZoneInfo('America/New_York')
    offsets = {at(r['BarStart']).astimezone(ny).utcoffset().total_seconds() for r in rows}
    assert offsets == {-14400., -18000.}
    save(WORK / 'others/precheck.json', {
        'status': 'PASS', 'source_sha256': digest(Path(__file__)),
        'feature_source_sha256': digest(WORK / 'src/features.py'),
        'scalar_boundaries': 'strictLow equality,doji,bigGap equality,smallGap,oldnotuniversalSubset',
        'first_bar_and_prior_end_fail_closed': True, 'training_rows': len(rows),
        'halfday_prior_close': True, 'both_DST_offsets': True, 'future_feature_prefix': 'PASS',
        'new_future_labels_read': 0, 'new_accounts': 0})
    print('OPENING_PRECHECK_PASS;NO_RETURN_LABELS_READ', flush=True)


if __name__ == '__main__':
    main()
