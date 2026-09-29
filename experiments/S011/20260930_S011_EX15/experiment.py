"""Preregistered development search; complete SRT/TXE accounting, no governance writes."""
from __future__ import annotations
from datetime import date
from pathlib import Path
from itertools import product
import importlib.util
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from dataflows import Dataset, DataRequest
from strategy_runtime import StrategyCandidate, implementation_sha256, StrategyRuntime, TradableWindow
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentStage,
    ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentCapability, ExperimentResult, ExperimentOutcome,
)
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX15'
SEED=2026093013
BUDGET=96
START=date(2025,2,6)
CUTOFF=date(2026,9,28)
PREDECESSORS={'20260929_S011_EX12':'19f9d2da8376080b046864ff01df40ed0be56506685e5c0c4252456126a8b067',
              '20260930_S011_EX14':'a6de0a102c8a53e8ba427b58812ca6266eae88269b46bfb50d2126da463f2984'}
SOURCE=('strategies/s011_reversal.py',)
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime/strategy_runtime'


def module():
    spec=importlib.util.spec_from_file_location('s011_ex15_precheck', RUNTIME/SOURCE[0])
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def configurations():
    m=module()
    baseline=(.5,0.,.2,0.,3,60,0.)
    space=list(product((.25,.5,.75),(0.,.15,.3),(.1,.2,.3,.4),(-.2,0.,.05),(1,2,3),(20,60,120),(0.,.003,.01)))
    space.remove(baseline)
    selected=[baseline]+[space[int(i)] for i in np.random.default_rng(SEED).choice(len(space),BUDGET-1,replace=False)]
    return [dict(zip(m.FIELDS,p)) for p in selected]


def payload(params):
    return {'strategy_kind':'s011_short_pressure_reversal','symbol':'159326.SZ',
            'parameters':params,'runtime':{'module':'strategy_runtime.strategies.s011_reversal',
                'qualname':'S011Reversal','contract_version':1,'source_files':list(SOURCE),
                'source_sha256':implementation_sha256(SOURCE,source_root=RUNTIME)}}


def synthetic():
    m=module();dates=pd.bdate_range('2024-12-26',periods=100)
    v=1+np.arange(100)/1000;v+=np.sin(np.arange(100))*.02
    daily=pd.DataFrame({'Date':dates,'Open':v,'Close':v,'High':v+.02,'Low':v-.02})
    bars=pd.DataFrame([{'Date':d+pd.Timedelta(hours=h,minutes=mm),'Close':float(v[i]+np.sin(i+j)*.01)}
        for i,d in enumerate(dates) for j,(h,mm) in enumerate(((10,0),(10,30),(11,0),(11,30),(13,30),(14,0),(14,30),(15,0)))])
    inputs={'daily':daily,'bars':bars,'market':daily.copy(),
            'spx':pd.DataFrame({'Date':dates,'PercentChange':np.sin(np.arange(100))*.01})}
    f=m.features(inputs);p=configurations()[0];sessions=dates[30:]
    a=m.policy(f,p,sessions)
    pd.testing.assert_frame_equal(a.iloc[:35],m.policy(f.iloc[:65],p,sessions[:35]))
    changed={k:v.copy() for k,v in inputs.items()}
    for k in ('daily','market'):
        changed[k].loc[70:,['Open','Close','High','Low']]*=2
    changed['bars'].loc[changed['bars'].Date>=dates[70],'Close']*=2
    changed['spx'].loc[70:,'PercentChange']=.9
    b=m.features(changed);pd.testing.assert_frame_equal(f.iloc[:70],b.iloc[:70])
    scaled={k:v.copy() for k,v in inputs.items()};scales=pd.Series(np.arange(1,101),index=dates)
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
        c=StrategyCandidate('S011',f'EX15T{i:03}',payload(params),RUNTIME)
        StrategyRuntime().describe(c)
        impl=m.S011Reversal(c)
        scope=impl.derive_calculation_scope(TradableWindow(date(2025,2,6),date(2025,3,3)),tuple(pd.bdate_range('2024-12-01','2025-03-31').date))
        assert all(scope.inputs[k].start==date(2024,12,26) for k in ('daily','bars','market'))
        assert scope.inputs['spx'].start==date(2024,12,16)
        out=m.policy(f,params,sessions)
        runs=out.target_position.groupby(out.target_position.ne(out.target_position.shift()).cumsum()).sum()
        assert runs.max()<=params['max_days'] and out.target_position.isin([0,1]).all()
    bad=dict(p,max_days=4)
    try:StrategyRuntime().describe(StrategyCandidate('S011','EX15BAD',payload(bad),RUNTIME))
    except ValueError:pass
    else:raise AssertionError('illegal parameter accepted')
    assert len({json.dumps(p,sort_keys=True) for p in configurations()})==BUDGET


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Can causal short-pressure repair meet the three complete-account objectives?',
            hypothesis='Market and ETF pressure with optional prior SPX confirmation admits tradable next-session repair.',
            falsification_conditions=('No sampled expression meets all three objectives','Price or causal input contract fails'),
            development_cutoff=CUTOFF,random_seed=SEED,
            allowed_datasets=tuple(d.value for d in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,
                Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,Dataset.GLOBAL_INDEX_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=(ExperimentDependency('numpy',np.__version__),ExperimentDependency('pandas',pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True,selects_parameters=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=('Temporary pressure may reverse within one to three sessions',),
                information_paths=('T completed inputs -> T+1 limit buy or market exit',),
                stage_objectives=('Full SRT/TXE account meets return drawdown frequency mandate',),
                observation_metrics=('CAGR','Maximum drawdown','60 x closed trades / all sessions','Missed participation and fees'),
                methodology=('96 seeded joint parameter points, all full accounts','Development pool only; no independent validation'),
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
            artifacts.append(context.workspace.register_artifact(name,'S011-EX15-ledger'))
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX15-contract'))
        failed=ROOT.parent/'20260930_S011_EX13'
        validate_experiment_archive(failed)
        if sha256((failed/'experiment_manifest.json').read_bytes()).hexdigest()!='e2a250b792ce3b5cc6b1bce97aa7ff9d8ac52968760a85d98f2435beaaa40973':raise ValueError('technical predecessor changed')
        params=configurations()
        previous=json.loads((ROOT.parent/'20260930_S011_EX14/artifacts/trial_parameters.json').read_text())
        if params!=previous:raise ValueError('successor changed the fixed 96 parameter points')
        js('trial_parameters.json',params)
        provenance=[]
        class AuditedData:
            def fetch(self,request):
                result=context.data.fetch(request)
                if not result.ready or result.identity is None:
                    raise ValueError('managed source unavailable: '+str(request.dataset))
                meta=dict(result.identity.metadata)
                expected='hfq' if request.dataset==Dataset.ETF_OHLCV else ('none' if request.dataset==Dataset.ETF_UNADJUSTED_DAILY else None)
                if expected is not None and meta.get('adjustment')!=expected:
                    raise ValueError('price basis mismatch: '+str(request.dataset))
                number=len(provenance)
                save(f'sources/source_{number:02}.csv.gz',result.dataframe)
                provenance.append({'dataset':str(request.dataset),'symbol':request.symbol,'frequency':request.frequency,
                    'start':str(request.start),'end':str(request.end),'content_sha256':result.identity.content_sha256,'metadata':meta})
                return result
        audited=AuditedData()
        print('EX15 preparing managed execution inputs',flush=True)
        data=prepare_backtest_execution_data(srt_data_root=repo/'.tmp/s011-ex15-execution',symbol='159326.SZ',asset_type='etf',
            start=START,end=CUTOFF,env_file=repo/'.env',dataflows=audited)
        for dataset,symbol in ((Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH'),(Dataset.GLOBAL_INDEX_DAILY,'SPX')):
            audited.fetch(DataRequest(dataset,symbol,'2024-12-16',CUTOFF.isoformat(),None,'daily',{'env_file':str(repo/'.env')}))
        js('source_identities.json',provenance)
        for name,frame in [('execution_daily',data.execution_daily),('execution_intraday',data.execution_intraday),('adjusted_daily',data.adjusted_daily)]:
            save(name+'.csv.gz',frame)
        adjustment=data.adjusted_daily.set_index('dt').close/data.execution_daily.set_index('dt').close
        gate=adjustment.loc[adjustment.index>='2025-02-05']
        stable=bool(np.allclose(gate,gate.iloc[0],rtol=1e-8,atol=1e-10))
        js('execution_data_gate.json',{'fingerprint':data.fingerprint,'factor_min':float(gate.min()),
            'factor_max':float(gate.max()),'constant_factor':stable,'sessions':len(data.evaluation_sessions)})
        if not stable:
            js('summary.json',{'decision':'EXECUTION_CORPORATE_ACTION_GATE_BLOCKED','evaluated':0})
            return ExperimentResult(outcome=ExperimentOutcome.INCONCLUSIVE,facts={'decision':'EXECUTION_CORPORATE_ACTION_GATE_BLOCKED','evaluated':0},diagnostics={},artifacts=tuple(artifacts))
        rows=[];failures=[]
        for i,p in enumerate(params):
            candidate=StrategyCandidate('S011',f'EX15T{i:03}',payload(p),RUNTIME)
            binding={'candidate_id':candidate.reference_id,'source_files':list(SOURCE),'implementation_sha256':candidate.payload['runtime']['source_sha256']}
            js(f'trials/T{i:03}/payload.json',payload(p))
            result=context.evaluation.evaluate(EvaluationRequest(repository_root=repo,experiment_id=ID,strategy=candidate,
                runtime_binding=binding,symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),
                development_cutoff=CUTOFF,initial_cash=1e6,costs=(EvaluationCost('standard',.001,'SCREENING'),),execution_data=data))
            run=result.runs[0];execution=run.execution;bh=run.buyhold.account_daily.equity
            for name in ('decisions','orders','fills','account_daily','trades'):
                save(f'trials/T{i:03}/{name}.csv.gz',getattr(execution,name))
            js(f'trials/T{i:03}/identity.json',{'result_hash':result.result_hash,'request_hash':result.request_hash,
                'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash})
            if i==0:
                save('buyhold_account.csv.gz',run.buyhold.account_daily);save('buyhold_orders.csv',run.buyhold.orders)
            eq=execution.equity;n=len(eq);cagr=float((eq.iloc[-1]/1e6)**(252/n)-1)
            b_cagr=float((bh.iloc[-1]/1e6)**(252/n)-1)
            dd=float((eq/eq.cummax().clip(lower=1e6)-1).min());b_dd=float((bh/bh.cummax().clip(lower=1e6)-1).min())
            count=int(execution.trades.status.eq('CLOSED').sum());freq=60*count/n
            ret_ok=cagr>=1.5*b_cagr and (b_cagr>0 or (cagr>0 and cagr>b_cagr))
            row={'trial':i,**p,'cagr':cagr,'buyhold_cagr':b_cagr,'drawdown':dd,'buyhold_drawdown':b_dd,
                'closed_trades':count,'sessions':n,'frequency':freq,'return_pass':bool(ret_ok),'drawdown_pass':dd>b_dd,
                'frequency_pass':4<=freq<=6,'qualified':bool(ret_ok and dd>b_dd and 4<=freq<=6),
                'fees':float(execution.fills.fees.sum()),'orders':len(execution.orders),'fills':len(execution.fills)}
            rows.append(row)
            print(json.dumps(row),flush=True)
        table=pd.DataFrame(rows);save('trials.csv',table)
        previous=pd.read_csv(ROOT.parent/'20260930_S011_EX14/artifacts/trials.csv')
        comparison=table[['trial','cagr','drawdown','frequency','qualified']].merge(
            previous[['trial','cagr','drawdown','frequency','qualified']],on='trial',suffixes=('_corrected','_EX14'),validate='one_to_one')
        for field in ('cagr','drawdown','frequency'):
            comparison[field+'_delta']=comparison[field+'_corrected']-comparison[field+'_EX14']
        save('warmup_correction_comparison.csv',comparison)
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        eligible=table.loc[table.qualified];anchor=(eligible if len(eligible) else table).sort_values(['cagr','trial'],ascending=[False,True]).iloc[0]
        decision='STAGE_THREE_SCREENED_POINTS' if len(eligible) else 'NO_QUALIFIED_EXPRESSION'
        summary={'decision':decision,'evaluated':len(rows),'qualified':len(eligible),'diagnostic_anchor':int(anchor.trial),
                 'development_only':True,'stage_four_complete':False,'candidate_package_created':False}
        js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.PASS if len(eligible) else ExperimentOutcome.FAIL,
            facts=summary,diagnostics={'buyhold_cagr':float(anchor.buyhold_cagr)},artifacts=tuple(artifacts))
