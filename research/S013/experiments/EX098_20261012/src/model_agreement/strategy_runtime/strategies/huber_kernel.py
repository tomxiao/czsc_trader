"""Fixed Huber net-payoff expression; pure arithmetic, no input/account I/O.

Huber uses unscaled training MAD, never clips targets, and retains every mature
sample.  This is a new loss expression of existing information, not new alpha.
"""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20',
            'feature_overnight_down_energy20', 'turnover20', 'volume_ratio20')
MODELS = ('training_mean', 'huber_net')
MAX_ITERATIONS = 500
GRADIENT_TOLERANCE = 1e-10
COEFFICIENT_TOLERANCE = 1e-12


def hyperparameters(ridge_alpha, huber_multiple):
    if type(ridge_alpha) is not float or not np.isfinite(ridge_alpha) or not 1. <= ridge_alpha <= 100.:
        raise ValueError('Original ridge_alpha finite float1..100 required')
    if type(huber_multiple) is not float or not np.isfinite(huber_multiple) or not .5 <= huber_multiple <= 3.:
        raise ValueError('Huber multiple finite float .5..3 required')


def ecdf_rank(train, values):
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side='left') +
            np.searchsorted(ordered, values, side='right')) / (2 * len(train)) - .5


def objective_gradient(design, target, coefficients, delta, ridge_alpha):
    residual = target - design @ coefficients
    absolute = np.abs(residual)
    rho = np.where(absolute <= delta, .5 * residual ** 2,
                   delta * (absolute - .5 * delta))
    psi = np.where(absolute <= delta, residual, delta * np.sign(residual))
    penalty = np.r_[0., np.full(design.shape[1] - 1, ridge_alpha)]
    loss = float(rho.sum() + .5 * np.sum(penalty * coefficients ** 2))
    gradient = -(design.T @ psi) + penalty * coefficients
    if not np.isfinite(loss) or not np.isfinite(gradient).all():
        raise ValueError('Finite true Huber objective and gradient required')
    return loss, gradient


def fit(train, target, test, ridge_alpha=10.0, huber_multiple=1.345):
    hyperparameters(ridge_alpha, huber_multiple)
    train, target, test = np.asarray(train, float), np.asarray(target, float), np.asarray(test, float)
    if train.ndim != 2 or test.ndim != 2 or train.shape[1] != test.shape[1] or target.ndim != 1 or len(target) != len(train) or len(train) < 40:
        raise ValueError('Aligned two-dimensional complete training/test and at least40 targets required')
    if not all(np.isfinite(value).all() for value in (train, target, test)):
        raise ValueError('Only finite fit arrays accepted')
    median = float(np.median(target))
    mad = float(np.median(np.abs(target - median)))
    delta = huber_multiple * mad
    constant = bool((target == target[0]).all())
    proof = {'status': 'AVAILABLE', 'reason': None, 'training_n': len(target),
             'ridge_alpha': ridge_alpha, 'huber_multiple': huber_multiple,
             'training_median': median, 'training_mad': mad, 'delta': delta,
             'mad_normalisation_multiplier': 1.0, 'targets_clipped': False,
             'intercept_penalized': False, 'coefficients': None, 'iterations': 0,
             'max_abs_gradient': None, 'max_coefficient_change': None,
             'objective': None, 'constant_target_definition': False}
    if not np.isfinite(delta):
        raise ValueError('Finite training-only Huber scale required')
    if mad == 0:
        if not constant:
            proof.update(status='UNAVAILABLE', reason='ZERO_MAD_WITH_VARIED_TARGET')
            return np.full(len(test), np.nan), proof
        beta = np.r_[target[0], np.zeros(train.shape[1])]
        proof.update(coefficients=beta.tolist(), max_abs_gradient=0.,
                     max_coefficient_change=0., objective=0., constant_target_definition=True)
        return np.full(len(test), float(target[0])), proof
    design = np.column_stack((np.ones(len(train)), train))
    query = np.column_stack((np.ones(len(test)), test))
    penalty = np.diag(np.r_[0., np.full(train.shape[1], ridge_alpha)])
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ target)
    for iteration in range(1, MAX_ITERATIONS + 1):
        residual = target - design @ beta
        absolute = np.abs(residual)
        weights = np.ones(len(target))
        outside = absolute > delta
        weights[outside] = delta / absolute[outside]
        updated = np.linalg.solve(design.T @ (weights[:, None] * design) + penalty,
                                  design.T @ (weights * target))
        change = float(np.max(np.abs(updated - beta)))
        beta = updated
        loss, gradient = objective_gradient(design, target, beta, delta, ridge_alpha)
        norm = float(np.max(np.abs(gradient)))
        if not np.isfinite(beta).all() or not np.isfinite(change):
            raise ValueError('Finite IRLS coefficients and change required')
        proof.update(coefficients=beta.tolist(), iterations=iteration, max_abs_gradient=norm,
                     max_coefficient_change=change, objective=loss)
        if norm <= GRADIENT_TOLERANCE and change <= COEFFICIENT_TOLERANCE:
            predictions = query @ beta
            if not np.isfinite(predictions).all():
                raise ValueError('Finite Huber forecasts required, no clipping/fallback')
            return predictions, proof
    proof.update(status='FAILED', reason='HUBER_IRLS_NONCONVERGENCE_500')
    raise ValueError(proof)


def validate(features, labels):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or not len(axis) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Nonempty unique ordered naive midnight signal dates required')
    if tuple(features.columns) != FEATURES or not labels.index.equals(axis) or labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns):
        raise ValueError('Exact original14, paired h4 labels and common axis required')
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()) or np.isinf(x).any() or np.isinf(y).any():
        raise ValueError('Finite or missing numeric inputs and naive midnight maturity required')
    if not np.array_equal(np.isfinite(y), ends.notna().to_numpy()) or (ends[np.isfinite(y)].to_numpy() <= axis[np.isfinite(y)].to_numpy()).any():
        raise ValueError('Paired future label maturity required')
    return axis, x, y, ends


def forecasts(features, labels, ridge_alpha=10.0, huber_multiple=1.345):
    hyperparameters(ridge_alpha, huber_multiple)
    axis, x, y, ends = validate(features, labels)
    complete = np.isfinite(x).all(axis=1)
    scores = pd.DataFrame(np.nan, index=axis, columns=MODELS)
    traces = []
    for year in range(2021, 2027):
        test_days = axis[axis.year == year]
        first = test_days[0] if len(test_days) else None
        training = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year)
        training &= (ends < first).to_numpy() if first is not None else False
        test = complete & (axis.year == year)
        positions, test_positions = np.flatnonzero(training), np.flatnonzero(test)
        reason = 'NO_TEST_YEAR' if first is None else 'INSUFFICIENT_MATURE_TRAINING' if len(positions) < 40 else None
        row = {'year': year, 'first_test': first.isoformat() if first is not None else None,
               'train_positions': positions.tolist(), 'test_positions': test_positions.tolist(),
               'train_n': len(positions), 'test_feature_n': len(test_positions),
               'max_maturity': ends[training].max().isoformat() if len(positions) else None,
               'future_test_count_gate': False, 'available': False, 'reason': reason,
               'cdf_rule': 'training midpointECDF-.5, all complete mature training',
               'cdf_training_sorted': None, 'target_mean': None, 'fit': None}
        if reason is None:
            tx = np.column_stack([ecdf_rank(x[training, j], x[training, j]) for j in range(14)])
            vx = np.column_stack([ecdf_rank(x[training, j], x[test, j]) for j in range(14)])
            prediction, proof = fit(tx, y[training], vx, ridge_alpha, huber_multiple)
            row.update(cdf_training_sorted=[np.sort(x[training, j]).tolist() for j in range(14)],
                       target_mean=float(y[training].mean()), fit=proof,
                       available=proof['status'] == 'AVAILABLE', reason=proof['reason'])
            if row['available']:
                scores.loc[test, 'training_mean'] = row['target_mean']
                scores.loc[test, 'huber_net'] = prediction
        traces.append(row)
    return scores, traces
