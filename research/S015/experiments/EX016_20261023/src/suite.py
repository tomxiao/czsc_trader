"""Bounded ten-round research; public complete accounts and explicit dual gates."""
# ruff: noqa: E402
import argparse
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import numpy as np
import pandas as pd
import optuna
from czsc_trader.application import (RepositoryContext,create_research_context,publish_evidence,
    publish_evidence_many,open_research_execution,load_candidate)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,ExecutionResources,
    EvidenceRef,MaterialEvidenceWrite,EvaluationRequest,EvaluationWindow,EvaluationCost,
    EvaluationBenchmark,LimitBuyHold,EvaluationEvidenceWrite,ExecutionCheckpointRequest,CheckpointMode)
from strategy_runtime import StrategyCandidate,implementation_sha256
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
SOURCE = HOME/'src/strategy_runtime'


def read(p):
    return json.loads(p.read_bytes())


def plain(v):
    if isinstance(v,Mapping):
        return {k:plain(x) for k,x in v.items()}
    if isinstance(v,(tuple,list)):
        return [plain(x) for x in v]
    return v


def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(plain(v),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(8,1,13))


def material(ex,name,p):
    return publish_evidence(context(),MaterialEvidenceWrite(ex,name,p.read_bytes(),
        {'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))


def candidate(cid,p):
    if set(p)=={'registered_control'}:
        return load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',p['registered_control']))
    files = ['strategies/pressure_path.py']
    payload = {'decision_feedback':'MARKET_INTENT','parameters':p,'runtime':{
        'module':'strategy_runtime.strategies.pressure_path','qualname':'PressurePath','contract_version':2,
        'source_files':files,'source_sha256':implementation_sha256(files,source_root=SOURCE)}}
    return StrategyCandidate('S015',cid,payload,SOURCE)


def request(ctx,ex,cid,p,windows='both',cost=.001):
    c = candidate(cid,p)
    all_windows = (EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),
                   EvaluationWindow('s011_common',date(2025,2,6),date(2026,10,21)))
    selected = all_windows if windows=='both' else tuple(w for w in all_windows if w.window_id==windows)
    return ctx.evaluation.prepare(EvaluationRequest(ROOT,ex.experiment_id,c,{
        'candidate_id':c.reference_id,'source_files':list(c.payload['runtime']['source_files']),
        'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',selected,
        date(2026,10,21),100000.,(EvaluationCost('standard' if cost==.001 else 'fee_x2',cost),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))


def summary(req,result):
    runs = {}
    for run in result.runs:
        a,t,f = run.execution.account_daily,run.execution.trades,run.execution.fills
        eq = np.r_[100000.,a.equity.to_numpy(float)]
        dd = float(np.max(1-eq/np.maximum.accumulate(eq)))
        net,cagr = float(eq[-1]/100000-1),float((eq[-1]/100000)**(252/len(a))-1)
        exits = pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.normalize()
        ds = pd.DatetimeIndex(pd.to_datetime(a.date)).normalize()
        counts = exits.value_counts().reindex(ds,fill_value=0)
        rolling = counts.rolling(60).sum().dropna()
        b = np.r_[100000.,run.buyhold.account_daily.equity.to_numpy(float)]
        bcagr = float((b[-1]/100000)**(252/len(a))-1)
        bdd = float(np.max(1-b/np.maximum.accumulate(b)))
        np.testing.assert_allclose(f.fees.astype(float),f.quantity.astype(float)*f.price.astype(float)*req.costs[0].one_way_cost,atol=1e-8,rtol=1e-12)
        sid = run.window_id
        assert len(a)==(434 if sid=='full' else 415)
        assert float(a.cash_before.iloc[0])==100000 and int(a.quantity_before.iloc[0])==0
        checks = {'return':cagr>=1.5*bcagr if bcagr>0 else cagr>0,'relative_drawdown':dd<=.8*bdd,
            'absolute_drawdown':dd<=.25,'frequency_median':float(rolling.median())>=6,
            'frequency_coverage':int((rolling>=3).sum())*10>=9*len(rolling)}
        runs[sid] = {'net_return':net,'cagr':cagr,'dd':dd,'fees':float(f.fees.sum()),
            'closed':int(t.status.eq('CLOSED').sum()),'frequency_median':float(rolling.median()),
            'frequency_good':int((rolling>=3).sum()),'frequency_windows':len(rolling),
            'benchmark_cagr':bcagr,'benchmark_dd':bdd,'checks':checks,'center_pass':all(checks.values()),
            'equity_sha256':sha256(np.asarray(a.equity,dtype='<f8').tobytes()).hexdigest()}
    if 's011_common' in runs:
        s=runs['s011_common']
        s['return_superior'],s['dd_superior'] = s['net_return']>.9158029150000013,s['dd']<.07248663749114126
        s['dual_pass'] = s['return_superior'] and s['dd_superior']
    return {'candidate_id':req.strategy.candidate_id,'parameters':dict(req.strategy.payload['parameters']),
        'request_hash':result.request_hash,'result_hash':result.result_hash,'runs':runs,
        'both_center_pass':bool('full' in runs and 's011_common' in runs and runs['full']['center_pass'] and runs['s011_common']['dual_pass'])}


def prepare():
    ex = ExperimentRef('S015','EX016_20261023')
    assert not (HOME/'protocols/round.json').exists()
    budget = {'authorization':'授权10轮实验的额度，请你以产出合格策略为目标自主执行。',
        'maximum_experiments':10,'first_experiment':ex.to_dict(),'current_branch':'codex/s015-stage2-dual-objective',
        'counting':'One prospective research question with declared comparisons is one round; not one account. Technical same-request retries do not create rounds and must be counted separately.',
        'scope':'Autonomous stage2/3/4 research toward a fully qualified research candidate; existing ETF daily/30m only,434 original+415 common independent cash accounts, no new sources/windows, no freeze/PTE/production.',
        'center_limit_per_round':64,'maximum_new_center_account_scenarios':1280,
        'self_check_limit':8,'self_checks':'Only dual-center-qualified candidates:32 default5% perturbations+1 fee stress on434. Same content and same account contract; all eight ranking evidence, original target defaults.',
        'resources':{'processes':8,'native_threads':1,'seed':13},
        'success':'434 original economic+frequency+32 perturbations+fee stress AND415 net>.9158029150000013 and DD<.07248663749114126; raw values strict. No added annual or predictive gates.',
        'allocation':'First examine pressure order, staged commitment, trend interaction and rebound memory. Followups require a specific observed mechanism/boundary; reserve rounds for validation. No obligation to spend all10 if goals achieved or no defensible question remains.',
        'selection_bias':'All history seen repeatedly; all configuration/account/round counts retained. No claims of independent validation.',
        'phase_authorization':'Current explicit10-round goal authorization covers necessary strategy construction and original validation; precise candidate selection/freeze/production remains separate.',
        'source_mandate':read(ROOT/'research/S015/deliveries/MANDATE/3/receipt.json')['reference'],
        'prior_report':read(ROOT/'research/S015/experiments/EX015_20261023/report_ref.json')['report']}
    save(HOME/'protocols/ten_round_budget.json',budget)
    configs = [{'mode':m,'entry':0.,'exit':.005,'hold':3} for m in ('base','cross','recover','deteriorate')]
    protocol = {'round':1,'question':'Does pressure order distinguish transient shock from persistent deterioration, under unchanged exits?',
        'mechanisms':{'base':'Existing daily pressure episode control with equity targets',
            'cross':'Enter only when crossing from positive to nonpositive pressure',
            'recover':'Enter at nonpositive pressure only if better than previous day',
            'deteriorate':'Reverse control: nonpositive pressure worse than previous day'},
        'configurations':configs,'paired_windows':'434 full AND415 s011_common, each100k/zero holdings',
        'controls':'No range filter, model forecast or date gates. Initial four natural-sign comparisons, no threshold search.',
        'decision':'Consider followup only with a clear full-account risk/return or boundary improvement; frequency or insufficient-return failures retained, no new gates.',
        'source_files':['src/strategy_runtime/strategies/pressure_path.py','src/suite.py']}
    save(HOME/'protocols/round.json',protocol)
    refs = [material(ex,p.stem,p).to_dict() for p in (HOME/'protocols/ten_round_budget.json',HOME/'protocols/round.json',SOURCE/'strategies/pressure_path.py',Path(__file__))]
    save(HOME/'others/protocol_refs.json',refs)
    print('ROUND1_PROTOCOL_AND_BUDGET_PUBLISHED',flush=True)


def run(experiment,precheck=False):
    ex = ExperimentRef('S015',experiment)
    here = ex.resolve(ROOT)
    assert not (here/'others/results.json').exists()
    protocol = read(here/'protocols/round.json')
    refs = read(here/'others/protocol_refs.json')
    for ref in refs:
        EvidenceRef.from_dict(ref).resolve(ROOT)
    source = next(r for r in refs if r['name']=='pressure_path')
    assert sha256((SOURCE/'strategies/pressure_path.py').read_bytes()).hexdigest()==source['sha256']
    runner = next(r for r in reversed(refs) if r['name'].startswith('execution_suite'))
    assert sha256(Path(__file__).read_bytes()).hexdigest()==runner['sha256']
    ctx=context()
    specs=[]
    study=optuna.create_study(directions=['maximize','minimize'],sampler=optuna.samplers.RandomSampler(seed=13))
    for i,p in enumerate(protocol['configurations']):
        study.enqueue_trial({'configuration_index':i})
    for i in range(len(protocol['configurations'])):
        trial=study.ask()
        j=trial.suggest_int('configuration_index',0,len(protocol['configurations'])-1)
        assert j==i
        p=protocol['configurations'][j]
        specs.append((trial,f'C{1600+100*(protocol["round"]-1)+i:04d}',p))
    reqs=[request(ctx,ex,cid,p) for _,cid,p in specs]
    serial=None
    if precheck:
        started=perf_counter()
        serial=ctx.evaluation.evaluate(reqs[0])
        print({'serial_seconds':perf_counter()-started,'metrics':summary(reqs[0],serial)},flush=True)
    rows=[]
    start=perf_counter()
    with open_research_execution(ctx,experiment=ex,checkpoint=ExecutionCheckpointRequest(ex.experiment_id.lower()+'_accounts',CheckpointMode.CREATE)) as session:
        for left in range(0,len(reqs),8):
            block=reqs[left:left+8]
            outs=ctx.evaluation.evaluate_many(tuple(block),execution=session)
            writes=[]
            new=[]
            for offset,(req,out) in enumerate(zip(block,outs,strict=True)):
                assert out.status.value=='SUCCEEDED',str(out.error)
                row=summary(req,out.result)
                if precheck and left+offset==0:
                    assert out.result.result_hash==serial.result_hash
                    for a,b in zip(serial.runs,out.result.runs,strict=True):
                        for table in ('account_daily','decisions','orders','fills','trades'):
                            pd.testing.assert_frame_equal(getattr(a.execution,table),getattr(b.execution,table))
                study.tell(specs[left+offset][0],[row['runs']['s011_common']['net_return'],row['runs']['s011_common']['dd']])
                writes.append(EvaluationEvidenceWrite(ex,row['candidate_id'],req,out.result))
                new.append(row)
            pubs=publish_evidence_many(ctx,tuple(writes),execution=session)
            for row,pub in zip(new,pubs,strict=True):
                assert pub.status.value=='PUBLISHED',str(pub.error)
                row['evidence']=pub.reference.to_dict()
            rows.extend(new)
            save(here/'others/progress.json',{'rows':rows,'completed':len(rows),'total':len(reqs)})
            print({'round':protocol['round'],'completed':len(rows),'dual_centers':sum(r['both_center_pass'] for r in rows),'elapsed':perf_counter()-start},flush=True)
    result={'round':protocol['round'],'rows':rows,'new_configurations':len(rows),'account_scenarios':2*len(rows),
        'technical_precheck_extra_scenarios':2 if precheck else 0,'precheck_five_ledgers_equal':precheck,
        'qualified_centers':sum(r['both_center_pass'] for r in rows),'execution_stats':asdict(session.stats),
        'optuna':[{'number':t.number,'params':t.params,'values':t.values,'state':str(t.state)} for t in study.trials]}
    save(here/'others/results.json',result)
    print('ROUND_COMPLETE',experiment,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('prepare','run','precheck'))
    p.add_argument('--experiment',default='EX016_20261023')
    a=p.parse_args()
    if a.mode=='prepare':
        prepare()
    else:
        run(a.experiment,a.mode=='precheck')
