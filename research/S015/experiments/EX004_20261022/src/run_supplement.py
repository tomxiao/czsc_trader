"""Public TDR account evaluation; Optuna owns proposed parameter configurations."""
# ruff: noqa: E402
# Native thread budgets must be fixed before importing numeric libraries in spawned workers.
import argparse
import json
import os
from datetime import date
from pathlib import Path
from hashlib import sha256
from collections.abc import Mapping

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'

import pandas as pd
import optuna
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    publish_evidence_many)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvaluationResources,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    EvaluationEvidenceWrite)
from strategy_runtime import StrategyCandidate, implementation_sha256

ROOT=Path.cwd()
EXPERIMENT=ExperimentRef('S015','EX004_20261022')
EROOT=EXPERIMENT.resolve(ROOT)
WORK=ROOT/'research/S015/assets/runs/EX004_20261022/range_weights'
SOURCE=EROOT/'src/strategy_runtime'


def save(path, data):
    def plain(value):
        if isinstance(value,Mapping):
            return {k:plain(v) for k,v in value.items()}
        if isinstance(value,(tuple,list)):
            return [plain(v) for v in value]
        return value
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(plain(data),ensure_ascii=False,indent=2,default=str),encoding='utf-8',newline='\n')


def candidate(number,parameters):
    module,qualname='range_weight_reversal','RangeWeightReversal'
    files=[f'strategies/{module}.py']
    payload={'decision_feedback':'MARKET_INTENT','runtime':{
        'module':f'strategy_runtime.strategies.{module}','qualname':qualname,
        'contract_version':2,'source_files':files,
        'source_sha256':implementation_sha256(files,source_root=SOURCE)},'parameters':parameters}
    return StrategyCandidate('S015',f'C{number:04d}',payload,SOURCE)


def request(number,parameters):
    c=candidate(number,parameters)
    return EvaluationRequest(ROOT,EXPERIMENT.experiment_id,c,{
        'candidate_id':c.reference_id,'source_files':list(c.payload['runtime']['source_files']),
        'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',
        (EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),),date(2026,10,21),100000.,
        (EvaluationCost('standard',.001),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000)),workers=1)


def summarize(req,result):
    run=result.runs[0]
    m=run.observation.to_dict()
    account=run.execution.account_daily
    trades=run.execution.trades
    orders=run.execution.orders
    info={'candidate_id':req.strategy.candidate_id,'parameters':dict(req.strategy.payload['parameters']),
          'observation':m,'benchmark_metrics':run.buyhold.metrics,'evaluation_id':run.identity.evaluation_id,
          'request_hash':result.request_hash,'result_hash':result.result_hash,
          'columns':{'account':list(account),'trades':list(trades),'orders':list(orders)},
          'orders_count':len(orders),'fills_count':len(run.execution.fills),
          'input_bindings':{k:v.to_dict() for k,v in req.input_bindings.items()}}
    dates=pd.DatetimeIndex(pd.to_datetime(account['date'])).normalize()
    exits=pd.to_datetime(trades.loc[trades['status']=='CLOSED','exit_date']).dt.normalize()
    counts=pd.Series(0,index=dates,dtype=int)
    counts=counts.add(exits.value_counts(),fill_value=0).reindex(dates).astype(int)
    rolling=counts.rolling(60).sum().dropna()
    benchmark_cagr=(float(run.buyhold.account_daily['equity'].iloc[-1])/100000.)**(252/len(account))-1
    checks={'return':m['net_cagr']>=1.5*benchmark_cagr if benchmark_cagr>0 else m['net_cagr']>0,
        'relative_drawdown':abs(m['max_drawdown'])<=.8*abs(run.buyhold.metrics['max_drawdown']),
        'absolute_drawdown':abs(m['max_drawdown'])<=.25,
        'frequency_median':float(rolling.median())>=6,
        'frequency_coverage':int((rolling>=3).sum())*10>=9*len(rolling)}
    if len(account)!=434 or len(rolling)!=375 or sum(counts)!=m['closed_trades']:
        raise AssertionError('frequency denominator or actual closed ledger inconsistent')
    if rolling.median()!=m['rolling_closed_trades_median']:
        raise AssertionError('SE median differs from direct exit ledger')
    info.update(benchmark_cagr=benchmark_cagr,frequency={'windows':len(rolling),
        'median':float(rolling.median()),'windows_at_least_3':int((rolling>=3).sum()),
        'fraction_at_least_3':float((rolling>=3).mean())},checks=checks,passed=all(checks.values()),
        economic_path_sha256=sha256(account[['date','cash','quantity','equity']].to_csv(index=False,float_format='%.9f').encode()).hexdigest(),
        order_status_counts={str(k):int(v) for k,v in orders['status'].value_counts().items()})
    fills=run.execution.fills
    exposure=account['quantity'].astype(float)*account['close'].astype(float)/account['equity'].astype(float)
    info['execution_diagnostics']={'fees':float(fills['fees'].sum()),
        'buy_gross':float((fills.loc[fills.side=='BUY','quantity']*fills.loc[fills.side=='BUY','price']).sum()),
        'sell_gross':float((fills.loc[fills.side=='SELL','quantity']*fills.loc[fills.side=='SELL','price']).sum()),
        'mean_realized_weight':float(exposure.mean()),'max_realized_weight':float(exposure.max()),
        'target_mean':float(account['target_position'].mean()),'zero_target_days':int((account['target_position']==0).sum()),
        'closed_trades':int((trades.status=='CLOSED').sum())}
    return info


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['precheck','initial','followup','boundary'])
    args=parser.parse_args()
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=EvaluationResources(8,1,13))
    protocol=json.loads((EROOT/'protocols/supplement_search.json').read_text(encoding='utf-8'))
    if args.mode=='precheck':
        p=protocol['initial_configurations'][7]
        req=ctx.evaluation.prepare(request(900,p))
        serial=ctx.evaluation.evaluate(req)
        outcomes=ctx.evaluation.evaluate_many((req,req))
        for outcome in outcomes:
            assert outcome.status.value=='SUCCEEDED',outcome.error
            for name in ('decisions','orders','fills','trades','account_daily'):
                pd.testing.assert_frame_equal(getattr(serial.runs[0].execution,name),getattr(outcome.result.runs[0].execution,name))
            assert outcome.result.result_hash==serial.result_hash
        ref=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'parallel_precheck',req,serial))
        row=summarize(req,serial)
        row['evidence']=ref.to_dict()
        save(WORK/'precheck.json',row)
        print(json.dumps({'precheck':'PASS','executions':3,'metrics':row['observation']},ensure_ascii=False),flush=True)
        return
    configs=protocol['initial_configurations'] if args.mode=='initial' else json.loads((EROOT/f'protocols/{args.mode}.json').read_text(encoding='utf-8'))['configurations']
    first_id={'initial':200,'followup':300,'boundary':400}[args.mode]
    study=optuna.create_study(directions=['maximize','minimize'],sampler=optuna.samplers.RandomSampler(seed=13))
    for p in configs:
        study.enqueue_trial(p)
    domain={k:list(dict.fromkeys(p[k] for p in configs)) for k in configs[0]}
    specs=[]
    for i in range(len(configs)):
        trial=study.ask()
        p={k:trial.suggest_categorical(k,v) for k,v in domain.items()}
        specs.append((trial,first_id+i,p))
    assert len({json.dumps(p,sort_keys=True) for _,_,p in specs})==len(configs)
    save(WORK/f'{args.mode}_proposals.json',[{'trial':t.number,'candidate_id':f'C{i:04d}','parameters':p} for t,i,p in specs])
    all_rows=[]
    for start in range(0,len(specs),8):
        block=specs[start:start+8]
        reqs=tuple(ctx.evaluation.prepare(request(i,p)) for t,i,p in block)
        outcomes=ctx.evaluation.evaluate_many(reqs)
        publications=[]
        rows=[]
        for (trial,i,p),req,out in zip(block,reqs,outcomes,strict=True):
            if out.status.value!='SUCCEEDED':
                study.tell(trial,state=optuna.trial.TrialState.FAIL)
                raise RuntimeError(out.error)
            row=summarize(req,out.result)
            row['trial']=trial.number
            study.tell(trial,[row['observation']['net_cagr'],abs(row['observation']['max_drawdown'])])
            rows.append(row)
            publications.append(EvaluationEvidenceWrite(EXPERIMENT,f'{args.mode}_{i:04d}',req,out.result))
        for row,pub in zip(rows,publish_evidence_many(ctx,tuple(publications)),strict=True):
            assert pub.status.value=='PUBLISHED',pub.error
            row['evidence']=pub.reference.to_dict()
        all_rows.extend(rows)
        save(WORK/f'{args.mode}_results.json',all_rows)
        print(json.dumps({'completed':len(all_rows),'passed':sum(r['passed'] for r in all_rows)},ensure_ascii=False),flush=True)
    save(WORK/f'optuna_{args.mode}_trials.json',[{'number':t.number,'parameters':t.params,'values':t.values,'state':str(t.state)} for t in study.trials])

if __name__=='__main__':
    main()
