"""Pure, past-visible expressions, chronological membership and supported matching."""
from collections import Counter
import numpy as np

NAMES = ('D', 'R', 'C', 'D_NR')
HORIZONS = (3, 13, 26, 65, 130)


def flags(f):
    d = f['previous_close'] <= f['previous_mean'] - 2 * f['previous_atr']
    r = f['close'] > f['previous_high']
    return {'D': d, 'R': r, 'C': d and r, 'D_NR': d and not r}


def sparse(indices, n):
    result, boundary = [], -1
    for i in sorted(indices):
        if i > boundary:
            result.append(i)
            boundary = i + n + 1
    return result


def episodes(facts):
    result = []
    previous = None
    active = None
    for item in facts:
        i, signal = item['i'], flags(item['facts'])
        if previous is not None and i != previous + 1:
            raise ValueError('Episode construction needs consecutive decision indices')
        if signal['D']:
            if active is None:
                active = {'start': i, 'end': i, 'members': [], 'confirmations': [],
                          'left_censored': previous is None, 'right_censored': False}
                result.append(active)
            active['end'] = i
            active['members'].append(i)
            if signal['C']:
                active['confirmations'].append(i)
        else:
            active = None
        previous = i
    if active is not None:
        active['right_censored'] = True
    return result


def stats(values):
    a = np.array([v for v in values if v is not None], dtype=float)
    if not len(a):
        return {'count': 0}
    wins, losses = a[a > 0], a[a < 0]
    return {'count': len(a), 'mean': float(a.mean()), 'median': float(np.median(a)),
            'win_rate': float((a > 0).mean()),
            'payoff_ratio': float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
            'q10': float(np.quantile(a, .1)), 'q90': float(np.quantile(a, .9))}


def summary(rows):
    return {'events': len(rows), 'days': len({r['date'] for r in rows}),
            'status': dict(Counter(r['status'] for r in rows)),
            'price': stats([r['price_net_return'] for r in rows])}


def supported(control, targets):
    cells = {r['stratum'] for r in control if r['price_net_return'] is not None}
    complete = [r for r in targets if r['price_net_return'] is not None]
    return ([r for r in complete if r['stratum'] in cells],
            [r['i'] for r in complete if r['stratum'] not in cells])


def match(control, targets):
    chosen, absent = supported(control, targets)
    groups = {}
    for r in control:
        if r['price_net_return'] is not None:
            groups.setdefault(r['stratum'], []).append(r['price_net_return'])
    means = {k: float(np.mean(v)) for k, v in groups.items()}
    counts = Counter(r['stratum'] for r in chosen)
    return {'all_target': summary(targets), 'supported_target': summary(chosen),
            'unmatched_indices': absent, 'supported_indices': [r['i'] for r in chosen],
            'control': stats([means[r['stratum']] for r in chosen]),
            'difference': stats([r['price_net_return'] - means[r['stratum']] for r in chosen]),
            'support': {'cells': len(counts),
                'minimum_control_count': min((len(groups[r['stratum']]) for r in chosen), default=None),
                'singleton_targets': sum(len(groups[r['stratum']]) == 1 for r in chosen)}}


def block_weights(day_count, replicates=1000, block=20, seed=17):
    if day_count < block:
        raise ValueError('Insufficient sessions')
    starts = np.random.default_rng(seed).integers(0, day_count-block+1,
        size=(replicates, int(np.ceil(day_count/block))))
    weights = np.array([np.bincount((s[:, None]+np.arange(block)).ravel()[:day_count],
                                   minlength=day_count) for s in starts], dtype=np.int32)
    return weights, starts


def interval(values):
    good = [x for x in values if x is not None]
    return {'valid_replicates': len(good), 'undefined_replicates': len(values)-len(good),
            'interval_95': [float(x) for x in np.quantile(good, [.025, .975])] if good else None}


def bootstrap(control, targets, days, weights):
    chosen, absent = supported(control, targets)
    day = {d: i for i, d in enumerate(days)}
    cells = {s: i for i, s in enumerate(sorted({r['stratum'] for r in control+targets}))}
    def arrays(rows):
        rows = [r for r in rows if r['price_net_return'] is not None]
        return (np.array([r['price_net_return'] for r in rows], dtype=float),
                np.array([day[r['date']] for r in rows], dtype=int),
                np.array([cells[r['stratum']] for r in rows], dtype=int))
    y, yd, yc = arrays(chosen)
    x, xd, xc = arrays(control)
    a, ad, _ = arrays(targets)
    draws = {'all_target_mean': [], 'supported_target_mean': [], 'difference': []}
    empty, unsupported = 0, 0
    for w in weights:
        aw, yw, xw = w[ad], w[yd], w[xd]
        draws['all_target_mean'].append(float(np.dot(a, aw)/aw.sum()) if aw.sum() else None)
        if not yw.sum():
            empty += 1
            draws['supported_target_mean'].append(None)
            draws['difference'].append(None)
            continue
        draws['supported_target_mean'].append(float(np.dot(y, yw)/yw.sum()))
        den = np.bincount(xc, weights=xw, minlength=len(cells))
        num = np.bincount(xc, weights=xw*x, minlength=len(cells))
        if np.any((yw > 0) & (den[yc] == 0)):
            unsupported += 1
            draws['difference'].append(None)
            continue
        mean = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
        draws['difference'].append(float(np.dot(y-mean[yc], yw)/yw.sum()))
    return {'intervals': {k: interval(v) for k, v in draws.items()},
            'empty_target_replicates': empty, 'unsupported_control_replicates': unsupported,
            'original_unmatched': len(absent)}, draws
