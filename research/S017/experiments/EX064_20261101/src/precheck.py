"""Same-day event, complete-grid and intraday future-prefix boundaries; no labels."""
from collections import Counter
from copy import deepcopy
from pathlib import Path

from common import WORK, account_input, digest, save
from features import GROUPS, at, derive, predicates


def must_fail(bars, sessions):
    try:
        derive(bars, sessions)
    except ValueError:
        return
    raise AssertionError('Missing or malformed grid was accepted')


def main():
    assert predicates(100., 99., 101., 100., 90., True)['UP_CROSS']
    assert not predicates(99., 98., 100., 100., 90., True)['UP_CROSS']
    assert predicates(101., 100.01, 102., 100., 90., True)['UP_ACCEPT']
    assert not predicates(101., 100., 102., 100., 90., True)['UP_ACCEPT']
    assert not predicates(101., 100.01, 102., 100., 90., False)['UP_ACCEPT']
    assert predicates(90., 89., 91., 100., 90., False)['LOW_REJECT']
    assert not predicates(90., 90., 91., 100., 90., False)['LOW_REJECT']
    assert not predicates(90., 89., 90., 100., 90., False)['LOW_REJECT']
    assert not predicates(89., 88., 91., 100., 90., False)['LOW_REJECT']
    # Cross and full-bar acceptance may occur together,without a compulsory extra delay.
    a = predicates(100., 100.1, 101., 100., 90., True)
    assert a['UP_CROSS'] and a['UP_ACCEPT']
    value, _, _ = account_input()
    bars = value['products']['bars']
    sessions = value['data']['sessions']['metadata']['sessions']
    rows = derive(bars, sessions)
    for g in GROUPS:
        dates = [r['session_date'] for r in rows if r[g]]
        assert len(dates) == len(set(dates))
        for day in {r['session_date'] for r in rows}:
            matches = [r for r in rows if r['session_date'] == day and r['raw_' + g]]
            selected = [r for r in rows if r['session_date'] == day and r[g]]
            assert selected == matches[:1]
    assert all(1 < r['completed_bar_ordinal'] < r['total_session_bars'] for r in rows)
    assert Counter(r['total_session_bars'] for r in rows) == {13: 5456, 7: 30}
    assert all(at(r['same_session_next_start']) == at(r['signal_at']) for r in rows)
    for day in {r['session_date'] for r in rows}:
        current = [r for r in rows if r['session_date'] == day]
        assert len({(r['prior_session_high'], r['prior_session_low'], r['prior_session_date']) for r in current}) == 1
        assert all(r['prior_session_date'] < day for r in current)
    changed = deepcopy(bars)
    cutoff = at('2025-06-02T17:00:00+00:00')
    for b in changed:
        if at(b['Date']) >= cutoff:
            for k in ('Open', 'High', 'Low', 'Close'):
                b[k] *= 1.7
    after = derive(changed, sessions)
    assert [r for r in rows if at(r['signal_at']) < cutoff] == [r for r in after if at(r['signal_at']) < cutoff]
    # Missing first, middle or terminal prior-session observations must not become last-seen ranges.
    for i in (526, 529, 538):
        must_fail(bars[:i] + bars[i + 1:], sessions)
    bad = deepcopy(bars)
    bad[530]['BarStart'] = bad[530]['Date']
    must_fail(bad, sessions)
    save(WORK / 'others/precheck.json', {'status': 'PASS', 'source_sha256': digest(Path(__file__)),
        'feature_source_sha256': digest(WORK / 'src/features.py'), 'eligible_observations': len(rows),
        'scalar_equality_and_samebar_cross_accept': True, 'daily_first_without_replacement': True,
        'first_and_last_slot_excluded': True, 'halfday_slots': 30, 'normal_slots': 5456,
        'previous_range_all_day_frozen': True, 'full_grid_missing_rows_fail': True,
        'intraday_future_prefix_including_current_day_later_extremes': 'PASS',
        'new_future_labels_read': 0, 'new_accounts': 0})
    print('SESSION_RANGE_PRECHECK_PASS;NO_RETURN_LABELS_READ', flush=True)


if __name__ == '__main__':
    main()
