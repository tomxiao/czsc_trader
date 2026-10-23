"""Independent read-only checks of existing event aggregates and interval bounds."""
from bisect import bisect_right
import csv
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path
import random
import statistics

HERE = Path(__file__).resolve().parents[1]
SEGMENTS = ((0, 100), (100, 184), (184, 268), (268, 352), (352, 434))
ADDITIVE = ('n', 'positive_n', 'negative_n', 'zero_n', 'positive_yuan',
            'negative_yuan', 'net_yuan', 'gross_yuan', 'fees_yuan',
            'entry_gross_yuan', 'entry_net_yuan', 'subsequent_gross_yuan')


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8), (actual, expected)


def summary(rows):
    if not rows:
        return {'n': 0}
    ys = [r['net'] for r in rows]
    return dict(n=len(rows), positive_n=sum(y > 0 for y in ys),
                negative_n=sum(y < 0 for y in ys), zero_n=sum(y == 0 for y in ys),
                positive_yuan=math.fsum(max(y, 0) for y in ys),
                negative_yuan=-math.fsum(min(y, 0) for y in ys), net_yuan=math.fsum(ys),
                gross_yuan=math.fsum(r['gross'] for r in rows),
                fees_yuan=math.fsum(r['buy_fee'] + r['sell_fee'] for r in rows),
                entry_gross_yuan=math.fsum(r['entry_gross'] for r in rows),
                entry_net_yuan=math.fsum(r['entry_net'] for r in rows),
                subsequent_gross_yuan=math.fsum(r['subsequent_gross'] for r in rows),
                net_mean_return=statistics.mean(ys) / 100000,
                net_median_return=statistics.median(ys) / 100000,
                before_entry_mean_change=statistics.mean(r['before_entry_change'] for r in rows))


def verify(saved, rows):
    expected = summary(rows)
    for key, value in expected.items():
        close(saved[key], value)
    if rows:
        close(saved['net_yuan'], saved['gross_yuan'] - saved['fees_yuan'])
        close(saved['gross_yuan'], saved['entry_gross_yuan'] + saved['subsequent_gross_yuan'])


def partition(total, parts):
    for key in ADDITIVE:
        close(total.get(key, 0), math.fsum(p.get(key, 0) for p in parts))


def optimum_dp(intervals):
    """Unit-weight scheduling DP, distinct from production earliest-finish greedy."""
    ordered = sorted(intervals)
    ends = [end for end, start in ordered]
    values = [0]
    for i, (end, start) in enumerate(ordered):
        assert start < end
        predecessor_count = bisect_right(ends, start, 0, i)
        values.append(max(values[-1], 1 + values[predecessor_count]))
    return values[-1]


def optimum_exhaustive(intervals):
    for size in range(len(intervals), -1, -1):
        for subset in combinations(intervals, size):
            ordered = sorted(subset)
            if all(ordered[i][1] >= ordered[i-1][0] for i in range(1, size)):
                return size
    raise AssertionError('Empty subset must be feasible')


def main():
    inputs = {name: HERE / 'others' / name for name in ('events.csv', 'results.json', 'supplement.json')}
    events = list(csv.DictReader(inputs['events.csv'].open(encoding='utf-8', newline='')))
    for row in events:
        row['horizon'], row['position'] = int(row['horizon']), int(row['position'])
        for key in ('A', 'B', 'C', 'P', 'P25'):
            assert row[key] in ('True', 'False')
            row[key] = row[key] == 'True'
        if row['status'] == 'CLOSED':
            for key in ('net', 'gross', 'buy_fee', 'sell_fee', 'entry_gross', 'entry_net',
                        'subsequent_gross', 'before_entry_change'):
                row[key] = float(row[key])
                assert math.isfinite(row[key])
    results, supplement = (json.loads(inputs[n].read_text(encoding='utf-8')) for n in ('results.json', 'supplement.json'))
    assert len(events) == 1302 and len({(r['horizon'], r['date']) for r in events}) == 1302
    dates = sorted({r['date'] for r in events})
    assert len(dates) == 434
    summaries_checked, partitions_checked = 0, 0
    counts = []
    for h in (1, 3, 5):
        frame = [r for r in events if r['horizon'] == h]
        closed = [r for r in frame if r['status'] == 'CLOSED']
        assert len(frame) == 434 and sorted(r['position'] for r in frame) == list(range(434))
        sr, su = results['horizons'][str(h)], supplement['horizons'][str(h)]
        for key in ('A', 'B', 'C'):
            whole = sr['comparisons'][key]
            selected, excluded = [r for r in closed if r[key]], [r for r in closed if not r[key]]
            for saved, rows in ((whole['all'], closed), (whole['in'], selected), (whole['out'], excluded)):
                verify(saved, rows)
                summaries_checked += 1
            partition(whole['all'], [whole['in'], whole['out']])
            partitions_checked += 1
            bounds = []
            for left in range(375):
                intervals = [(r['actual_exit_date'], r['entry_date']) for r in selected
                             if dates[left] <= r['actual_exit_date'] <= dates[left+59]]
                bounds.append(optimum_dp(intervals))
            density = su['density'][key]
            assert bounds == density['nonoverlap_optimistic_rolling_upper_bounds']
            assert len(bounds) == density['windows'] == 375
            assert statistics.median(bounds) == density['nonoverlap_optimistic_60_median_upper_bound']
            assert sum(v >= 3 for v in bounds) == density['nonoverlap_optimistic_windows_at_least3_upper_bound']
            assert density['signal_n'] == sum(r[key] for r in frame)
            assert density['closed_n'] == len(selected)
            counts.append(dict(condition=key, horizon=h, median_upper=statistics.median(bounds),
                               windows_ge3_upper=sum(v >= 3 for v in bounds), windows=375))
        for left, right in SEGMENTS:
            period = su['periods'][f'{left}:{right}']
            rows = [r for r in closed if left <= r['position'] < right]
            verify(period['all'], rows)
            summaries_checked += 1
            for key in ('A', 'B', 'C'):
                groups = period['groups'][key]
                verify(groups['in'], [r for r in rows if r[key]])
                verify(groups['out'], [r for r in rows if not r[key]])
                verify(sr['comparisons'][key]['periods'][f'{left}:{right}'], [r for r in rows if r[key]])
                summaries_checked += 3
                partition(period['all'], [groups['in'], groups['out']])
                partitions_checked += 1
            incremental = period['B_increment']
            verify(incremental['B'], [r for r in rows if r['B']])
            verify(incremental['A_not_B'], [r for r in rows if r['A'] and not r['B']])
            partition(period['groups']['A']['in'], list(incremental.values()))
            summaries_checked += 2
            partitions_checked += 1
            for pressure in ('P', 'P25'):
                cells = period['C_pressure_cells'][pressure]
                for cv in (False, True):
                    for pv in (False, True):
                        verify(cells[f'C{int(cv)}_P{int(pv)}'], [r for r in rows if r['C'] == cv and r[pressure] == pv])
                        summaries_checked += 1
                partition(period['all'], list(cells.values()))
                partition(period['groups']['C']['in'], [cells['C1_P0'], cells['C1_P1']])
                partition(period['groups']['C']['out'], [cells['C0_P0'], cells['C0_P1']])
                partitions_checked += 3
        partition(sr['comparisons']['A']['all'], [p['all'] for p in su['periods'].values()])
        partitions_checked += 1
    rng = random.Random(13)
    fixtures = [[], [(1, 0), (2, 1), (3, 2)], [(4, 0), (4, 1), (4, 2)], [(5, 0), (2, 0), (4, 2), (6, 4)]]
    for _ in range(256):
        case = []
        for _ in range(rng.randrange(10)):
            start = rng.randrange(10)
            case.append((start + rng.randrange(1, 7), start))
        fixtures.append(case)
    for case in fixtures:
        assert optimum_dp(case) == optimum_exhaustive(case)
    output = dict(status='PASS', existing_event_rows=1302, new_events=0, new_accounts=0,
                  summary_records_verified=summaries_checked, partition_identities_verified=partitions_checked,
                  interval_window_bounds_verified=9*375, exhaustive_synthetic_cases=len(fixtures),
                  independent_algorithm='Unit-weight interval scheduling dynamic programming; synthetic exhaustive subset cross-check.',
                  bound_scope='Per-window optimistic maximum for subsets of exact fixed-horizon one-buy-one-sell events; same-day reentry allowed, independent window optimization, no cash constraint. Not a bound on altered entry/exit or combined mechanisms.',
                  fixed_cells=counts, input_sha256={n:sha256(p.read_bytes()).hexdigest() for n,p in inputs.items()},
                  audit_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'others/summary_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
