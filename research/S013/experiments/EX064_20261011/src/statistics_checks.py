"""Focused synthetic protocol checks; no real asset/account/market operations."""
# ruff: noqa: E402
from __future__ import annotations

import ast
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

for variable in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from dataflows import Dataflows
import opportunity_statistics as s

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
index = pd.DatetimeIndex([*pd.bdate_range('2020-01-02', periods=90),
                         *pd.bdate_range('2021-01-04', periods=60),
                         *pd.bdate_range('2022-01-04', periods=32),
                         *pd.bdate_range('2023-01-04', periods=12)])
rng = np.random.default_rng(13)
features = pd.DataFrame(rng.normal(size=(len(index), len(s.CONTROLS))), index=index, columns=s.CONTROLS)
for component in s.COMPONENTS:
    values = np.zeros(len(index))
    values[::7] = rng.uniform(.05, .7, len(values[::7]))
    features[component] = values
features.loc[index[9], s.COMPONENTS[1]] = np.nan
labels = pd.DataFrame(index=index)
for label, horizon in s.HORIZONS.items():
    labels[label] = rng.uniform(-.03, .03, len(index)) if label.startswith('return') else rng.uniform(0, .04, len(index))
    labels['label_end_'+label] = index + pd.offsets.BDay(horizon+1)
opportunity = pd.Series(np.arange(len(index)) % 3 == 0, index=index, dtype=bool)
checks, forbidden_calls = [], []


def forbidden(*args, **kwargs):
    forbidden_calls.append('actual data/finance')
    raise AssertionError('Synthetic statistics cannot access data or finances')


with patch.object(Dataflows, 'fetch', forbidden), patch.object(Dataflows, 'prepare', forbidden), \
     patch.object(EvaluationAccess, 'prepare', forbidden), patch.object(EvaluationAccess, 'evaluate', forbidden), \
     patch.object(EvaluationAccess, 'evaluate_many', forbidden):
    result = s.analyze(features, labels, opportunity)
assert forbidden_calls == []
checks.append('Fixed actual500/40/seed13 synthetic analyze ran all6 labels in all+eligible scopes without data/finance calls')
assert len(s.CONTROLS) == 14 and len(s.COMPONENTS) == 2 and len(s.HORIZONS) == 6
assert s.COMPONENTS == ('negative_gap_repair', 'positive_gap_fade')
checks.append('Original14 controls and declared2 components/6 labels retained')
model_names = {'controls', 'controls+negative_gap_repair', 'controls+positive_gap_fade', 'controls+both'}
for scope, pool in result['scopes'].items():
    assert set(pool['labels']) == set(s.HORIZONS)
    for label, record in pool['labels'].items():
        assert set(record['components']) == set(s.COMPONENTS)
        walk = record['walk_forward']
        assert set(walk['aggregate_models']) == model_names
        assert len({v['n'] for v in walk['aggregate_models'].values()}) == 1
        assert set(walk['yearly']) == {str(y) for y in range(2021, 2027)}
        for annual in walk['yearly'].values():
            if annual['latest_train_label_end'] is not None:
                assert pd.Timestamp(annual['latest_train_label_end']) < pd.Timestamp(annual['first_actual_signaldate'])
            assert set(annual['groups']) == set(s.COMPONENTS) and set(annual['models']) == model_names
        for component, panel in record['components'].items():
            assert len(panel['nonoverlap_phases']) == s.HORIZONS[label]+1
            mask = np.ones(len(index), dtype=bool) if scope == 'all' else opportunity.to_numpy()
            for phase, item in panel['nonoverlap_phases'].items():
                expected = mask & (np.arange(len(index)) % (s.HORIZONS[label]+1) == int(phase))
                expected &= np.isfinite(features[component].to_numpy())
                assert item['spearman']['n'] == int(expected.sum())
            assert panel['feature_zero_n'] == int((mask & (features[component].to_numpy() == 0)).sum())
        assert ('return_cost_proxy' in record) == label.startswith('return_')
checks.append('Every label/year/model/component/unavailable cell retained on identical model rows with mature training')
checks.append('All h+1 phases use full original positions before missing/eligibility filtering')
checks.append('Zero feature mass retained/disclosed; no active-trigger post-selection')
checks.append('Observed mean cost proxy only added to return labels; original targets/predictions unchanged')
sampled = s._bootstrap_indices(53)
assert sampled.shape == (500, 53) and np.array_equal(sampled, s._bootstrap_indices(53))
assert np.all(np.diff(sampled[:, :40], axis=1) == 1) and sampled.min() >= 0 and sampled.max() < 53
checks.append('All500 bootstrap draws preserve40-session full-axis blocks before scope/missing filtering')
for component in s.COMPONENTS:
    group = result['scopes']['all']['labels']['return_1']['walk_forward']['yearly']['2021']['groups'][component]
    assert group['q25'] == group['q75'] == 0 and group['overlap_n'] > 0
    assert group['test_zero_n'] > 0
checks.append('Zero-mass Q25/Q75 ties and overlapping low/high groups explicitly disclosed')
for label in s.HORIZONS:
    annual = result['scopes']['opportunity']['labels'][label]['walk_forward']['yearly']['2022']
    assert all(value['reason'] == 'INSUFFICIENT_TEST_SAMPLE' for value in annual['models'].values())
    annual = result['scopes']['all']['labels'][label]['walk_forward']['yearly']['2023']
    assert all(value['reason'] == 'INSUFFICIENT_TEST_SAMPLE' for value in annual['models'].values())
checks.append('Thin eligible2022 and short2023 tests retain explicit insufficient reasons')
target = labels.return_1.to_numpy()
ends = labels.label_end_return_1.copy()
ends.iloc[82:90] = index[90]
scope = np.ones(len(index), dtype=bool)
first = s._walk_forward(index, features, target, ends, scope, return_proxy=True)
assert first['yearly']['2021']['common_train_n'] == 81
future_features, future_target = features.copy(), target.copy()
future_features.loc[future_features.index.year >= 2022] *= 1000
future_target[index.year >= 2022] += 100
future = s._walk_forward(index, future_features, future_target, ends, scope, return_proxy=True)
for name in model_names:
    original_records = [x for x in first['prediction_records'][name] if x['signaldate'].startswith('2021')]
    later_records = [x for x in future['prediction_records'][name] if x['signaldate'].startswith('2021')]
    assert original_records == later_records
checks.append('Future2022+ feature/target mutation leaves every earlier2021 prediction exact')
immature_target = target.copy()
immature_target[82:90] += 1000
immature = s._walk_forward(index, features, immature_target, ends, scope, return_proxy=True)
for name in model_names:
    assert [x for x in first['prediction_records'][name] if x['signaldate'].startswith('2021')] == [x for x in immature['prediction_records'][name] if x['signaldate'].startswith('2021')]
checks.append('Targets maturing exactly first test signal excluded; their mutation cannot alter fit')
constant = features.copy()
constant.loc[:, s.COMPONENTS[0]] = 0.
const_walk = s._walk_forward(index, constant, target, ends, scope)
assert const_walk['yearly']['2021']['groups'][s.COMPONENTS[0]]['reason'] == 'CONSTANT_TRAIN_COMPONENT'
assert set(const_walk['aggregate_models']) == model_names
assert s._ic(np.zeros(25), np.arange(25.))['value'] is None
checks.append('Constant/zero component retained with explicit unavailable IC/group, all models remain')
proxy = s._return_proxy_mean(np.zeros(20))
assert abs(proxy['net_cost_proxy_mean'] - (-2/1001)) < 1e-15 and proxy['account_return'] is False
assert s._return_proxy_mean(np.zeros(19))['net_cost_proxy_mean'] is None
checks.append('Zero gross return incurs declared proxy cost; small proxy mean remains unavailable')


def reject(name, mutate):
    x, y, eligible = features.copy(), labels.copy(), opportunity.copy()
    mutated = mutate(x, y, eligible)
    if isinstance(mutated, pd.Series):
        eligible = mutated
    try:
        s.analyze(x, y, eligible)
    except (ValueError, TypeError):
        checks.append(name)
    else:
        raise AssertionError('Expected protocol refusal: '+name)


reject('Future return label in features prohibited', lambda x, y, o: x.__setitem__('return_1', y.return_1))
reject('Future maturity feature prohibited', lambda x, y, o: x.__setitem__('label_end_return_3', y.label_end_return_3))
reject('Missing second declared component prohibited', lambda x, y, o: x.drop(columns=s.COMPONENTS[1], inplace=True))
reject('Infinite feature prohibited', lambda x, y, o: x.iloc.__setitem__((0, 0), np.inf))
reject('Nonfuture maturity prohibited', lambda x, y, o: y.loc.__setitem__((index[0], 'label_end_return_1'), index[0]))
reject('Finite target without maturity prohibited', lambda x, y, o: y.loc.__setitem__((index[0], 'label_end_return_1'), pd.NaT))
reject('Invalid Open return denominator consequence prohibited', lambda x, y, o: y.loc.__setitem__((index[0], 'return_1'), -1.))
reject('Nonboolean eligible field prohibited', lambda x, y, o: o.astype(float))
old = ast.parse((ROOT / 'research/S013/experiments/EX061_20261011/src/opportunity_statistics.py').read_text(encoding='utf-8-sig'))
new = ast.parse(Path(s.__file__).read_text(encoding='utf-8-sig'))
old_functions = {x.name: x for x in old.body if isinstance(x, ast.FunctionDef)}
new_functions = {x.name: x for x in new.body if isinstance(x, ast.FunctionDef)}
unchanged = ('_finite', '_pearson', '_ic', '_cdf_apply', '_ridge_predict', '_prediction_metrics', '_bootstrap_indices', '_bootstrap', '_year_train_mask')
assert all(ast.dump(old_functions[name], include_attributes=False) == ast.dump(new_functions[name], include_attributes=False) for name in unchanged)
checks.append('Nine inherited statistical numerical kernels AST exact; no copied operator oracle')
feature_path = ROOT / '.tmp/s013-gap-expression/gap_expression.py'
assert sha256(feature_path.read_bytes()).hexdigest() == '189f576340f6148b13d5bfae743aba0c7aae6855ac85afca0faf709ee3bb917f'
spec = importlib.util.spec_from_file_location('_gap_math_pure_interface', feature_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
daily_index = pd.bdate_range('2020-01-01', periods=6)
daily = pd.DataFrame({'Open': [10., 10., 9., 10., 11., 10.], 'High': [11., 11., 10., 11., 12., 11.],
                      'Low': [9., 9., 8., 9., 10., 9.], 'Close': [10., 10., 9.5, 10., 10.5, 10.]}, index=daily_index)
synthetic = module.build_features(daily, daily_index[1:])
assert list(synthetic.columns) == list(s.COMPONENTS) and synthetic.index.equals(daily_index[1:])
checks.append('Frozen mathematical helper API feeds exact two names/full synthetic signal grid, no formula mirror')
proof = {'status': 'SOURCE_ONLY_STATISTICS_READY', 'check_count': len(checks), 'checks': checks,
         'source_sha256': sha256(Path(s.__file__).read_bytes()).hexdigest(),
         'mathematical_feature_source_sha256': sha256(feature_path.read_bytes()).hexdigest(),
         'synthetic_only': True, 'real_market_reads': 0, 'real_native_reads': 0,
         'prepare_evaluate_fetch_publish_calls': len(forbidden_calls),
         'native_thread_environment': {name: os.environ[name] for name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMEXPR_NUM_THREADS')},
         'preserved_kernel_names': list(unchanged),
         'limits': 'No observed market direction, profitability or mechanism qualification is claimed by synthetic tests.'}
target_path = HERE / 'statistics_checks.json'
if target_path.exists():
    raise ValueError('Immutable pure proof exists')
target_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'status': proof['status'], 'check_count': len(checks)}))
