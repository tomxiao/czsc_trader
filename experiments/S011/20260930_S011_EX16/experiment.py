"""Fixed lot-sized benchmark replay and all-point qualification audit."""
from pathlib import Path
from datetime import date
import json
import numpy as np
import pandas as pd
from dataflows import Dataset
from strategy_runtime import StrategyCandidate,StrategyRuntime,implementation_sha256,TradableWindow
from research_experiment import (
    ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentStage,ExperimentProtocol,
    ExperimentDependency,ExperimentCapabilities,ExperimentCapability,ExperimentResult,ExperimentOutcome)
from czsc_trader.research_tools import EvaluationRequest,EvaluationWindow,EvaluationCost
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.experiment_archive import validate_experiment_archive

ID='20260930_S011_EX16';SEED=2026093016;BUDGET=1;CUTOFF=date(2026,9,28);START=date(2025,2,6)
PREDECESSORS={'20260930_S011_EX15':'de2edb5fcd83395ec3b3f68ae9cabe2acb933c4ad36332dc708f33c6639d8014'}
ROOT=Path(__file__).resolve().parent;RUNTIME=ROOT/'runtime/strategy_runtime';SOURCE=('strategies/s011_buyhold.py',)


def payload():
    return {'strategy_kind':'s011_investable_buyhold','symbol':'159326.SZ','parameters':{'premium':.003},
        'runtime':{'module':'strategy_runtime.strategies.s011_buyhold','qualname':'S011BuyHold','contract_version':1,
                   'source_files':list(SOURCE),'source_sha256':implementation_sha256(SOURCE,source_root=RUNTIME)}}


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.DISCOVERY,
            research_question='Does the unchanged strategy pass against an integer-lot executable BuyHold?',
            hypothesis='The short-pressure expression meets the original account mandate with a comparable investable baseline.',
            falsification_conditions=('No EX15 account passes the investable benchmark','Benchmark accounting or causal execution fails'),
            development_cutoff=CUTOFF,random_seed=SEED,
            allowed_datasets=tuple(d.value for d in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',),dependencies=(ExperimentDependency('numpy',np.__version__),ExperimentDependency('pandas',pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True),
            protocol=ExperimentProtocol(stage=ExperimentStage.PROTOTYPE,
                first_principles=('A complete-account comparison requires tradable share quantities',),
                information_paths=('Prior-session intent -> executable integer-lot BuyHold',),
                stage_objectives=('Reassess unchanged 96 accounts against the investable baseline',),
                observation_metrics=('CAGR','Drawdown','Whole-window frequency','Benchmark fractional-share discrepancy'),
                methodology=('One fixed benchmark account; no new parameter search','Retain all prior selection history'),
                predecessor_experiment_ids=tuple(PREDECESSORS)))

    def synthetic_precheck(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('benchmark_precheck',RUNTIME/SOURCE[0]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        candidate=StrategyCandidate('S011','EX16BH',payload(),RUNTIME)
        impl=m.S011BuyHold(candidate);definition=StrategyRuntime().describe(candidate)
        sessions=pd.bdate_range('2025-02-05',periods=40)
        history=impl.calculate_history({},sessions)
        assert history.target_position.eq(1).all()
        pd.testing.assert_frame_equal(history.iloc[:10],impl.calculate_history({},sessions[:10]))
        scope=impl.derive_calculation_scope(TradableWindow(date(2025,2,6),date(2025,3,3)),tuple(pd.bdate_range('2025-01-01','2025-04-01').date))
        assert scope.signal_dates[date(2025,2,6)]==date(2025,2,5)
        assert definition.execution.settings['instrument']['lot_size']==100

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root=ROOT.parent/'20260930_S011_EX15';validate_experiment_archive(root)
        if context.predecessors[root.name].receipt_sha256!=PREDECESSORS[root.name]:raise ValueError('predecessor mismatch')
        p=root/'artifacts';artifacts=[]
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,lineterminator='\n',compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'S011-EX16-account'))
        def js(name,value):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX16-evidence'))
        frames={k:pd.read_csv(p/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
        gate=json.loads((p/'execution_data_gate.json').read_text())
        if not gate['constant_factor'] or gate['factor_min']!=1. or gate['factor_max']!=1.:raise ValueError('price basis not proved')
        days=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(CUTOFF)),'dt'])
        data=BacktestExecutionData(root=ROOT.parents[2]/'.tmp/s011-ex16-execution',symbol='159326.SZ',asset_type='etf',
            fingerprint=gate['fingerprint'],cutoff=CUTOFF,evaluation_sessions=days,**frames)
        candidate=StrategyCandidate('S011','EX16BH',payload(),RUNTIME);js('benchmark_payload.json',payload())
        result=context.evaluation.evaluate(EvaluationRequest(repository_root=ROOT.parents[2],experiment_id=ID,strategy=candidate,
            runtime_binding={'candidate_id':candidate.reference_id,'source_files':list(SOURCE),'implementation_sha256':candidate.payload['runtime']['source_sha256']},
            symbol='159326.SZ',asset_type='etf',windows=(EvaluationWindow('full',START,CUTOFF),),development_cutoff=CUTOFF,
            initial_cash=1e6,costs=(EvaluationCost('standard',.001,'SCREENING'),),execution_data=data))
        run=result.runs[0]
        for name in ('decisions','orders','fills','account_daily','trades'):save('benchmark_'+name+'.csv.gz',getattr(run.execution,name))
        js('benchmark_identity.json',{'request_hash':result.request_hash,'result_hash':result.result_hash,
            'strategy_identity':result.strategy_identity,'data_identity':result.data_identity,'runtime_binding_hash':result.runtime_binding_hash})
        b=run.execution.equity;bc=float((b.iloc[-1]/1e6)**(252/len(b))-1);bd=float((b/b.cummax().clip(lower=1e6)-1).min())
        rows=[]
        for trial in range(96):
            account=pd.read_csv(p/f'trials/T{trial:03}/account_daily.csv.gz');trades=pd.read_csv(p/f'trials/T{trial:03}/trades.csv.gz')
            if list(pd.to_datetime(account.date))!=list(b.index):raise ValueError('account dates differ from benchmark')
            eq=account.equity;n=len(eq);c=float((eq.iloc[-1]/1e6)**(252/n)-1);d=float((eq/eq.cummax().clip(lower=1e6)-1).min())
            closed=int(trades.status.eq('CLOSED').sum());freq=60*closed/n
            ret=c>=1.5*bc and (bc>0 or (c>0 and c>bc))
            rows.append({'trial':trial,'cagr':c,'drawdown':d,'closed_trades':closed,'sessions':n,'frequency':freq,
                'buyhold_cagr':bc,'buyhold_drawdown':bd,'return_pass':bool(ret),'drawdown_pass':d>bd,
                'frequency_pass':4<=freq<=6,'qualified':bool(ret and d>bd and 4<=freq<=6)})
        table=pd.DataFrame(rows);save('qualification.csv',table)
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        passing=table.loc[table.qualified].sort_values(['cagr','trial'],ascending=[False,True])
        decision='STAGE_THREE_QUALIFIED_PENDING_INDEPENDENT_AUDIT' if len(passing) else 'NO_QUALIFIED_EXPRESSION'
        old=pd.read_csv(p/'trials.csv').iloc[0]
        summary={'decision':decision,'evaluated':1,'reassessed_strategy_accounts':96,'qualified':len(passing),
            'qualified_trials':[int(x) for x in passing.trial],
            'diagnostic_anchor':None if passing.empty else int(passing.iloc[0].trial),'buyhold_cagr':bc,'buyhold_drawdown':bd,
            'prior_fractional_buyhold_cagr':float(old.buyhold_cagr),'prior_fractional_buyhold_drawdown':float(old.buyhold_drawdown),
            'benchmark_shares':int(run.execution.account_daily.quantity.iloc[-1]),
            'benchmark_first_fill':str(run.execution.fills.fill_time.iloc[0]),
            'benchmark_fees':float(run.execution.fills.fees.sum()),'stage_four_complete':False,'development_only':True}
        js('summary.json',summary)
        return ExperimentResult(outcome=ExperimentOutcome.PASS if len(passing) else ExperimentOutcome.FAIL,
            facts=summary,diagnostics={},artifacts=tuple(artifacts))
