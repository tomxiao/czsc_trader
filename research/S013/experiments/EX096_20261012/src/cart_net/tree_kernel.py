"""Fixed annual original14 net-return CART: depth2, minleaf40, no lookahead.

This changes expression, not market information. Greedy strictly positive root
improvement cannot discover a perfectly symmetric XOR; no depth2 peek rescues it.
The effective native domains are depth1..4 and leaf20..120. Defaults are the
fixed2/40 centre; exposing legal coordinates never searches their values.
"""
from math import ceil, fsum

import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
MODELS = ('training_mean', 'cart_net')
MAX_DEPTH = 2
MIN_LEAF = 40
MIN_TRAIN = 40
QUANTILES = (.25, .5, .75)
PROSPECTIVE_NATIVE_DOMAINS = {'max_depth': [1, 4], 'minimum_leaf': [20, 120]}


def mean_sse(values):
    values = [float(value) for value in values]
    if not values or not all(np.isfinite(value) for value in values):
        raise ValueError('Nonempty finite target required')
    mean = fsum(values) / len(values)
    sse = fsum((value - mean) ** 2 for value in values)
    return mean, sse


def ranks(train, values):
    train, values = np.asarray(train, float), np.asarray(values, float)
    if train.ndim != 1 or values.ndim != 1 or not len(train) or not np.isfinite(train).all() or not np.isfinite(values).all():
        raise ValueError('Finite one-dimensional training/test ranks required')
    ordered = np.sort(train, kind='stable')
    return (np.searchsorted(ordered, values, side='left') + np.searchsorted(ordered, values, side='right')) / (2 * len(train)) - .5


def tree_parameters(max_depth=MAX_DEPTH, minimum_leaf=MIN_LEAF):
    if type(max_depth) is not int or not 1 <= max_depth <= 4:
        raise ValueError('Tree depth integer full domain1..4')
    if type(minimum_leaf) is not int or not 20 <= minimum_leaf <= 120:
        raise ValueError('Minimum leaf integer full domain20..120')


def fit_tree(train, target, *, max_depth=MAX_DEPTH, minimum_leaf=MIN_LEAF):
    tree_parameters(max_depth, minimum_leaf)
    train, target = np.asarray(train, float), np.asarray(target, float)
    if train.ndim != 2 or train.shape[1] != len(FEATURES) or target.ndim != 1 or len(target) != len(train) or len(train) < max(MIN_TRAIN, minimum_leaf) or not np.isfinite(train).all() or not np.isfinite(target).all():
        raise ValueError('Complete finite original14 training and at least max(40, minimum_leaf) targets required')

    def node(positions, depth):
        values = target[positions]
        mean, sse = mean_sse(values)
        result = {'depth': depth, 'positions': [int(i) for i in positions], 'n': len(positions), 'mean': mean, 'sse': sse,
                  'leaf': True, 'reason': 'DEPTH_LIMIT' if depth >= max_depth else 'NO_STRICT_SSE_IMPROVEMENT',
                  'feature_index': None, 'feature_name': None, 'quantile': None, 'threshold': None,
                  'split_sse': None, 'gain': None, 'candidates': [], 'left': None, 'right': None}
        if depth >= max_depth:
            return result
        best, best_sse = None, sse
        for feature in range(len(FEATURES)):
            ordered = np.sort(train[positions, feature], kind='stable')
            for quantile in QUANTILES:
                location = ceil(len(positions) * quantile) - 1
                threshold = float(ordered[location])
                left = positions[train[positions, feature] <= threshold]
                right = positions[train[positions, feature] > threshold]
                valid = len(left) >= minimum_leaf and len(right) >= minimum_leaf
                left_sse = mean_sse(target[left])[1] if valid else None
                right_sse = mean_sse(target[right])[1] if valid else None
                split_sse = fsum((left_sse, right_sse)) if valid else None
                result['candidates'].append({'feature_index': feature, 'feature_name': FEATURES[feature],
                    'quantile': quantile, 'orderstat_position': location, 'threshold': threshold,
                    'left_n': len(left), 'right_n': len(right), 'valid': bool(valid),
                    'left_sse': left_sse, 'right_sse': right_sse, 'split_sse': split_sse})
                if valid and split_sse < best_sse:
                    best_sse = split_sse
                    best = (feature, quantile, threshold, left, right)
        if best is None:
            return result
        feature, quantile, threshold, left, right = best
        result.update({'leaf': False, 'reason': 'STRICT_SSE_IMPROVEMENT', 'feature_index': feature,
                       'feature_name': FEATURES[feature], 'quantile': quantile, 'threshold': threshold,
                       'split_sse': best_sse, 'gain': sse - best_sse,
                       'left': node(left, depth + 1), 'right': node(right, depth + 1)})
        return result

    return node(np.arange(len(train)), 0)


def predict_tree(tree, test):
    test = np.asarray(test, float)
    if test.ndim != 2 or test.shape[1] != len(FEATURES) or not np.isfinite(test).all():
        raise ValueError('Finite ranked original14 test matrix required')
    prediction = []
    for row in test:
        current = tree
        while not current['leaf']:
            current = current['left'] if row[current['feature_index']] <= current['threshold'] else current['right']
        prediction.append(float(current['mean']))
    return np.asarray(prediction, float)


def validate(features, labels):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()) or not len(axis):
        raise ValueError('Complete ordered naive midnight signal axis required')
    if tuple(features.columns) != FEATURES or labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns) or not labels.index.equals(axis):
        raise ValueError('Exact original14 and paired aligned h4 labels required')
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError('Naive midnight maturity dates required')
    finite = np.isfinite(y)
    if np.isinf(x).any() or np.isinf(y).any() or not np.array_equal(finite, ends.notna()) or (y[finite] <= -1).any() or (ends[finite].to_numpy() <= axis[finite].to_numpy()).any():
        raise ValueError('Finite or missing original inputs, paired future maturity and positive price factors')
    return axis, x, y, ends


def forecasts(features, labels, *, max_depth=MAX_DEPTH, minimum_leaf=MIN_LEAF):
    tree_parameters(max_depth, minimum_leaf)
    axis, x, y, ends = validate(features, labels)
    complete = np.isfinite(x).all(axis=1)
    scores = pd.DataFrame(np.nan, index=axis, columns=MODELS)
    traces = []
    for year in range(2021, 2027):
        days = axis[axis.year == year]
        first = days[0] if len(days) else None
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year)
        train &= (ends < first).to_numpy() if first is not None else False
        test = complete & (axis.year == year)
        row = {'year': year, 'first_test': first.isoformat() if first is not None else None,
               'train_positions': np.flatnonzero(train).tolist(), 'test_positions': np.flatnonzero(test).tolist(),
               'train_n': int(train.sum()), 'future_test_count_gate': False,
               'max_maturity': ends[train].max().isoformat() if train.any() else None,
               'max_depth': max_depth, 'minimum_leaf': minimum_leaf, 'train_cdfs': None, 'tree': None, 'reason': None}
        if first is None or train.sum() < max(MIN_TRAIN, minimum_leaf):
            row['reason'] = 'NO_YEAR' if first is None else 'INSUFFICIENT_MATURE_TRAINING'
            traces.append(row)
            continue
        tr = np.column_stack([ranks(x[train, j], x[train, j]) for j in range(len(FEATURES))])
        te = np.column_stack([ranks(x[train, j], x[test, j]) for j in range(len(FEATURES))])
        tree = fit_tree(tr, y[train], max_depth=max_depth, minimum_leaf=minimum_leaf)
        scores.loc[test, 'training_mean'] = mean_sse(y[train])[0]
        scores.loc[test, 'cart_net'] = predict_tree(tree, te)
        row.update({'train_cdfs': [np.sort(x[train, j], kind='stable').tolist() for j in range(len(FEATURES))], 'tree': tree})
        traces.append(row)
    return scores, traces
