"""EX098 pure score/availability/fit/vote causal checks, no real data."""
from hashlib import sha256
import importlib
import itertools
import json
from pathlib import Path
import sys
import types
import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = next(p for p in WORK.parents if (p / 'pyproject.toml').exists())
PACKAGE = types.ModuleType('_s013_agreement_pure')
PACKAGE.__path__ = [str(WORK)]
sys.modules[PACKAGE.__name__] = PACKAGE
k = importlib.import_module(PACKAGE.__name__ + '.agreement_kernel')


def run():
    axis = pd.bdate_range('2021-01-01', periods=64)
    cases = list(itertools.product((-1., 0., 1., np.nan), repeat=3))
    model = pd.DataFrame(cases, index=axis, columns=k.MODELS)
    voted = k.aggregate(model)
    for i, case in enumerate(cases):
        valid = all(np.isfinite(value) for value in case)
        assert bool(voted.all_available.iloc[i]) is valid
        if valid:
            count = sum(value > 0 for value in case)
            assert voted.positive_votes.iloc[i] == count
            assert voted.vote_score.iloc[i] == float(count >= 2)
        else:
            assert pd.isna(voted.positive_votes.iloc[i]) and pd.isna(voted.vote_score.iloc[i])
    rng = np.random.default_rng(98)
    tx = rng.uniform(-.5, .5, (180, 14))
    tx[:, 8] = 0.
    y = .01 + .02 * tx[:, 0] + .03 * tx[:, 13] + rng.normal(0, .002, len(tx))
    prediction, fit = k.fit_joint(tx, y, tx)
    beta = np.asarray(fit['coefficients'])
    assert abs(beta[1]) > .005 and abs(beta[14]) > .005 and beta[9] == 0.
    design = np.column_stack((np.ones(len(tx)), tx))
    penalty = np.diag(np.r_[0., np.full(14, 10.)])
    expected_beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    np.testing.assert_allclose(beta, expected_beta, atol=1e-14, rtol=1e-12)
    np.testing.assert_allclose(prediction, design @ expected_beta, atol=1e-14, rtol=1e-12)
    assert fit['max_abs_gradient'] < 1e-12 and not fit['intercept_penalized']
    axis = pd.bdate_range('2020-09-01', periods=400).as_unit('ns')
    f = pd.DataFrame(rng.normal(size=(400, 14)), index=axis, columns=k.FEATURES)
    f.iloc[120, 4] = np.nan
    yy = .003 + .005 * (f.iloc[:, 0] > 0).to_numpy() + rng.normal(0, .002, len(f))
    yy[-5:] = np.nan
    ends = pd.Series(axis, index=axis).shift(-5)
    labels = pd.DataFrame({'return_4': yy, 'label_end_return_4': ends}, index=axis)
    labels.iloc[40, 1] = axis[100]
    scores, traces = k.forecasts(f, labels)
    assert scores.loc[axis.year == 2020, list(k.MODELS)].isna().all().all()
    assert scores.iloc[120][list(k.MODELS)].isna().all()
    assert scores.iloc[-5:].all_available.all() and scores.iloc[-5:].vote_score.notna().all()
    cart, ct = k.tree.forecasts(f, labels)
    robust, ht = k.huber.forecasts(f, labels)
    pd.testing.assert_series_equal(scores.cart_net, cart.cart_net, check_exact=True)
    pd.testing.assert_series_equal(scores.huber_net, robust.huber_net, check_exact=True)
    assert traces['cart_net'] == ct and traces['huber_net'] == ht
    cut = axis[axis.year == 2022][0]
    keep = axis <= cut
    prefix, prefix_traces = k.forecasts(f.loc[keep], labels.loc[keep])
    pd.testing.assert_frame_equal(prefix, scores.loc[keep], check_exact=False, atol=1e-14, rtol=0)
    np.testing.assert_array_equal(prefix.vote_score, scores.loc[keep].vote_score)
    for name in k.MODELS:
        for left, right in zip(prefix_traces[name], traces[name]):
            omit = ('test_positions', 'test_feature_n')
            assert {key:value for key,value in left.items() if key not in omit} == {key:value for key,value in right.items() if key not in omit}
    badfuture = labels.copy()
    badfuture.loc[badfuture.label_end_return_4 >= cut, 'return_4'] = .9
    changed, changed_traces = k.forecasts(f, badfuture)
    pd.testing.assert_frame_equal(changed, scores, check_exact=True)
    assert changed_traces == traces
    futuref = f.copy()
    futuref.loc[axis > cut] *= -10
    changed, changed_traces = k.forecasts(futuref, labels)
    pd.testing.assert_frame_equal(changed.loc[keep], scores.loc[keep], check_exact=True)
    assert changed_traces == traces
    for trace in traces['joint_ridge']:
        if trace['available']:
            assert trace['fit']['max_abs_gradient'] < 1e-10
            assert trace['train_n'] >= 40
            assert all(axis[i].year >= 2020 and axis[i].year < trace['year'] and labels.label_end_return_4.iloc[i] < pd.Timestamp(trace['first_test']) for i in trace['train_positions'])
    # A varied target with exactly zero MAD leaves Huber NA; never two-model rescue.
    madzero = labels.copy()
    madzero.return_4 = np.where(np.arange(len(axis)) % 10 == 0, .01, .003)
    madzero.loc[madzero.label_end_return_4.isna(), 'return_4'] = np.nan
    zero, ztr = k.forecasts(f, madzero)
    known = axis.year > 2020
    assert zero.loc[known, 'joint_ridge'].notna().any() and zero.loc[known, 'cart_net'].notna().any()
    assert zero.loc[known, 'huber_net'].isna().all() and zero.loc[known, 'vote_score'].isna().all()
    assert all(row['reason'] in ('NO_TEST_YEAR', 'ZERO_MAD_WITH_VARIED_TARGET') for row in ztr['huber_net'])
    for alpha, multiple, depth, leaf in ((1., .5, 1, 20), (100., 3., 4, 120)):
        k.hyperparameters(alpha, multiple, depth, leaf)
    refused = []
    for alpha, multiple, depth, leaf in ((1,1.345,2,40),(0.,1.345,2,40),(101.,1.345,2,40),(10.,.49,2,40),(10.,3.1,2,40),(10.,1.345,0,40),(10.,1.345,5,40),(10.,1.345,True,40),(10.,1.345,2,19),(10.,1.345,2,121)):
        try:
            k.forecasts(f, labels, ridge_alpha=alpha, huber_multiple=multiple, tree_depth=depth, minimum_leaf=leaf)
        except ValueError:
            refused.append(str((alpha,multiple,depth,leaf)))
        else:
            raise AssertionError('Invalid hyperparameters accepted')
    for invalid in (model.iloc[:, ::-1], model.assign(joint_ridge=np.inf)):
        try:
            k.aggregate(invalid)
        except ValueError:
            refused.append('bad_model_columns_or_inf')
        else:
            raise AssertionError('Invalid current votes accepted')
    copied = {'tree_kernel.py': ROOT/'.tmp/s013-new-goal/cart_net/tree_kernel.py',
              'huber_kernel.py': ROOT/'.tmp/s013-new-goal/huber_net/huber_kernel.py'}
    for name, old in copied.items():
        assert (WORK/name).read_bytes() == old.read_bytes()
        assert (WORK/name).read_bytes() == (WORK/'strategy_runtime/strategies'/name).read_bytes()
    assert (WORK/'agreement_kernel.py').read_bytes() == (WORK/'strategy_runtime/strategies/agreement_kernel.py').read_bytes()
    output = {'status':'PASS','synthetic_only':True,'real_inputs_read':0,'real_inputs':0,'new_accounts':0,'experiments_allocated':0,
        'checks':['Current fixed2of3 strict-positive64 truth cells and all3 availability','JointRidge all14 rather than confirmation-only','Unpenalized intercept and stationary closed-form coefficients',
          'Exact CART/Huber copied scores and traces','Annual mature common40 training and delayed labels','2020NA/missing features/current unknowntruth tail predicts',
          'Causal prefix and future truth/features invariant','ZeroMAD varied Huber NA never rescued by two available models','Full six effective domains and illegal inputs','Frozen core copies exact; aggregate is vote not expectedreturn'],
        'check_count':10,'rejections':refused,'rejection_count':len(refused),'vote_truth_cells':64,
        'source_sha256':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('agreement_kernel.py','tree_kernel.py','huber_kernel.py','checks.py')},
        'copied_frozen_sha256':{name:sha256(old.read_bytes()).hexdigest() for name,old in copied.items()}}
    (WORK/'checks.json').write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print({'status':'PASS','checks':10,'rejections':len(refused),'real_inputs':0})


if __name__ == '__main__':
    run()
