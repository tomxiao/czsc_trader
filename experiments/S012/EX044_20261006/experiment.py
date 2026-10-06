"""First complete account contrasts of the approved S012 component panel."""
from datetime import date
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import optuna
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentDependency, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentCapability,
)
from strategy_runtime import StrategyCandidate, implementation_sha256
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, NextOpenBuyHold
from .strategy_runtime.strategies.s012 import synthetic_selfcheck

EID='EX044_20261006'
BASE=dict(opportunity='union',confirm_o01=False,hold_days=5,cooldown=0,
          risk_gate='none',risk_exit=False,trailing_stop=0.0,entry_premium=0.0,allocation=1.0)
CONFIGS=(
    dict(BASE,opportunity='o01'),dict(BASE,opportunity='o01',confirm_o01=True),
    dict(BASE,opportunity='m05'),dict(BASE,opportunity='o01_m05'),
    dict(BASE,opportunity='o01_m05',confirm_o01=True),dict(BASE,opportunity='n09'),
    dict(BASE,opportunity='momentum'),dict(BASE,opportunity='momentum_union'),
    dict(BASE,opportunity='o01_m05',hold_days=1),dict(BASE,opportunity='momentum',hold_days=1),
    dict(BASE,opportunity='m05',hold_days=1),dict(BASE,opportunity='always'),
)
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')

def summarize(run):
    o=run.observation;b=dict(run.buyhold.metrics)
    b['cagr']=float((run.buyhold.account_daily.equity.iloc[-1]/100000.)**(252/len(run.buyhold.account_daily))-1)
    freq=o.closed_trades*60/1535
    goals=[o.net_cagr>=float(b['cagr'])*1.5,abs(o.max_drawdown)<abs(float(b['max_drawdown'])),freq>=5]
    e=run.execution
    return dict(net_cagr=o.net_cagr,max_drawdown=o.max_drawdown,closed_trades=o.closed_trades,
                frequency=freq,benchmark=b,goals=goals,passed_all=all(goals),
                evaluation_sessions=len(e.account_daily),final_equity=float(e.account_daily.equity.iloc[-1]),
                final_quantity=int(e.account_daily.quantity.iloc[-1]),orders=len(e.orders),fills=len(e.fills),
                equity_columns=list(e.account_daily),trade_columns=list(e.trades),
                exposure=float((e.account_daily.quantity>0).mean()))

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,EID,'S012',ExperimentMode.FORMAL,
            '阶段二机会、确认与风险职责组合能否在真实账户中共同满足收益、回撤和频率目标？',
            '机会事件增益可能被限价成交、现金空置和费用抵消；用完整账户对照定位机制。',
            ('任一经济目标不成立即非达标候选。','确认或风险门降低容量时完整披露，不只选择保留收益。'),
            date(2026,9,30),12044,
            tuple(x.value for x in (Dataset.STRATEGY_FEATURE_EVIDENCE,Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY,Dataset.TRADING_CALENDAR)),
            ExperimentProtocol(ExperimentStage.PROTOTYPE,
                ('全部已见开发池；策略和基准实际区间2020-06-08至2026-09-30，损失上市首日1日。',),
                ('12个固定完整账户对照；Optuna enqueue/ask/tell，FULL计算，无筛选快算。',),
                ('净CAGR>=基准1.5倍、回撤幅度<基准、闭合交易*60/1535>=5同时成立。',),
                ('持有5日、日有效前收盘限价、每日重报；static全仓/半仓、二元风险退出。',),
                ('17:00信息截止，SRT20:31计划，T+1执行；100股、100000元、每侧10bp。',
                 '信号持有期非实际成交年龄；30m Low严格小于限价才触价，开盘优先。',
                 '数据继承EX017机会/EX018风险/EX019确认/EX041原生M05与全域动量，CSV不含未来标签或事后质量过滤。',
                 '初轮不作为搜索闭合；后继按成交、频率与收益分解扩展。'),
                predecessor_experiment_ids=('EX017_20261005','EX018_20261005','EX019_20261005','EX041_20261006')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','optuna')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True,selects_parameters=True,creates_candidate=True))

    def synthetic_precheck(self):
        facts=synthetic_selfcheck()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('CAUSAL_SIGNAL_CYCLES',ExperimentPreflightStatus.PASS,str(facts)),),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE,facts,{'scope':'synthetic boundaries only'}))

    def execute(self,context):
        context.record_capability(ExperimentCapability.SEARCH_PARAMETERS)
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        context.record_capability(ExperimentCapability.CREATE_CANDIDATE)
        root=Path.cwd();exp=Path(__file__).resolve().parent
        feature=exp/'strategy_runtime/resources/features.csv'
        # Raw predecessor hashes authenticated again inside the formal boundary.
        provenance=json.loads((exp/'feature_provenance.json').read_text(encoding='utf-8'))
        for full,expected in provenance['inputs'].items():
            eid,name=full.split('/',1)
            allowed={x.path:x.sha256 for x in context.predecessors[eid].artifacts}
            actual=sha256((exp.parent/eid/'artifacts/rex'/name).read_bytes()).hexdigest()
            assert allowed[name]==actual==expected
        assert sha256(feature.read_bytes()).hexdigest()==provenance['feature_sha256']
        study=optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=12044),direction='maximize')
        for p in CONFIGS:study.enqueue_trial(p)
        requests=[];trials=[]
        sources=('strategies/s012.py','resources/features.csv')
        package=exp/'strategy_runtime'
        digest=implementation_sha256(sources,source_root=package)
        for i in range(len(CONFIGS)):
            trial=study.ask()
            p={name:trial.suggest_categorical(name,list(dict.fromkeys(x[name] for x in CONFIGS))) for name in BASE}
            parameters={**p,'rule':{'data_source':{'package':'strategy_runtime','path':'resources/features.csv','sha256':provenance['feature_sha256']}}}
            payload={'runtime':{'module':'strategy_runtime.strategies.s012','qualname':'S012PlannedCycle','contract_version':1,'source_sha256':digest,'source_files':sources},'parameters':parameters}
            candidate=StrategyCandidate('S012',f'C{i+4100:04d}',payload,package)
            req=EvaluationRequest(root,EID,candidate,{'candidate_id':candidate.reference_id,'source_files':sources,'implementation_sha256':digest},
                '518850.SH','etf',(EvaluationWindow('DEVELOPMENT',date(2020,6,8),date(2026,9,30)),),
                date(2026,9,30),100000.,(EvaluationCost('BASE',.001,'FORMAL'),),
                benchmark=EvaluationBenchmark(execution=NextOpenBuyHold(lot_size=100)),workers=1,execution_mode='FULL')
            requests.append(req);trials.append((trial,p,payload))
        rows=[]
        shared=None
        for offset,end in ((0,1),(1,5),(5,9),(9,len(requests))):
            batch=tuple(replace(req,execution_data=shared) for req in requests[offset:end])
            outcomes=context.evaluation.evaluate_many(batch)
            for req,(trial,p,payload),out in zip(requests[offset:end],trials[offset:end],outcomes):
                if out.result is not None: shared=out.result.execution_data
                metrics=None if out.result is None else summarize(out.result.runs[0])
                study.tell(trial,state=optuna.trial.TrialState.FAIL) if metrics is None else study.tell(trial,metrics['net_cagr'])
                row={'candidate_id':req.strategy.candidate_id,'parameters':p,'payload':payload,
                     'source_root':package.relative_to(root).as_posix(),'hypothesis':self.definition.research_question,'implementation_sha256':digest,'feature_sha256':provenance['feature_sha256'],
                     'record':out.record.to_dict(),'metrics':metrics,'passed_all':bool(metrics and metrics['passed_all']),
                     'preflight_path':(exp/'artifacts/preflight.json').relative_to(root).as_posix()}
                rows.append(row)
                print('ACCOUNT',req.strategy.candidate_id,metrics if metrics else out.record.error_message,flush=True)
            write(context.workspace.path('trials.json'),rows)
        write(context.workspace.path('search.json'),{'method':'Optuna fixed contrasts enqueue/ask/tell','version':optuna.__version__,'seed':12044,'configs':CONFIGS,'stop_reason':'固定对照完成，需后继参数与密度优化，尚未完成阶段三。'})
        artifacts=tuple(context.workspace.register_artifact(name,'full_account_contrasts') for name in ('trials.json','search.json'))
        valid=[x for x in rows if x['metrics']]
        return ExperimentResult(ExperimentOutcome.PASS if any(x['passed_all'] for x in rows) else ExperimentOutcome.FAIL,
            {'formal_trials':len(rows),'successful_accounts':len(valid),'qualified':sum(x['passed_all'] for x in rows)},
            {'stage':'first contrasts; successors required','original_frequency_denominator':1535,'actual_sessions':1534},artifacts)
