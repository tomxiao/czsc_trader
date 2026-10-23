"""Exactly two prospective arms, four public TDR strategy accounts."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,EvaluationRequest,EvaluationWindow,EvaluationCost,EvaluationBenchmark,LimitBuyHold,EvaluationEvidenceWrite)
from strategy_runtime import StrategyCandidate,implementation_sha256
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent
EX=ExperimentRef('S015',HERE.name);SOURCE=HERE/'src/strategy_runtime';FILES=['strategies/funding_trend.py']
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def module(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def candidate(use):
    return StrategyCandidate('S015','C3301' if use else 'C3300',{'decision_feedback':'MARKET_INTENT','parameters':{'use_funding':use},'runtime':{'module':'strategy_runtime.strategies.funding_trend','qualname':'FundingTrend','contract_version':2,'source_files':FILES,'source_sha256':implementation_sha256(FILES,source_root=SOURCE)}},SOURCE)
def prepare():
    assert not (HERE/'others/source_refs.json').exists()
    save(HERE/'others/source_refs.json',{p.name:material(p).to_dict() for p in (SOURCE/FILES[0],Path(__file__))})
def check_signals():
    refs=read(HERE/'others/source_refs.json')
    for name,path in [('funding_trend.py',SOURCE/FILES[0]),('run.py',Path(__file__))]:
        ref=EvidenceRef.from_dict(refs[name]);ref.resolve(ROOT);assert sha256(path.read_bytes()).hexdigest()==ref.sha256
    old=module(BASE/'EX026_20261023/src/study.py','old_event')
    inp=old.sources();adj,raw,bars,rules,ids=old.inputs(inp)
    for f in (adj,raw,bars):f.attrs={}
    sr=EvidenceRef.from_dict(read(BASE/'EX027_20261023/others/published_refs.json')['materials']['others/own_shares.csv']);s=pd.read_csv(sr.resolve(ROOT))
    m=module(SOURCE/FILES[0],'new_funding');f=m.causal_features(adj,s)
    outputs={};scalar=0;prefix=0
    for use in (False,True):
        a=m.intentions(f,use);age=0;w=0.
        for j,row in enumerate(f.itertuples()):
            if age>0:
                if row.close<=row.average20 or row.return5<=0 or age>=3:age=0;w=0.
                else:age+=1
            elif row.close>row.average20 and row.return5>0:age=1;w=.5 if use and row.funding20<=0 else 1.
            assert a.intent_age.iloc[j]==age and a.target_position.iloc[j]==w;scalar+=1
        outputs[str(use)]=a
        for j in range(len(f)):
            t=f.index[j];aa=adj[pd.to_datetime(adj.Date)<=t].copy();ss=s[pd.to_datetime(s.Date)<t].copy()
            b=m.intentions(m.causal_features(aa,ss),use)
            np.testing.assert_allclose(a.target_position.iloc[:j+1],b.target_position,rtol=0,atol=0);prefix+=1
        out=a.reset_index().rename(columns={'Date':'date'});out.to_csv(HERE/f'others/signals_{int(use)}.csv',index=False)
    np.testing.assert_array_equal(outputs['False'].intent_age,outputs['True'].intent_age)
    # Unit check: a funding-state switch inside a trend cycle must not resize its intent.
    synthetic=pd.DataFrame({'trend_ok':[True]*5,'funding20':[-.1,.1,.1,.1,.1]})
    got=m.intentions(synthetic,True);assert got.target_position.tolist()==[.5,.5,.5,0.,1.]
    density={}
    for use,a in outputs.items():
        z=a.loc['2025-01-02':'2026-10-20'];density[use]={'positive_target_days':int(z.target_position.gt(0).sum()),'half_target_days':int(z.target_position.eq(.5).sum()),'entry_intents':int(z.intent_age.eq(1).sum()),'exit_intents':int((z.intent_age.eq(0)&z.intent_age.shift(1).gt(0)).sum())}
    save(HERE/'others/signal_checks.json',{'status':'PASS','scalar_checks':scalar,'full_prefix_checks':prefix,'synthetic_locked_weight':'PASS','same_intent_age':'PASS','density_is_not_closed_frequency':density,'data_identities':ids,'shares':sr.to_dict(),'prior_input_refs':{k:v.to_dict() for k,v in inp.items()}})
    print({'signal_checks':'PASS','density':density},flush=True)
def request(ctx,use):
    c=candidate(use)
    return ctx.evaluation.prepare(EvaluationRequest(ROOT,EX.experiment_id,c,{'candidate_id':c.reference_id,'source_files':FILES,'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',
        (EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),EvaluationWindow('s011_common',date(2025,2,6),date(2026,10,21))),date(2026,10,21),100000.,(EvaluationCost('standard',.001),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))
def run():
    assert read(HERE/'others/signal_checks.json')['status']=='PASS'
    assert not (HERE/'others/results.json').exists()
    # Reuse the prior audited public-account summary, authenticate its published source.
    suite=module(BASE/'EX016_20261023/src/suite.py','old_suite')
    refs=read(BASE/'EX025_20261023/others/protocol_refs.json');sr=next(EvidenceRef.from_dict(v) for v in refs if v['name'].startswith('execution_suite'))
    sr.resolve(ROOT);assert sha256((BASE/'EX016_20261023/src/suite.py').read_bytes()).hexdigest()==sr.sha256
    ctx=context();rows=[]
    for use in (False,True):
        req=request(ctx,use);print('Prepared',req.strategy.candidate_id,flush=True)
        result=ctx.evaluation.evaluate(req);row=suite.summary(req,result)
        ref=publish_evidence(ctx,EvaluationEvidenceWrite(EX,row['candidate_id'],req,result));row['evidence']=ref.to_dict()
        for run in result.runs:
            for table in ('account_daily','decisions','orders','fills','trades'):
                getattr(run.execution,table).to_csv(HERE/f'others/{row["candidate_id"]}_{run.window_id}_{table}.csv',index=False)
        rows.append(row);save(HERE/'others/progress.json',{'rows':rows,'completed':len(rows),'total':2})
        print(row,flush=True)
    save(HERE/'others/results.json',{'rows':rows,'configurations':2,'strategy_accounts':4,'benchmark_output_scenarios':4,'center_joint_pass':sum(r['both_center_pass'] for r in rows),'summary_source':sr.to_dict()})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','check','run']);{'prepare':prepare,'check':check_signals,'run':run}[p.parse_args().mode]()
