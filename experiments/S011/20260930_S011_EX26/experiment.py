"""Preregistered stage-four diagnostics of every feasible archived configuration."""
from pathlib import Path
from datetime import date
from hashlib import sha256
from io import StringIO
import json
import numpy as np
import pandas as pd
from dataflows import Dataset
from strategy_runtime import StrategyCandidate
from research_experiment import (ResearchExperiment, ExperimentDefinition, ExperimentMode,
    ExperimentStage, ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentCapability, ExperimentResult, ExperimentOutcome)
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX26'; SEED=2026093026; BUDGET=216; WORKERS=8
START=date(2025,2,6); CUTOFF=date(2026,9,28)
ROOT=Path(__file__).resolve().parent; REPO=ROOT.parents[2]
PREDECESSORS={
    '20260930_S011_EX15':'de2edb5fcd83395ec3b3f68ae9cabe2acb933c4ad36332dc708f33c6639d8014',
    '20260930_S011_EX16':'8df1748c63ac7ef1601203a161968351214ddf10b4fa7e83673946bf5924622e',
    '20260930_S011_EX20':'3689ecb8e4fbc9f6f59cad52f099db7bf09dc3bc24c775751ed274e2675f1799',
    '20260930_S011_EX23':'f9bfa2035bdb96eea6ddc8abc426301cf1ae78f437a91b43fa06f1e2c458a827',
    '20260930_S011_EX22':'8c35b0cc01c89ada91946e8f47971ebaf3c12789a4c3a88b63a5dcafb91e94d1',
    '20260930_S011_EX24':'c215ce0978fb9a7587336cd38ec9c88145760d03557b34efd8152750175b754e',
    '20260930_S011_EX25':'5d936c5fd0b46fe697138c476f282594fe24f58582494f8ec5c2f6160102ddfc'}
STEPS={'tail_weight':.025,'spx_weight':.025,'entry':.005,'exit':.025,'max_days':1.,'lookback':10.,'premium':.0005}
FEES=(.001,.00125,.0015,.002,.0025,.003,.004,.005)
SCENARIOS=('standard','fee_12_5bp','fee_15bp','fee_20bp','fee_25bp','fee_30bp','fee_40bp','fee_50bp')
LEDGERS=('decisions','orders','fills','account_daily','trades')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def metrics(account, trades=None):
    eq=account.equity.astype(float); n=len(eq)
    result={'cagr':float((eq.iloc[-1]/1e6)**(252/n)-1),
        'drawdown':float((eq/eq.cummax().clip(lower=1e6)-1).min()),'end_equity':float(eq.iloc[-1]),'sessions':n}
    if trades is not None:
        result['closed_trades']=int(trades.status.eq('CLOSED').sum())
        result['frequency']=60*result['closed_trades']/n
    return result


def qualifies(m,b):
    return bool(m['cagr']>=1.5*b['cagr'] and (b['cagr']>0 or (m['cagr']>0 and m['cagr']>b['cagr']))
        and m['drawdown']>b['drawdown'] and 4<=m['frequency']<=6)


def catalog():
    rows=[]; seen=set()
    for ex in (15,23,22,24,25):
        folder=ROOT.parent/f'20260930_S011_EX{ex}'
        table=pd.read_csv(ROOT.parent/'20260930_S011_EX16/artifacts/qualification.csv' if ex==15 else folder/'artifacts/trials.csv',float_precision='round_trip')
        params=read_json(folder/'artifacts/trial_parameters.json')
        provenance=read_json(folder/'artifacts/source_trials.json') if ex==23 else None
        for r in table.to_dict('records'):
            i=int(r['trial']); key=json.dumps(params[i],sort_keys=True)
            if key in seen:continue
            seen.add(key)
            account=pd.read_csv(folder/f'artifacts/trials/T{i:03}/account_daily.csv.gz',float_precision='round_trip')
            cid=provenance[i]['candidate_id'] if provenance is not None else f'EX{ex}T{i:03}'
            rows.append({**r,**params[i],'reference':f'EX{ex}T{i:03}','candidate_id':cid,
                'archive':folder.name,'trial_path':f'artifacts/trials/T{i:03}',
                'account_key':sha256(account[['date','cash','quantity','equity']].to_csv(index=False).encode()).hexdigest()})
    return pd.DataFrame(rows)


def neighborhoods(table):
    fields=list(STEPS); matrix=table[fields].to_numpy(float); scale=np.array(list(STEPS.values()))
    rows=[]; links=[]
    for row in table.loc[table.qualified].to_dict('records'):
        diff=(matrix-np.array([row[k] for k in fields]))/scale
        nonzero=~np.isclose(diff,0,rtol=0,atol=1e-9)
        nearby=(np.abs(diff).max(axis=1)<=1+1e-9)&nonzero.any(axis=1)
        sides=0; dimensions=0
        for j,field in enumerate(fields):
            axis=nearby & (nonzero.sum(axis=1)==1) & nonzero[:,j]
            negative=axis & (diff[:,j]<0); positive=axis & (diff[:,j]>0)
            sides+=int(negative.any())+int(positive.any())
            dimensions+=int(negative.any() and positive.any())
            for sign,mask in (('-',negative),('+',positive)):
                neighbors=table.loc[mask]
                links.append({'center':row['reference'],'parameter':field,'side':sign,'tested':len(neighbors),
                    'qualified':int(neighbors.qualified.sum()),'neighbor_references':'|'.join(neighbors.reference),
                    'distinct_accounts':neighbors.account_key.nunique(),
                    'new_behaviors':neighbors.loc[neighbors.account_key.ne(row['account_key'])].account_key.nunique()})
        joint=table.loc[nearby]
        rows.append({'reference':row['reference'],'covered_sides':sides,'two_sided_dimensions':dimensions,
            'unmeasured_sides':14-sides,'joint_tested':len(joint),'joint_qualified':int(joint.qualified.sum()),
            'joint_qualification_share':None if joint.empty else float(joint.qualified.mean()),
            'joint_distinct_accounts':joint.account_key.nunique()})
    return pd.DataFrame(rows),pd.DataFrame(links)


def time_diagnostics(account,bh,fills,trades,reference,bootstrap_indices):
    eq=account.equity.to_numpy(float); be=bh.equity.to_numpy(float)
    dates=pd.DatetimeIndex(pd.to_datetime(account.date)); assert dates.equals(pd.DatetimeIndex(pd.to_datetime(bh.date)))
    returns=eq/np.r_[1e6,eq[:-1]]-1; benchmark=be/np.r_[1e6,be[:-1]]-1
    segments=[]
    for unit,labels in (('year',dates.year.astype(str)),('quarter',dates.to_period('Q').astype(str))):
        for label in sorted(set(labels)):
            mask=labels==label
            segments.append({'reference':reference,'unit':unit,'period':label,'sessions':int(mask.sum()),
                'strategy_return':float(np.prod(1+returns[mask])-1),'buyhold_return':float(np.prod(1+benchmark[mask])-1)})
    rolling=pd.DataFrame({'reference':reference,'end_date':dates,
        'strategy_return':pd.Series(1+returns).rolling(60).apply(np.prod,raw=True)-1,
        'buyhold_return':pd.Series(1+benchmark).rolling(60).apply(np.prod,raw=True)-1}).dropna()
    rolling['excess']=rolling.strategy_return-rolling.buyhold_return
    cash=fills.quantity*fills.price*fills.side.map({'BUY':-1.,'SELL':1.})-fills.fees
    pnl=cash.groupby(fills.cycle_id).sum().reindex(trades.loc[trades.status.eq('CLOSED'),'cycle_id'])
    positive=pnl.loc[pnl>0].sort_values(ascending=False)
    concentration={'reference':reference,'closed_trades':len(pnl),'wins':int((pnl>0).sum()),
        'top3_positive_pnl_share':float(positive.head(3).sum()/positive.sum()),
        'rolling60_positive_excess_share':float(rolling.excess.gt(0).mean()),'worst_rolling60_excess':float(rolling.excess.min())}
    for k in (1,3,5):
        modified=returns.copy(); modified[np.argsort(returns)[-k:]]=0
        concentration[f'best_{k}_days_zero_cagr']=float(np.prod(1+modified)**(252/len(eq))-1)
    excess=np.log1p(returns)-np.log1p(benchmark); samples=[]
    for block,index in bootstrap_indices.items():
        values=excess[index].mean(axis=1)*252
        samples.append({'reference':reference,'block':block,'resamples':len(values),
            'annual_log_excess_p025':float(np.quantile(values,.025)),
            'annual_log_excess_median':float(np.median(values)),
            'annual_log_excess_p975':float(np.quantile(values,.975)),
            'positive_resample_share':float((values>0).mean())})
    return pd.DataFrame(segments),rolling,concentration,pd.DataFrame(samples)


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Do all feasible configurations have sufficient neighborhood and execution robustness evidence for representative selection?',
            hypothesis='The feasible set may support a representative region after accounting for local coverage, concentration, temporal dependence and costs.',
            falsification_conditions=('Feasibility is isolated or depends on narrow execution assumptions','Coverage cannot establish a representative region'),
            development_cutoff=CUTOFF,random_seed=SEED,allowed_datasets=tuple(d.value for d in
                (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,Dataset.GLOBAL_INDEX_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=(ExperimentDependency('numpy',np.__version__),ExperimentDependency('pandas',pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.ROBUSTNESS,
                first_principles=('Robustness requires distinguishing parameter coverage from repeated account behavior',),
                information_paths=('Immutable development accounts -> preregistered diagnostics and same-candidate cost replays',),
                stage_objectives=('Assess every feasible configuration without inventing acceptance gates',),
                observation_metrics=('Neighborhood coverage','Same-cost gates','Segment excess','Concentration','Paired block uncertainty'),
                methodology=('No new parameter proposals; 26 existing candidates plus integer-lot BuyHold at eight costs',
                    'Public same-candidate managed preparation; 8-thread evaluation; no automatic retries',
                    'Diagnostics only; human RSCH handoff decision remains explicit'),predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        assert len(FEES)==len(SCENARIOS)==WORKERS and BUDGET==27*8
        assert qualifies({'cagr':.5,'drawdown':-.1,'frequency':4},{'cagr':.2,'drawdown':-.2})
        assert not qualifies({'cagr':.5,'drawdown':-.1,'frequency':6.1},{'cagr':.2,'drawdown':-.2})
        base={k:0. for k in STEPS}; items=[]
        for index,x in enumerate((0.,.005,-.005)):
            items.append({**base,'entry':x,'reference':str(index),'qualified':True,'account_key':str(index)})
        n,l=neighborhoods(pd.DataFrame(items)); assert n.iloc[0].two_sided_dimensions==1 and n.iloc[0].covered_sides==2
        assert metrics(pd.DataFrame({'equity':[1e6,1.1e6]}))['drawdown']==0

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        for ex,receipt in PREDECESSORS.items():
            validate_experiment_archive(ROOT.parent/ex)
            assert context.predecessors[ex].receipt_sha256==receipt
        artifacts=[]
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,lineterminator='\n',compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'S011-EX26-evidence'))
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX26-evidence'))
        table=catalog(); eligible=table.loc[table.qualified].copy()
        assert len(table)==559 and len(eligible)==26 and eligible.account_key.nunique()==18
        save('parameter_catalog.csv',table); save('qualified_parameters.csv',eligible)
        ns,nl=neighborhoods(table); save('neighborhood_summary.csv',ns); save('neighborhood_directions.csv',nl)
        p=ROOT.parent/'20260930_S011_EX15/artifacts'
        frames={k:pd.read_csv(p/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
        gate=read_json(p/'execution_data_gate.json'); assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1
        days=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(CUTOFF)),'dt'])
        specs=[{'reference':'EX16BH','candidate_id':'EX16BH','archive':'20260930_S011_EX16','trial_path':'artifacts','is_benchmark':True}]
        specs+=eligible.assign(is_benchmark=False).to_dict('records')
        for spec in specs:
            cid=spec['candidate_id']; original=int(cid.split('T')[0][2:]) if 'T' in cid else 16
            spec['cache_root']=f'.tmp/s011-ex{original}-execution'
            cache=REPO/spec['cache_root']; matches=list(cache.glob(f'S011{cid}_159326_*/preparations/20250206_20260928/prepared-data.json'))
            assert len(matches)==1,('missing same-candidate managed preparation',cid)
        rng=np.random.default_rng(SEED); indices={}
        for block in (10,20):
            starts=rng.integers(0,403,size=(2000,int(np.ceil(403/block))))
            indices[block]=((starts[:,:,None]+np.arange(block))%403).reshape(2000,-1)[:,:403]
        benchmark={}; rows=[]; segments=[]; rolling=[]; concentrations=[]; bootstrap=[]
        for position,spec in enumerate(specs):
            folder=ROOT.parent/spec['archive']; original=folder/spec['trial_path']; cid=spec['candidate_id']; ref=spec['reference']
            payload=read_json(original/('benchmark_payload.json' if spec['is_benchmark'] else 'payload.json'))
            candidate=StrategyCandidate('S011',cid,payload,folder/'runtime/strategy_runtime')
            data=BacktestExecutionData(root=REPO/spec['cache_root'],symbol='159326.SZ',asset_type='etf',fingerprint=gate['fingerprint'],cutoff=CUTOFF,evaluation_sessions=days,**frames)
            result=context.evaluation.evaluate(EvaluationRequest(repository_root=REPO,experiment_id=ID,strategy=candidate,
                runtime_binding={'candidate_id':candidate.reference_id,'source_files':list(payload['runtime']['source_files']),'implementation_sha256':payload['runtime']['source_sha256']},
                symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),development_cutoff=CUTOFF,initial_cash=1e6,
                costs=tuple(EvaluationCost(s,f,'SCREENING' if s=='standard' else 'STRESS') for s,f in zip(SCENARIOS,FEES)),execution_data=data,workers=WORKERS))
            js(f'accounts/{ref}/identity.json',{'candidate_id':candidate.reference_id,'payload':payload,'request_hash':result.request_hash,'result_hash':result.result_hash,
                'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash,'same_candidate_cache':spec['cache_root']})
            for run in result.runs:
                s=run.scenario_id; fee=FEES[SCENARIOS.index(s)]; execution=run.execution
                for name in LEDGERS:
                    observed=pd.read_csv(StringIO(getattr(execution,name).to_csv(index=False)))
                    save(f'accounts/{ref}/{s}/{name}.csv.gz',observed)
                    if s=='standard':
                        archived=pd.read_csv(original/(('benchmark_' if spec['is_benchmark'] else '')+name+'.csv.gz'))
                        pd.testing.assert_frame_equal(archived,observed,check_exact=False,rtol=1e-12,atol=1e-8)
                m=metrics(execution.account_daily,execution.trades)
                assert len(execution.account_daily)==403 and execution.account_daily.cash.ge(-1e-8).all()
                assert execution.account_daily.quantity.mod(100).eq(0).all()
                assert np.allclose(execution.fills.fees,execution.fills.quantity*execution.fills.price*fee,rtol=0,atol=1e-8)
                if spec['is_benchmark']:benchmark[s]=execution.account_daily.copy()
                b=metrics(benchmark[s]); qualified=None if spec['is_benchmark'] else qualifies(m,b)
                if s=='standard' and not spec['is_benchmark']:assert qualified
                rows.append({'reference':ref,'scenario':s,'one_way_cost':fee,'is_benchmark':spec['is_benchmark'],**m,
                    'buyhold_cagr':b['cagr'],'buyhold_drawdown':b['drawdown'],'original_gates_under_scenario':qualified,
                    'fees':float(execution.fills.fees.sum()),'unfilled_orders':int(execution.orders.status.ne('FILLED').sum())})
                if s=='standard' and not spec['is_benchmark']:
                    seg,rol,con,boot=time_diagnostics(execution.account_daily,benchmark[s],execution.fills,execution.trades,ref,indices)
                    segments.append(seg); rolling.append(rol); concentrations.append(con); bootstrap.append(boot)
            js(f'checkpoints/through_{position+1:02}.json',{'completed_candidates':position+1,'completed_accounts':len(rows)})
            print(json.dumps({'completed_candidates':position+1,'reference':ref,'completed_accounts':len(rows)}),flush=True)
        costs=pd.DataFrame(rows); save('cost_sensitivity.csv',costs)
        save('period_returns.csv',pd.concat(segments,ignore_index=True)); save('rolling60_returns.csv',pd.concat(rolling,ignore_index=True))
        save('concentration.csv',pd.DataFrame(concentrations)); save('block_bootstrap.csv',pd.concat(bootstrap,ignore_index=True))
        summary={'decision':'ROBUSTNESS_DIAGNOSTICS_COMPLETE_PENDING_RSCH_JUDGMENT','evaluated':len(rows),'qualified':26,
            'original_unique_parameters':len(table),'original_distinct_qualified_accounts':18,'full_baseline_ledgers_equal':True,
            'maximum_two_sided_dimensions':int(ns.two_sided_dimensions.max()),
            'cost_scenario_pass_counts':{s:int(costs.loc[(~costs.is_benchmark)&costs.scenario.eq(s),'original_gates_under_scenario'].sum()) for s in SCENARIOS},
            'configured_workers':WORKERS,'parallelism':'PUBLIC_HARNESS_THREADS_PER_COST_SCENARIO','native_threads_per_process':1,
            'new_parameter_search':False,'development_only':True,'stage_four_complete':False,'candidate_selected':False}
        assert len(rows)==BUDGET; js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.INCONCLUSIVE,facts=summary,diagnostics={'all_diagnostics_report_only':True},artifacts=tuple(artifacts))
