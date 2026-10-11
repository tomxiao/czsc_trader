"""EX081 immutable fixed nested context study; zero accounts/providers."""
from datetime import date
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import create_experiment, ExperimentRequest
from czsc_trader.research_tools.context import ExperimentRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution as base

WORK = ROOT / '.tmp/s013-confirm-context'
OUT = ROOT / '.tmp/s013-confirm-context-result'
read, digest, write, public, put = base.read, base.digest, base.write, base.public, base.put


def check(plan):
    for name, expected in plan['source_files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen source drift: ' + name)
    for ref in (*plan['input_references'].values(), plan['continuation_budget_reference']):
        public(ref)
    authority = read(public(plan['continuation_budget_reference']))
    if authority['reserved_experiment_sequence'] != [f'EX{i:03}' for i in range(79, 89)]:
        raise ValueError('Exact10round authority')


def stage():
    plan = read(OUT / 'plan.json')
    check(plan)
    exp = ExperimentRef.from_dict(plan['experiment'])
    refs = read(exp.resolve(ROOT) / 'protocols/method_references.json')
    if read(public(refs['plan.json'])) != plan:
        raise ValueError('Published prospective differs')
    return exp, plan


def inputs(plan):
    def frame(key):
        value = pd.read_csv(public(plan['input_references'][key]), index_col='signal_date', float_precision='round_trip')
        value.index = pd.to_datetime(value.index).as_unit('ns')
        return value
    features, labels, prices = frame('features.csv'), frame('labels.csv'), frame('prices.csv')
    labels['label_end_return_4'] = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    axis = features.index
    if len(axis) != 1635 or axis[0] != pd.Timestamp('2020-01-02') or axis[-1] != pd.Timestamp('2026-09-29') or not axis.equals(prices.index[1:-1]):
        raise ValueError('Original1635T and full native price axis')
    raw_y = prices['open'].shift(-5) / prices['open'].shift(-1) * (.999 / 1.001) - 1
    maturity = pd.Series(prices.index, index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4, raw_y.reindex(axis), atol=2e-13, rtol=2e-11, equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(), maturity.reindex(axis).to_numpy())
    rows = read(public(plan['input_references']['prior_scores.json']))['forecasts']
    prior_axis = pd.DatetimeIndex(pd.to_datetime([r['signal_date'] for r in rows])).as_unit('ns')
    if not prior_axis.equals(axis):
        raise ValueError('Prior forecast axis changed')
    kernel = base.load('context_kernel_inputs', WORK / 'kernel.py')
    prior = pd.DataFrame([[r['scores'][m] for m in kernel.MODELS[:3]] for r in rows], index=axis, columns=kernel.MODELS[:3]).astype(float)
    prior_truth = np.array([r['target'] if r['target'] is not None else np.nan for r in rows])
    np.testing.assert_allclose(prior_truth, labels.return_4, atol=2e-13, rtol=2e-11, equal_nan=True)
    np.testing.assert_array_equal([r['truth_missing'] for r in rows], labels.return_4.isna())
    np.testing.assert_array_equal([r['feature_complete'] for r in rows], np.isfinite(features.to_numpy()).all(axis=1))
    return features, labels, prior


def declare():
    plan = read(WORK / 'prospective.json')
    check(plan)
    if read(WORK / 'focused_checks.json')['status'] != 'PASS':
        raise ValueError('Synthetic checks required')
    ctx = base.common().context(1)
    exp = create_experiment(ctx, ExperimentRequest('确认信息与涨跌状态的最小机制对照', '控制原确认分数与20日涨跌方向后，单一交互项是否增加固定四日净机会识别能力？', date(2026, 10, 12)))
    if exp.experiment_id != 'EX081_20261012':
        raise ValueError('Slot3 must beEX081; never allocate again')
    plan = {**plan, 'experiment': exp.to_dict()}
    write(OUT / 'plan.json', plan)
    path = exp.resolve(ROOT)
    write(path / 'protocols/plan.json', plan)
    refs = {'plan.json': put(ctx, exp, OUT / 'plan.json'), 'focused_checks.json': put(ctx, exp, WORK / 'focused_checks.json')}
    for name in plan['source_files']:
        refs[name] = put(ctx, exp, ROOT / name)
        if (ROOT / name).is_relative_to(ROOT / '.tmp'):
            with (path / 'src' / Path(name).name).open('xb') as stream:
                stream.write((ROOT / name).read_bytes())
    write(path / 'protocols/method_references.json', refs)
    print({'experiment': exp.experiment_id, 'slot': 3, 'accounts': 0}, flush=True)


def study():
    exp, plan = stage()
    write(OUT / 'study_attempt_v2.json', {'status': 'STARTED', 'analyze_calls_maximum': 1, 'new_accounts': 0})
    features, labels, prior = inputs(plan)
    kernel = base.load('context_primary_kernel', WORK / 'kernel.py')
    scores, result = kernel.analyze(features, labels, prior)
    with (OUT / 'forecasts.csv').open('x', encoding='utf-8', newline='\n') as stream:
        scores.to_csv(stream, index_label='signal_date', float_format='%.17g')
    write(OUT / 'statistics.json', result)
    write(OUT / 'input_checks.json', {'status': 'PASS', 'original14': list(features.columns), 'signals': len(features),
                                    'mature_price_labels_exact': True, 'original_scores_reused': list(prior.columns),
                                    'new_accounts': 0, 'provider_calls': 0, 'labels_from_original_native_HFQ_OPEN': True})
    write(OUT / 'study_complete.json', {'status': 'COMPLETE', 'analyze_calls': 1, 'new_annual_models': result['new_annual_models'], 'statistics_sha256': digest(OUT / 'statistics.json'), 'new_accounts': 0})
    ctx = base.common().context(1)
    refs = {name: put(ctx, exp, OUT / name) for name in ('forecasts.csv', 'statistics.json', 'input_checks.json', 'study_complete.json')}
    write(exp.resolve(ROOT) / 'protocols/result_references.json', refs)
    print({'experiment': exp.experiment_id, 'status': 'STUDY_COMPLETE', 'annual_models': result['new_annual_models'], 'accounts': 0}, flush=True)


def audit():
    exp, plan = stage()
    refs = read(exp.resolve(ROOT) / 'protocols/result_references.json')
    features, labels, prior = inputs(plan)
    scores = pd.read_csv(public(refs['forecasts.csv']), index_col='signal_date', float_precision='round_trip')
    scores.index = pd.to_datetime(scores.index).as_unit('ns')
    report = read(public(refs['statistics.json']))
    oracle = base.load('context_independent_audit', WORK / 'audit.py')
    proof = oracle.verify(features, labels, prior, scores, report)
    proof['result_references'] = refs
    proof['plan_reference'] = read(exp.resolve(ROOT) / 'protocols/method_references.json')['plan.json']
    write(OUT / 'verification.json', proof)
    ctx = base.common().context(1)
    ref = put(ctx, exp, OUT / 'verification.json')
    write(exp.resolve(ROOT) / 'protocols/audit_reference.json', ref)
    print({'status': proof['status'], 'bootstrap_checks': proof['bootstrap_quantities'] * proof['bootstrap_replicates'], 'accounts': 0}, flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'declare':
        raise ValueError('Repair driver cannot allocate another experiment')
    repair = read(ROOT / 'research/S013/experiments/EX081_20261012/protocols/caller_repair.json')
    if digest(Path(__file__)) != repair['revised_driver_sha256']:
        raise ValueError('Frozen caller repair source drift')
    {'study': study, 'audit': audit}[sys.argv[1]]()
