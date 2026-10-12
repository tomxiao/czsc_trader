"""Pure CART fixed-centre structural and causal checks; zero real input."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

import tree_kernel as k

WORK = Path(__file__).resolve().parent


def run():
    corners = np.repeat(np.asarray([[0., 0.], [0., 1.], [1., 0.], [1., 1.]]), 80, axis=0)
    x = np.zeros((320, 14))
    x[:, :2] = corners
    and_y = corners[:, 0] * corners[:, 1]
    tree = k.fit_tree(x, and_y)
    prediction = k.predict_tree(tree, x)
    np.testing.assert_array_equal(prediction, and_y)
    design = np.column_stack((np.ones(len(x)), x[:, :2]))
    additive = design @ np.linalg.lstsq(design, and_y, rcond=None)[0]
    assert np.mean((additive - and_y) ** 2) > .01
    assert tree['feature_index'] == 0 and tree['quantile'] == .25
    xor_y = (corners[:, 0] != corners[:, 1]).astype(float)
    xor_tree = k.fit_tree(x, xor_y)
    assert xor_tree['leaf'] and xor_tree['reason'] == 'NO_STRICT_SSE_IMPROVEMENT'
    np.testing.assert_array_equal(k.predict_tree(xor_tree, x), np.full(len(x), .5))
    tied_x = np.repeat(x[:, :1], 14, axis=1)
    tied_tree = k.fit_tree(tied_x, x[:, 0])
    assert tied_tree['feature_index'] == 0 and tied_tree['quantile'] == .25
    assert tied_tree['threshold'] == 0
    equality = np.zeros((1, 14))
    equality[0, 0] = tied_tree['threshold']
    assert k.predict_tree(tied_tree, equality)[0] == tied_tree['left']['mean']
    no_split = k.fit_tree(np.zeros((79, 14)), np.arange(79.))
    assert no_split['leaf'] and all(not candidate['valid'] for candidate in no_split['candidates'])
    single40 = k.fit_tree(np.zeros((40, 14)), np.full(40, .003))
    assert single40['leaf'] and k.predict_tree(single40, np.zeros((1, 14)))[0] == .003

    def leaves(node):
        return [node] if node['leaf'] else leaves(node['left']) + leaves(node['right'])

    assert all(node['depth'] <= 2 and node['n'] >= 40 for node in leaves(tree))
    assert all(node['reason'] == 'DEPTH_LIMIT' for node in leaves(tree) if node['depth'] == 2)
    ordered = np.arange(200, dtype=float)
    xx = np.zeros((200, 14))
    xx[:, 0] = ordered
    split = k.fit_tree(xx, np.where(ordered < 100, -.01, .02))
    root_candidates = split['candidates'][:3]
    assert [row['orderstat_position'] for row in root_candidates] == [49, 99, 149]
    assert [row['threshold'] for row in root_candidates] == [49., 99., 149.]

    axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
    rng = np.random.default_rng(96)
    features = pd.DataFrame(rng.normal(size=(400, 14)), index=axis, columns=k.FEATURES)
    features.iloc[120, 7] = np.nan
    y = .002 + .006 * ((features.iloc[:, 0] > 0) & (features.iloc[:, 1] > 0)).to_numpy() + rng.normal(0, .003, 400)
    y[-5:] = np.nan
    ends = pd.Series(axis, index=axis).shift(-5)
    labels = pd.DataFrame({'return_4': y, 'label_end_return_4': ends}, index=axis)
    labels.iloc[40, 1] = axis[100]
    scores, traces = k.forecasts(features, labels)
    explicit_scores, explicit_traces = k.forecasts(features, labels, max_depth=2, minimum_leaf=40)
    pd.testing.assert_frame_equal(scores, explicit_scores, check_exact=True)
    assert traces == explicit_traces
    for depth, leaf in ((1, 20), (4, 120)):
        edge = k.fit_tree(x, and_y, max_depth=depth, minimum_leaf=leaf)
        assert all(row['depth'] <= depth and row['n'] >= leaf for row in leaves(edge))
    assert k.fit_tree(x[:40], and_y[:40], minimum_leaf=20)['n'] == 40
    assert k.fit_tree(x[:120], and_y[:120], minimum_leaf=120)['n'] == 120
    for n, leaf in ((39, 20), (119, 120)):
        try:
            k.fit_tree(x[:n], and_y[:n], minimum_leaf=leaf)
        except ValueError:
            pass
        else:
            raise AssertionError('Training must retain max(40,minimum_leaf) support')
    assert scores.loc[axis.year == 2020].isna().all().all()
    assert scores.iloc[120].isna().all()
    assert scores.iloc[-5:].notna().all().all()
    first = next(row for row in traces if row['year'] == 2021)
    assert 40 not in first['train_positions']
    for row in traces:
        if row['reason'] is None:
            assert all(axis[j].year >= 2020 and axis[j].year < row['year'] and labels.label_end_return_4.iloc[j] < pd.Timestamp(row['first_test']) for j in row['train_positions'])
    second = next(row for row in traces if row['year'] == 2022)
    assert 40 in second['train_positions'] and 120 not in second['train_positions']
    assert all(pos in second['train_positions'] for pos in first['train_positions'])
    cut = axis[axis.year == 2022][0]
    keep = axis <= cut
    prefix, prefix_trace = k.forecasts(features.loc[keep], labels.loc[keep])
    pd.testing.assert_frame_equal(prefix, scores.loc[keep], check_exact=True)
    altered = labels.copy()
    altered.loc[altered.label_end_return_4 >= cut, 'return_4'] = .9
    changed, changed_trace = k.forecasts(features, altered)
    pd.testing.assert_frame_equal(changed, scores, check_exact=True)
    assert [row['tree'] for row in changed_trace] == [row['tree'] for row in traces]
    assert [row['train_cdfs'] for row in prefix_trace] == [row['train_cdfs'] for row in traces]
    future_features = features.copy()
    future_features.loc[axis > cut] *= -10
    changed, changed_trace = k.forecasts(future_features, labels)
    pd.testing.assert_frame_equal(changed.loc[keep], scores.loc[keep], check_exact=True)
    assert [row['tree'] for row in changed_trace] == [row['tree'] for row in traces]

    refusals = []
    for depth, leaf in ((0, 40), (5, 40), (True, 40), (2., 40), (2, 19), (2, 121), (2, True), (2, 40.)):
        try:
            k.forecasts(features, labels, max_depth=depth, minimum_leaf=leaf)
        except ValueError:
            refusals.append('invalid_depth_leaf_' + str((depth, leaf)))
        else:
            raise AssertionError('Illegal numeric CART domain accepted')
    for kind in ('infinite_feature', 'wrong_columns', 'unordered_axis', 'unaligned_labels', 'unpaired_truth', 'not_future', 'bad_price_factor'):
        bad_x, bad_y = features.copy(), labels.copy()
        if kind == 'infinite_feature':
            bad_x.iloc[0, 0] = np.inf
        elif kind == 'wrong_columns':
            bad_x = bad_x.iloc[:, ::-1]
        elif kind == 'unordered_axis':
            bad_x, bad_y = bad_x.iloc[::-1], bad_y.iloc[::-1]
        elif kind == 'unaligned_labels':
            bad_y.index = bad_y.index + pd.Timedelta(days=1)
        elif kind == 'unpaired_truth':
            bad_y.iloc[0, 1] = pd.NaT
        elif kind == 'not_future':
            bad_y.iloc[0, 1] = axis[0]
        else:
            bad_y.iloc[0, 0] = -1
        try:
            k.forecasts(bad_x, bad_y)
        except ValueError:
            refusals.append(kind)
        else:
            raise AssertionError('Invalid CART forecast input accepted: ' + kind)
    for kind in ('less_than40', 'nonfinite_target', 'bad_width', 'missing_prediction'):
        try:
            if kind == 'less_than40':
                k.fit_tree(x[:39], and_y[:39])
            elif kind == 'nonfinite_target':
                target = and_y.copy()
                target[0] = np.nan
                k.fit_tree(x, target)
            elif kind == 'bad_width':
                k.fit_tree(x[:, :2], and_y)
            else:
                k.predict_tree(tree, np.full((1, 14), np.nan))
        except ValueError:
            refusals.append(kind)
        else:
            raise AssertionError('Invalid CART tree input accepted: ' + kind)
    output = {'status': 'PASS', 'synthetic_only': True, 'real_inputs': 0, 'real_inputs_read': 0,
        'new_accounts': 0, 'experiments_allocated': 0, 'new_models_on_real_inputs': 0,
        'checks': ['AND interaction exactly fits while additive cannot', 'Symmetric XOR root no gain remains single leaf',
                   'Exact ties choose first feature/quantile and <= threshold branch', 'Depth2 and40min leaves maintained',
                   'No valid split is valid tree leaf, not fallback', 'Orderstat quartiles use ceil(nq)-1 with no interpolation',
                   'Original14 complete/mature/2020-start annual expanding support', 'Delayed labels and missing features excluded',
                   '2020 prediction NA and unavailable future-label tail still predicted', 'Prefix and future mutation preserve tree/CDF/past prediction',
                   'Previous-year observations retained across annual update', 'Strict illegal input refusal',
                   'Effective depth1..4/leaf20..120 domains and explicit centre identical',
                   'Basic mature training remains max(40,minimum_leaf) at all legal parameters'],
        'check_count': 14, 'rejections': refusals, 'rejection_count': len(refusals),
        'synthetic_only_annual_trees': sum(row['reason'] is None for row in traces),
        'AND_additive_mse': float(np.mean((additive - and_y) ** 2)), 'AND_cart_mse': float(np.mean((prediction - and_y) ** 2)),
        'symmetric_XOR_unlearned_mse': .25, 'fixed_centre': {'max_depth': 2, 'minimum_leaf': 40},
        'prospective_native_domains': k.PROSPECTIVE_NATIVE_DOMAINS,
        'source_sha256': {name: sha256((WORK / name).read_bytes()).hexdigest() for name in ('tree_kernel.py', 'checks.py')}}
    with (WORK / 'checks.json').open('w', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print({'status': 'PASS', 'checks': output['check_count'], 'rejections': len(refusals), 'real_inputs': 0})


if __name__ == '__main__':
    run()
