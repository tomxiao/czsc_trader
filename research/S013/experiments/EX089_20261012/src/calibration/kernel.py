"""EX089 fixed causal calibration of already-issued h4 forecasts; no new fit.

calibrated = rawmean + (current forecast - past20 forecast mean).
This is a new expression of existing information, not independent market data.
All clocks and bootstrap selections remain price proxies, not actual accounts.
"""
import numpy as np
import pandas as pd

INPUTS = ('confirmation_110', 'original14_110')
FAMILIES = ('confirmation', 'original14')
KINDS = ('historical', 'matched', 'rawmean', 'calibrated')
MODELS = tuple(f'{family}_{kind}' for family in FAMILIES for kind in KINDS)
SUFFIXES = ('mse_improvement_vs_matched', 'mse_improvement_vs_rawmean',
            'calibrated_positive_mean', 'calibrated_positive_minus_matched',
            'calibrated_positive_minus_rawmean', 'calibrated_greedy_minus_matched_greedy')
QUANTITIES = tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)
STATE_SUFFIXES = ('issued_net_forecast', 'eligible_mature_count', 'available',
                 'past20_truth_mean', 'past20_forecast_mean', 'past20_residual_mean',
                 'calibrated_net_forecast')


def validate(scores, labels):
    axis = scores.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique ordered naive midnight signal dates')
    if tuple(scores.columns) != INPUTS or not labels.index.equals(axis) or len(axis) < 40:
        raise ValueError('Exact two frozen forecast columns and shared axis of at least40')
    if labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns):
        raise ValueError('Paired return_4 and label_end_return_4 required')
    p, y = scores.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError('Naive midnight label maturity dates')
    finite = np.isfinite(y)
    if np.isinf(p).any() or np.isinf(y).any() or not np.array_equal(finite, ends.notna()):
        raise ValueError('Finite or missing forecasts and paired truth/maturity')
    if (y[finite] <= -1).any() or (ends[finite].to_numpy() <= axis[finite].to_numpy()).any() or np.isfinite(p[axis.year == 2020]).any():
        raise ValueError('Positive price factors, future maturity, unavailable2020 forecasts')
    return axis, p, y, ends


def decisions(scores, labels):
    axis, p, y, ends = validate(scores, labels)
    signals = pd.DataFrame(np.nan, index=axis, columns=MODELS)
    states = pd.DataFrame(index=axis)
    traces = []
    positions = np.arange(len(axis))
    for column, family in enumerate(FAMILIES):
        issued = p[:, column]
        counts = np.zeros(len(axis), int)
        available = np.zeros(len(axis), bool)
        truth_mean = np.full(len(axis), np.nan)
        forecast_mean = np.full(len(axis), np.nan)
        residual_mean = np.full(len(axis), np.nan)
        calibrated = np.full(len(axis), np.nan)
        for i, date in enumerate(axis):
            eligible = np.flatnonzero((positions < i) & np.isfinite(issued) & np.isfinite(y) & (ends <= date).to_numpy())
            counts[i] = len(eligible)
            window = eligible[-20:] if len(eligible) >= 20 else np.array([], dtype=int)
            available[i] = len(window) == 20 and np.isfinite(issued[i])
            if available[i]:
                truth_mean[i] = float(y[window].mean())
                forecast_mean[i] = float(issued[window].mean())
                residual_mean[i] = float((y[window] - issued[window]).mean())
                calibrated[i] = issued[i] + residual_mean[i]
            traces.append({'family': family, 'signal_date': date.isoformat(),
                           'eligible_mature_count': int(counts[i]), 'available': bool(available[i]),
                           'positions': [int(j) for j in window],
                           'max_maturity': ends.iloc[window].max().isoformat() if len(window) else None,
                           'model_year_crossing': bool(len(window) and (axis[window].year != date.year).any())})
        signals[family + '_historical'] = issued
        signals[family + '_matched'] = np.where(available, issued, np.nan)
        signals[family + '_rawmean'] = truth_mean
        signals[family + '_calibrated'] = calibrated
        values = (issued, counts, available, truth_mean, forecast_mean, residual_mean, calibrated)
        for key, value in zip(STATE_SUFFIXES, values):
            states[family + '_' + key] = value
        np.testing.assert_allclose(calibrated[available], truth_mean[available] + issued[available] - forecast_mean[available], atol=2e-14, rtol=0)
    return states, signals, traces


def selected(y, prediction, mask):
    eligible = mask & np.isfinite(prediction)
    positive = eligible & (prediction > 0)
    mature = positive & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(eligible.sum()), 'positive_forecasts': int(positive.sum()),
            'mature_positive': n, 'missing_positive_truth': int((positive & ~np.isfinite(y)).sum()),
            'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def selector_masks(signals, clock):
    masks = {}
    for family in FAMILIES:
        matched, raw, calibrated = [signals[family + '_' + kind].to_numpy(float) for kind in KINDS[1:]]
        masks[family] = np.column_stack((calibrated > 0, matched > 0, raw > 0,
                                        clock.entries(calibrated, 'greedy'), clock.entries(matched, 'greedy')))
    return masks


def paired_errors(y, signals, ids, family):
    predictions = signals.loc[:, [family + '_' + kind for kind in KINDS[1:]]].to_numpy(float)[ids]
    yy = y[ids]
    finite = np.isfinite(yy) & np.isfinite(predictions).all(axis=1)
    n = int(finite.sum())
    errors = ((predictions[finite] - yy[finite, None]) ** 2).mean(axis=0) if n >= 20 else np.full(3, np.nan)
    result = {'paired_mature': n, 'matched_mse': float(errors[0]) if n >= 20 else None,
              'rawmean_mse': float(errors[1]) if n >= 20 else None,
              'calibrated_mse': float(errors[2]) if n >= 20 else None,
              'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}
    for j, other in enumerate(('matched', 'rawmean')):
        valid = n >= 20 and errors[j] > 0
        result['mse_improvement_vs_' + other] = float((errors[j] - errors[2]) / errors[j]) if valid else None
        result['improvement_status_vs_' + other] = ('AVAILABLE' if valid else 'ZERO_CONTROL_ERROR' if n >= 20 else 'INSUFFICIENT_DATA')
    return result


def quantities(y, signals, masks, ids):
    out = {}
    for family, mask in masks.items():
        yy, mm = y[ids], mask[ids]
        finite = np.isfinite(yy)
        means = [float(yy[finite & mm[:, j]].mean()) if (finite & mm[:, j]).sum() >= 20 else None for j in range(5)]
        def difference(a, b):
            return means[a] - means[b] if means[a] is not None and means[b] is not None else None

        error = paired_errors(y, signals, ids, family)
        values = (error['mse_improvement_vs_matched'], error['mse_improvement_vs_rawmean'],
                  means[0], difference(0, 1), difference(0, 2), difference(3, 4))
        out.update({family + '_' + suffix: value for suffix, value in zip(SUFFIXES, values)})
    return out


def bootstrap(y, signals, masks):
    n, rng = len(y), np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    ids = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, signals, masks, np.arange(n))
    records = [quantities(y, signals, masks, row) for row in ids]
    summary = {}
    for key, value in original.items():
        good = [record[key] for record in records if record[key] is not None]
        available = value is not None and len(good) >= 400
        summary[key] = {'value': value, 'valid_replicates': len(good),
                        'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if available else None,
                        'status': 'AVAILABLE' if available else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500,
            'seed': 13, 'refitted_models': 0, 'clock_resimulation_within_replicates': False,
            'fixed_forecasts_and_entry_masks': True}


def analyze(scores, labels, clock):
    states, signals, traces = decisions(scores, labels)
    axis = signals.index
    y = labels.return_4.to_numpy(float)
    groups = {'all': np.ones(len(y), bool),
              **{'year_' + str(year): axis.year == year for year in range(2020, 2027)},
              **{'phase_' + str(k): np.arange(len(y)) % 5 == k for k in range(5)}}
    panels = {key: {name: selected(y, signals[name].to_numpy(float), mask) for name in MODELS}
              for key, mask in groups.items()}
    schedules = {name: {kind: clock.schedule(axis, signals[name].to_numpy(float), y, kind) for kind in clock.CLOCKS}
                 for name in MODELS}
    masks = selector_masks(signals, clock)
    quality = {key: quantities(y, signals, masks, np.flatnonzero(mask)) for key, mask in groups.items()}
    errors = {key: {family: paired_errors(y, signals, np.flatnonzero(mask), family) for family in FAMILIES}
              for key, mask in groups.items()}
    return states, signals, {'signals': len(y), 'panels': panels, 'schedules': schedules,
                            'state_traces': traces, 'selection_quality': quality, 'paired_prediction_errors': errors,
                            'bootstrap': bootstrap(y, signals, masks), 'schedule_count': len(MODELS) * len(clock.CLOCKS),
                            'new_annual_models': 0, 'new_accounts': 0, 'provider_calls': 0,
                            'historical_forecasts_unchanged': True, 'calibration_identity': 'rawmean + currentq - pastmeanq',
                            'new_independent_market_information': False, 'objective_achieved': False}
