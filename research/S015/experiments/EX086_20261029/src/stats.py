"""Event-study summaries extracted from frozen S017 EX019/EX020 methods.

No old experiment imports or market-data access. ``date`` denotes planned entry
session; ``signal_days`` retains the original field name for compatibility.
"""
from collections import Counter
from hashlib import sha256

import numpy as np


def nonoverlap(indices, n):
    """Greedy chronological selection; the caller provides ordered signal indices."""
    selected, end = [], -1
    for i in indices:
        if i > end:
            selected.append(i)
            end = i + n + 1
    return set(selected)


def stats(values):
    a = np.array([v for v in values if v is not None], dtype=float)
    if not len(a):
        return {'count': 0}
    wins, losses = a[a > 0], a[a < 0]
    return {
        'count': len(a), 'mean': float(a.mean()), 'median': float(np.median(a)),
        'win_rate': float(np.mean(a > 0)), 'flat_rate': float(np.mean(a == 0)),
        'average_win': float(wins.mean()) if len(wins) else None,
        'average_loss_magnitude': float(-losses.mean()) if len(losses) else None,
        'payoff_ratio': float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
        'q10': float(np.quantile(a, .1)), 'q90': float(np.quantile(a, .9)),
    }


def summarize(rows):
    return {
        'events': len(rows), 'signal_days': len({r['date'] for r in rows}),
        'status': dict(Counter(r['status'] for r in rows)),
        'entry_status': dict(Counter(r['entry_status'] for r in rows)),
        'exit_status': dict(Counter(r['exit_status'] for r in rows)),
        'information': stats([r['information_return'] for r in rows]),
        'price': stats([r['price_net_return'] for r in rows]),
        'close_path_min': stats([r['close_path_min'] for r in rows]),
        'close_path_max': stats([r['close_path_max'] for r in rows]),
    }


def match(control, selected):
    groups = {}
    for row in control:
        if row['price_net_return'] is not None:
            groups.setdefault(row['stratum'], []).append(row['price_net_return'])
    chosen = [r for r in selected if r['price_net_return'] is not None]
    counts = Counter(r['stratum'] for r in chosen)
    means = {k: float(np.mean(v)) for k, v in groups.items()}
    if any(r['stratum'] not in groups for r in chosen):
        raise ValueError('Selected event lacks matched control support')
    return {
        'count': len(chosen),
        'control_mean': float(np.mean([means[r['stratum']] for r in chosen])) if chosen else None,
        'difference': stats([r['price_net_return'] - means[r['stratum']] for r in chosen]),
        'control_support': {
            'unique_cells': len(counts),
            'singleton_target_events': sum(len(groups[r['stratum']]) == 1 for r in chosen),
            'all_target_cell_events': sum(len(groups[r['stratum']]) == counts[r['stratum']] for r in chosen),
            'median_control_events_per_target': float(np.median([len(groups[r['stratum']]) for r in chosen])) if chosen else None,
            'minimum_control_events': min((len(groups[r['stratum']]) for r in chosen), default=None),
        },
    }


def concentration(rows):
    """Positive event-return concentration; observed years, not a fixed market window."""
    positive = [r for r in rows if r['price_net_return'] is not None and r['price_net_return'] > 0]
    total = sum(r['price_net_return'] for r in positive)
    years = sorted({r['date'][:4] for r in rows})
    yearly = {
        year: sum(r['price_net_return'] for r in positive if r['date'].startswith(year))
        for year in years
    }
    return {
        'positive_return_sum': total, 'positive_events': len(positive),
        'largest_event_share': max((r['price_net_return'] for r in positive), default=0) / total if total else None,
        'largest_year_share': max(yearly.values()) / total if total else None,
        'positive_sum_by_year': yearly,
        'scope': 'Sum of independent event returns, not account PnL contribution.',
    }


def block_weights(day_count, replicates=1000, block=20, seed=17):
    if day_count < block:
        raise ValueError('Insufficient trading days for declared block length')
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, day_count - block + 1, size=(replicates, int(np.ceil(day_count / block))))
    offsets = np.arange(block)
    weights = np.zeros((replicates, day_count), dtype=np.int32)
    for j, values in enumerate(starts):
        indices = (values[:, None] + offsets[None, :]).ravel()[:day_count]
        weights[j] = np.bincount(indices, minlength=day_count)
    return weights, sha256(starts.astype('<i8').tobytes()).hexdigest()


def bootstrap(rows, selected, control, days, weights):
    day_index = {day: i for i, day in enumerate(days)}
    cells = {cell: i for i, cell in enumerate(sorted({r['stratum'] for r in rows}))}

    def arrays(pop):
        valid = [r for r in pop if r['price_net_return'] is not None]
        return (
            np.array([r['price_net_return'] for r in valid], dtype=float),
            np.array([day_index[r['date']] for r in valid], dtype=int),
            np.array([cells[r['stratum']] for r in valid], dtype=int),
        )

    y, yd, yc = arrays(selected)
    x, xd, xc = arrays(control)
    means, differences = [], []
    for weight in weights:
        yw, xw = weight[yd], weight[xd]
        if not len(y) or yw.sum() == 0:
            means.append(None)
            differences.append(None)
            continue
        denominator = np.bincount(xc, weights=xw, minlength=len(cells))
        numerator = np.bincount(xc, weights=xw * x, minlength=len(cells))
        if np.any((yw > 0) & (denominator[yc] == 0)):
            raise ValueError('Bootstrap target lacks positive-weight matched controls')
        baseline = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
        means.append(float(np.sum(yw * y) / yw.sum()))
        differences.append(float(np.sum(yw * (y - baseline[yc])) / yw.sum()))

    def interval(values):
        valid = [value for value in values if value is not None]
        return {
            'valid_replicates': len(valid), 'empty_replicates': len(values) - len(valid),
            'interval_95': [float(value) for value in np.quantile(valid, [.025, .975])] if valid else None,
        }

    return (
        {'price_mean': interval(means), 'matched_difference': interval(differences)},
        {'price_mean': means, 'matched_difference': differences},
    )
