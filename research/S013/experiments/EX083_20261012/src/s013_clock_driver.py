"""EX083 fixed reuse-only clock attribution: allocation, study, scalar audit."""
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

WORK, OUT = ROOT / '.tmp/s013-calendar-clock', ROOT / '.tmp/s013-calendar-clock-result'
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
    quota = read(public(plan['input_references']['prior_budget.json']))
    if (quota['started'], quota['completed'], quota['next_allowed']) != (4, 4, 'EX083'):
        raise ValueError('Exact fifth quota slot')


def stage():
    plan = read(OUT / 'plan.json')
    check(plan)
    exp = ExperimentRef.from_dict(plan['experiment'])
    refs = read(exp.resolve(ROOT) / 'protocols/method_references.json')
    if read(public(refs['plan.json'])) != plan:
        raise ValueError('Published prospective plan differs')
    return exp, plan


def inputs(plan):
    def frame(key):
        f = pd.read_csv(public(plan['input_references'][key]), index_col='signal_date', float_precision='round_trip')
        f.index = pd.to_datetime(f.index).as_unit('ns')
        return f
    scores, labels, prices = frame('forecasts.csv'), frame('labels.csv'), frame('prices.csv')
    axis = scores.index
    if len(axis) != 1635 or axis[0] != pd.Timestamp('2020-01-02') or axis[-1] != pd.Timestamp('2026-09-29') or not axis.equals(prices.index[1:-1]):
        raise ValueError('Original1635signal axis and native price axis')
    labels['label_end_return_4'] = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    raw_y = prices['open'].shift(-5) / prices['open'].shift(-1) * (.999 / 1.001) - 1
    maturity = pd.Series(prices.index, index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4, raw_y.reindex(axis), atol=2e-13, rtol=2e-11, equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(), maturity.reindex(axis).to_numpy())
    previous = read(public(plan['input_references']['prior_statistics.json']))
    proof = read(public(plan['input_references']['prior_verification.json']))
    if proof['status'] != 'PASS' or proof['result_references']['forecasts.csv'] != plan['input_references']['forecasts.csv']:
        raise ValueError('Exact audited EX082 forecasts required')
    kernel = base.load('clock_inputs_definition', WORK / 'kernel.py')
    kernel.validate(scores, labels)
    return scores, labels, previous


def declare():
    plan = read(WORK / 'prospective.json')
    check(plan)
    if read(WORK / 'focused_checks.json')['status'] != 'PASS':
        raise ValueError('Synthetic checks first')
    c = base.common()
    ctx = c.context(1)
    exp = create_experiment(ctx, ExperimentRequest('日期机会的固定时钟及集中盈利归因', 'EX082日期代理的改善是否依赖特定入场时钟或少数大赚机会，而非稳定的信息增量？', date(2026, 10, 12)))
    if exp.experiment_id != 'EX083_20261012':
        raise ValueError('Exact fifth slot; never allocate again')
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
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'slot': 5, 'new_models': 0, 'accounts': 0}, flush=True)


def study():
    exp, plan = stage()
    write(OUT / 'study_attempt.json', {'status': 'STARTED', 'analyze_calls_maximum': 1, 'new_models': 0, 'new_accounts': 0})
    scores, labels, previous = inputs(plan)
    kernel = base.load('clock_primary_kernel', WORK / 'kernel.py')
    result = kernel.analyze(scores, labels, previous)
    write(OUT / 'statistics.json', result)
    write(OUT / 'input_checks.json', {'status': 'PASS', 'signals': len(scores), 'models': list(scores.columns),
          'forecast_sha256': plan['input_references']['forecasts.csv']['sha256'], 'forecast_reuse': 'EXACT',
          'original_greedy_records': 'EXACT', 'original_native_HFQ_OPEN_labels': 'PASS', 'provider_calls': 0, 'new_accounts': 0})
    write(OUT / 'study_complete.json', {'status': 'COMPLETE', 'analyze_calls': 1, 'new_annual_models': 0,
          'schedule_count': result['schedule_count'], 'statistics_sha256': digest(OUT / 'statistics.json'), 'new_accounts': 0})
    c = base.common()
    ctx = c.context(1)
    refs = {name: put(ctx, exp, OUT / name) for name in ('statistics.json', 'input_checks.json', 'study_complete.json')}
    write(exp.resolve(ROOT) / 'protocols/result_references.json', refs)
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'status': 'STUDY_COMPLETE', 'new_models': 0, 'schedules': result['schedule_count'], 'accounts': 0}, flush=True)


def audit():
    exp, plan = stage()
    refs = read(exp.resolve(ROOT) / 'protocols/result_references.json')
    scores, labels, _ = inputs(plan)
    report = read(public(refs['statistics.json']))
    oracle = base.load('clock_independent_audit', WORK / 'audit.py')
    proof = oracle.verify(scores, labels, report)
    proof['result_references'] = refs
    proof['plan_reference'] = read(exp.resolve(ROOT) / 'protocols/method_references.json')['plan.json']
    write(OUT / 'verification.json', proof)
    c = base.common()
    ref = put(c.context(1), exp, OUT / 'verification.json')
    write(exp.resolve(ROOT) / 'protocols/audit_reference.json', ref)
    assert not c.SOURCE_CALLS
    print({'status': proof['status'], 'schedules': 36, 'bootstrap_checks': 4500, 'accounts': 0}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'study': study, 'audit': audit}[sys.argv[1]]()
