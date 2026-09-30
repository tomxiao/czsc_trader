"""Paired balanced perturbation study on four fixed S011 configurations."""
from pathlib import Path
from datetime import date
from io import StringIO
from threading import Lock
from hashlib import sha256
import json
import os
import time
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
from design import CENTERS,FIELDS,STEPS,SEED,design,study,synthetic

ID='20260930_S011_EX28';START=date(2025,2,6);CUTOFF=date(2026,9,28)
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parents[2];RUNTIME=ROOT/'runtime/strategy_runtime'
SOURCE=('strategies/s011_reversal.py',);WORKERS=max(1,(os.cpu_count() or 1)//2)
SLOTS,POINTS=design();BUDGET=len(POINTS)*2
PREDECESSORS={
 '20260930_S011_EX15':'de2edb5fcd83395ec3b3f68ae9cabe2acb933c4ad36332dc708f33c6639d8014',
 '20260930_S011_EX24':'c215ce0978fb9a7587336cd38ec9c88145760d03557b34efd8152750175b754e',
 '20260930_S011_EX26':'15d21ed0b8f17b4a5b004f5f17a5cdd6b3b796a73fe38d30265128361de787b1',
 '20260930_S011_EX27':'b55070de3c4d5c3214940e356f972be150e2229d2e4ac7d6e387304b63e92631'}
LEDGERS=('decisions','orders','fills','account_daily','trades')

def payload(p):
    return {'strategy_kind':'s011_short_pressure_reversal','symbol':'159326.SZ','parameters':p,
      'runtime':{'module':'strategy_runtime.strategies.s011_reversal','qualname':'S011Reversal','contract_version':1,
                 'source_files':list(SOURCE),'source_sha256':implementation_sha256(SOURCE,source_root=RUNTIME)}}

def metrics(account,trades):
    eq=account.equity;n=len(eq);count=int(trades.status.eq('CLOSED').sum())
    return {'cagr':float((eq.iloc[-1]/1e6)**(252/n)-1),'drawdown':float((eq/eq.cummax().clip(lower=1e6)-1).min()),
            'closed_trades':count,'frequency':60*count/n,'end_equity':float(eq.iloc[-1]),'sessions':n}

def normalized(frames):
    maps={k:{} for k in ('decision_id','order_id','fill_id','cycle_id')};out={}
    for name,frame in frames.items():
        f=frame.copy()
        for key,mapping in maps.items():
            if key not in f:continue
            def value(v):
                if pd.isna(v):return v
                if v not in mapping:mapping[v]=f'{key}:{len(mapping)}'
                return mapping[v]
            f[key]=f[key].map(value)
        out[name]=f
    return out

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='How do four fixed front configurations behave under matched balanced joint perturbations?',
            hypothesis='Observed local support may differ between equivalent centers and between return/drawdown behaviors.',
            falsification_conditions=('Local deterioration contradicts broad-region support','Equivalent centers diverge under matched changes'),
            development_cutoff=CUTOFF,random_seed=SEED,allowed_datasets=tuple(d.value for d in
                (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,Dataset.GLOBAL_INDEX_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=tuple(ExperimentDependency(n,v) for n,v in
                (('numpy',np.__version__),('pandas',pd.__version__),('optuna',optuna.__version__))),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.ROBUSTNESS,
                first_principles=('Parameter perturbation evidence must have matched geometry and disclosed aliasing',),
                information_paths=('Fixed four centers -> balanced design -> Optuna queue -> public process SRT/TXE accounts',),
                stage_objectives=('Complete prespecified diagnostics without selection or new economic gates',),
                observation_metrics=('Original goal margins','Return/drawdown distributions','Paired differences','Holding-period interactions'),
                methodology=('188 design slots deduplicated to 184 parameter vectors; two cost scenarios each',
                    'Optuna InMemoryStorage in parent; half logical cores spawn workers; one native thread;10s start spacing',
                    'No adaptive winner optimization, no retry or imputation; retain source identities and complete ledgers'),
                predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING);synthetic()
        assert len(POINTS)==184 and BUDGET==368 and WORKERS==8
        for i,p in enumerate(POINTS):StrategyRuntime().describe(StrategyCandidate('S011',f'EX28SYN{i:03}',payload(p),RUNTIME))
        assert payload(POINTS[0])['runtime']['source_sha256']=='53faf44a861c97e83ce72c7827685791530a96b1e53ee0a6cefb5dab11fab71e'

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS);context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        for ex,receipt in PREDECESSORS.items():
            validate_experiment_archive(ROOT.parent/ex);assert context.predecessors[ex].receipt_sha256==receipt
        artifacts=[];lock=Lock();rows=[];completion=[]
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
            with lock:artifacts.append(context.workspace.register_artifact(name,'S011-EX28-evidence'))
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,lineterminator='\n',compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            with lock:artifacts.append(context.workspace.register_artifact(name,'S011-EX28-account'))
        prior=ROOT.parent/'20260930_S011_EX15/artifacts'
        frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
        gate=json.loads((prior/'execution_data_gate.json').read_text());assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1
        days=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(CUTOFF)),'dt'])
        data=BacktestExecutionData(root=REPO/'.tmp/s011-ex28-execution',symbol='159326.SZ',asset_type='etf',fingerprint=gate['fingerprint'],cutoff=CUTOFF,evaluation_sessions=days,**frames)
        benchmark={}
        for scenario in ('standard','fee_20bp'):
            a=pd.read_csv(ROOT.parent/f'20260930_S011_EX26/artifacts/accounts/EX16BH/{scenario}/account_daily.csv.gz');eq=a.equity
            benchmark[scenario]={'cagr':float((eq.iloc[-1]/1e6)**(252/len(eq))-1),'drawdown':float((eq/eq.cummax().clip(lower=1e6)-1).min())}
        js('design_slots.json',SLOTS);js('unique_parameters.json',POINTS)
        js('protocol.json',{'seed':SEED,'slots':188,'unique_parameters':184,'budget':BUDGET,'workers':WORKERS,'steps':dict(zip(FIELDS,STEPS)),
            'benchmark':benchmark,'center_ids':list(CENTERS),'no_new_hard_gates':True,'development_only':True,'automatic_promotion':False})
        s=study()
        def objective(trial):
            i=trial.suggest_int('design_id',0,len(POINTS)-1);p=POINTS[i];candidate=StrategyCandidate('S011',f'EX28T{i:03}',payload(p),RUNTIME)
            trial.set_user_attr('actual_parameters',p);js(f'trials/T{i:03}/payload.json',payload(p))
            try:
                result=context.evaluation.evaluate(EvaluationRequest(repository_root=REPO,experiment_id=ID,strategy=candidate,
                    runtime_binding={'candidate_id':candidate.reference_id,'source_files':list(SOURCE),'implementation_sha256':payload(p)['runtime']['source_sha256']},
                    symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),development_cutoff=CUTOFF,initial_cash=1e6,
                    costs=(EvaluationCost('standard',.001,'SCREENING'),EvaluationCost('fee_20bp',.002,'STRESS')),execution_data=data,workers=1))
            except Exception as exc:
                js(f'trials/T{i:03}/failure.json',{'state':'FAIL','parameters':p,'error':str(exc)});raise
            js(f'trials/T{i:03}/identity.json',{'candidate_id':candidate.reference_id,'request_hash':result.request_hash,'result_hash':result.result_hash,
                'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash})
            for run in result.runs:
                observed={name:pd.read_csv(StringIO(getattr(run.execution,name).to_csv(index=False))) for name in LEDGERS}
                for name,f in observed.items():save(f'trials/T{i:03}/{run.scenario_id}/{name}.csv.gz',f)
                if i<4 and run.scenario_id=='standard':
                    old_index=(3,11,7,15)[i]
                    old={name:pd.read_csv(ROOT.parent/f'20260930_S011_EX24/artifacts/trials/T{old_index:03}/{name}.csv.gz') for name in LEDGERS}
                    aa,bb=normalized(old),normalized(observed)
                    for name in LEDGERS:pd.testing.assert_frame_equal(aa[name],bb[name],check_exact=False,rtol=1e-12,atol=1e-8)
                    js(f'trials/T{i:03}/anchor_check.json',{'center_config_id':list(CENTERS)[i],'five_economic_ledgers_equal':True})
                m=metrics(run.execution.account_daily,run.execution.trades);b=benchmark[run.scenario_id]
                flags={'return_pass':m['cagr']>=1.5*b['cagr'] and (b['cagr']>0 or m['cagr']>max(0,b['cagr'])),
                       'drawdown_pass':m['drawdown']>b['drawdown'],'frequency_pass':4<=m['frequency']<=6}
                frames_norm=normalized(observed);behavior=sha256(''.join(frames_norm[n].to_json(orient='split',date_format='iso',double_precision=10) for n in LEDGERS).encode()).hexdigest()
                row={'design_id':i,'optuna_trial':trial.number,'scenario':run.scenario_id,**p,**m,**flags,'qualified':all(flags.values()),
                     'fees':float(run.execution.fills.fees.sum()),'unfilled_orders':int(run.execution.orders.status.ne('FILLED').sum()),'behavior_hash':behavior}
                with lock:rows.append(row)
                if run.scenario_id=='standard':standard=row
            with lock:completion.append(i);done=len(completion)
            js(f'trials/T{i:03}/metrics.json',[r for r in rows if r['design_id']==i])
            print(json.dumps({'completed':done,'total':len(POINTS),'design_id':i,'cagr':standard['cagr'],'qualified':standard['qualified']}),flush=True)
            return standard['cagr'],standard['drawdown']
        def callback(study,frozen):
            i=frozen.params['design_id'];js(f'trials/T{i:03}/optuna.json',{'number':frozen.number,'state':frozen.state.name,'parameters':frozen.params,
               'user_attrs':frozen.user_attrs,'values':frozen.values,'started':str(frozen.datetime_start),'completed':str(frozen.datetime_complete),
               'distributions':{k:optuna.distributions.distribution_to_json(v) for k,v in frozen.distributions.items()}})
        try:s.optimize(objective,n_trials=len(POINTS),n_jobs=WORKERS,callbacks=[callback])
        finally:
            save('completed_accounts.csv',pd.DataFrame(rows).sort_values(['design_id','scenario']) if rows else pd.DataFrame())
            js('completion_order.json',completion)
            js('trial_states.json',[{'number':t.number,'params':t.params,'state':t.state.name} for t in s.trials])
        assert len(rows)==BUDGET and len(completion)==len(POINTS)
        table=pd.DataFrame(rows);save('trials.csv',table)
        summary={'decision':'PERTURBATION_DIAGNOSTICS_COMPLETE_PENDING_USER_DECISION','evaluated':len(rows),'parameter_vectors':len(POINTS),
                 'design_slots':188,'configured_workers':WORKERS,'storage':'InMemoryStorage','center_replays_equal':4,
                 'new_hard_gates':False,'automatic_promotion':False,'statistical_scope':'fixed balanced design, not population success probability'}
        js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.INCONCLUSIVE,facts=summary,diagnostics={'full_factorial_not_tested':True,'development_only':True},artifacts=tuple(artifacts))
