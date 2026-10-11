"""EX086 fixed conditional payoff means; EX084 probabilities remain frozen."""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'confirmation_probability_payoff',
          'original14_probability_payoff', 'confirmation_conditional_payoff', 'original14_conditional_payoff')
PROBABILITIES = ('training_probability', 'confirmation_logit', 'original14_logit')
MAGNITUDES = ('confirmation_gain', 'confirmation_loss', 'original14_gain', 'original14_loss')
QUANTITIES = tuple(f'{prefix}_{suffix}' for prefix in ('confirmation', 'original14')
                   for suffix in ('gain_mse_improvement', 'loss_mse_improvement', 'net_mse_improvement_vs_fixed',
                                  'conditional_positive_mean', 'mean_difference_vs_fixed'))


def validate(features, labels, probabilities, prior):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Ordered unique naive midnight dates')
    if tuple(features.columns) != FEATURES or tuple(probabilities.columns) != PROBABILITIES or tuple(prior.columns) != MODELS[:5] or not all(f.index.equals(axis) for f in (labels, probabilities, prior)):
        raise ValueError('Exact original14 and EX084 probabilities/net controls with shared axis')
    x, y, p, n = features.to_numpy(float), labels.return_4.to_numpy(float), probabilities.to_numpy(float), prior.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if any(np.isinf(a).any() for a in (x, y, p, n)) or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError('Finite or missing inputs with paired label maturity')
    if (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any() or probabilities.loc[axis.year < 2021].notna().any().any() or prior.loc[axis.year < 2021].notna().any().any():
        raise ValueError('Future label maturity and no 2020 forecast')
    finite = p[np.isfinite(p)]
    if ((finite <= 0) | (finite >= 1)).any():
        raise ValueError('Strict probabilities, no boundary clipping')
    return axis, x, y, ends


def rank(train, values):
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side='left') + np.searchsorted(ordered, values, side='right')) / (2 * len(train)) - .5


def fit(train, magnitude, test):
    """Minimize sum(eta + m exp(-eta)) + 5||slope||^2; zero m allowed."""
    if train.ndim != 2 or test.ndim != 2 or train.shape[1] != test.shape[1] or len(train) != len(magnitude) or not len(train) or not np.isfinite(train).all() or not np.isfinite(test).all() or not np.isfinite(magnitude).all() or (magnitude < 0).any() or magnitude.mean() <= 0:
        raise ValueError('Finite nonnegative magnitudes and strictly positive training mean required')
    a = np.column_stack((np.ones(len(train)), train))
    v = np.column_stack((np.ones(len(test)), test))
    beta = np.r_[np.log(magnitude.mean()), np.zeros(train.shape[1])]
    penalty = np.r_[0., np.full(train.shape[1], 10.)]

    def objective(b):
        z = a @ b
        with np.errstate(over='raise', invalid='raise'):
            return float(np.sum(z + magnitude * np.exp(-z)) + .5 * np.sum(penalty * b**2))

    for iteration in range(100):
        ratio = magnitude * np.exp(-(a @ beta))
        gradient = a.T @ (1 - ratio) + penalty * beta
        norm = float(np.max(np.abs(gradient)))
        if norm <= 1e-10:
            prediction = np.exp(v @ beta)
            if not np.isfinite(prediction).all() or (prediction <= 0).any():
                raise ValueError('Nonfinite positive mean; no clipping or fallback')
            return prediction, {'coefficients': beta.tolist(), 'iterations': iteration,
                                'max_abs_gradient': norm, 'objective': objective(beta)}
        hessian = a.T @ (a * ratio[:, None]) + np.diag(penalty)
        step = np.linalg.solve(hessian, gradient)
        old, rate = objective(beta), 1.
        for _ in range(40):
            candidate = beta - rate * step
            if objective(candidate) <= old - 1e-4 * rate * float(gradient @ step) + 1e-12:
                beta = candidate
                break
            rate *= .5
        else:
            raise ValueError('Conditional mean line search failed')
    raise ValueError('Conditional mean convergence failed')


def forecasts(features, labels, probabilities, prior, prior_statistics):
    axis, x, y, ends = validate(features, labels, probabilities, prior)
    complete = np.isfinite(x).all(axis=1)
    nets = prior.reindex(columns=MODELS).copy()
    magnitudes = pd.DataFrame(np.nan, index=axis, columns=MAGNITUDES)
    constants = pd.DataFrame(np.nan, index=axis, columns=('gain', 'loss'))
    years = {}
    for year in sorted(set(axis.year[axis.year >= 2021])):
        first = axis[axis.year == year][0]
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year) & (ends < first).to_numpy()
        test = complete & (axis.year == year)
        wins, losses = train & (y > 0), train & (y <= 0)
        n, nw, nl = int(train.sum()), int(wins.sum()), int(losses.sum())
        available = n >= 40 and nw >= 20 and nl >= 20
        previous = prior_statistics['fit_years'][str(year)]
        dates = [t.isoformat() for t in axis[train]]
        if previous['train_dates'] != dates or previous['train_n'] != n or previous['available'] != available:
            raise ValueError('EX084 matched training differs; do not silently refit control')
        row = {'first_signal': first.isoformat(), 'train_n': n, 'win_n': nw, 'nonpositive_n': nl,
               'zero_net_n': int((train & (y == 0)).sum()), 'train_dates': dates, 'max_maturity': ends[train].max().isoformat() if n else None,
               'feature_test_n': int(test.sum()), 'available': available, 'future_test_count_gate': False, 'models': {}, 'payoffs': None}
        if available:
            g, loss = float(y[wins].mean()), float(-y[losses].mean())
            row['payoffs'] = {'gain': g, 'loss': loss}
            if loss <= 0:
                raise ValueError('Zero mean loss magnitudes; no fallback')
            constants.loc[test] = [g, loss]
            tr = np.column_stack([rank(x[train, j], x[train, j]) for j in range(14)])
            te = np.column_stack([rank(x[train, j], x[test, j]) for j in range(14)])
            for family, columns, p_name, fixed, conditional in ((0, [8], PROBABILITIES[1], MODELS[3], MODELS[5]),
                                                               (1, list(range(14)), PROBABILITIES[2], MODELS[4], MODELS[6])):
                p = probabilities.loc[test, p_name].to_numpy()
                np.testing.assert_allclose(prior.loc[test, fixed], p * g - (1 - p) * loss, atol=3e-13, rtol=2e-11)
                predicted = []
                for offset, mask, target in ((0, y[train] > 0, y[train]), (1, y[train] <= 0, -y[train])):
                    m, proof = fit(tr[mask][:, columns], target[mask], te[:, columns])
                    name = MAGNITUDES[2 * family + offset]
                    magnitudes.loc[test, name] = m
                    row['models'][name] = proof
                    predicted.append(m)
                nets.loc[test, conditional] = p * predicted[0] - (1 - p) * predicted[1]
        years[str(year)] = row
    return magnitudes, constants, nets, years


def selected(y, prediction, mask):
    eligible = mask & np.isfinite(prediction)
    positive = eligible & (prediction > 0)
    mature = positive & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(eligible.sum()), 'positive_forecasts': int(positive.sum()), 'mature_positive': n,
            'missing_positive_truth': int((positive & ~np.isfinite(y)).sum()), 'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y, mag, constants, nets, ids):
    yy, m, c, n = y[ids], mag[ids], constants[ids], nets[ids]
    good = np.isfinite(yy) & np.isfinite(m).all(axis=1) & np.isfinite(c).all(axis=1) & np.isfinite(n).all(axis=1)
    yy, m, c, n = yy[good], m[good], c[good], n[good]
    if len(yy) < 20:
        return dict.fromkeys(QUANTITIES)
    out = {}
    for family in range(2):
        keys = QUANTITIES[5 * family:5 * family + 5]
        for offset, mask in ((0, yy > 0), (1, yy <= 0)):
            truth = np.abs(yy[mask])
            baseline = float(np.mean((c[mask, offset] - truth)**2)) if len(truth) >= 20 else None
            out[keys[offset]] = float(1 - np.mean((m[mask, 2 * family + offset] - truth)**2) / baseline) if baseline is not None and baseline > 0 else None
        old, new = 3 + family, 5 + family
        baseline = float(np.mean((n[:, old] - yy)**2))
        out[keys[2]] = float(1 - np.mean((n[:, new] - yy)**2) / baseline) if baseline > 0 else None
        means = [float(yy[n[:, j] > 0].mean()) if (n[:, j] > 0).sum() >= 20 else None for j in (new, old)]
        out[keys[3]] = means[0]
        out[keys[4]] = means[0] - means[1] if all(v is not None for v in means) else None
    return out


def bootstrap(y, mag, constants, nets):
    n, rng = len(y), np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    ids = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, mag, constants, nets, np.arange(n))
    records = [quantities(y, mag, constants, nets, row) for row in ids]
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        ok = value is not None and len(good) >= 400
        summary[name] = {'value': value, 'valid_replicates': len(good),
                         'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                         'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500, 'seed': 13, 'refitted_models': 0}


def analyze(features, labels, probabilities, prior, prior_statistics, clock):
    mag, constants, nets, years = forecasts(features, labels, probabilities, prior, prior_statistics)
    axis, _, y, _ = validate(features, labels, probabilities, prior)
    common = np.isfinite(y) & np.isfinite(nets.to_numpy()).all(axis=1)
    masks = {'all': np.ones(len(y), bool), **{'year_' + str(t): axis.year == t for t in range(2020, 2027)},
             **{'phase_' + str(k): np.arange(len(y)) % 5 == k for k in range(5)}}
    panels = {key: {m: selected(y, nets[m].to_numpy(), mask) for m in MODELS} for key, mask in masks.items()}
    schedules = {m: {c: clock.schedule(axis, nets[m].to_numpy(), y, c) for c in clock.CLOCKS} for m in MODELS}
    quality = {key: quantities(y, mag.to_numpy(), constants.to_numpy(), nets.to_numpy(), np.flatnonzero(mask)) for key, mask in masks.items()}
    result = {'signals': len(y), 'mature_common': int(common.sum()), 'fit_years': years, 'panels': panels,
              'conditional_quality': quality, 'schedules': schedules,
              'bootstrap': bootstrap(y, mag.to_numpy(), constants.to_numpy(), nets.to_numpy()),
              'new_annual_models': 4 * sum(r['available'] for r in years.values()), 'reused_probability_models': 12,
              'new_accounts': 0, 'provider_calls': 0, 'controls': 'EX084_EXACT', 'objective_achieved': False}
    return mag, constants, nets, result
