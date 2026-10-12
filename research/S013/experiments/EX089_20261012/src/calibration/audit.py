"""Independent scalar audit of matured, previously issued forecast calibration.

No real-input loading, accounts, publishing, or primary-kernel imports.
"""
from math import fsum, ceil
import numpy as np
import pandas as pd

FAMILIES = ('confirmation', 'original14')
INPUTS = ('confirmation_110', 'original14_110')
KINDS = ('historical', 'matched', 'rawmean', 'calibrated')
MODELS = tuple(f'{family}_{kind}' for family in FAMILIES for kind in KINDS)
SUFFIXES = ('mse_improvement_vs_matched', 'mse_improvement_vs_rawmean',
            'calibrated_positive_mean', 'calibrated_positive_minus_matched',
            'calibrated_positive_minus_rawmean', 'calibrated_greedy_minus_matched_greedy')
QUANTITIES = tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)
STATE_SUFFIXES = ('issued_net_forecast', 'eligible_mature_count', 'available',
                  'past20_truth_mean', 'past20_forecast_mean',
                  'past20_residual_mean', 'calibrated_net_forecast')


def mean(values):
    return fsum(float(value) for value in values) / len(values)


def compare(actual, expected, where='root'):
    if isinstance(expected, dict):
        assert set(actual) == set(expected), (where, set(actual), set(expected))
        for key in expected:
            compare(actual[key], expected[key], where + '/' + str(key))
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), where
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            compare(a, e, where + '/' + str(i))
    elif isinstance(expected, float):
        assert np.isclose(actual, expected, atol=3e-12, rtol=2e-9), (where, actual, expected)
    else:
        assert actual == expected, (where, actual, expected)


def independent_decisions(scores, labels):
    """Enumerate prior positions separately at every T; no rolling algorithm."""
    axis = scores.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans:
        raise ValueError('Naive finite datetime signal axis required')
    if not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique increasing midnight axis required')
    if not labels.index.equals(axis) or tuple(scores.columns) != INPUTS or len(axis) < 40:
        raise ValueError('Exact original two forecast columns and common label axis required')
    if labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns):
        raise ValueError('Unique labels with paired truth/maturity required')
    y = labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError('Naive midnight maturity dates required')
    q = scores.to_numpy(float)
    if np.isinf(q).any() or np.isinf(y).any():
        raise ValueError('Infinite forecast/truth refused')
    if not np.array_equal(np.isfinite(y), ends.notna().to_numpy()):
        raise ValueError('Truth and maturity missingness mismatch')
    if np.isfinite(q[axis.year == 2020]).any():
        raise ValueError('2020 frozen forecasts must be unavailable')
    for i, value in enumerate(y):
        if np.isfinite(value) and (ends.iloc[i] <= axis[i] or value <= -1):
            raise ValueError('Truth must mature in future and preserve positive price factor')
    rows, signal_rows, traces = [], [], []
    for i, current in enumerate(axis):
        row, out = {}, []
        for j, family in enumerate(FAMILIES):
            candidates = [k for k in range(i) if np.isfinite(q[k, j])
                          and np.isfinite(y[k]) and ends.iloc[k] <= current]
            chosen = candidates[-20:] if len(candidates) >= 20 else []
            available = len(chosen) == 20 and np.isfinite(q[i, j])
            truth_mean = mean([y[k] for k in chosen]) if available else np.nan
            forecast_mean = mean([q[k, j] for k in chosen]) if available else np.nan
            residual = mean([float(y[k]) - float(q[k, j]) for k in chosen]) if available else np.nan
            calibrated = float(q[i, j]) + residual if available else np.nan
            values = (float(q[i, j]), len(candidates), bool(available), truth_mean,
                      forecast_mean, residual, calibrated)
            for suffix, value in zip(STATE_SUFFIXES, values, strict=True):
                row[family + '_' + suffix] = value
            out.extend((float(q[i, j]), float(q[i, j]) if available else np.nan,
                        truth_mean, calibrated))
            traces.append({'family': family, 'signal_date': current.isoformat(),
                           'eligible_mature_count': len(candidates), 'available': bool(available),
                           'positions': chosen,
                           'max_maturity': max(ends.iloc[k] for k in chosen).isoformat() if chosen else None,
                           'model_year_crossing': bool(chosen and any(axis[k].year != current.year for k in chosen))})
        rows.append(row)
        signal_rows.append(out)
    traces.sort(key=lambda row: (FAMILIES.index(row['family']), row['signal_date']))
    return pd.DataFrame(rows, index=axis), pd.DataFrame(signal_rows, index=axis, columns=MODELS), traces


def group(y, prediction, ids):
    available = [i for i in ids if np.isfinite(prediction[i])]
    positive = [i for i in available if prediction[i] > 0]
    mature = [i for i in positive if np.isfinite(y[i])]
    n = len(mature)
    return {'forecasts': len(available), 'positive_forecasts': len(positive),
            'mature_positive': n, 'missing_positive_truth': len(positive) - n,
            'positive_mean': mean([y[i] for i in mature]) if n >= 20 else None,
            'hit_rate': sum(y[i] > 0 for i in mature) / n if n >= 20 else None,
            'false_positive_rate': sum(y[i] <= 0 for i in mature) / n if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def quantities(y, predictions, greedy, ids):
    output = {}
    for j, family in enumerate(FAMILIES):
        positions = [int(i) for i in ids if np.isfinite(y[int(i)])
                     and all(np.isfinite(predictions[int(i), 4 * j + k]) for k in (1, 2, 3))]
        mse = [mean([(predictions[i, 4 * j + k] - y[i]) ** 2 for i in positions])
               for k in (1, 2, 3)] if len(positions) >= 20 else None
        avg = []
        for k in (1, 2, 3):
            positive = [i for i in positions if predictions[i, 4 * j + k] > 0]
            avg.append(mean([y[i] for i in positive]) if len(positive) >= 20 else None)
        gmean = []
        for k in (1, 3):
            selected = [int(i) for i in ids if int(i) in greedy[4 * j + k] and np.isfinite(y[int(i)])]
            gmean.append(mean([y[i] for i in selected]) if len(selected) >= 20 else None)
        values = (1 - mse[2] / mse[0] if mse is not None and mse[0] > 0 else None,
                  1 - mse[2] / mse[1] if mse is not None and mse[1] > 0 else None,
                  avg[2], avg[2] - avg[0] if avg[2] is not None and avg[0] is not None else None,
                  avg[2] - avg[1] if avg[2] is not None and avg[1] is not None else None,
                  gmean[1] - gmean[0] if all(v is not None for v in gmean) else None)
        for suffix, value in zip(SUFFIXES, values, strict=True):
            output[family + '_' + suffix] = float(value) if value is not None else None
    return output


def paired_errors(y, predictions, ids, family):
    j = FAMILIES.index(family)
    chosen = [int(i) for i in ids if np.isfinite(y[int(i)])
              and all(np.isfinite(predictions[int(i), 4 * j + k]) for k in (1, 2, 3))]
    n = len(chosen)
    mse = [mean([(predictions[i, 4 * j + k] - y[i]) ** 2 for i in chosen])
           for k in (1, 2, 3)] if n >= 20 else [None, None, None]
    result = {'paired_mature': n, 'matched_mse': mse[0], 'rawmean_mse': mse[1],
              'calibrated_mse': mse[2], 'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}
    for k, control in enumerate(('matched', 'rawmean')):
        valid = n >= 20 and mse[k] > 0
        result['mse_improvement_vs_' + control] = 1 - mse[2] / mse[k] if valid else None
        result['improvement_status_vs_' + control] = ('AVAILABLE' if valid else
            'ZERO_CONTROL_ERROR' if n >= 20 else 'INSUFFICIENT_DATA')
    return result


def schedules(axis, y, predictions, clock):
    output = {}
    for j, model in enumerate(MODELS):
        p = predictions[:, j]
        positive = [i for i, value in enumerate(p) if np.isfinite(value) and value > 0]
        output[model] = {}
        for name in clock.CLOCKS:
            ids = clock.selected(p, name)
            accepted = set(ids)
            mature = [i for i in ids if np.isfinite(y[i])]
            blocked = [i for i in positive if i not in accepted]
            mb = [i for i in blocked if np.isfinite(y[i])]
            panels = {'all': clock.attribution(y, ids),
                      **{'year_' + str(t): clock.attribution(y, [i for i in ids if axis[i].year == t])
                         for t in range(2020, 2027)}}
            output[model][name] = {'accepted': len(ids), 'missing_truth_accepted': len(ids) - len(mature),
                'positive_forecasts': len(positive), 'blocked_positive_forecasts': len(blocked),
                'accepted_mean': mean([y[i] for i in mature]) if len(mature) >= 20 else None,
                'blocked_positive_mean': mean([y[i] for i in mb]) if len(mb) >= 20 else None,
                'mature_blocked_positive': len(mb), 'panels': panels,
                'records': [{'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(p[i]),
                             'proxy_return': float(y[i]) if np.isfinite(y[i]) else None} for i in ids]}
    return output


def verify(scores, labels, reported_states, reported_signals, report, clock):
    states, signals, traces = independent_decisions(scores, labels)
    pd.testing.assert_frame_equal(reported_states, states, check_exact=False, atol=3e-12, rtol=2e-9)
    pd.testing.assert_frame_equal(reported_signals, signals, check_exact=False, atol=3e-12, rtol=2e-9)
    np.testing.assert_array_equal(reported_signals.to_numpy() > 0, signals.to_numpy() > 0)
    compare(report['state_traces'], traces, 'state_traces')
    axis, y, p = signals.index, labels.return_4.to_numpy(float), signals.to_numpy(float)
    masks = {'all': list(range(len(y))),
             **{'year_' + str(t): [i for i, d in enumerate(axis) if d.year == t] for t in range(2020, 2027)},
             **{'phase_' + str(k): [i for i in range(len(y)) if i % 5 == k] for k in range(5)}}
    greedy = {j: set(clock.selected(p[:, j], 'greedy')) for j in range(8)}
    compare(report['panels'], {key: {model: group(y, p[:, j], ids) for j, model in enumerate(MODELS)}
                               for key, ids in masks.items()}, 'panels')
    compare(report['selection_quality'], {key: quantities(y, p, greedy, ids) for key, ids in masks.items()}, 'selection_quality')
    compare(report['paired_prediction_errors'],
            {key: {family: paired_errors(y, p, ids, family) for family in FAMILIES}
             for key, ids in masks.items()}, 'paired_prediction_errors')
    compare(report['schedules'], schedules(axis, y, p, clock), 'schedules')
    if len(y) < 40:
        raise ValueError('Full-axis bootstrap requires at least40 positions')
    rng = np.random.default_rng(13)
    starts = rng.integers(0, len(y) - 39, (500, ceil(len(y) / 40)))
    samples = np.concatenate([starts[:, j:j + 1] + np.arange(40) for j in range(starts.shape[1])], axis=1)[:, :len(y)]
    records = [quantities(y, p, greedy, ids) for ids in samples]
    compare(report['bootstrap']['records'], records, 'bootstrap_records')
    summary = {}
    for key, value in quantities(y, p, greedy, list(range(len(y)))).items():
        good = [row[key] for row in records if row[key] is not None]
        ok = value is not None and len(good) >= 400
        summary[key] = {'value': value, 'valid_replicates': len(good),
                        'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                        'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'], summary, 'bootstrap_summary')
    metadata = {'blocks': 40, 'repetitions': 500, 'seed': 13, 'refitted_models': 0,
                'clock_resimulation_within_replicates': False,
                'fixed_forecasts_and_entry_masks': True}
    compare({key: report['bootstrap'][key] for key in metadata}, metadata, 'bootstrap_method')
    assert report['signals'] == len(y) and report['schedule_count'] == 48
    assert report['new_annual_models'] == report['new_accounts'] == report['provider_calls'] == 0
    assert report['historical_forecasts_unchanged'] is True
    assert report['new_independent_market_information'] is False
    assert report['objective_achieved'] is False
    return {'status': 'PASS', 'forecast_rows': len(y), 'state_windows': 2 * len(y),
            'traces_verified': len(traces), 'schedules': 48, 'year_panels': 48 * 8,
            'causal_prefix_windows': 2 * len(y),
            'strict_positive_flags': 'EXACT', 'entry_positions': 'EXACT',
            'bootstrap_replicates': 500, 'bootstrap_quantities': 12,
            'bootstrap_records_checked': 6000, 'new_models': 0, 'new_accounts': 0}
