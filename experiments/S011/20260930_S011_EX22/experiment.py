"""Preregistered paired entry/exit boundary expansion; full SRT/TXE accounts."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import importlib.util
import json
from hashlib import sha256
import numpy as np
import pandas as pd
import time
from dataflows import Dataset
from strategy_runtime import StrategyCandidate, implementation_sha256, StrategyRuntime, TradableWindow
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentStage,
    ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentCapability, ExperimentResult, ExperimentOutcome,
)
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX22'
SEED=2026093022
BUDGET=42
START=date(2025,2,6)
CUTOFF=date(2026,9,28)
PREDECESSORS={}
SOURCE=('strategies/s011_reversal.py',)
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime/strategy_runtime'
BASELINE=dict(tail_weight=.75,spx_weight=.15,entry=.3,exit=0.,max_days=2,lookback=120,premium=.003)
ANCHOR=dict(tail_weight=.575,spx_weight=.05,entry=.335,exit=.025,max_days=2,lookback=130,premium=.005)
ENTRY_VALUES=(.325,.335,.345)
EXIT_VALUES=tuple(round(i*.025,8) for i in range(14))


def module():
    spec=importlib.util.spec_from_file_location('s011_ex22_precheck', RUNTIME/SOURCE[0])
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def configurations():
    points=[BASELINE.copy(),ANCHOR.copy()]
    for entry in ENTRY_VALUES:
        for exit_value in EXIT_VALUES:
            if exit_value>=entry:continue
            point=dict(ANCHOR,entry=entry,exit=exit_value)
            if point not in points:points.append(point)
    return points


def payload(params):
    return {'strategy_kind':'s011_short_pressure_reversal','symbol':'159326.SZ',
            'parameters':params,'runtime':{'module':'strategy_runtime.strategies.s011_reversal',
                'qualname':'S011Reversal','contract_version':1,'source_files':list(SOURCE),
                'source_sha256':implementation_sha256(SOURCE,source_root=RUNTIME)}}


def frontier(table):
    eligible=table.loc[table.qualified]
    ids=[]
    for row in eligible.itertuples():
        dominated=((eligible.cagr>=row.cagr)&(eligible.drawdown>=row.drawdown)&
                   ((eligible.cagr>row.cagr)|(eligible.drawdown>row.drawdown))).any()
        if not dominated:ids.append(int(row.trial))
    return ids



def canonical_ledgers(frames):
    """Normalize identity strings bijectively; retain every business field and join."""
    maps={name:{} for name in ('decision_id','order_id','fill_id','cycle_id')}
    result={}
    for name,frame in frames.items():
        out=frame.copy()
        for column,mapping in maps.items():
            if column not in out:continue
            values=[]
            for value in out[column]:
                if pd.isna(value):values.append(value);continue
                if value not in mapping:mapping[value]=f'{column}:{len(mapping)}'
                values.append(mapping[value])
            out[column]=values
        result[name]=out
    return result

def synthetic():
    a={'decisions':pd.DataFrame({'decision_id':['a','b'],'target_position':[1,0]}),'orders':pd.DataFrame({'decision_id':['a'],'order_id':['x']})}
    b={'decisions':pd.DataFrame({'decision_id':['c','d'],'target_position':[1,0]}),'orders':pd.DataFrame({'decision_id':['c'],'order_id':['y']})}
    for k in a:pd.testing.assert_frame_equal(canonical_ledgers(a)[k],canonical_ledgers(b)[k])
    b['orders']['decision_id']=['d']
    assert not canonical_ledgers(a)['orders'].equals(canonical_ledgers(b)['orders'])
    m=module();dates=pd.bdate_range('2024-12-26',periods=300)
    v=1+np.arange(300)/1000;v+=np.sin(np.arange(300))*.02
    daily=pd.DataFrame({'Date':dates,'Open':v,'Close':v,'High':v+.02,'Low':v-.02})
    bars=pd.DataFrame([{'Date':d+pd.Timedelta(hours=h,minutes=mm),'Close':float(v[i]+np.sin(i+j)*.01)}
        for i,d in enumerate(dates) for j,(h,mm) in enumerate(((10,0),(10,30),(11,0),(11,30),(13,30),(14,0),(14,30),(15,0)))])
    inputs={'daily':daily,'bars':bars,'market':daily.copy(),
            'spx':pd.DataFrame({'Date':dates,'PercentChange':np.sin(np.arange(300))*.01})}
    f=m.features(inputs);p=configurations()[0];sessions=dates[30:]
    a=m.policy(f,p,sessions)
    pd.testing.assert_frame_equal(a.iloc[:35],m.policy(f.iloc[:65],p,sessions[:35]))
    changed={k:v.copy() for k,v in inputs.items()}
    for k in ('daily','market'):
        changed[k].loc[70:,['Open','Close','High','Low']]*=2
    changed['bars'].loc[changed['bars'].Date>=dates[70],'Close']*=2
    changed['spx'].loc[70:,'PercentChange']=.9
    b=m.features(changed);pd.testing.assert_frame_equal(f.iloc[:70],b.iloc[:70])
    scaled={k:v.copy() for k,v in inputs.items()};scales=pd.Series(np.arange(1,301),index=dates)
    for col in ('Open','Close','High','Low'):scaled['daily'][col]*=scales.to_numpy()
    scaled['bars']['Close']*=scaled['bars'].Date.dt.normalize().map(scales)
    ff=m.features(scaled)
    for col in ('tail','risk5'):assert np.allclose(f[col],ff[col],equal_nan=True)
    assert (f.spx_source_time.dropna()<f.spx_decision_time.loc[f.spx_source_time.notna()]).all()
    assert f.spx.iloc[2]==inputs['spx'].PercentChange.iloc[1]
    broken=f.copy();broken.loc[sessions[0],'tail']=np.nan
    try:m.policy(broken,p,sessions)
    except ValueError:pass
    else:raise AssertionError('missing input accepted')
    for i,params in enumerate(configurations()):
        c=StrategyCandidate('S011',f'EX22T{i:03}',payload(params),RUNTIME)
        StrategyRuntime().describe(c)
        impl=m.S011Reversal(c)
        scope=impl.derive_calculation_scope(TradableWindow(date(2025,2,6),date(2025,3,3)),tuple(pd.bdate_range('2024-12-01','2025-03-31').date))
        assert all(scope.inputs[k].start==date(2024,12,26) for k in ('daily','bars','market'))
        assert scope.inputs['spx'].start==date(2024,12,16)
        out=m.policy(f,params,sessions)
        runs=out.target_position.groupby(out.target_position.ne(out.target_position.shift()).cumsum()).sum()
        assert runs.max()<=params['max_days'] and out.target_position.isin([0,1]).all()
    bad=dict(p,max_days=4)
    try:StrategyRuntime().describe(StrategyCandidate('S011','EX22BAD',payload(bad),RUNTIME))
    except ValueError:pass
    else:raise AssertionError('illegal parameter accepted')
    assert len({json.dumps(p,sort_keys=True) for p in configurations()})==len(configurations())
    assert len(configurations())==BUDGET
    assert all(p['exit']<p['entry'] for p in configurations())

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Can earlier pressure-release exits jointly with nearby entry thresholds improve EX19T054?',
            hypothesis='Raising the pressure-release exit threshold can reduce adverse second-session exposure without losing the original return and frequency gates.',
            falsification_conditions=('No evaluated feasible point improves the EX19 frontier','Causal or execution identity fails'),
            development_cutoff=CUTOFF,random_seed=SEED,
            allowed_datasets=tuple(d.value for d in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,
                Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,Dataset.GLOBAL_INDEX_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=tuple(ExperimentDependency(n,v) for n,v in
                (('numpy',np.__version__),('pandas',pd.__version__))),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True,selects_parameters=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=('Temporary pressure may reverse within one to three sessions',),
                information_paths=('T completed inputs -> T+1 limit buy or market exit',),
                stage_objectives=('Improve CAGR and drawdown subject to unchanged three hard gates',),
                observation_metrics=('CAGR','Drawdown','Whole-window frequency','Pareto improvement','Boundary and block progress'),
                methodology=('42 deterministic full accounts: two anchors and an entry/exit grid through the valid exit boundary',
                             'No new mechanism; T040 and EX19T054 paired economic ledger checks',
                             'No pruning or success stopping; development pool only'),
                predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        synthetic()

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        repo=ROOT.parents[2];artifacts=[]
        for ex,sha in PREDECESSORS.items():
            if context.predecessors[ex].receipt_sha256!=sha:raise ValueError('predecessor changed')
            validate_experiment_archive(ROOT.parent/ex)
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,lineterminator='\n',
                         compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'S011-EX22-ledger'))
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX22-evidence'))
        prior=ROOT.parent/'20260930_S011_EX15/artifacts'
        frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt'])
                for k in ('execution_daily','execution_intraday','adjusted_daily')}
        gate=json.loads((prior/'execution_data_gate.json').read_text())
        if not gate['constant_factor'] or gate['factor_min']!=1. or gate['factor_max']!=1.:
            raise ValueError('execution price gate failed')
        days=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(CUTOFF)),'dt'])
        data=BacktestExecutionData(root=repo/'.tmp/s011-ex22-execution',symbol='159326.SZ',asset_type='etf',
            fingerprint=gate['fingerprint'],cutoff=CUTOFF,evaluation_sessions=days,**frames)
        benchmark=pd.read_csv(ROOT.parent/'20260930_S011_EX16/artifacts/benchmark_account_daily.csv.gz')
        be=benchmark.equity
        bc=float((be.iloc[-1]/1e6)**(252/len(be))-1)
        bd=float((be/be.cummax().clip(lower=1e6)-1).min())
        anchor=pd.read_csv(ROOT.parent/'20260930_S011_EX16/artifacts/qualification.csv').set_index('trial').loc[40]
        previous=json.loads((ROOT.parent/'20260930_S011_EX21/artifacts/trials/T054/metrics.json').read_text())
        assert json.loads((ROOT.parent/'20260930_S011_EX21/artifacts/trials/T054/payload.json').read_text())['parameters']==ANCHOR
        js('search_contract.json',{'seed':SEED,'budget':BUDGET,'entry_values':ENTRY_VALUES,'exit_values':EXIT_VALUES,
            'configurations':configurations(),'directions':['maximize_cagr','maximize_negative_drawdown'],
            'benchmark_cagr':bc,'benchmark_drawdown':bd,'predecessors':PREDECESSORS,
            'warmup_policy':'unchanged 2024-12-26; min20 observations; capped expanding until lookback full'})
        rows=[];parameters=[];seen={};behaviors={}
        for i,p in enumerate(configurations()):
            if i:time.sleep(3)
            parameters.append(p)
            js(f'trials/T{i:03}/payload.json',payload(p))
            candidate=StrategyCandidate('S011',f'EX22T{i:03}',payload(p),RUNTIME)
            binding={'candidate_id':candidate.reference_id,'source_files':list(SOURCE),
                     'implementation_sha256':candidate.payload['runtime']['source_sha256']}
            try:
                result=context.evaluation.evaluate(EvaluationRequest(repository_root=repo,experiment_id=ID,strategy=candidate,
                    runtime_binding=binding,symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),
                    development_cutoff=CUTOFF,initial_cash=1e6,costs=(EvaluationCost('standard',.001,'SCREENING'),),execution_data=data))
            except Exception as exc:
                js(f'trials/T{i:03}/failure.json',{'state':'FAIL','error':str(exc),'parameters':p})
                raise
            execution=result.runs[0].execution
            originals={};observations={}
            for name in ('decisions','orders','fills','account_daily','trades'):
                frame=getattr(execution,name)
                save(f'trials/T{i:03}/{name}.csv.gz',frame)
                if i in (0,1):
                    original_path=(prior/f'trials/T040/{name}.csv.gz' if i==0 else
                                   ROOT.parent/f'20260930_S011_EX21/artifacts/trials/T054/{name}.csv.gz')
                    originals[name]=pd.read_csv(original_path)
                    from io import StringIO
                    observations[name]=pd.read_csv(StringIO(frame.to_csv(index=False)))
            if i in (0,1):
                originals=canonical_ledgers(originals);observations=canonical_ledgers(observations)
                for name in originals:pd.testing.assert_frame_equal(originals[name],observations[name],check_exact=False,rtol=1e-12,atol=1e-8)
            js(f'trials/T{i:03}/identity.json',{'result_hash':result.result_hash,'request_hash':result.request_hash,
                'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash})
            eq=execution.equity;n=len(eq)
            assert list(pd.to_datetime(benchmark.date))==list(eq.index) and n==403
            c=float((eq.iloc[-1]/1e6)**(252/n)-1);d=float((eq/eq.cummax().clip(lower=1e6)-1).min())
            count=int(execution.trades.status.eq('CLOSED').sum());freq=60*count/n
            ret=c>=1.5*bc and (bc>0 or (c>0 and c>bc))
            qualified=bool(ret and d>bd and 4<=freq<=6)
            constraints=[float(1.5*bc-c),float(np.nextafter(bd,np.inf)-d),float(4-freq),float(freq-6)]
            if bc<=0:constraints.extend([float(np.nextafter(0.,np.inf)-c),float(np.nextafter(bc,np.inf)-c)])
            assert qualified==all(x<=0 for x in constraints)
            js(f'trials/T{i:03}/search_trial.json',{'number':i,'state':'COMPLETE',
                'parameters':p,'values':[c,d],'constraints':constraints,'method':'PREREGISTERED_GRID'})
            key=json.dumps(p,sort_keys=True)
            behavior=sha256(execution.account_daily[['date','cash','quantity','equity']].to_csv(index=False).encode()).hexdigest()
            row={'trial':i,**p,'cagr':c,'drawdown':d,'closed_trades':count,'sessions':n,'frequency':freq,
                 'buyhold_cagr':bc,'buyhold_drawdown':bd,'qualified':qualified,
                 'return_pass':bool(ret),'drawdown_pass':d>bd,'frequency_pass':4<=freq<=6,
                 'fees':float(execution.fills.fees.sum()),'orders':len(execution.orders),'fills':len(execution.fills),
                 'duplicate_parameter_of':seen.get(key,-1),'same_account_as':behaviors.get(behavior,-1),
                 'cagr_delta_T040':c-float(anchor.cagr),'drawdown_improvement_T040':d-float(anchor.drawdown),
                 'cagr_delta_EX19T054':c-previous['cagr'],'drawdown_improvement_EX19T054':d-previous['drawdown'],
                 'dominates_EX19T054':bool(qualified and c>=previous['cagr'] and d>=previous['drawdown'] and (c>previous['cagr'] or d>previous['drawdown'])),
                 'dominates_T040':bool(qualified and c>=anchor.cagr and d>=anchor.drawdown and (c>anchor.cagr or d>anchor.drawdown))}
            rows.append(row);seen.setdefault(key,i);behaviors.setdefault(behavior,i)
            js(f'trials/T{i:03}/metrics.json',row)
            print(json.dumps(row),flush=True)
        table=pd.DataFrame(rows);save('trials.csv',table);js('trial_parameters.json',parameters)
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        pareto=frontier(table);save('pareto.csv',table.loc[table.trial.isin(pareto)])
        blocks=[]
        for end in (2,12,24,36,BUDGET):
            prefix=table.iloc[:end];eligible=prefix.loc[prefix.qualified]
            blocks.append({'through':end,'qualified':len(eligible),'unique_parameters':int((prefix.duplicate_parameter_of<0).sum()),
                'dominates_T040':int(prefix.dominates_T040.sum()),'pareto_trials':frontier(prefix),
                'best_cagr':None if eligible.empty else float(eligible.cagr.max()),
                'best_drawdown':None if eligible.empty else float(eligible.drawdown.max())})
        js('search_progress.json',blocks)
        eligible=table.loc[table.qualified]
        summary={'decision':'IMPROVED_EX19_FRONTIER' if table.dominates_EX19T054.any() else 'NO_EX19_DOMINANCE_FOUND',
            'evaluated':len(rows),'unique_parameters':len(seen),'distinct_accounts':len(behaviors),
            'qualified':len(eligible),'dominates_T040':int(table.dominates_T040.sum()),'dominates_EX19T054':int(table.dominates_EX19T054.sum()),'pareto_trials':pareto,
            'highest_return_trial':None if eligible.empty else int(eligible.sort_values(['cagr','drawdown'],ascending=False).iloc[0].trial),
            'lowest_drawdown_trial':None if eligible.empty else int(eligible.sort_values(['drawdown','cagr'],ascending=False).iloc[0].trial),
            'baseline_exact_replay':True,'development_only':True,'stage_four_complete':False,
            'stop_reason':'Preregistered round complete; continuation determined by frontier and boundary evidence, not first success'}
        js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.PASS if len(eligible) else ExperimentOutcome.FAIL,
            facts=summary,diagnostics={'buyhold_cagr':bc},artifacts=tuple(artifacts))
