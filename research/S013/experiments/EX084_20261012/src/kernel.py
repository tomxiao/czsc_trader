"""EX084 causal net-profit probability and fixed training payoff decomposition."""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'confirmation_probability_payoff', 'original14_probability_payoff')
PROBABILITIES = ('training_probability', 'confirmation_logit', 'original14_logit')
QUANTITIES = ('confirmation_brier_improvement_vs_prior', 'original14_brier_improvement_vs_prior',
              'confirmation_logloss_improvement_vs_prior', 'original14_logloss_improvement_vs_prior',
              'confirmation_payoff_positive_mean', 'original14_payoff_positive_mean',
              'confirmation_payoff_mean_minus_original_confirmation', 'original14_payoff_mean_minus_original14',
              'confirmation_payoff_mse_improvement_vs_original_confirmation', 'original14_payoff_mse_improvement_vs_original14')


def validate(features, labels, prior):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Ordered unique naive midnight dates')
    if tuple(features.columns) != FEATURES or not labels.index.equals(axis) or not prior.index.equals(axis) or tuple(prior.columns) != MODELS[:3]:
        raise ValueError('Exact original14, old three scores and shared axis')
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if np.isinf(x).any() or np.isinf(y).any() or np.isinf(prior.to_numpy()).any() or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError('Finite or missing numerical inputs with paired maturity')
    if (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any() or prior.loc[axis.year < 2021].notna().any().any():
        raise ValueError('Future truth maturity and no prospective2020 predictions')
    return axis, x, y, ends


def rank(train, values):
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side='left') + np.searchsorted(ordered, values, side='right')) / (2 * len(train)) - .5


def fit(train, binary, test):
    if train.ndim != 2 or not np.isfinite(train).all() or not np.isfinite(test).all() or not np.isin(binary, [0., 1.]).all() or len(binary) != len(train) or len(np.unique(binary)) != 2:
        raise ValueError('Finite logistic training and both binary classes required')
    a = np.column_stack((np.ones(len(train)), train))
    v = np.column_stack((np.ones(len(test)), test))
    beta = np.zeros(a.shape[1])
    fraction = float(binary.mean())
    beta[0] = np.log(fraction / (1 - fraction))
    penalty = np.r_[0., np.full(train.shape[1], 10.)]
    loss = lambda b: float((np.logaddexp(0., a @ b) - binary * (a @ b)).sum() + .5 * np.sum(penalty * b * b))
    for iteration in range(100):
        z = a @ beta
        p = np.exp(-np.logaddexp(0., -z))
        gradient = a.T @ (p - binary) + penalty * beta
        norm = float(np.max(np.abs(gradient)))
        if norm <= 1e-10:
            prediction = np.exp(-np.logaddexp(0., -(v @ beta)))
            if not ((prediction > 0) & (prediction < 1)).all():
                raise ValueError('Strict finite interior forecast probabilities')
            return prediction, {'coefficients': beta.tolist(), 'iterations': iteration, 'max_abs_gradient': norm, 'objective': loss(beta)}
        hessian = a.T @ ((p * (1 - p))[:, None] * a) + np.diag(penalty)
        step = np.linalg.solve(hessian, gradient)
        rate = 1.
        old = loss(beta)
        for _ in range(40):
            candidate = beta - rate * step
            if loss(candidate) <= old - 1e-4 * rate * float(gradient @ step) + 1e-12:
                beta = candidate
                break
            rate *= .5
        else:
            raise ValueError('Logistic line search did not converge')
    raise ValueError('Logistic gradient not converged within100iterations')


def forecasts(features, labels, prior):
    axis, x, y, ends = validate(features, labels, prior)
    complete = np.isfinite(x).all(axis=1)
    nets = prior.copy()
    for m in MODELS[3:]:
        nets[m] = np.nan
    probs = pd.DataFrame(np.nan, index=axis, columns=PROBABILITIES)
    fits = {}
    for year in sorted(set(axis.year[axis.year >= 2021])):
        first = axis[axis.year == year][0]
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year) & (ends < first).to_numpy()
        test = complete & (axis.year == year)
        win = train & (y > 0)
        lose = train & (y <= 0)
        n, nwin, nlose = int(train.sum()), int(win.sum()), int(lose.sum())
        available = n >= 40 and nwin >= 20 and nlose >= 20
        row = {'first_signal': first.isoformat(), 'train_n': n, 'win_n': nwin, 'nonpositive_n': nlose,
               'max_maturity': ends[train].max().isoformat() if n else None,
               'train_dates': [t.isoformat() for t in axis[train]], 'feature_test_n': int(test.sum()),
               'available': available, 'future_test_count_gate': False, 'payoffs': None, 'models': {}}
        if available:
            fraction, gain, nonpositive = nwin / n, float(y[win].mean()), float(y[lose].mean())
            threshold = -nonpositive / (gain - nonpositive)
            expected_mean = fraction * gain + (1 - fraction) * nonpositive
            np.testing.assert_allclose(prior.loc[test, 'training_mean'], expected_mean, atol=2e-14, rtol=2e-12)
            row['payoffs'] = {'win_fraction': fraction, 'mean_positive': gain, 'mean_nonpositive': nonpositive,
                              'break_even_probability': threshold, 'unconditional_net_mean': expected_mean}
            probs.loc[test, 'training_probability'] = fraction
            for model, probability, columns in zip(MODELS[3:], PROBABILITIES[1:], ((8,), tuple(range(14)))):
                tx = np.column_stack([rank(x[train, j], x[train, j]) for j in columns])
                vx = np.column_stack([rank(x[train, j], x[test, j]) for j in columns])
                prediction, proof = fit(tx, (y[train] > 0).astype(float), vx)
                probs.loc[test, probability] = prediction
                nets.loc[test, model] = prediction * gain + (1 - prediction) * nonpositive
                row['models'][probability] = proof
        fits[str(year)] = row
    return probs, nets, fits


def selected(y, prediction, mask):
    forecast = mask & np.isfinite(prediction)
    positive = forecast & (prediction > 0)
    mature = positive & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(forecast.sum()), 'positive_forecasts': int(positive.sum()), 'mature_positive': n,
            'missing_positive_truth': int((positive & ~np.isfinite(y)).sum()),
            'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y, p, nets, ids):
    yy, pp, nn = y[ids], p[ids], nets[ids]
    valid = np.isfinite(yy) & np.isfinite(pp).all(axis=1) & np.isfinite(nn).all(axis=1)
    yy, pp, nn = yy[valid], pp[valid], nn[valid]
    if len(yy) < 20:
        return dict.fromkeys(QUANTITIES)
    b = (yy > 0).astype(float)
    brier = np.mean((pp - b[:, None]) ** 2, axis=0)
    logloss = np.mean(-b[:, None] * np.log(pp) - (1 - b[:, None]) * np.log1p(-pp), axis=0)
    mse = np.mean((nn - yy[:, None]) ** 2, axis=0)
    means = [float(yy[nn[:, j] > 0].mean()) if (nn[:, j] > 0).sum() >= 20 else None for j in range(5)]
    result = {key: float(1 - brier[a] / brier[0]) if brier[0] > 0 else None for key, a in zip(QUANTITIES[:2], (1, 2))}
    result.update({key: float(1 - logloss[a] / logloss[0]) if logloss[0] > 0 else None for key, a in zip(QUANTITIES[2:4], (1, 2))})
    result.update(dict(zip(QUANTITIES[4:6], means[3:])))
    for key, new, old in ((QUANTITIES[6], 3, 1), (QUANTITIES[7], 4, 2)):
        result[key] = means[new] - means[old] if means[new] is not None and means[old] is not None else None
    result.update({key: float(1 - mse[a] / mse[b]) if mse[b] > 0 else None for key, a, b in ((QUANTITIES[8], 3, 1), (QUANTITIES[9], 4, 2))})
    return result


def bootstrap(y, probs, nets):
    n = len(y)
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    ids = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, probs, nets, np.arange(n))
    records = [quantities(y, probs, nets, row) for row in ids]
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        ok = value is not None and len(good) >= 400
        summary[name] = {'value': value, 'valid_replicates': len(good), 'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                         'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500, 'seed': 13, 'refitted_models': 0}


def analyze(features, labels, prior, clock):
    probs, nets, fits = forecasts(features, labels, prior)
    axis, _, y, _ = validate(features, labels, prior)
    common = np.isfinite(y) & np.isfinite(probs.to_numpy()).all(axis=1) & np.isfinite(nets.to_numpy()).all(axis=1)
    masks = {'all': np.ones(len(y), bool), **{'year_' + str(year): axis.year == year for year in range(2020, 2027)},
             **{'phase_' + str(k): np.arange(len(y)) % 5 == k for k in range(5)}}
    panels = {name: {m: selected(y, nets[m].to_numpy(float), mask) for m in MODELS} for name, mask in masks.items()}
    probability_quality = {}
    for name, mask in masks.items():
        valid = common & mask
        b = (y[valid] > 0).astype(float)
        probability_quality[name] = {}
        for m in PROBABILITIES:
            p = probs[m].to_numpy()[valid]
            probability_quality[name][m] = {'n': len(p), 'brier': float(np.mean((p - b) ** 2)) if len(p) >= 20 else None,
                'logloss': float(np.mean(-b * np.log(p) - (1 - b) * np.log1p(-p))) if len(p) >= 20 else None,
                'mean_probability': float(np.mean(p)) if len(p) >= 20 else None,
                'observed_positive_fraction': float(np.mean(b)) if len(p) >= 20 else None}
    schedules = {m: {c: clock.schedule(axis, nets[m].to_numpy(), y, c) for c in clock.CLOCKS} for m in MODELS}
    result = {'signals': len(y), 'mature_common': int(common.sum()), 'fit_years': fits, 'panels': panels,
              'probability_quality': probability_quality, 'schedules': schedules, 'bootstrap': bootstrap(y, probs.to_numpy(), nets.to_numpy()),
              'new_annual_models': 2 * sum(r['available'] for r in fits.values()), 'new_accounts': 0, 'provider_calls': 0,
              'original_return_models_reused': list(MODELS[:3]), 'objective_achieved': False, 'scientific_judgment': 'NOT_PREJUDGED'}
    return probs, nets, result
