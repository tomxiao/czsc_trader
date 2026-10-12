"""Independent scalar audit of expanding mature-pool P/G forecasting.

No real-input loading, accounts, publishing, or primary-kernel imports.
"""
from math import fsum, ceil, exp
from bisect import bisect_left, bisect_right
import numpy as np
import pandas as pd

FAMILIES = ('confirmation', 'original14')
INPUTS = ('confirmation_110', 'original14_110')
KINDS = ('historical', 'matched', 'training_mean', 'online_pg')
MODELS = tuple(f'{family}_{kind}' for family in FAMILIES for kind in KINDS)
SUFFIXES = ('net_mse_improvement_vs_matched', 'net_mse_improvement_vs_training_mean',
            'online_positive_mean', 'online_positive_minus_matched',
            'online_positive_minus_training_mean', 'online_greedy_minus_matched_greedy')
QUANTITIES = tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)
FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
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


def check_fit(design, target, proof, kind):
    """Recompute objective and every gradient coordinate at published beta.

    Strictly convex objectives have a unique stationary solution.  This audit
    validates that solution, not the Newton/Armijo iteration trajectory.
    """
    beta = np.asarray(proof['coefficients'], float)
    if beta.shape != (design.shape[1],) or not np.isfinite(beta).all():
        raise ValueError('Finite full coefficient vector required')
    eta = [fsum(float(a) * float(b) for a, b in zip(row, beta, strict=True)) for row in design]
    if kind == 'probability':
        prediction = [exp(-float(np.logaddexp(0., -z))) for z in eta]
        residual = [p - float(t) for p, t in zip(prediction, target, strict=True)]
        terms = [float(np.logaddexp(0., z)) - float(t) * z for z, t in zip(eta, target, strict=True)]
    elif kind == 'gain':
        ratios = [float(t) * exp(-z) for z, t in zip(eta, target, strict=True)]
        residual = [1 - v for v in ratios]
        terms = [z + v for z, v in zip(eta, ratios, strict=True)]
    else:
        raise ValueError('Exactly probability/gain model roles required')
    gradient = [fsum(float(row[j]) * r for row, r in zip(design, residual, strict=True))
                + (0. if j == 0 else 10. * float(beta[j])) for j in range(len(beta))]
    norm = max(abs(value) for value in gradient)
    objective = fsum(terms) + 5 * fsum(float(value) ** 2 for value in beta[1:])
    if norm > 1.05e-10 or not 0 <= proof['iterations'] < 100:
        raise ValueError(('All-fit strict stationary solution required', kind, norm))
    assert 0 <= proof['max_abs_gradient'] <= 1e-10, (kind, proof)
    assert np.isclose(proof['max_abs_gradient'], norm, atol=5e-12, rtol=1e-5), (kind, norm, proof)
    assert np.isclose(proof['objective'], objective, atol=3e-10, rtol=2e-12), (kind, objective, proof)
    return beta, norm


def independent_forecasts(features, labels, old_scores, fit_trace):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans:
        raise ValueError('Naive finite datetime signal axis required')
    if not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique increasing midnight axis required')
    if tuple(features.columns) != FEATURES or tuple(old_scores.columns) != INPUTS:
        raise ValueError('Frozen exact original14 and two110 columns required')
    if not labels.index.equals(axis) or not old_scores.index.equals(axis) or len(axis) < 40:
        raise ValueError('Common axis of at least40 positions required')
    if labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns):
        raise ValueError('Unique labels with paired truth/maturity required')
    x, y, old = features.to_numpy(float), labels.return_4.to_numpy(float), old_scores.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError('Naive midnight maturity dates required')
    if any(np.isinf(a).any() for a in (x, y, old)):
        raise ValueError('Infinite model inputs refused')
    if not np.array_equal(np.isfinite(y), ends.notna().to_numpy()):
        raise ValueError('Truth and maturity missingness mismatch')
    for i, value in enumerate(y):
        if np.isfinite(value) and (value <= -1 or ends.iloc[i] <= axis[i]):
            raise ValueError('Positive price factor and future maturity required')
    if np.isfinite(old[axis.year < 2021]).any():
        raise ValueError('Frozen2020 forecasts unavailable')
    complete = [all(np.isfinite(value) for value in row) for row in x]
    supplied = {(row['family'], row['position']): row for row in fit_trace}
    if len(supplied) != len(fit_trace) or len(fit_trace) != 2 * len(axis):
        raise ValueError('Exactly one fit trace per family/T required')
    matrix = np.full((len(axis), 8), np.nan)
    matrix[:, 0], matrix[:, 4] = old[:, 0], old[:, 1]
    checked, norms = 0, []
    for i, current in enumerate(axis):
        train = [k for k in range(i) if axis[k].year >= 2020 and complete[k]
                 and np.isfinite(y[k]) and ends.iloc[k] <= current]
        win = [k for k in train if y[k] > 0]
        lose = [k for k in train if y[k] <= 0]
        available = current.year >= 2021 and complete[i] and len(train) >= 40 and len(win) >= 20 and len(lose) >= 20
        ranked = None
        if available:
            ordered = [sorted(float(x[k, c]) for k in train) for c in range(14)]
            def rankrow(k):
                return [(bisect_left(ordered[c], float(x[k, c])) +
                         bisect_right(ordered[c], float(x[k, c]))) / (2 * len(train)) - .5
                        for c in range(14)]
            ranked = np.asarray([rankrow(k) for k in train])
            test = rankrow(i)
        for j, family in enumerate(FAMILIES):
            row = supplied[(family, i)]
            columns = [8] if j == 0 else list(range(14))
            expected = {'family': family, 'signal_date': current.isoformat(), 'position': i,
                        'columns': columns, 'train_n': len(train), 'win_n': len(win),
                        'nonpositive_n': len(lose), 'zero_net_n': sum(y[k] == 0 for k in train),
                        'train_positions': train, 'max_maturity': max(ends.iloc[k] for k in train).isoformat() if train else None,
                        'current_features_complete': complete[i], 'available': bool(available),
                        'future_test_count_gate': False}
            expected['status'] = ('AVAILABLE' if available else 'PRE2021_UNAVAILABLE' if current.year < 2021 else
                                  'CURRENT_FEATURES_MISSING' if not complete[i] else 'INSUFFICIENT_MATURE_TRAINING')
            assert set(row) == set(expected) | {'training_mean', 'loss_mean', 'probability', 'gain',
                                             'online_pg', 'probability_fit', 'gain_fit'}
            compare({key: row[key] for key in expected}, expected, 'fit_trace/' + family + '/' + str(i))
            if not available:
                assert all(row[key] is None for key in ('training_mean', 'loss_mean', 'probability', 'gain', 'online_pg', 'probability_fit', 'gain_fit'))
                continue
            design = np.column_stack((np.ones(len(train)), ranked[:, columns]))
            wins_in_pool = [k for k, position in enumerate(train) if y[position] > 0]
            p_beta, p_norm = check_fit(design, np.asarray([float(y[k] > 0) for k in train]), row['probability_fit'], 'probability')
            g_beta, g_norm = check_fit(design[wins_in_pool], np.asarray([y[k] for k in win]), row['gain_fit'], 'gain')
            norms.extend((p_norm, g_norm))
            query = [1.] + [test[c] for c in columns]
            p_eta = fsum(float(a) * float(b) for a, b in zip(query, p_beta, strict=True))
            g_eta = fsum(float(a) * float(b) for a, b in zip(query, g_beta, strict=True))
            probability, gain = exp(-float(np.logaddexp(0., -p_eta))), exp(g_eta)
            loss, average = mean([-y[k] for k in lose]), mean([y[k] for k in train])
            net = probability * gain - (1 - probability) * loss
            values = {'training_mean': average, 'loss_mean': loss, 'probability': probability, 'gain': gain, 'online_pg': net}
            compare({key: row[key] for key in values}, values, 'fit_values/' + family + '/' + str(i))
            assert 0 < probability < 1 and gain > 0 and loss >= 0
            matrix[i, 4 * j + 1:4 * j + 4] = (old[i, j], average, net)
            checked += 2
    expected_order = [(family, i) for family in FAMILIES for i in range(len(axis))]
    assert [(row['family'], row['position']) for row in fit_trace] == expected_order
    return pd.DataFrame(matrix, index=axis, columns=MODELS), {'fits_verified': checked,
        'causal_prefix_windows': 2 * len(axis), 'max_independent_stationary_gradient': max(norms) if norms else None}


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
            positive = [int(i) for i in ids if np.isfinite(y[int(i)])
                        and np.isfinite(predictions[int(i), 4 * j + k])
                        and predictions[int(i), 4 * j + k] > 0]
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
    result = {'paired_mature': n, 'matched_mse': mse[0], 'training_mean_mse': mse[1],
              'online_pg_mse': mse[2], 'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}
    for k, control in enumerate(('matched', 'training_mean')):
        valid = n >= 20 and mse[k] > 0
        result['net_mse_improvement_vs_' + control] = 1 - mse[2] / mse[k] if valid else None
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


def verify(features, labels, old_scores, reported_scores, report, clock):
    signals, fit_checks = independent_forecasts(features, labels, old_scores, report['fit_trace'])
    pd.testing.assert_frame_equal(reported_scores, signals, check_exact=False, atol=3e-12, rtol=2e-9)
    np.testing.assert_array_equal(reported_scores.to_numpy() > 0, signals.to_numpy() > 0)
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
                'clock_resimulation_within_replicates': False, 'fixed_forecasts_and_entry_masks': True}
    compare({key: report['bootstrap'][key] for key in metadata}, metadata, 'bootstrap_method')
    assert report['signals'] == len(y) and report['schedule_count'] == 48
    assert report['new_daily_models'] == fit_checks['fits_verified']
    assert report['new_annual_models'] == 0
    assert report['new_accounts'] == report['provider_calls'] == 0
    assert report['historical_forecasts_unchanged'] is True
    assert report['new_independent_market_information'] is False
    assert report['training_rule'] == 'expanding mature original14 from2020; strict earlier T; label_end<=currentT'
    assert report['objective_achieved'] is False
    return {'status': 'PASS', 'forecast_rows': len(y), **fit_checks,
            'fit_trace_rows': len(report['fit_trace']), 'schedules': 48, 'year_panels': 48 * 8,
            'strict_positive_flags': 'EXACT', 'entry_positions': 'EXACT',
            'bootstrap_replicates': 500, 'bootstrap_quantities': 12,
            'bootstrap_records_checked': 6000, 'new_models_refitted_by_audit': 0, 'new_accounts': 0}


