"""Independent scalar causal annual ridge, grouped utility and block audit."""
from bisect import bisect_left, bisect_right
from math import fsum, exp, log1p, sin, cos, pi
from calendar import monthrange
import numpy as np
import pandas as pd

MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'calendar_only', 'confirmation_calendar', 'original14_calendar')
NEW_MODELS = MODELS[3:]
QUANTITIES = ('calendar_mse_improvement_vs_mean', 'confirmation_calendar_mse_improvement_vs_confirmation',
              'original14_calendar_mse_improvement_vs_original14', 'calendar_positive_mean',
              'confirmation_calendar_positive_mean', 'original14_calendar_positive_mean',
              'calendar_positive_mean_minus_all', 'confirmation_calendar_positive_mean_minus_confirmation',
              'original14_calendar_positive_mean_minus_original14', 'original14_calendar_mse_improvement_vs_mean')


def mean(values):
    return fsum(float(v) for v in values) / len(values)


def cdf(train, values):
    ordered = sorted(float(x) for x in train)
    return [(bisect_left(ordered, float(v)) + bisect_right(ordered, float(v))) / (2 * len(ordered)) for v in values]


def solve(matrix, right):
    n = len(right)
    a = [[float(v) for v in row] + [float(right[i])] for i, row in enumerate(matrix)]
    for i in range(n):
        best = max(range(i, n), key=lambda j: abs(a[j][i]))
        a[i], a[best] = a[best], a[i]
        if abs(a[i][i]) < 1e-14:
            raise ValueError('Independent normal equations singular')
        pivot = a[i][i]
        a[i] = [v / pivot for v in a[i]]
        for j in range(n):
            if j != i:
                factor = a[j][i]
                a[j] = [u - factor * v for u, v in zip(a[j], a[i])]
    return [a[i][-1] for i in range(n)]


def ridge(train, target, test):
    n, d = len(train), len(train[0])
    mx, my = [mean([r[j] for r in train]) for j in range(d)], mean(target)
    z = [[r[j] - mx[j] for j in range(d)] for r in train]
    matrix = [[fsum(z[i][a] * z[i][b] for i in range(n)) + (10 if a == b else 0) for b in range(d)] for a in range(d)]
    right = [fsum(z[i][j] * (float(target[i]) - my) for i in range(n)) for j in range(d)]
    slopes = solve(matrix, right)
    intercept = my - fsum(a * b for a, b in zip(mx, slopes))
    pred = [intercept + fsum(a * b for a, b in zip(row, slopes)) for row in test]
    return pred, [intercept, *slopes]


def calendar(dates):
    return [[.5 * sin(2 * pi * (d.day - 1) / monthrange(d.year, d.month)[1]),
             .5 * cos(2 * pi * (d.day - 1) / monthrange(d.year, d.month)[1])] for d in dates]


def forecasts(features, labels, prior):
    axis, x = features.index, features.to_numpy(float)
    complete = [all(np.isfinite(v) for v in r) for r in x]
    target = labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    result = prior.copy()
    for name in MODELS[3:]:
        result[name] = np.nan
    fits = {}
    for year in sorted(set(day.year for day in axis if day.year >= 2021)):
        first = next(day for day in axis if day.year == year)
        tr = [i for i, t in enumerate(axis) if complete[i] and np.isfinite(target[i]) and 2020 <= t.year < year and ends.iloc[i] < first]
        te = [i for i, t in enumerate(axis) if complete[i] and t.year == year]
        row = {'first_signal': first.isoformat(), 'train_n': len(tr), 'feature_test_n': len(te),
               'max_maturity': max(ends.iloc[i] for i in tr).isoformat() if tr else None,
               'train_dates': [axis[i].isoformat() for i in tr], 'future_test_count_gate': False, 'coefficients': {}}
        if len(tr) >= 40:
            rt = [cdf(x[tr, j], x[tr, j]) for j in range(14)]
            rv = [cdf(x[tr, j], x[te, j]) for j in range(14)]
            ct, cv = calendar(axis[tr]), calendar(axis[te])
            for name, columns in zip(MODELS[3:], ((), (8,), tuple(range(14)))):
                tx = [[rt[j][i] - .5 for j in columns] + ct[i] for i in range(len(tr))]
                vx = [[rv[j][i] - .5 for j in columns] + cv[i] for i in range(len(te))]
                prediction, coef = ridge(tx, target[tr], vx)
                result.iloc[te, result.columns.get_loc(name)] = prediction
                row['coefficients'][name] = coef
        fits[str(year)] = row
    return result, fits


def compare(a, b, where='root'):
    if isinstance(b, dict):
        if set(a) != set(b):
            raise AssertionError('keys: ' + where)
        for k in b:
            compare(a[k], b[k], where + '/' + k)
    elif isinstance(b, list):
        if len(a) != len(b):
            raise AssertionError('length: ' + where)
        for i, (aa, bb) in enumerate(zip(a, b)):
            compare(aa, bb, where + '/' + str(i))
    elif isinstance(b, float):
        if not np.isclose(a, b, atol=2e-12, rtol=2e-9):
            raise AssertionError('number: ' + where)
    elif a != b:
        raise AssertionError('value: ' + where)


def grouped(target, prediction, ids):
    eligible = [i for i in ids if np.isfinite(prediction[i])]
    positive = [i for i in eligible if prediction[i] > 0]
    mature = [i for i in positive if np.isfinite(target[i])]
    n = len(mature)
    return {'forecasts': len(eligible), 'positive_forecasts': len(positive), 'mature_positive': n,
            'missing_positive_truth': len(positive) - n,
            'positive_mean': mean([target[i] for i in mature]) if n >= 20 else None,
            'hit_rate': sum(target[i] > 0 for i in mature) / n if n >= 20 else None,
            'false_positive_rate': sum(target[i] <= 0 for i in mature) / n if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(target, scores, ids):
    ix = [int(i) for i in ids if np.isfinite(target[i]) and all(np.isfinite(v) for v in scores[i])]
    errors = [mean([(float(target[i]) - float(scores[i, j])) ** 2 for i in ix]) for j in range(6)] if len(ix) >= 20 else None
    avg = [mean([target[i] for i in ix if scores[i, j] > 0]) if sum(scores[i, j] > 0 for i in ix) >= 20 else None for j in range(6)]
    out = {key: float(1 - errors[a] / errors[b]) if errors is not None and errors[b] > 0 else None
           for key, (a, b) in zip(QUANTITIES[:3], ((3, 0), (4, 1), (5, 2)))}
    out.update(dict(zip(QUANTITIES[3:6], avg[3:])))
    out[QUANTITIES[6]] = avg[3] - mean([target[i] for i in ix]) if avg[3] is not None and len(ix) >= 20 else None
    for key, new, old in ((QUANTITIES[7], 4, 1), (QUANTITIES[8], 5, 2)):
        out[key] = avg[new] - avg[old] if avg[new] is not None and avg[old] is not None else None
    out[QUANTITIES[9]] = float(1 - errors[5] / errors[0]) if errors is not None and errors[0] > 0 else None
    return out


def verify(features, labels, prior, reported_scores, report):
    expected, fits = forecasts(features, labels, prior)
    np.testing.assert_allclose(reported_scores.to_numpy(), expected.to_numpy(), rtol=2e-9, atol=2e-12, equal_nan=True)
    np.testing.assert_array_equal(reported_scores.to_numpy() > 0, expected.to_numpy() > 0)
    compare(report['fit_years'], fits, 'fits')
    y, p, axis = labels.return_4.to_numpy(float), expected.to_numpy(float), features.index
    common = [i for i in range(len(axis)) if np.isfinite(y[i]) and np.isfinite(p[i]).all()]
    quality = {m: {'n': len(common), 'mse': mean([(p[i, j] - y[i]) ** 2 for i in common])} for j, m in enumerate(MODELS)}
    compare(report['quality'], quality, 'quality')
    masks = {'all': list(range(len(axis))), **{'year_' + str(t): [i for i, x in enumerate(axis) if x.year == t] for t in range(2020, 2027)},
             'rising': [i for i in range(len(axis)) if features.momentum20.iloc[i] > 0],
             'falling': [i for i in range(len(axis)) if features.momentum20.iloc[i] < 0],
             'zero_momentum': [i for i in range(len(axis)) if features.momentum20.iloc[i] == 0],
             **{'civil_quarter_' + str(q): [i for i, x in enumerate(axis) if 4 * (x.day - 1) // monthrange(x.year, x.month)[1] == q] for q in range(4)},
             **{'phase_' + str(k): [i for i in range(len(axis)) if i % 5 == k] for k in range(5)}}
    panels = {key: {m: grouped(y, p[:, j], ids) for j, m in enumerate(MODELS)} for key, ids in masks.items()}
    compare(report['panels'], panels, 'panels')
    for j, model in enumerate(MODELS[1:], 1):
        remaining, records = 0, []
        for i in range(len(axis)):
            if remaining > 0:
                remaining -= 1
            elif np.isfinite(p[i, j]) and p[i, j] > 0:
                remaining = 4
                records.append({'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(p[i, j]),
                                'proxy_return': float(y[i]) if np.isfinite(y[i]) else None})
        mature = [r['proxy_return'] for r in records if r['proxy_return'] is not None]
        result = {'accepted': len(records), 'mature': len(mature), 'mean_proxy': mean(mature) if len(mature) >= 20 else None,
                  'compound_proxy': exp(fsum(log1p(v) for v in mature)) - 1 if len(mature) >= 20 else None,
                  'records': records, 'actual_closed_trades': None, 'account_return': None}
        compare(report['nonoverlap_proxies'][model], result, 'episodes/' + model)
    n = len(axis)
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    indices = np.concatenate([starts[:, j:j + 1] + np.arange(40) for j in range(starts.shape[1])], axis=1)[:, :n]
    records = [quantities(y, p, row) for row in indices]
    compare(report['bootstrap']['records'], records, 'bootstrap_records')
    original = quantities(y, p, np.arange(n))
    summary = {}
    for key in QUANTITIES:
        good = [r[key] for r in records if r[key] is not None]
        ok = original[key] is not None and len(good) >= 400
        summary[key] = {'value': original[key], 'valid_replicates': len(good),
                        'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                        'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'], summary, 'bootstrap_summary')
    return {'status': 'PASS', 'new_accounts': 0, 'annual_models': 3 * len(fits), 'forecast_rows': len(axis),
            'strict_positive_flags': 'EXACT', 'panels_checked': len(panels), 'bootstrap_quantities': len(QUANTITIES),
            'bootstrap_replicates': 500, 'scalar_normal_equations': True, 'policy_clock_independent': True}
