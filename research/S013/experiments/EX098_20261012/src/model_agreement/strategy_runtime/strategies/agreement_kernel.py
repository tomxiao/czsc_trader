"""Fixed heterogeneous current2of3 agreement, no new information or model IO.

JointRidge uses all14 original predictors. CART/Huber are exact frozen copies.
The aggregate is a binary entry vote, never an expected net return estimator.
"""
import numpy as np
import pandas as pd
from . import tree_kernel as tree
from . import huber_kernel as huber

FEATURES = tree.FEATURES
MODELS = ('joint_ridge', 'cart_net', 'huber_net')
SCORE_COLUMNS = MODELS + ('all_available', 'positive_votes', 'vote_score')


def hyperparameters(ridge_alpha=10.0, huber_multiple=1.345, tree_depth=2, minimum_leaf=40):
    huber.hyperparameters(ridge_alpha, huber_multiple)
    tree.tree_parameters(tree_depth, minimum_leaf)


def fit_joint(train, target, test, ridge_alpha=10.0):
    if type(ridge_alpha) is not float or not np.isfinite(ridge_alpha) or not 1. <= ridge_alpha <= 100.:
        raise ValueError('Finite float shared ridge alpha full domain1..100 required')
    train, target, test = np.asarray(train, float), np.asarray(target, float), np.asarray(test, float)
    if train.ndim != 2 or test.ndim != 2 or train.shape[1] != 14 or test.shape[1] != 14 or target.shape != (len(train),) or len(train) < 40:
        raise ValueError('Complete all14 train/test and at least40 aligned targets required')
    if not all(np.isfinite(values).all() for values in (train, target, test)):
        raise ValueError('Finite all14 joint ridge arrays required')
    mean_x, mean_y = train.mean(axis=0), float(target.mean())
    centered = train - mean_x
    slopes = np.linalg.solve(centered.T @ centered + ridge_alpha * np.eye(14), centered.T @ (target - mean_y))
    beta = np.r_[mean_y - mean_x @ slopes, slopes]
    design = np.column_stack((np.ones(len(train)), train))
    residual = design @ beta - target
    penalty = np.r_[0., np.full(14, ridge_alpha)]
    gradient = design.T @ residual + penalty * beta
    objective = float(.5 * (residual @ residual) + .5 * ridge_alpha * (slopes @ slopes))
    # Fixed row-sized dot products keep output independent of test-batch length.
    prediction = np.asarray([float(row @ beta) for row in np.column_stack((np.ones(len(test)), test))])
    if not np.isfinite(beta).all() or not np.isfinite(gradient).all() or not np.isfinite(objective) or not np.isfinite(prediction).all():
        raise ValueError('Finite joint ridge stationary solution required; no fallback')
    return prediction, {'training_n': len(train), 'ridge_alpha': ridge_alpha,
        'feature_count': 14, 'intercept_penalized': False, 'coefficients': beta.tolist(),
        'gradient': gradient.tolist(), 'max_abs_gradient': float(np.max(np.abs(gradient))), 'objective': objective}


def joint_forecasts(features, labels, ridge_alpha=10.0):
    axis, x, y, ends = tree.validate(features, labels)
    if type(ridge_alpha) is not float or not np.isfinite(ridge_alpha) or not 1. <= ridge_alpha <= 100.:
        raise ValueError('Finite float shared ridge alpha full domain1..100 required')
    complete = np.isfinite(x).all(axis=1)
    scores = pd.Series(np.nan, index=axis, name='joint_ridge')
    traces = []
    for year in range(2021, 2027):
        days = axis[axis.year == year]
        first = days[0] if len(days) else None
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year)
        train &= (ends < first).to_numpy() if first is not None else False
        test = complete & (axis.year == year)
        reason = 'NO_YEAR' if first is None else 'INSUFFICIENT_MATURE_TRAINING' if train.sum() < 40 else None
        row = {'year': year, 'first_test': first.isoformat() if first is not None else None,
            'train_positions': np.flatnonzero(train).tolist(), 'test_positions': np.flatnonzero(test).tolist(),
            'train_n': int(train.sum()), 'max_maturity': ends[train].max().isoformat() if train.any() else None,
            'future_test_count_gate': False, 'available': reason is None, 'reason': reason,
            'train_cdfs': None, 'fit': None}
        if reason is None:
            tx = np.column_stack([tree.ranks(x[train, j], x[train, j]) for j in range(14)])
            vx = np.column_stack([tree.ranks(x[train, j], x[test, j]) for j in range(14)])
            prediction, fit = fit_joint(tx, y[train], vx, ridge_alpha)
            scores.loc[test] = prediction
            row.update(train_cdfs=[np.sort(x[train, j]).tolist() for j in range(14)], fit=fit)
        traces.append(row)
    return scores, traces


def aggregate(model_scores):
    axis = model_scores.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.equals(axis.normalize()) or not len(axis) or tuple(model_scores.columns) != MODELS or not axis.is_unique or not axis.is_monotonic_increasing:
        raise ValueError('Exact ordered aligned three model score columns required')
    values = model_scores.to_numpy(float)
    if np.isinf(values).any():
        raise ValueError('Finite or explicitly unavailable model scores required')
    complete = np.isfinite(values).all(axis=1)
    votes = np.where(complete, (values > 0).sum(axis=1), np.nan)
    scores = model_scores.copy()
    scores['all_available'] = complete
    scores['positive_votes'] = votes
    scores['vote_score'] = np.where(complete, (votes >= 2).astype(float), np.nan)
    return scores


def forecasts(features, labels, *, ridge_alpha=10.0, huber_multiple=1.345, tree_depth=2, minimum_leaf=40):
    hyperparameters(ridge_alpha, huber_multiple, tree_depth, minimum_leaf)
    joint, joint_trace = joint_forecasts(features, labels, ridge_alpha)
    cart, cart_trace = tree.forecasts(features, labels, max_depth=tree_depth, minimum_leaf=minimum_leaf)
    robust, huber_trace = huber.forecasts(features, labels, ridge_alpha, huber_multiple)
    models = pd.DataFrame({'joint_ridge': joint, 'cart_net': cart.cart_net, 'huber_net': robust.huber_net}, index=features.index)
    return aggregate(models), {'joint_ridge': joint_trace, 'cart_net': cart_trace, 'huber_net': huber_trace}
