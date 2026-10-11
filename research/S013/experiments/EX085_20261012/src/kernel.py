"""EX085 fixed causal20matured-h4 opportunity state vs matched original14."""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
STATES = ('mature_h4_win_fraction20', 'mature_h4_mean_net20')
MODELS = ('training_mean', 'original14_return', 'original14_state_return', 'original14_probability_payoff', 'original14_state_probability_payoff')
PROBABILITIES = ('training_probability', 'original14_probability', 'original14_state_probability')
QUANTITIES = ('state_brier_improvement_vs_original14', 'state_logloss_improvement_vs_original14',
              'state_return_mse_improvement_vs_original14', 'state_payoff_mse_improvement_vs_original14_payoff',
              'state_return_positive_mean', 'state_payoff_positive_mean',
              'state_return_mean_minus_original14', 'state_payoff_mean_minus_original14_payoff',
              'state_brier_improvement_vs_prior', 'state_logloss_improvement_vs_prior')


def validate(features, labels):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Ordered unique naive midnight dates')
    if tuple(features.columns) != FEATURES or not labels.index.equals(axis):
        raise ValueError('Exact original14 and shared axis')
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if np.isinf(x).any() or np.isinf(y).any() or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError('Finite or missing numbers with paired truth/maturity')
    if (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any():
        raise ValueError('Future label maturity strictly after own signal')
    return axis, x, y, ends


def states(axis, y, ends):
    result = np.full((len(axis), 2), np.nan)
    traces = []
    for i, date in enumerate(axis):
        eligible = np.flatnonzero(np.isfinite(y) & (ends <= date).to_numpy())
        window = eligible[-20:] if len(eligible) >= 20 else np.array([], dtype=int)
        if len(window):
            result[i] = [float((y[window] > 0).mean()), float(y[window].mean())]
        traces.append({'signal_date': date.isoformat(), 'eligible_mature': len(eligible), 'available': len(window) == 20,
                       'positions': [int(j) for j in window],
                       'max_maturity': ends.iloc[window].max().isoformat() if len(window) else None})
    return pd.DataFrame(result, index=axis, columns=STATES), traces


def rank(train, values):
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side='left') + np.searchsorted(ordered, values, side='right')) / (2 * len(train)) - .5


def ridge(train, target, test):
    mx, my = train.mean(axis=0), float(target.mean())
    z = train - mx
    slopes = np.linalg.solve(z.T @ z + 10 * np.eye(train.shape[1]), z.T @ (target - my))
    intercept = float(my - mx @ slopes)
    return intercept + test @ slopes, [intercept, *slopes.tolist()]


def forecasts(features, labels, logit):
    axis, x, y, ends = validate(features, labels)
    state, traces = states(axis, y, ends)
    all_x = np.column_stack((x, state.to_numpy()))
    complete = np.isfinite(all_x).all(axis=1)
    nets = pd.DataFrame(np.nan, index=axis, columns=MODELS)
    probs = pd.DataFrame(np.nan, index=axis, columns=PROBABILITIES)
    fits = {}
    for year in sorted(set(axis.year[axis.year >= 2021])):
        first = axis[axis.year == year][0]
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year) & (ends < first).to_numpy()
        test = complete & (axis.year == year)
        win, loss = train & (y > 0), train & (y <= 0)
        n, nwin, nloss = int(train.sum()), int(win.sum()), int(loss.sum())
        available = n >= 40 and nwin >= 20 and nloss >= 20
        row = {'first_signal': first.isoformat(), 'train_n': n, 'win_n': nwin, 'nonpositive_n': nloss,
               'max_maturity': ends[train].max().isoformat() if n else None, 'train_dates': [t.isoformat() for t in axis[train]],
               'feature_test_n': int(test.sum()), 'available': available, 'future_test_count_gate': False,
               'payoffs': None, 'return_models': {}, 'probability_models': {}}
        if available:
            fraction, gain, negative = nwin / n, float(y[win].mean()), float(y[loss].mean())
            mean = float(y[train].mean())
            np.testing.assert_allclose(fraction * gain + (1 - fraction) * negative, mean, atol=2e-14)
            row['payoffs'] = {'win_fraction': fraction, 'mean_positive': gain, 'mean_nonpositive': negative,
                              'break_even_probability': -negative / (gain - negative), 'unconditional_net_mean': mean}
            nets.loc[test, 'training_mean'] = mean
            probs.loc[test, 'training_probability'] = fraction
            tr = np.column_stack([rank(all_x[train, j], all_x[train, j]) for j in range(16)])
            te = np.column_stack([rank(all_x[train, j], all_x[test, j]) for j in range(16)])
            for dimensions, net_name, prob_name, payoff_name in ((14, MODELS[1], PROBABILITIES[1], MODELS[3]), (16, MODELS[2], PROBABILITIES[2], MODELS[4])):
                r, coefficients = ridge(tr[:, :dimensions], y[train], te[:, :dimensions])
                p, proof = logit.fit(tr[:, :dimensions], (y[train] > 0).astype(float), te[:, :dimensions])
                nets.loc[test, net_name] = r
                probs.loc[test, prob_name] = p
                nets.loc[test, payoff_name] = p * gain + (1 - p) * negative
                row['return_models'][net_name] = coefficients
                row['probability_models'][prob_name] = proof
        fits[str(year)] = row
    return state, traces, probs, nets, fits


def selected(y, prediction, mask):
    eligible = mask & np.isfinite(prediction)
    positive = eligible & (prediction > 0)
    mature = positive & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(eligible.sum()), 'positive_forecasts': int(positive.sum()), 'mature_positive': n,
            'missing_positive_truth': int((positive & ~np.isfinite(y)).sum()),
            'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y, probs, nets, ids):
    yy, p, n = y[ids], probs[ids], nets[ids]
    good = np.isfinite(yy) & np.isfinite(p).all(axis=1) & np.isfinite(n).all(axis=1)
    yy, p, n = yy[good], p[good], n[good]
    if len(yy) < 20:
        return dict.fromkeys(QUANTITIES)
    b = (yy > 0).astype(float)
    brier = np.mean((p - b[:, None]) ** 2, axis=0)
    loss = np.mean(-b[:, None] * np.log(p) - (1 - b[:, None]) * np.log1p(-p), axis=0)
    mse = np.mean((n - yy[:, None]) ** 2, axis=0)
    means = [float(yy[n[:, j] > 0].mean()) if (n[:, j] > 0).sum() >= 20 else None for j in range(5)]
    pairs = ((brier, 2, 1), (loss, 2, 1), (mse, 2, 1), (mse, 4, 3))
    out = {key: float(1 - values[a] / values[b]) if values[b] > 0 else None for key, (values, a, b) in zip(QUANTITIES[:4], pairs)}
    out.update({QUANTITIES[4]: means[2], QUANTITIES[5]: means[4]})
    for key, new, old in ((QUANTITIES[6], 2, 1), (QUANTITIES[7], 4, 3)):
        out[key] = means[new] - means[old] if means[new] is not None and means[old] is not None else None
    out[QUANTITIES[8]] = float(1 - brier[2] / brier[0]) if brier[0] > 0 else None
    out[QUANTITIES[9]] = float(1 - loss[2] / loss[0]) if loss[0] > 0 else None
    return out


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


def analyze(features, labels, logit, clock):
    state, traces, probs, nets, fits = forecasts(features, labels, logit)
    axis, _, y, _ = validate(features, labels)
    common = np.isfinite(y) & np.isfinite(probs.to_numpy()).all(axis=1) & np.isfinite(nets.to_numpy()).all(axis=1)
    masks = {'all': np.ones(len(y), bool), **{'year_' + str(t): axis.year == t for t in range(2020, 2027)},
             **{'phase_' + str(k): np.arange(len(y)) % 5 == k for k in range(5)}}
    panels = {name: {m: selected(y, nets[m].to_numpy(), mask) for m in MODELS} for name, mask in masks.items()}
    quality = {}
    for name, mask in masks.items():
        ix = common & mask
        b = (y[ix] > 0).astype(float)
        quality[name] = {}
        for m in PROBABILITIES:
            p = probs[m].to_numpy()[ix]
            quality[name][m] = {'n': len(p), 'brier': float(np.mean((p - b) ** 2)) if len(p) >= 20 else None,
                'logloss': float(np.mean(-b*np.log(p)-(1-b)*np.log1p(-p))) if len(p) >= 20 else None,
                'mean_probability': float(p.mean()) if len(p) >= 20 else None,
                'observed_positive_fraction': float(b.mean()) if len(p) >= 20 else None}
    schedules = {m: {c: clock.schedule(axis, nets[m].to_numpy(), y, c) for c in clock.CLOCKS} for m in MODELS}
    result = {'signals': len(y), 'mature_common': int(common.sum()), 'state_traces': traces, 'fit_years': fits,
              'panels': panels, 'probability_quality': quality, 'schedules': schedules,
              'bootstrap': bootstrap(y, probs.to_numpy(), nets.to_numpy()),
              'new_annual_models': 4*sum(r['available'] for r in fits.values()), 'new_accounts': 0, 'provider_calls': 0,
              'matched_original14_refit': True, 'objective_achieved': False, 'scientific_judgment': 'NOT_PREJUDGED'}
    return state, probs, nets, result
