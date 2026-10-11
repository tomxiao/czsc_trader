"""Fixed EX081 confirmation by signed price context; supplied frames only."""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'confirmation_trend', 'confirmation_trend_interaction')
NEW_MODELS = MODELS[3:]
QUANTITIES = ('interaction_mse_improvement_vs_control', 'control_mse_improvement_vs_confirmation',
              'interaction_mse_improvement_vs_confirmation', 'interaction_mse_improvement_vs_mean',
              'control_mse_improvement_vs_mean', 'interaction_positive_mean', 'control_positive_mean',
              'interaction_positive_mean_minus_control', 'interaction_positive_mean_minus_confirmation',
              'interaction_positive_mean_minus_all')


def validate(features, labels, prior):
    axis = pd.DatetimeIndex(features.index).as_unit('ns')
    if axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('ordered unique naive midnight signal dates')
    if tuple(features.columns) != FEATURES or not labels.index.equals(axis) or not prior.index.equals(axis):
        raise ValueError('Exact original14 and shared axis required')
    x = features.to_numpy(float)
    y = labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if np.isinf(x).any() or np.isinf(y).any() or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError('Finite features and paired target/maturity missingness')
    if (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any():
        raise ValueError('Maturity strictly after T')
    if tuple(prior.columns) != MODELS[:3] or np.isinf(prior.to_numpy(float)).any():
        raise ValueError('Exactly three authenticated prior scores')
    return axis, x, y, ends


def rank(train, values):
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side='left') + np.searchsorted(ordered, values, side='right')) / (2. * len(train))


def design(train_cf, cf, momentum, interaction):
    confirmation = rank(train_cf, cf) - .5
    state = np.sign(momentum)
    cols = [confirmation, state]
    if interaction:
        cols.append(confirmation * state)
    return np.column_stack(cols)


def fit(train, target, test):
    mx, my = train.mean(axis=0), float(target.mean())
    centered = train - mx
    slopes = np.linalg.solve(centered.T @ centered + 10. * np.eye(train.shape[1]), centered.T @ (target - my))
    intercept = float(my - mx @ slopes)
    return intercept + test @ slopes, [intercept, *slopes.tolist()]


def forecasts(features, labels, prior):
    axis, x, y, ends = validate(features, labels, prior)
    complete = np.isfinite(x).all(axis=1)
    scores = prior.copy()
    for model in NEW_MODELS:
        scores[model] = np.nan
    years = {}
    cf, mom = x[:, 8], x[:, 0]
    for year in sorted(set(axis.year[axis.year >= 2021])):
        first = axis[axis.year == year][0]
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year) & (ends < first).to_numpy()
        test = complete & (axis.year == year)
        available = int(train.sum()) >= 40
        if not np.array_equal(np.isfinite(prior.loc[axis.year == year].to_numpy()).all(axis=1), test[axis.year == year] & available):
            raise ValueError('Prior/current predictable rows differ')
        row = {'first_signal': first.isoformat(), 'train_n': int(train.sum()), 'feature_test_n': int(test.sum()),
               'max_maturity': ends[train].max().isoformat() if train.any() else None,
               'train_dates': [t.isoformat() for t in axis[train]], 'future_test_count_gate': False,
               'train_state_counts': {str(int(s)): int((np.sign(mom[train]) == s).sum()) for s in (-1, 0, 1)},
               'coefficients': {}}
        if available:
            np.testing.assert_allclose(prior.loc[test, 'training_mean'], y[train].mean(), rtol=2e-12, atol=2e-14)
            for model, interaction in zip(NEW_MODELS, (False, True)):
                tx = design(cf[train], cf[train], mom[train], interaction)
                vx = design(cf[train], cf[test], mom[test], interaction)
                prediction, coef = fit(tx, y[train], vx)
                scores.loc[test, model] = prediction
                row['coefficients'][model] = coef
        years[str(year)] = row
    if prior.loc[axis.year < 2021].notna().any().any():
        raise ValueError('No prospective2020 scores')
    return scores, years


def group(y, prediction, mask):
    available = mask & np.isfinite(prediction)
    chosen = available & (prediction > 0)
    mature = chosen & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(available.sum()), 'positive_forecasts': int(chosen.sum()), 'mature_positive': n,
            'missing_positive_truth': int((chosen & ~np.isfinite(y)).sum()),
            'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y, prediction, indices):
    yy, pp = y[indices], prediction[indices]
    valid = np.isfinite(yy) & np.isfinite(pp).all(axis=1)
    yy, pp = yy[valid], pp[valid]
    means = [float(yy[pp[:, j] > 0].mean()) if int((pp[:, j] > 0).sum()) >= 20 else None for j in range(5)]
    mse = np.mean((yy[:, None] - pp) ** 2, axis=0) if len(yy) >= 20 else None
    pairs = ((4, 3), (3, 1), (4, 1), (4, 0), (3, 0))
    result = {key: (float(1 - mse[a] / mse[b]) if mse is not None and mse[b] > 0 else None)
              for key, (a, b) in zip(QUANTITIES[:5], pairs)}
    result.update(dict(zip(QUANTITIES[5:7], (means[4], means[3]))))
    for key, other in zip(QUANTITIES[7:9], (3, 1)):
        result[key] = means[4] - means[other] if means[4] is not None and means[other] is not None else None
    result[QUANTITIES[9]] = means[4] - float(yy.mean()) if means[4] is not None and len(yy) >= 20 else None
    return result


def bootstrap(y, scores):
    n = len(y)
    if n < 40:
        raise ValueError('At least40 supplied signal positions for block method')
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 40 + 1, size=(500, (n + 39) // 40))
    indices = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, scores, np.arange(n))
    records = [quantities(y, scores, row) for row in indices]
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        summary[name] = {'value': value, 'valid_replicates': len(good),
                         'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if value is not None and len(good) >= 400 else None,
                         'status': 'AVAILABLE' if value is not None and len(good) >= 400 else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500, 'seed': 13, 'refitted_models': 0}


def episodes(scores, y):
    entry = None
    records = []
    for i, value in enumerate(scores.to_numpy(float)):
        if entry is not None:
            if i - entry >= 4:
                entry = None
        elif np.isfinite(value) and value > 0:
            entry = i
            records.append({'signal_date': scores.index[i].isoformat(), 'position': i,
                            'prediction': float(value), 'proxy_return': float(y[i]) if np.isfinite(y[i]) else None})
    mature = [x['proxy_return'] for x in records if x['proxy_return'] is not None]
    return {'accepted': len(records), 'mature': len(mature), 'mean_proxy': float(np.mean(mature)) if len(mature) >= 20 else None,
            'compound_proxy': float(np.prod(1 + np.asarray(mature)) - 1) if len(mature) >= 20 else None,
            'records': records, 'actual_closed_trades': None, 'account_return': None}


def analyze(features, labels, prior):
    scores, years = forecasts(features, labels, prior)
    axis, _, y, _ = validate(features, labels, prior)
    all_valid = np.isfinite(y) & np.isfinite(scores.to_numpy(float)).all(axis=1)
    quality = {name: {'n': int(all_valid.sum()), 'mse': float(np.mean((scores[name].to_numpy()[all_valid] - y[all_valid]) ** 2))}
               for name in MODELS}
    masks = {'all': np.ones(len(axis), bool), **{'year_' + str(y): axis.year == y for y in range(2020, 2027)},
             'rising': features.momentum20.to_numpy() > 0, 'falling': features.momentum20.to_numpy() < 0,
             'zero_momentum': features.momentum20.to_numpy() == 0,
             **{'phase_' + str(k): np.arange(len(axis)) % 5 == k for k in range(5)}}
    panels = {key: {m: group(y, scores[m].to_numpy(float), mask) for m in MODELS} for key, mask in masks.items()}
    greedy = {model: episodes(scores[model], y) for model in MODELS[1:]}
    result = {'signals': len(axis), 'fit_years': years, 'quality': quality, 'panels': panels,
              'bootstrap': bootstrap(y, scores.to_numpy(float)), 'nonoverlap_proxies': greedy,
              'new_annual_models': 2 * len(years), 'reused_prior_models': list(MODELS[:3]), 'new_accounts': 0,
              'scientific_judgment': 'NOT_PREJUDGED', 'future_test_count_gate': False}
    return scores, result
