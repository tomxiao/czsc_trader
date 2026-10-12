"""Synthetic Huber checks only: no data provider, account, or experiment."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent


def run():
    spec = importlib.util.spec_from_file_location('huber_pure_checked', WORK / 'huber_kernel.py')
    kernel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kernel)
    rng = np.random.default_rng(97)
    x = rng.uniform(-.5, .5, (400, 14))
    y = .01 + .004 * x[:, 0]
    test = x[:40]
    prediction, proof = kernel.fit(x, y, test)
    design = np.column_stack((np.ones(len(x)), x))
    penalty = np.diag(np.r_[0., np.full(14, 10.)])
    ols = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    assert np.max(np.abs(y - design @ ols)) <= proof['delta']
    np.testing.assert_allclose(proof['coefficients'], ols, atol=2e-12, rtol=0)
    np.testing.assert_allclose(prediction, np.column_stack((np.ones(len(test)), test)) @ ols, atol=2e-12, rtol=0)
    checks = ['OLS all-inlier same penalized solution and unpenalized intercept']
    shock = y.copy()
    shock[np.argsort(x[:, 0])[-3:]] += .8
    robust, robust_proof = kernel.fit(x, shock, test)
    shock_ols = np.linalg.solve(design.T @ design + penalty, design.T @ shock)
    assert np.linalg.norm(np.asarray(robust_proof['coefficients']) - ols) < np.linalg.norm(shock_ols - ols)
    assert not robust_proof['targets_clipped'] and robust_proof['training_n'] == 400
    for target, fit in ((y, proof), (shock, robust_proof)):
        beta = np.asarray(fit['coefficients'])
        delta = fit['delta']
        r = target - design @ beta
        psi = np.sign(r) * np.minimum(np.abs(r), delta)
        gradient = -(design.T @ psi) + np.r_[0., 10 * beta[1:]]
        objective = np.sum(np.where(np.abs(r) <= delta, .5 * r * r, delta * (np.abs(r) - .5 * delta))) + 5 * np.sum(beta[1:] ** 2)
        assert np.max(np.abs(gradient)) <= 1e-10
        assert fit['max_coefficient_change'] <= 1e-12 and np.isclose(fit['objective'], objective, atol=1e-12)
        assert fit['delta'] == 1.345 * np.median(np.abs(target - np.median(target)))
    assert np.isfinite(robust).all()
    checks.append('few shocks have less coefficient influence; full true gradient/Huber loss/MAD verified')
    const, constant = kernel.fit(x, np.full(400, .015), test)
    np.testing.assert_array_equal(const, np.full(40, .015))
    assert constant['constant_target_definition'] and constant['coefficients'] == [.015] + [0.] * 14
    varied = np.zeros(400)
    varied[-40:] = .02
    missing, unavailable = kernel.fit(x, varied, test)
    assert np.isnan(missing).all() and unavailable['reason'] == 'ZERO_MAD_WITH_VARIED_TARGET'
    assert unavailable['coefficients'] is None and unavailable['status'] == 'UNAVAILABLE'
    checks.append('zeroMAD constant definition and variedtarget explicit NA without scale fallback')
    # Force only the stopping test to fail; arithmetic remains pure and the
    # fixed500 loop must reject, never return its initial OLS as a fallback.
    original = kernel.objective_gradient

    def never_stationary(design, target, coefficients, delta, ridge_alpha):
        loss, _ = original(design, target, coefficients, delta, ridge_alpha)
        return loss, np.ones(len(coefficients))

    kernel.objective_gradient = never_stationary
    try:
        kernel.fit(x, y, test)
    except ValueError as error:
        failure = error.args[0]
        assert failure['reason'] == 'HUBER_IRLS_NONCONVERGENCE_500'
        assert failure['iterations'] == 500 and failure['status'] == 'FAILED'
    else:
        raise AssertionError('Nonconvergence accepted')
    finally:
        kernel.objective_gradient = original
    checks.append('fixed500 nonconvergence rejects with last proof; no OLS fallback')
    days = [day for year in range(2020, 2027)
            for day in pd.bdate_range(str(year) + '-01-01', periods=80 if year == 2020 else 55 if year == 2026 else 53)]
    axis = pd.DatetimeIndex(days).as_unit('ns')
    features = pd.DataFrame(rng.normal(0, 1, (400, 14)), index=axis, columns=kernel.FEATURES)
    features.iloc[:10, 2] = np.nan
    features.iloc[117, 5] = np.nan
    target = .001 + .004 * features.iloc[:, 0].to_numpy() + rng.normal(0, .01, 400)
    target[-5:] = np.nan
    labels = pd.DataFrame({'return_4': target, 'label_end_return_4': pd.Series(axis, index=axis).shift(-5)}, index=axis)
    labels.iloc[76, 1] = axis[100]
    scores, traces = kernel.forecasts(features, labels)
    assert tuple(scores.columns) == kernel.MODELS and len(traces) == 6
    assert scores.loc[axis.year == 2020].isna().all().all()
    assert scores.iloc[-5:].notna().all().all() and scores.iloc[117].isna().all()
    for row in traces:
        first = pd.Timestamp(row['first_test'])
        expected_train = [i for i in range(len(axis)) if 2020 <= axis[i].year < row['year']
                          and np.isfinite(target[i]) and features.iloc[i].notna().all()
                          and labels.label_end_return_4.iloc[i] < first]
        assert row['train_positions'] == expected_train
        assert row['available'] and row['fit']['status'] == 'AVAILABLE' and not row['future_test_count_gate']
        for j, ordered in enumerate(row['cdf_training_sorted']):
            assert ordered == sorted(features.iloc[expected_train, j].tolist())
        assert row['fit']['max_abs_gradient'] <= 1e-10 and row['fit']['max_coefficient_change'] <= 1e-12
    checks.append('all six mature annual supports/CDF/scale/beta; tail/current availability independent of future truth')
    cut = axis[axis.year == 2024][0] + pd.Timedelta(days=3)
    keep = axis <= cut
    prefix, _ = kernel.forecasts(features.loc[keep], labels.loc[keep])
    pd.testing.assert_frame_equal(prefix, scores.loc[keep], check_exact=False, atol=2e-14, rtol=0)
    np.testing.assert_array_equal(prefix.to_numpy() > 0, scores.loc[keep].to_numpy() > 0)
    changed = labels.copy()
    changed.loc[changed.label_end_return_4 >= axis[axis.year == 2024][0], 'return_4'] = .9
    altered, _ = kernel.forecasts(features.loc[keep], changed.loc[keep])
    pd.testing.assert_frame_equal(altered, scores.loc[keep], check_exact=False, atol=2e-14, rtol=0)
    checks.append('causal prefix and immature futurelabel mutation do not change prior forecasts')
    no_year, no_trace = kernel.forecasts(features.loc[axis.year == 2020], labels.loc[axis.year == 2020])
    assert no_year.isna().all().all() and all(row['reason'] == 'NO_TEST_YEAR' for row in no_trace)
    thin = features.copy()
    thin.loc[axis.year == 2020] = np.nan
    _, thin_trace = kernel.forecasts(thin, labels)
    assert thin_trace[0]['reason'] == 'INSUFFICIENT_MATURE_TRAINING'
    checks.append('no-year and insufficient mature training explicitly unavailable')
    refused = []
    for kind in ('columns', 'label_axis', 'unordered', 'duplicate', 'timezone', 'infinite_x',
                 'infinite_y', 'unpaired_maturity', 'not_future', 'alpha_low', 'alpha_high',
                 'alpha_int', 'multiple_low', 'multiple_high', 'multiple_nan', 'fit_short', 'fit_nan'):
        try:
            f, lab = features.copy(), labels.copy()
            if kind == 'columns':
                f = f.iloc[:, ::-1]
            elif kind == 'label_axis':
                lab.index = lab.index + pd.Timedelta(days=1)
            elif kind == 'unordered':
                f, lab = f.iloc[::-1], lab.iloc[::-1]
            elif kind == 'duplicate':
                f.index = f.index.where(np.arange(400) != 1, f.index[0])
                lab.index = f.index
            elif kind == 'timezone':
                f.index = f.index.tz_localize('Asia/Shanghai')
                lab.index = f.index
            elif kind == 'infinite_x':
                f.iloc[80, 0] = np.inf
            elif kind == 'infinite_y':
                lab.iloc[80, 0] = np.inf
            elif kind == 'unpaired_maturity':
                lab.iloc[80, 1] = pd.NaT
            elif kind == 'not_future':
                lab.iloc[80, 1] = axis[80]
            elif kind.startswith('alpha_'):
                kernel.fit(x, y, test, ridge_alpha={'alpha_low': .999, 'alpha_high': 100.001, 'alpha_int': 10}[kind])
                raise AssertionError('Bad alpha accepted')
            elif kind.startswith('multiple_'):
                kernel.fit(x, y, test, huber_multiple={'multiple_low': .499, 'multiple_high': 3.001, 'multiple_nan': np.nan}[kind])
                raise AssertionError('Bad multiple accepted')
            elif kind == 'fit_short':
                kernel.fit(x[:39], y[:39], test)
                raise AssertionError('Short fit accepted')
            else:
                bad = y.copy()
                bad[0] = np.nan
                kernel.fit(x, bad, test)
                raise AssertionError('Nonfinite fit accepted')
            kernel.forecasts(f, lab)
        except ValueError:
            refused.append(kind)
        else:
            raise AssertionError('Bad input accepted: ' + kind)
    result = {'status': 'PASS', 'synthetic_only': True, 'real_inputs_read': 0,
              'accounts': 0, 'experiments_allocated': 0, 'new_statistics': 0,
              'checks': checks, 'check_count': len(checks), 'rejections': refused,
              'rejection_count': len(refused), 'synthetic_annual_models': 6,
              'source_sha256': {name: sha256((WORK / name).read_bytes()).hexdigest()
                                for name in ('huber_kernel.py', 'checks.py')},
              'counterevidence': 'rare large gains may be suppressed; prior top-profit concentration and conditional-gain support remain',
              'original_native_parameter_domains': {'lookback': [40, 120], 'holding': [1, 60], 'ridge_alpha': [1., 100.]},
              'new_huber_multiple_domain': [.5, 3.]}
    (WORK / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({'status': 'PASS', 'checks': len(checks), 'refusals': len(refused), 'real_inputs': 0})


if __name__ == '__main__':
    run()
