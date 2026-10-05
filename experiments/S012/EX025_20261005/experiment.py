"""Dense/discount/fractional witnesses for real account execution equivalence."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from research_experiment import (
    ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentDataScope,
    ExperimentCapabilities,ExperimentProtocol,ExperimentStage,ExperimentResult,
    ExperimentOutcome,ExperimentDependency,ExperimentPrecheckResult,
    ExperimentPreflightCheck,ExperimentPreflightStatus,ExperimentCapability,
)
from dataflows import Dataset
from strategy_runtime import StrategyCandidate,implementation_sha256
from czsc_trader.research_tools import EvaluationRequest,EvaluationWindow,EvaluationCost
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark,NextOpenBuyHold
from .strategy_runtime.strategies.s012 import synthetic_selfcheck
from .managed_market import load
from .shared_binding import baseline,for_candidate

EID='EX025_20261005'
BASE=dict(opportunity='union',confirm_o01=False,hold_days=1,cooldown=0,risk_gate='none',risk_exit=False,trailing_stop=0.,entry_premium=.005,allocation=1.)
CONFIGS=(dict(BASE,opportunity='always',entry_premium=-.005),dict(BASE),dict(BASE,hold_days=2,entry_premium=.01,allocation=.5),dict(BASE,opportunity='always',hold_days=3,entry_premium=-.02,allocation=.5))

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,EID,'S012',ExperimentMode.FORMAL,
            '密集短持有、溢价/折价与半仓策略的完整成交现金台账能否被研究加速器忠实复现？',
            '复用同一策略函数与公开TXE成交规则可降低研究计算成本，必须先验证真实完整账本而非只比较指标。',
            ('任何信号、逐日现金、数量、费用、订单或交易经济字段不一致则禁止加速比较。',),
            date(2026,9,30),12024,tuple(x.value for x in (Dataset.STRATEGY_FEATURE_EVIDENCE,Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY,Dataset.TRADING_CALENDAR)),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('阶段三资源下执行语义验证，不改平台，不改变目标或数据；加速仅研究预筛，达标全部FULL。',),
                ('4个固定真实FULL账户：密集h1折价0.5%、联合h1溢价0.5%、联合h2溢价1%半仓、密集h3折价2%半仓。',),
                ('信号、全逐日账户、订单、成交、交易经济字段逐项等价，CAGR/MDD/频率三门照常报告。',),
                ('真实原价1534实际评价日、原1535硬频率分母，每侧10bp，100000元/100股。',),
                ('输入复用已有DFLS正式prepare，公开fetch逐身份核验并由REX记录，不重取数。',
                 '从已成功EX023-C0012正式单次结果取public input binding，newCandidate公开plan_inputs须全部请求相等才复用prepared。',
                 '策略源码及特征资源复用同S012 EX023模块，SHA验证；其全轮尚运行，完成后纳入最终交付证据闭包。',
                 '本实验4worker与EX023同时4worker，总8且原生线程1，半CPU资源约束。'),
                predecessor_experiment_ids=('EX017_20261005','EX018_20261005','EX019_20261005')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','optuna')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True,creates_candidate=True))

    def synthetic_precheck(self):
        facts=synthetic_selfcheck()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('CAUSAL_PUBLIC_POLICY',ExperimentPreflightStatus.PASS,str(facts)),),ExperimentResult(ExperimentOutcome.INCONCLUSIVE,facts,{'synthetic_only':True}))

    def execute(self,context):
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS);context.record_capability(ExperimentCapability.CREATE_CANDIDATE)
        root=Path.cwd();exp=Path(__file__).resolve().parent;package=exp.parent/'EX023_20261005/strategy_runtime'
        sources=('strategies/s012.py','resources/features.csv');digest=implementation_sha256(sources,source_root=package)
        assert digest==implementation_sha256(sources,source_root=exp/'strategy_runtime')
        data,market=load(context)
        prior,proof=baseline(root)
        calendar=context.data.fetch(prior.plan.requests[prior.plan.calendar_name],prepared=prior.prepared)
        write(context.workspace.path('source_reuse_proof.json'),{'baseline':proof,'implementation_sha256':digest,'market_fingerprint':data.fingerprint,'input_identities':data.input_identities,'mode':'new public runtime plan; exact request equality before preparation reuse'})
        requests=[];payloads=[]
        feature_sha=sha256((package/'resources/features.csv').read_bytes()).hexdigest()
        for i,p in enumerate(CONFIGS):
            payload={'runtime':{'module':'strategy_runtime.strategies.s012','qualname':'S012PlannedCycle','contract_version':1,'source_sha256':digest,'source_files':sources},'parameters':{**p,'rule':{'data_source':{'package':'strategy_runtime','path':'resources/features.csv','sha256':feature_sha}}}}
            candidate=StrategyCandidate('S012',f'C{100+i:04d}',payload,package)
            input_binding=for_candidate(context,candidate,prior,calendar)
            req=EvaluationRequest(root,EID,candidate,{'candidate_id':candidate.reference_id,'source_files':sources,'implementation_sha256':digest},'518850.SH','etf',
                (EvaluationWindow('DEVELOPMENT',date(2020,6,8),date(2026,9,30)),),date(2026,9,30),100000.,(EvaluationCost('BASE',.001,'FORMAL'),),
                benchmark=EvaluationBenchmark(execution=NextOpenBuyHold(lot_size=100)),execution_data=data,input_bindings={'DEVELOPMENT':input_binding},workers=1,execution_mode='FULL')
            requests.append(req);payloads.append(payload)
        outcomes=context.evaluation.evaluate_many(tuple(requests));rows=[]
        for req,p,payload,out in zip(requests,CONFIGS,payloads,outcomes):
            m=None
            if out.result is not None:
                run=out.result.runs[0];o=run.observation;b=dict(run.buyhold.metrics)
                b['cagr']=float((run.buyhold.account_daily.equity.iloc[-1]/100000.)**(252/1534)-1)
                frequency=o.closed_trades*60/1535;goals=[o.net_cagr>=b['cagr']*1.5,abs(o.max_drawdown)<abs(b['max_drawdown']),frequency>=5]
                m={'net_cagr':o.net_cagr,'max_drawdown':o.max_drawdown,'closed_trades':o.closed_trades,'frequency':frequency,'benchmark':b,'goals':goals,'passed_all':all(goals)}
            rows.append({'candidate_id':req.strategy.candidate_id,'parameters':p,'payload':payload,'source_root':package.relative_to(root).as_posix(),'hypothesis':self.definition.research_question,'record':out.record.to_dict(),'metrics':m,'passed_all':bool(m and m['passed_all']),'preflight_path':(exp/'artifacts/preflight.json').relative_to(root).as_posix()})
            print('WITNESS_ACCOUNT',req.strategy.candidate_id,m if m else out.record.error_message,flush=True)
        write(context.workspace.path('trials.json'),rows)
        artifacts=tuple(context.workspace.register_artifact(n,'equivalence_witness') for n in ('trials.json','source_reuse_proof.json'))
        return ExperimentResult(ExperimentOutcome.PASS if all(x['metrics'] for x in rows) else ExperimentOutcome.FAIL,{'formal_trials':4,'successful_accounts':sum(x['metrics'] is not None for x in rows),'qualified':sum(x['passed_all'] for x in rows)}, {'scope':'仅FULL见证账本，加速等价需独立比较'},artifacts)
