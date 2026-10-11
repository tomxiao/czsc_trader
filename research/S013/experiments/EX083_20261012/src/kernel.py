"""EX083 fixed forecast reuse: opportunity clocks and profit attribution."""
import numpy as np
import pandas as pd

MODELS = ('training_mean', 'confirmation_only', 'original14_joint', 'calendar_only', 'confirmation_calendar', 'original14_calendar')
CLOCKS = ('greedy', 'phase_0', 'phase_1', 'phase_2', 'phase_3', 'phase_4')
QUANTITIES = ('calendar_greedy_mean', 'calendar_greedy_minus_confirmation_greedy',
              'calendar_greedy_minus_blocked_positive', 'calendar_phase_0_mean', 'calendar_phase_1_mean',
              'calendar_phase_2_mean', 'calendar_phase_3_mean', 'calendar_phase_4_mean', 'calendar_worst_phase_mean')


def validate(scores, labels):
    axis = scores.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique ordered naive midnight signal dates')
    if tuple(scores.columns) != MODELS or not labels.index.equals(axis):
        raise ValueError('Exact six authenticated forecast columns and shared axis')
    p, y = scores.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if np.isinf(p).any() or np.isinf(y).any() or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError('Finite or missing predictions, paired truth/maturity missingness')
    if (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any():
        raise ValueError('Future truth maturity strictly after signal T')
    available = np.isfinite(p)
    if not (available == available[:, :1]).all() or available[axis.year == 2020].any():
        raise ValueError('Shared forecast support and unavailable2020')
    if len(axis) < 40 or np.any(y[np.isfinite(y)] <= -1):
        raise ValueError('At least40 positions and positive open price factors')
    return axis, p, y


def entries(prediction, clock):
    positive = np.isfinite(prediction) & (prediction > 0)
    selected = np.zeros(len(prediction), bool)
    if clock == 'greedy':
        entry = None
        for i, eligible in enumerate(positive):
            if entry is not None:
                if i - entry >= 4:
                    entry = None
            elif eligible:
                selected[i] = True
                entry = i
    elif clock in CLOCKS[1:]:
        selected = positive & (np.arange(len(prediction)) % 5 == int(clock[-1]))
    else:
        raise ValueError('Only prospective six clock controls')
    return selected


def attribution(y, selected, subset):
    ids = np.flatnonzero(selected & subset & np.isfinite(y))
    values = y[ids]
    winners = np.flatnonzero(values > 0)
    ranked = sorted(winners, key=lambda j: (-values[j], int(ids[j])))
    k = (len(winners) + 9) // 10
    best = ranked[:1]
    top = ranked[:k]
    positive_sum = float(values[values > 0].sum())
    compound = lambda v: float(np.prod(1 + v) - 1) if len(v) else None
    without = lambda positions: values[~np.isin(np.arange(len(values)), positions)]
    return {'mature': len(ids), 'mean_net_proxy': float(values.mean()) if len(ids) >= 20 else None,
            'mean_status': 'AVAILABLE' if len(ids) >= 20 else 'INSUFFICIENT_DATA',
            'compound_net_proxy': compound(values), 'positive_count': len(winners),
            'top_positive_count': k, 'top_positive_contribution': float(values[top].sum()) / positive_sum if positive_sum > 0 else None,
            'best_positive_contribution': float(values[best].sum()) / positive_sum if positive_sum > 0 else None,
            'compound_without_best_positive': compound(without(best)) if best else None,
            'compound_without_top10pct_positive': compound(without(top)) if top else None,
            'best_positive_positions': [int(ids[j]) for j in best], 'top_positive_positions': [int(ids[j]) for j in top],
            'actual_closed_trades': None, 'continuous_account_return': None}


def schedule(axis, p, y, clock):
    mask = entries(p, clock)
    positive = np.isfinite(p) & (p > 0)
    available_truth = np.isfinite(y)
    blocked = positive & ~mask
    accepted_mean = float(y[mask & available_truth].mean()) if (mask & available_truth).sum() >= 20 else None
    blocked_mean = float(y[blocked & available_truth].mean()) if (blocked & available_truth).sum() >= 20 else None
    panels = {'all': attribution(y, mask, np.ones(len(y), bool)),
              **{'year_' + str(year): attribution(y, mask, axis.year == year) for year in range(2020, 2027)}}
    return {'accepted': int(mask.sum()), 'missing_truth_accepted': int((mask & ~available_truth).sum()),
            'positive_forecasts': int(positive.sum()), 'blocked_positive_forecasts': int(blocked.sum()),
            'accepted_mean': accepted_mean, 'blocked_positive_mean': blocked_mean,
            'mature_blocked_positive': int((blocked & available_truth).sum()), 'panels': panels,
            'records': [{'signal_date': axis[i].isoformat(), 'position': int(i), 'prediction': float(p[i]),
                         'proxy_return': float(y[i]) if available_truth[i] else None} for i in np.flatnonzero(mask)]}


def means(y, masks, indices):
    yy = y[indices]
    values = {}
    for name, mask in masks.items():
        chosen = mask[indices] & np.isfinite(yy)
        values[name] = float(yy[chosen].mean()) if chosen.sum() >= 20 else None
    return values


def quantities(y, masks, indices):
    m = means(y, masks, indices)
    out = {QUANTITIES[0]: m['greedy']}
    for key, other in ((QUANTITIES[1], 'confirmation_greedy'), (QUANTITIES[2], 'blocked_positive')):
        out[key] = m['greedy'] - m[other] if m['greedy'] is not None and m[other] is not None else None
    for phase in range(5):
        out[QUANTITIES[3 + phase]] = m['phase_' + str(phase)]
    vals = [m['phase_' + str(k)] for k in range(5)]
    out[QUANTITIES[-1]] = min(vals) if all(v is not None for v in vals) else None
    return out


def bootstrap(y, p):
    masks = {clock: entries(p[:, 3], clock) for clock in CLOCKS}
    masks['confirmation_greedy'] = entries(p[:, 1], 'greedy')
    masks['blocked_positive'] = (np.isfinite(p[:, 3]) & (p[:, 3] > 0)) & ~masks['greedy']
    n = len(y)
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    samples = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, masks, np.arange(n))
    records = [quantities(y, masks, ids) for ids in samples]
    summary = {}
    for name, value in original.items():
        good = [r[name] for r in records if r[name] is not None]
        ok = value is not None and len(good) >= 400
        summary[name] = {'value': value, 'valid_replicates': len(good),
                         'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                         'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500, 'seed': 13,
            'refitted_models': 0, 'replayed_policies': 0, 'fixed_forecasts_and_entry_masks': True}


def analyze(scores, labels, previous):
    axis, p, y = validate(scores, labels)
    schedules = {model: {clock: schedule(axis, p[:, j], y, clock) for clock in CLOCKS} for j, model in enumerate(MODELS)}
    for model in MODELS[1:]:
        prior, current = previous['nonoverlap_proxies'][model], schedules[model]['greedy']
        if prior['records'] != current['records'] or prior['accepted'] != current['accepted'] or prior['mature'] != current['panels']['all']['mature']:
            raise ValueError('Original greedy must exactly reuse prior episode identities')
        np.testing.assert_allclose(prior['compound_proxy'], current['panels']['all']['compound_net_proxy'], atol=2e-14)
    return {'signals': len(axis), 'schedules': schedules, 'bootstrap': bootstrap(y, p),
            'new_annual_models': 0, 'new_accounts': 0, 'provider_calls': 0, 'forecast_reuse': 'EXACT',
            'schedule_count': len(MODELS) * len(CLOCKS), 'original_greedy_reproduced': True,
            'scientific_judgment': 'NOT_PREJUDGED', 'objective_achieved': False}
