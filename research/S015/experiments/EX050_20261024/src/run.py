"""Fixed P2 allocation comparison through public TDR, no search or refitting."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import argparse
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, open_research_execution,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    EvaluationEvidenceWrite,
)
from strategy_runtime import StrategyCandidate, ParameterSet, implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
OLD = HERE.parent / 'EX042_20261023'
SOURCE = HERE / 'src/strategy_runtime'
FILES = ['strategies/cycle_risk_allocation.py']
EX = ExperimentRef('S015', HERE.name)
MODES = ('fixed100', 'fixed50', 'fixed75', 'risk_reject', 'risk_half')


def read(path):
    return json.loads(path.read_bytes())


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def save(path, value):
    path.write_text(json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def context(workers=4):
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
                                   resources=ExecutionResources(workers, 1, 13))


def material(path):
    return publish_evidence(context(1), MaterialEvidenceWrite(EX, path.stem, path.read_bytes(),
        {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}[path.suffix], path.suffix[1:]))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def authenticated_sources():
    refs = read(OLD / 'others/account_refs.json')
    keys = ('others/models_A.json', 'others/training_manifest.json', 'others/training_audit.json',
            'others/runtime_checks.json', 'src/strategy_runtime/strategies/price_information.py')
    chosen = {key: refs[key] for key in keys}
    for key, value in chosen.items():
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() == (OLD / key).read_bytes()
    audit = read(OLD / 'others/training_audit.json')
    assert audit['status'] == 'PASS' and audit['training_samples_strictly_known_before_release']
    for key, digest in audit['sha256'].items():
        assert sha256((OLD / key).read_bytes()).hexdigest() == digest
    # This source owns the original objective arithmetic, authenticated by its published reference.
    summary_ref = EvidenceRef.from_dict(read(HERE.parent / 'EX033_20261023/others/results.json')['summary_source'])
    summary_path = HERE.parent / 'EX016_20261023/src/suite.py'
    assert summary_ref.resolve(ROOT).read_bytes() == summary_path.read_bytes()
    chosen['summary_source'] = summary_ref.to_dict()
    plan = read(OLD / 'protocols/stage3_plan.json')
    for key, value in plan['sources'].items():
        EvidenceRef.from_dict(value).resolve(ROOT)
        chosen['training_input:' + key] = value
    return chosen, module(summary_path, 'ex050_authenticated_summary')


def params(mode):
    return {'allocation_mode': mode, 'hold': 3, 'schedule': read(OLD / 'others/models_A.json')}


def candidate(index):
    return StrategyCandidate('S015', f'C{5000+index:04d}', {
        'decision_feedback': 'MARKET_INTENT', 'parameters': params(MODES[index]),
        'runtime': {'module': 'strategy_runtime.strategies.cycle_risk_allocation',
                    'qualname': 'CycleRiskAllocation', 'contract_version': 2, 'source_files': FILES,
                    'source_sha256': implementation_sha256(FILES, source_root=SOURCE)}}, SOURCE)


def request(ctx, index):
    strategy = candidate(index)
    return ctx.evaluation.prepare(EvaluationRequest(ROOT, EX.experiment_id, strategy,
        {'candidate_id': strategy.reference_id, 'source_files': FILES,
         'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        '159326.SZ', 'etf', (EvaluationWindow('full', date(2025, 1, 2), date(2026, 10, 21)),
                              EvaluationWindow('s011_common', date(2025, 2, 6), date(2026, 10, 21))),
        date(2026, 10, 21), 100000., (EvaluationCost('standard', .001),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000))))


def prepare():
    assert not (HERE / 'others/protocol_refs.json').exists()
    sources, _ = authenticated_sources()
    protocol = {
        'question': '风险状态分配能否优于一般少持仓，在同一A-path三日意图容器中产生有针对性的目标改善？',
        'authorization': '用户同意切换RSCH、按新资金契约修订阶段二对照方案，并恢复实验并自主完成。',
        'stage': 2, 'configurations': [{'allocation_mode': mode, 'hold': 3} for mode in MODES],
        'execution': 'All five arms CYCLE_TARGET + signal_cash_fraction/entry_cycle, including fixed100. Host adoption locks inclusive-fee budget and target quantity; retries limited by both; no daily equity rebalance.',
        'clock': 'Canonical market-intent clock from EX042: three positive signal days, then one zero day; no same-day re-entry. Risk evaluated for admission/allocation at intention start, no intervening reallocation or early exit. Actual holding can be shorter due to late fill.',
        'arms': {'fixed100': 'path>=0, 100%', 'fixed50': 'path>=0, 50%', 'fixed75': 'path>=0, 75%',
                 'risk_reject': 'path>=0 and risk<=training-fitted median, 100%',
                 'risk_half': 'path>=0; risk<=training-fitted median:100%, else50%'},
        'models': 'Reuse authenticated EX042 A schedule exactly: four path and four volatility features, Ridge10, >=30 mature labels, releases every20 sessions from2025-02-27; no refit, no threshold/hold/fraction search.',
        'windows': '434 (2025-01-02..2026-10-21) and415 (2025-02-06..2026-10-21), independent100k cash. Same original LimitBuyHold, 1% limit buy, market sell, 100-share lots, .001 tick, .001 fee each side, DAILY_RANGE_V3; no forced terminal sale.',
        'targets': 'All original434 center conditions and415 strict return>0.9158029150000013 and DD<0.07248663749114126. No new statistical/economic gates;32 perturbations and fee stress not in stage2.',
        'counts': {'configurations':5, 'formal_account_scenarios':10, 'serial_technical_scenarios':2,
                   'workers':4, 'native_threads':1, 'seed':13},
        'preflight': 'First fixed100 serial with max_workers1, then same request in public evaluate_many; exact result hash and five ledgers. Preserve serial formal evidence and exports, count technical separately.',
        'analysis': 'All objectives, fees, frequency, exposure, closed-cycle gains/losses, rejected/reduced model-ready common events. Cycle attribution and opportunity denominators distinguished from executable counterfactual accounts. Compare dynamic to both fixed reductions without optimizing exposure match.',
        'selection': 'Seen development pool and all prior selection retained; five configurations not independent hypotheses. Fixed50/75 are prospective controls, not ex-post fitted average exposure.',
        'stop': 'If broad reduction explains tradeoff, stop risk-allocation route; targeted benefit retained conditionally for stage3 design only. No P3 activation without a concrete distinguishable holding question.',
        'sources': sources,
        'input_limit': 'Prior EX042 unused intraday Volume discrepancy retained; only OHLC path fields and daily Amount/Volume used. No new external inputs or updated cutoff.',
    }
    save(HERE / 'protocols/allocation.json', protocol)
    refs = {path.relative_to(HERE).as_posix(): material(path).to_dict()
            for path in (HERE / 'protocols/allocation.json', Path(__file__), SOURCE / FILES[0])}
    save(HERE / 'others/protocol_refs.json', refs)
    print('P2_PROTOCOL_AND_SOURCE_PUBLISHED', flush=True)


def authenticate():
    for key, value in read(HERE / 'others/protocol_refs.json').items():
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() == (HERE / key).read_bytes()
    return authenticated_sources()


def check():
    sources, _ = authenticate()
    runtime = module(SOURCE / FILES[0], 'ex050_runtime_check')
    feature_ref = EvidenceRef.from_dict(sources['training_input:others/model_features.csv'])
    x = pd.read_csv(feature_ref.resolve(ROOT)).set_index('date')[list(runtime.COLUMNS)]
    x.index = pd.DatetimeIndex(x.index)
    x['feature_ready'] = True
    x = pd.concat([pd.DataFrame([{**{c:0. for c in runtime.COLUMNS}, 'feature_ready':False}],
                                index=pd.DatetimeIndex(['2024-12-31'])), x])
    outputs = {mode: runtime.intentions(x, params(mode)) for mode in MODES}
    old = module(OLD / 'src/strategy_runtime/strategies/price_information.py', 'ex050_old_runtime')
    historical = old.intentions(x, {'family':'A','mode':'path','hold':3,'exposure':1.,'schedule':params('fixed100')['schedule']})
    for mode, output in outputs.items():
        definition = runtime.CycleRiskAllocation(ParameterSet(params(mode))).definition
        assert definition.decision.output_kind == 'CYCLE_TARGET'
        assert dict(definition.execution.settings['capital']) == {'fee_rate':.001, 'mode':'signal_cash_fraction', 'target_scope':'entry_cycle'}
        if mode != 'risk_reject':
            pd.testing.assert_series_equal(output.target_position, historical.target_position)
        fraction = output.entry_allocation_fraction
        assert fraction[output.target_position.eq(0)].isna().all()
        assert fraction[output.target_position.eq(1)].isin([.5,.75,1.]).all()
        for stop in (1,35,100,200,435):
            pp = params(mode)
            pp['schedule'] = [r for r in pp['schedule'] if r['date'] <= x.index[stop-1].date().isoformat()]
            pd.testing.assert_frame_equal(runtime.intentions(x.iloc[:stop], pp), output.iloc[:stop])
        output.to_csv(HERE / f'others/signals_{mode}.csv', index_label='signal_date')
    # Every held intention keeps the allocation selected at its own start.
    for mode, output in outputs.items():
        opening = output.intent_age.eq(1).cumsum()
        for _, group in output[output.target_position.eq(1)].groupby(opening):
            assert group.entry_allocation_fraction.nunique() == 1
            if mode == 'risk_half':
                assert group.entry_allocation_fraction.iloc[0] == (1. if group.risk_allowed.iloc[0] else .5)
    save(HERE / 'others/runtime_checks.json', {
        'status':'PASS','source_sha256':sha256((SOURCE/FILES[0]).read_bytes()).hexdigest(),
        'authenticated_sources':sources,'model_releases':len(params('fixed100')['schedule']),
        'new_model_fits':0,'feature_rows':434,'checks':['five_CYCLE_TARGET_signal_cash_fraction_contracts',
            'four_path_arms_identical_old_intent_clock','25_physically_truncated_model_and_feature_prefixes',
            'flat_fraction_null','positive_fraction_bounds','within_intention_fraction_locked'],
        'training_causality':'Authenticated prior audit + all model known dates strictly before releases; unchanged40 A-role models. No new fitted coefficients.',
        'limits':'Runtime feature fields are verified against actual bound inputs in the post-account audit; prefix equality does not establish predictive usefulness.'})
    print('P2_RUNTIME_CHECK_PASS', flush=True)


def run():
    sources, suite = authenticate()
    assert read(HERE / 'others/runtime_checks.json')['status'] == 'PASS'
    assert not (HERE / 'others/results.json').exists()
    ctx = context()
    requests = [request(ctx, index) for index in range(5)]
    study = optuna.create_study(directions=['maximize','minimize','maximize','minimize'],
                                sampler=optuna.samplers.RandomSampler(seed=13))
    for index in range(5):
        study.enqueue_trial({'configuration_index':index})
    trials = []
    for index in range(5):
        trial = study.ask()
        assert trial.suggest_int('configuration_index',0,4) == index
        trials.append(trial)
    print('P2_PREPARED_5_REQUESTS', flush=True)
    serial = context(1).evaluation.evaluate(requests[0])
    serial_ref = publish_evidence(context(1), EvaluationEvidenceWrite(EX, 'fixed100_serial_technical', requests[0], serial))
    for run_result in serial.runs:
        for table in ('account_daily','decisions','orders','fills','trades'):
            getattr(run_result.execution,table).to_csv(HERE/f'others/serial_{run_result.window_id}_{table}.csv',index=False)
    save(HERE/'others/serial_precheck.json',{'evidence':serial_ref.to_dict(),'result_hash':serial.result_hash})
    print('P2_SERIAL_COMPLETE',flush=True)
    rows=[]
    with open_research_execution(ctx, experiment=EX) as session:
        for start in range(0,5,4):
            block=requests[start:start+4]
            outcomes=ctx.evaluation.evaluate_many(tuple(block),execution=session)
            for offset,(req,outcome) in enumerate(zip(block,outcomes,strict=True)):
                index=start+offset
                if outcome.status.value != 'SUCCEEDED':
                    save(HERE/'others/technical_failure.json',{'index':index,'status':outcome.status.value,'error':str(outcome.error),'completed':len(rows)})
                    raise RuntimeError(str(outcome.error))
                result=outcome.result
                if index == 0:
                    assert result.result_hash == serial.result_hash
                    for a,b in zip(serial.runs,result.runs,strict=True):
                        for table in ('account_daily','decisions','orders','fills','trades'):
                            pd.testing.assert_frame_equal(getattr(a.execution,table),getattr(b.execution,table))
                row=suite.summary(req,result)
                parameters=plain(row['parameters'])
                schedule=parameters.pop('schedule')
                row['parameters']=parameters
                row['schedule_sha256']=sha256(json.dumps(schedule,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                ref=publish_evidence(ctx,EvaluationEvidenceWrite(EX,row['candidate_id'],req,result))
                row['evidence']=ref.to_dict()
                for account in result.runs:
                    for table in ('account_daily','decisions','orders','fills','trades'):
                        getattr(account.execution,table).to_csv(HERE/f'others/{row["candidate_id"]}_{account.window_id}_{table}.csv',index=False)
                study.tell(trials[index],[row['runs']['full']['net_return'],row['runs']['full']['dd'],row['runs']['s011_common']['net_return'],row['runs']['s011_common']['dd']])
                rows.append(row)
                save(HERE/'others/progress.json',{'rows':rows,'completed':len(rows),'total':5})
                print(row['candidate_id'],MODES[index],{k:{n:v[n] for n in ('net_return','dd','closed','frequency_median','frequency_good')} for k,v in row['runs'].items()},flush=True)
    save(HERE/'others/results.json',{'rows':rows,'new_configurations':5,'account_scenarios':10,
        'technical_precheck_extra_scenarios':2,'serial_evidence':serial_ref.to_dict(),'precheck_five_ledgers_equal':True,
        'qualified_centers':sum(row['both_center_pass'] for row in rows),'summary_source':sources['summary_source'],
        'execution_stats':asdict(session.stats),
        'optuna':[{'number':t.number,'params':t.params,'values':t.values,'state':str(t.state)} for t in study.trials]})
    print('P2_ACCOUNTS_COMPLETE',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('prepare','check','run'))
    {'prepare':prepare,'check':check,'run':run}[parser.parse_args().mode]()
