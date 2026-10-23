"""Causal expanding training schedule for stage-three fixed account construction."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
PATH=['return_time_balance','extrema_order','excursion_balance','halfday_balance'];VOL=['range_expansion','prior_range_compression','shock_concentration','gap_energy_share'];LEGACY=['r1','r5','vol20','range20','pressure']
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(4,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def prepare():
    assert not (HERE/'others/training_refs.json').exists()
    source=read(BASE/'EX036_20261023/others/published_refs.json')['materials']
    proto={'authorization':'用户同意执行阶段三，承接不限轮数研究授权；同分支，原目标及数据边界不变，不自动进入阶段四/冻结/PTE。',
      'question':'路径的收益许可与波动的风险许可在实际连续账户中能否兑现，单职责与交集有什么代价？',
      'selection_history':'EX035-041同一开发池已见，采用两家族有限用途。阶段二4折信号只覆盖100以后，不能倒填434日。现在以明确历史学习程序构造全窗口账户，结果不能直接照搬阶段二比例。',
      'training':'Canonical434dates; train positions before D with actual known_date<D, target valid. First D with at least30 mature net3 AND loss3 examples, thereafter every20 canonical trading days. Expanding history, Ridge alpha10, train mean/population std, unpenalized intercept. No data before authorized pool is invented. Before first model: cash. All models share releases; independent100k/zero holdings windows share canonical learning timeline.',
      'models':{'A':{'path':PATH,'risk':VOL},'B':{'path':LEGACY+PATH,'risk':LEGACY+VOL}},
      'thresholds':'path predicted net3>=0; risk predicted loss3<=same-model fitted-training prediction median. No threshold search. all intermediate outcomes not yet known are excluded.',
      'runtime':'Model schedules embedded in immutable candidate parameter identity, never read mutable research files at runtime. SRT recomputes13 inputs from actual bound price data. Only effective model date<=D, max_training_known<D. Research replay validity through2026-10-21, no future-autotraining/deployment claim.',
      'first_accounts':'6 fixed modes A/B x path/risk/and; hold3 intent, exposure1. At T trigger, positive targets T,T+1,T+2, zero atT+3; usually sellT+4. Changes in intervening scores do not exit early. Canonical intent sequence, not actual-fill clock. entry_cycle locks initial quantity, can retry entry during positive target days; record this mismatch with isolated events.',
      'execution':'PublicSRTV2/TDR. available_cash_fraction allocation1 entry_cycle; binary targets. Same1% raw-close limit and originaltick/lot/upperguard/fees, marketexit, noforceendexit/no leverage. Switch from prior daily equity rebalance is explicit construction, not hidden compatibility fallback.',
      'evaluation':'434 full and415 S011common, each100k initial cash. Original full economic/frequency and415 strict return>.9158029150000013/DD<.07248663749114126. Do not introduce stats or yearly-performance hard gates. Standard .001 one-way; stage4 not authorized now.',
      'followup':'After fixed centers, diagnose realized execution/fees/holding/selection. Only investigate evidenced construction issues with prospective successor protocols; finite broad hold/exposure domains viaOptuna if justified, inspect genuine adjustable-domain boundary improvements; no obligation endless search, no new numeric experiment cap.',
      'resources':{'account_workers':4,'native_threads':1,'seed':13,'fit':'small deterministic matrices serial; full accounts spawn4, serial/parallel equality preflight'},
      'sources':{k:source[k] for k in ('others/model_features.csv','others/labels.csv')},
      'limitations':'Already-seen data, multiple selected hypotheses, labels publicTXE but historical publication/revisionPIT unverified. Adaptive historical schedule is not a deployable online learner.'}
    save(HERE/'protocols/stage3_plan.json',proto);save(HERE/'others/training_refs.json',{p.name:material(p).to_dict() for p in (HERE/'protocols/stage3_plan.json',Path(__file__))})
    repo=RepositoryContext.discover(ROOT);intent=read(ROOT/'research/registrations/S015/family.json')['research_intent'];intent['stage2_completed_budget']=intent['experiment_budget'];intent.update(current_experiment=EX.to_dict(),current_phase='已获授权进入阶段三：价格路径/风险许可固定账户对照',next_gate='自主完成阶段三构造及原中心目标检验；完整阶段四另批',experiment_budget={'unlimited':True,'authorized':None,'completed':0,'remaining':None,'source':read(HERE/'others/training_refs.json')['stage3_plan.json']})
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户明确同意执行阶段三；按原目标开展连续账户研究。');print('STAGE3_TRAINING_FROZEN',flush=True)
def inputs():
    refs=read(HERE/'others/training_refs.json')
    for name,folder in [('models.py','src'),('stage3_plan.json','protocols')]:assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/folder/name).read_bytes()
    source=read(HERE/'protocols/stage3_plan.json')['sources'];return tuple(pd.read_csv(EvidenceRef.from_dict(source[k]).resolve(ROOT)) for k in ('others/model_features.csv','others/labels.csv'))
def fit(g,cols):
    x=g[cols].to_numpy(float);mean=x.mean(0);scale=x.std(0);scale[scale==0]=1;a=np.column_stack([np.ones(len(x)),(x-mean)/scale]);penalty=np.eye(a.shape[1])*10;penalty[0,0]=0;beta=np.linalg.solve(a.T@a+penalty,a.T@g.y.to_numpy(float))
    return {'columns':cols,'center':mean.tolist(),'scale':scale.tolist(),'beta':beta.tolist()},a@beta
def learn():
    assert not (HERE/'others/models_A.json').exists();x,labels=inputs();schedules={'A':[],'B':[]};manifest=[];last=None;predictions=[]
    datasets={target:x.merge(labels[labels.target.eq(target)].drop(columns=['date']),on='position',validate='one_to_one') for target in ('net3','loss3')}
    for pos,date in enumerate(x.date):
        training={target:g[g.position.lt(pos)&g.y.notna()&g.known_date.lt(date)] for target,g in datasets.items()}
        ready=min(len(g) for g in training.values())>=30
        if ready and (last is None or pos-last>=20):
            for family in schedules:
                record={'date':date,'train_known_max':max(g.known_date.max() for g in training.values()),'models':{}}
                for role,target,cols in [('path','net3',PATH),('risk','loss3',VOL)]:
                    if family=='B':cols=LEGACY+cols
                    tr=training[target];m,p=fit(tr,cols)
                    if role=='risk':m['threshold']=float(np.median(p))
                    record['models'][role]=m
                    manifest.append({'family':family,'role':role,'release':date,'position':pos,'train_n':len(tr),'positions_sha256':sha256(tr.position.to_numpy(dtype='<i8').tobytes()).hexdigest(),'training_xy_sha256':sha256(tr[cols+['y']].to_numpy(dtype='<f8').tobytes()).hexdigest(),'max_known':tr.known_date.max(),'columns':cols,'alpha':10})
                assert record['train_known_max']<date;schedules[family].append(record)
            last=pos
        for family,schedule in schedules.items():
            row={'date':date,'position':pos,'family':family,'ready':bool(schedule),'model_date':schedule[-1]['date'] if schedule else None}
            for role in ('path','risk'):
                if not schedule:row[role]=None;continue
                m=schedule[-1]['models'][role];a=(x.loc[pos,m['columns']].to_numpy(float)-np.array(m['center']))/np.array(m['scale']);row[role]=float(np.r_[1.,a]@np.array(m['beta']))
            row['risk_threshold']=schedule[-1]['models']['risk']['threshold'] if schedule else None;predictions.append(row)
    for family,schedule in schedules.items():save(HERE/f'others/models_{family}.json',schedule)
    save(HERE/'others/training_manifest.json',manifest);pd.DataFrame(predictions).to_csv(HERE/'others/model_predictions.csv',index=False)
    save(HERE/'others/training_summary.json',{'first_release':schedules['A'][0]['date'],'releases':len(schedules['A']),'fitted_models':len(manifest),'mature_min':30,'retrain_step':20,'alpha':10,'input_refs':read(HERE/'protocols/stage3_plan.json')['sources']});print('MODELS_LEARNED',schedules['A'][0]['date'],len(manifest),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','learn']);{'prepare':prepare,'learn':learn}[p.parse_args().mode]()
