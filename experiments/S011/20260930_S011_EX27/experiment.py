"""Optuna-managed one-axis neighborhood diagnosis with full SRT/TXE accounts."""
from pathlib import Path
from datetime import date
import importlib.util
import json
import time
from io import StringIO
import numpy as np
import pandas as pd
import optuna
from dataflows import Dataset
from strategy_runtime import StrategyCandidate,StrategyRuntime,implementation_sha256
from research_experiment import (ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentStage,
    ExperimentProtocol,ExperimentDependency,ExperimentCapabilities,ExperimentCapability,ExperimentResult,ExperimentOutcome)
from czsc_trader.research_tools import EvaluationRequest,EvaluationWindow,EvaluationCost
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX27'; SEED=2026093027; BUDGET=120; WORKERS=8; TRIALS=15
START=date(2025,2,6); CUTOFF=date(2026,9,28)
ROOT=Path(__file__).resolve().parent; REPO=ROOT.parents[2]; RUNTIME=ROOT/'runtime/strategy_runtime'
SOURCE=('strategies/s011_reversal.py',)
PREDECESSORS={
    '20260930_S011_EX15':'de2edb5fcd83395ec3b3f68ae9cabe2acb933c4ad36332dc708f33c6639d8014',
    '20260930_S011_EX16':'8df1748c63ac7ef1601203a161968351214ddf10b4fa7e83673946bf5924622e',
    '20260930_S011_EX20':'3689ecb8e4fbc9f6f59cad52f099db7bf09dc3bc24c775751ed274e2675f1799',
    '20260930_S011_EX23':'f9bfa2035bdb96eea6ddc8abc426301cf1ae78f437a91b43fa06f1e2c458a827',
    '20260930_S011_EX22':'8c35b0cc01c89ada91946e8f47971ebaf3c12789a4c3a88b63a5dcafb91e94d1',
    '20260930_S011_EX24':'c215ce0978fb9a7587336cd38ec9c88145760d03557b34efd8152750175b754e',
    '20260930_S011_EX25':'5d936c5fd0b46fe697138c476f282594fe24f58582494f8ec5c2f6160102ddfc',
    '20260930_S011_EX26':'15d21ed0b8f17b4a5b004f5f17a5cdd6b3b796a73fe38d30265128361de787b1'}
CENTER={'tail_weight':.575,'spx_weight':.05,'entry':.325,'exit':.025,'max_days':2,'lookback':130,'premium':.0025}
STEPS={'tail_weight':.025,'spx_weight':.025,'entry':.005,'exit':.025,'max_days':1,'lookback':10,'premium':.0005}
FEES=(.001,.00125,.0015,.002,.0025,.003,.004,.005)
SCENARIOS=('standard','fee_12_5bp','fee_15bp','fee_20bp','fee_25bp','fee_30bp','fee_40bp','fee_50bp')
LEDGERS=('decisions','orders','fills','account_daily','trades')


def study():
    result=optuna.create_study(storage=optuna.storages.InMemoryStorage(),
        sampler=optuna.samplers.GridSampler({'axis':list(STEPS),'direction':[-1,1]},seed=SEED),directions=['maximize','maximize'])
    result.enqueue_trial({'axis':'entry','direction':0})
    return result


def suggest(trial):
    axis=trial.suggest_categorical('axis',list(STEPS)); direction=trial.suggest_int('direction',-1,1)
    params=dict(CENTER); params[axis]=round(params[axis]+direction*STEPS[axis],10)
    if axis in ('max_days','lookback'):params[axis]=int(params[axis])
    return axis,direction,params


def payload(params):
    return {'strategy_kind':'s011_short_pressure_reversal','symbol':'159326.SZ','parameters':params,
        'runtime':{'module':'strategy_runtime.strategies.s011_reversal','qualname':'S011Reversal','contract_version':1,
            'source_files':list(SOURCE),'source_sha256':implementation_sha256(SOURCE,source_root=RUNTIME)}}


def metrics(account,trades=None):
    eq=account.equity; n=len(eq)
    r={'cagr':float((eq.iloc[-1]/1e6)**(252/n)-1),'drawdown':float((eq/eq.cummax().clip(lower=1e6)-1).min()),'end_equity':float(eq.iloc[-1])}
    if trades is not None:r.update(closed_trades=int(trades.status.eq('CLOSED').sum()),frequency=60*int(trades.status.eq('CLOSED').sum())/n)
    return r


def qualifies(m,b):
    return bool(m['cagr']>=1.5*b['cagr'] and (b['cagr']>0 or(m['cagr']>0 and m['cagr']>b['cagr'])) and m['drawdown']>b['drawdown'] and 4<=m['frequency']<=6)


def canonical(frames):
    maps={k:{} for k in ('decision_id','order_id','fill_id','cycle_id')}; result={}
    for name,frame in frames.items():
        out=frame.copy()
        for key,mapping in maps.items():
            if key not in out:continue
            values=[]
            for value in out[key]:
                if pd.isna(value):values.append(value);continue
                if value not in mapping:mapping[value]=f'{key}:{len(mapping)}'
                values.append(mapping[value])
            out[key]=values
        result[name]=out
    return result


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Does the preregistered interior center retain the mandate under all seven two-sided parameter probes?',
            hypothesis='A supported representative region should extend beyond the two previously covered dimensions.',
            falsification_conditions=('Local changes reveal sharp feasibility loss','Signal or execution equivalence fails'),
            development_cutoff=CUTOFF,random_seed=SEED,allowed_datasets=tuple(d.value for d in
                (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,Dataset.GLOBAL_INDEX_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=tuple(ExperimentDependency(n,v) for n,v in
                (('numpy',np.__version__),('pandas',pd.__version__),('optuna',optuna.__version__))),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.ROBUSTNESS,first_principles=('Parameter support requires explicitly observed neighboring behavior',),
                information_paths=('Known center -> Optuna native grid -> independent candidate preparation -> complete accounts',),
                stage_objectives=('Complete seven-dimensional two-sided diagnostic coverage without optimizing a new winner',),
                observation_metrics=('Original gates','Account differences','Cost sensitivity','Coverage'),
                methodology=('InMemoryStorage; native GridSampler; fixed center plus 14 probes',
                    '8 concurrent cost evaluations per sequential proposal; full SRT/TXE; no automatic retries',
                    'Stage-four diagnostics only; no additional hard gates'),predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING); s=study(); points=[]
        def objective(trial):
            axis,d,p=suggest(trial); points.append(p)
            StrategyRuntime().describe(StrategyCandidate('S011',f'EX27SYN{trial.number:03}',payload(p),RUNTIME))
            return 0.,0.
        s.optimize(objective,n_trials=TRIALS,n_jobs=1)
        assert s.sampler.is_exhausted(s) and len(points)==TRIALS
        assert points[0]==CENTER and len({json.dumps(p,sort_keys=True) for p in points})==15
        assert BUDGET==TRIALS*len(FEES) and len(FEES)==WORKERS
        assert payload(CENTER)['runtime']['source_sha256']=='53faf44a861c97e83ce72c7827685791530a96b1e53ee0a6cefb5dab11fab71e'

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        for ex,receipt in PREDECESSORS.items():
            validate_experiment_archive(ROOT.parent/ex); assert context.predecessors[ex].receipt_sha256==receipt
        artifacts=[]
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,lineterminator='\n',compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'S011-EX27-account'))
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX27-evidence'))
        prior=ROOT.parent/'20260930_S011_EX15/artifacts'
        frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
        gate=json.loads((prior/'execution_data_gate.json').read_text()); assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1
        days=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(CUTOFF)),'dt'])
        data=BacktestExecutionData(root=REPO/'.tmp/s011-ex27-execution',symbol='159326.SZ',asset_type='etf',fingerprint=gate['fingerprint'],cutoff=CUTOFF,evaluation_sessions=days,**frames)
        bh={s:metrics(pd.read_csv(ROOT.parent/f'20260930_S011_EX26/artifacts/accounts/EX16BH/{s}/account_daily.csv.gz')) for s in SCENARIOS}
        rows=[]; parameters=[]; s=study()
        def objective(trial):
            if trial.number:time.sleep(10)
            axis,direction,p=suggest(trial); parameters.append(p); i=trial.number
            js(f'trials/T{i:03}/payload.json',payload(p))
            candidate=StrategyCandidate('S011',f'EX27T{i:03}',payload(p),RUNTIME)
            try:
                result=context.evaluation.evaluate(EvaluationRequest(repository_root=REPO,experiment_id=ID,strategy=candidate,
                    runtime_binding={'candidate_id':candidate.reference_id,'source_files':list(SOURCE),'implementation_sha256':payload(p)['runtime']['source_sha256']},
                    symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),development_cutoff=CUTOFF,initial_cash=1e6,
                    costs=tuple(EvaluationCost(scenario,fee,'SCREENING' if scenario=='standard' else 'STRESS') for scenario,fee in zip(SCENARIOS,FEES)),execution_data=data,workers=WORKERS))
            except Exception as exc:
                js(f'trials/T{i:03}/failure.json',{'state':'FAIL','parameters':p,'error':str(exc)}); raise
            js(f'trials/T{i:03}/identity.json',{'candidate_id':candidate.reference_id,'request_hash':result.request_hash,'result_hash':result.result_hash,
                'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash})
            standard=None
            for run in result.runs:
                execution=run.execution; scenario=run.scenario_id; fee=FEES[SCENARIOS.index(scenario)]
                observed={name:pd.read_csv(StringIO(getattr(execution,name).to_csv(index=False))) for name in LEDGERS}
                for name,frame in observed.items():save(f'trials/T{i:03}/{scenario}/{name}.csv.gz',frame)
                if i==0 and scenario=='standard':
                    old={name:pd.read_csv(ROOT.parent/f'20260930_S011_EX25/artifacts/trials/T014/{name}.csv.gz') for name in LEDGERS}
                    a,b=canonical(old),canonical(observed)
                    for name in LEDGERS:pd.testing.assert_frame_equal(a[name],b[name],check_exact=False,rtol=1e-12,atol=1e-8)
                m=metrics(execution.account_daily,execution.trades); b=bh[scenario]
                row={'trial':i,'axis':axis,'direction':direction,**p,'scenario':scenario,'fee':fee,**m,
                    'buyhold_cagr':b['cagr'],'buyhold_drawdown':b['drawdown'],'qualified':qualifies(m,b),
                    'unfilled_orders':int(execution.orders.status.ne('FILLED').sum())}
                rows.append(row)
                if scenario=='standard':standard=row
            trial.set_user_attr('actual_parameters',p); trial.set_user_attr('standard_qualified',standard['qualified'])
            js(f'checkpoints/T{i:03}.json',{'completed_parameters':len(parameters),'evaluated_accounts':len(rows),'standard':standard})
            print(json.dumps(standard),flush=True)
            return standard['cagr'],standard['drawdown']
        def record(study,frozen):
            js(f'trials/T{frozen.number:03}/optuna_trial.json',{'number':frozen.number,'state':frozen.state.name,'parameters':frozen.params,
                'values':frozen.values,'user_attrs':frozen.user_attrs,'system_attrs':frozen.system_attrs,
                'distributions':{k:optuna.distributions.distribution_to_json(v) for k,v in frozen.distributions.items()}})
        s.optimize(objective,n_trials=TRIALS,n_jobs=1,callbacks=[record])
        assert s.sampler.is_exhausted(s) and len(rows)==BUDGET
        table=pd.DataFrame(rows); standard=table.loc[table.scenario.eq('standard')]
        save('cost_sensitivity.csv',table); save('trials.csv',standard); js('trial_parameters.json',parameters)
        summary={'decision':'LOCAL_NEIGHBORHOOD_DIAGNOSIS_COMPLETE_PENDING_RSCH_JUDGMENT','evaluated':len(rows),
            'parameter_trials':len(standard),'qualified':int(standard.qualified.sum()),'qualified_neighbors':int(standard.iloc[1:].qualified.sum()),
            'covered_dimensions':7,'center_exact_replay':True,'configured_workers':WORKERS,'coordinator_n_jobs':1,
            'storage':'InMemoryStorage','parallelism':'PUBLIC_HARNESS_THREADS_PER_COST_SCENARIO','development_only':True,'stage_four_complete':False}
        js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.INCONCLUSIVE,facts=summary,diagnostics={'joint_parameter_cube_not_tested':True},artifacts=tuple(artifacts))
