"""Independent scalar ranks, ridge stationarity and full EX092 statistics.

The primary implementation and its numeric helper are never imported here.
Only the frozen independent EX083 clock primitives are supplied by the caller.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
from math import fsum, ceil, sqrt
import numpy as np
import pandas as pd

ORIGINAL = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20',
            'feature_overnight_down_energy20', 'turnover20', 'volume_ratio20')
CONTROLS = (*ORIGINAL, 'mean_a20', 'mean_b20', 'rms_a20', 'rms_b20', 'freq_a20', 'freq_b20',
            'late_recovery', 'early_volume_reclaim', 'early_down_share', 'max_down_run_share',
            'total_down', 'total_up', 'samebar_cov')
MODELS = ('pastmean', 'controls', 'augmented')
QUANTITIES = ('augmented_mse_improvement_vs_controls', 'augmented_mse_improvement_vs_pastmean',
              'augmented_positive_mean', 'augmented_positive_minus_controls')


def mean(values):
    return fsum(float(v) for v in values) / len(values)


def compare(actual, expected, where='root'):
    if isinstance(expected, dict):
        assert set(actual) == set(expected), (where, set(actual), set(expected))
        for key in expected:
            compare(actual[key], expected[key], where + '/' + str(key))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), where
        for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
            compare(a, b, where + '/' + str(i))
    elif isinstance(expected, float):
        assert np.isclose(actual, expected, atol=3e-12, rtol=2e-9), (where, actual, expected)
    else:
        assert actual == expected, (where, actual, expected)


def ranks(values):
    ordered = sorted(float(v) for v in values)
    return np.asarray([(bisect_left(ordered, float(v)) + bisect_right(ordered, float(v)) + 1) / 2
                       for v in values])


def correlation(x, y, controls=None):
    ids = [i for i in range(len(x)) if np.isfinite(x[i]) and np.isfinite(y[i])
           and (controls is None or all(np.isfinite(v) for v in controls[i]))]
    n = len(ids)
    result = {'n': n, 'finite_positions': ids, 'value': None, 'reason': None,
              'design_rank': None, 'residual_df': None, 'singular_values': None,
              'condition_number': None, 'component_residual_fraction': None,
              'target_residual_fraction': None}
    a, b = ranks([x[i] for i in ids]), ranks([y[i] for i in ids])
    if n:
        a -= mean(a)
        b -= mean(b)
    design, u, rank = None, None, None
    if controls is not None:
        design = np.column_stack([np.ones(n), *[ranks([controls[i, j] for i in ids])
                                               for j in range(controls.shape[1])]])
        u, _, _ = np.linalg.svd(design, full_matrices=False)
        singular = np.linalg.svd(design, compute_uv=False)
        cutoff = max(design.shape) * np.finfo(float).eps * singular[0] if len(singular) else 0.
        rank = sum(value > cutoff for value in singular) if n else 0
        result.update({'design_rank': int(rank), 'residual_df': n - int(rank),
                       'singular_values': singular.tolist(),
                       'condition_number': float(singular[0] / singular[-1])
                       if len(singular) and singular[-1] > 0 else None})
    if n < 20:
        result['reason'] = 'INSUFFICIENT_SAMPLE'
        return result
    if controls is not None and result['residual_df'] < 10:
        result['reason'] = 'INSUFFICIENT_RESIDUAL_DF'
        return result
    na, nb = sqrt(fsum(float(v) ** 2 for v in a)), sqrt(fsum(float(v) ** 2 for v in b))
    if na == 0 or nb == 0:
        result['reason'] = 'CONSTANT_COMPONENT' if na == 0 else 'CONSTANT_TARGET'
        return result
    if design is not None:
        # Orthogonal projection uses the retained SVD basis, unlike the primary
        # least-squares coefficient solve.  Both span the declared full design.
        basis = u[:, :rank]
        a -= basis @ (basis.T @ a)
        b -= basis @ (basis.T @ b)
        an = sqrt(fsum(float(v) ** 2 for v in a))
        bn = sqrt(fsum(float(v) ** 2 for v in b))
        result['component_residual_fraction'] = an / na
        result['target_residual_fraction'] = bn / nb
        if an <= 1e-10 * na or bn <= 1e-10 * nb:
            result['reason'] = 'EXPLAINED_COMPONENT' if an <= 1e-10 * na else 'TARGET_EXPLAINED_OR_CONSTANT'
            return result
    else:
        an, bn = na, nb
    value = fsum(float(v) * float(w) for v, w in zip(a, b, strict=True)) / (an * bn)
    result['value'] = min(1., max(-1., value))
    return result


def sample_indices(n):
    if n < 40:
        return None
    starts = np.random.default_rng(13).integers(0, n - 39, (500, ceil(n / 40)))
    return np.concatenate([starts[:, j:j + 1] + np.arange(40) for j in range(starts.shape[1])], axis=1)[:, :n]


def correlation_bootstrap(x, y, controls, samples):
    records = []
    for i in range(500):
        if samples is None:
            row = {'replicate': i, 'value': None, 'reason': 'INSUFFICIENT_FULL_AXIS',
                   'n': 0, 'design_rank': None, 'residual_df': None}
        else:
            ids = samples[i]
            row = correlation(x[ids], y[ids], controls[ids] if controls is not None else None)
            del row['finite_positions']
            row['replicate'] = i
        records.append(row)
    values = [row['value'] for row in records if row['value'] is not None]
    return {'requested': 500, 'valid': len(values), 'replicates': records,
            'status_counts': dict(Counter(row['reason'] or 'VALID' for row in records)),
            'ic95': np.quantile(values, [.025, .975], method='linear').tolist() if len(values) >= 400 else None,
            'reason': None if len(values) >= 400 else 'INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES'}


def independent_forecasts(features, labels, traces):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.equals(axis.normalize()):
        raise ValueError('Finite naive midnight dates required')
    if not axis.is_unique or not axis.is_monotonic_increasing or not labels.index.equals(axis):
        raise ValueError('Exact aligned ordered unique axis required')
    if tuple(features.columns) != (*CONTROLS, 'X') or labels.columns.has_duplicates:
        raise ValueError('Exact28 feature columns and unique labels required')
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if np.isinf(x).any() or np.isinf(y).any() or ends.dt.tz is not None:
        raise ValueError('Finite or missing numeric inputs and naive maturity required')
    if not np.array_equal(np.isfinite(y), ends.notna().to_numpy()):
        raise ValueError('Paired truth/maturity missingness required')
    if any(ends.iloc[i] <= axis[i] for i, value in enumerate(y) if np.isfinite(value)):
        raise ValueError('Future label maturity required')
    if len(traces) != 6 or [row['year'] for row in traces] != list(range(2021, 2027)):
        raise ValueError('Six fixed fit years required')
    complete = [all(np.isfinite(v) for v in row) for row in x]
    p = np.full((len(axis), 3), np.nan)
    fit_count, max_residual = 0, 0.
    for trace in traces:
        year = trace['year']
        days = [day for day in axis if day.year == year]
        first = days[0] if days else None
        train = [i for i, day in enumerate(axis) if first is not None and complete[i]
                 and np.isfinite(y[i]) and 2020 <= day.year < year and ends.iloc[i] < first]
        test = [i for i, day in enumerate(axis) if complete[i] and day.year == year]
        reason = 'NO_YEAR' if first is None else 'INSUFFICIENT_MATURE_TRAINING' if len(train) < 40 else None
        expected = {'year': year, 'first_test': first.isoformat() if first is not None else None,
                    'train_positions': train, 'test_positions': test,
                    'future_test_count_gate': False, 'reason': reason}
        assert set(trace) == set(expected) | {'models'}
        compare({key: trace[key] for key in expected}, expected, 'fit/' + str(year))
        if reason is not None:
            assert trace['models'] == {}
            continue
        ordered = [sorted(float(x[i, j]) for i in train) for j in range(28)]

        def ecdf(position):
            return [(bisect_left(ordered[j], float(x[position, j])) +
                     bisect_right(ordered[j], float(x[position, j]))) / (2 * len(train))
                    for j in range(28)]

        ranked = np.asarray([ecdf(i) for i in train])
        target_mean = mean([y[i] for i in train])
        assert set(trace['models']) == {'controls', 'augmented'}
        for j, name in enumerate(('controls', 'augmented'), 1):
            width = 26 + j
            proof = trace['models'][name]
            center = np.asarray([mean(ranked[:, c]) for c in range(width)])
            beta = np.asarray(proof['slope'], float)
            if beta.shape != (width,) or not np.isfinite(beta).all():
                raise ValueError('Finite complete ridge coefficients required')
            compare(proof['train_mean'], center.tolist(), 'train_mean/' + str(year) + '/' + name)
            compare(proof['target_mean'], target_mean, 'target_mean/' + str(year) + '/' + name)
            residual = [fsum((float(row[c]) - center[c]) * beta[c] for c in range(width))
                        - (float(y[i]) - target_mean) for row, i in zip(ranked, train, strict=True)]
            gradient = [fsum((float(row[c]) - center[c]) * value
                            for row, value in zip(ranked, residual, strict=True)) + 10 * beta[c]
                        for c in range(width)]
            norm = max(abs(value) for value in gradient)
            if norm > 1e-10:
                raise ValueError(('Ridge normal-equation failure', year, name, norm))
            max_residual = max(max_residual, norm)
            for i in test:
                query = ecdf(i)
                p[i, j] = target_mean + fsum((query[c] - center[c]) * beta[c] for c in range(width))
            fit_count += 1
        p[test, 0] = target_mean
    return pd.DataFrame(p, index=axis, columns=MODELS), fit_count, max_residual


def quantities(y, p, ids):
    paired = [int(i) for i in ids if np.isfinite(y[int(i)]) and all(np.isfinite(v) for v in p[int(i)])]
    mse = [mean([(p[i, j] - y[i]) ** 2 for i in paired]) for j in range(3)] if len(paired) >= 20 else None
    averages = []
    for j in range(3):
        selected = [int(i) for i in ids if np.isfinite(y[int(i)]) and np.isfinite(p[int(i), j]) and p[int(i), j] > 0]
        averages.append(mean([y[i] for i in selected]) if len(selected) >= 20 else None)
    return {QUANTITIES[0]: 1 - mse[2] / mse[1] if mse is not None and mse[1] > 0 else None,
            QUANTITIES[1]: 1 - mse[2] / mse[0] if mse is not None and mse[0] > 0 else None,
            QUANTITIES[2]: averages[2],
            QUANTITIES[3]: averages[2] - averages[1] if averages[2] is not None and averages[1] is not None else None}


def schedules(axis, y, p, clock):
    output = {}
    for j, model in enumerate(MODELS):
        prediction = p[:, j]
        positive = [i for i, value in enumerate(prediction) if np.isfinite(value) and value > 0]
        output[model] = {}
        for name in clock.CLOCKS:
            ids = clock.selected(prediction, name)
            accepted = set(ids)
            mature = [i for i in ids if np.isfinite(y[i])]
            blocked = [i for i in positive if i not in accepted]
            mb = [i for i in blocked if np.isfinite(y[i])]
            output[model][name] = {'accepted': len(ids), 'missing_truth_accepted': len(ids) - len(mature),
                'positive_forecasts': len(positive), 'blocked_positive_forecasts': len(blocked),
                'accepted_mean': mean([y[i] for i in mature]) if len(mature) >= 20 else None,
                'blocked_positive_mean': mean([y[i] for i in mb]) if len(mb) >= 20 else None,
                'mature_blocked_positive': len(mb),
                'panels': {'all': clock.attribution(y, ids),
                           **{'year_' + str(t): clock.attribution(y, [i for i in ids if axis[i].year == t]) for t in range(2020, 2027)}},
                'records': [{'signal_date': axis[i].isoformat(), 'position': i, 'prediction': float(prediction[i]),
                             'proxy_return': float(y[i]) if np.isfinite(y[i]) else None} for i in ids]}
    return output


def verify(features, labels, scores, report, numeric_clock):
    expected, fit_count, gradient = independent_forecasts(features, labels, report['fit_trace'])
    pd.testing.assert_frame_equal(scores, expected, check_exact=False, atol=3e-12, rtol=2e-9)
    np.testing.assert_array_equal(scores.to_numpy() > 0, expected.to_numpy() > 0)
    axis = features.index
    x, y, controls = features.X.to_numpy(float), labels.return_4.to_numpy(float), features[list(CONTROLS)].to_numpy(float)
    p = expected.to_numpy(float)
    ids = list(range(len(axis)))
    groups = {'all': ids, **{'year_' + str(t): [i for i in ids if axis[i].year == t] for t in range(2020, 2027)},
              **{'phase_' + str(k): [i for i in ids if i % 5 == k] for k in range(5)}}
    samples = sample_indices(len(axis))
    compare(report['raw'], correlation(x, y), 'raw')
    compare(report['partial'], correlation(x, y, controls), 'partial')
    compare(report['raw_bootstrap'], correlation_bootstrap(x, y, None, samples), 'raw_bootstrap')
    compare(report['partial_bootstrap'], correlation_bootstrap(x, y, controls, samples), 'partial_bootstrap')
    panels = {key: {'raw': correlation(x[positions], y[positions]),
                    'partial': correlation(x[positions], y[positions], controls[positions]),
                    'quantities': quantities(y, p, positions)} for key, positions in groups.items()}
    compare(report['panels'], panels, 'panels')
    records = [quantities(y, p, positions) for positions in samples] if samples is not None else []
    compare(report['bootstrap']['records'], records, 'prediction_bootstrap_records')
    summary = {}
    for key, value in quantities(y, p, ids).items():
        good = [row[key] for row in records if row[key] is not None]
        ok = value is not None and len(good) >= 400
        summary[key] = {'value': value, 'valid_replicates': len(good),
                        'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if ok else None,
                        'status': 'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    compare(report['bootstrap']['summary'], summary, 'prediction_bootstrap_summary')
    metadata = {'blocks': 40, 'repetitions': 500, 'seed': 13, 'refitted': 0}
    compare({key: report['bootstrap'][key] for key in metadata}, metadata, 'prediction_bootstrap_method')
    compare(report['schedules'], schedules(axis, y, p, numeric_clock), 'schedules')
    assert report['new_models'] == fit_count and report['signals'] == len(axis)
    assert report['controls'] == list(CONTROLS) and report['component'] == 'X' and report['fixed_hypothesis'] == 'negative'
    assert report['new_accounts'] == report['provider_calls'] == 0 and report['objective_achieved'] is False
    return {'status': 'PASS', 'forecast_rows': len(axis), 'ridge_fits_stationary': fit_count,
            'maximum_normal_equation_residual': gradient, 'correlation_panels': len(groups) * 2 + 2,
            'correlation_bootstrap_replicates': 1000, 'prediction_bootstrap_quantities': 4,
            'prediction_bootstrap_records': len(records) * 4, 'schedules': 18,
            'year_schedule_panels': 18 * 8, 'strict_positive_flags': 'EXACT',
            'new_models_refitted_by_audit': 0, 'new_accounts': 0}
