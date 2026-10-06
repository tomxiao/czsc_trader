"""EX052 fixed selected-search and prospective control FULL witness; two dependencies."""
from dataclasses import replace
from datetime import date
from importlib.metadata import version
from pathlib import Path
import json
from dataflows import Dataset
from research_experiment import (ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult, ExperimentOutcome,
    ExperimentDependency, ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentCapability)
from strategy_runtime import StrategyCandidate, implementation_sha256, ParameterSet
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, NextOpenBuyHold
from .factory_contract import read, require, digest, authenticate, planned_batches, SOURCES as SOURCE_FILES, FEATURE_SHA
from .strategy_runtime.strategies.s012 import S012PlannedCycle

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')

def summarize(run):
    account=run.execution.account_daily;benchmark=run.buyhold.account_daily
    def metrics(table):
        equity=table.equity.astype(float)
        return {'cagr':float((equity.iloc[-1]/100000.)**(252/len(equity))-1),
                'max_drawdown':float((equity/equity.cummax().clip(lower=100000.)-1).min())}
    m=metrics(account);b=metrics(benchmark)
    closed=int(run.execution.trades.status.eq('CLOSED').sum());freq=closed*60/1535
    goals=[m['cagr']>=b['cagr']*1.5,abs(m['max_drawdown'])<abs(b['max_drawdown']),freq>=5]
    return {'net_cagr':m['cagr'],'max_drawdown':m['max_drawdown'],'closed_trades':closed,
            'frequency':freq,'frequency_denominator':1535,'benchmark':b,'goals':goals,'passed_all':all(goals),
            'evaluation_sessions':len(account),'final_equity':float(account.equity.iloc[-1]),
            'final_quantity':int(account.quantity.iloc[-1]),'orders':len(run.execution.orders),
            'fills':len(run.execution.fills),'total_fees':float(run.execution.fills.fees.sum()),
            'exposure':float(account.quantity.gt(0).mean())}

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        config=read(Path(__file__).with_name('full_config.json'))
        return ExperimentDefinition(2,config['experiment_id'],'S012',ExperimentMode.FORMAL,
            '冷却期的持有尾部与计划入场时点，以及风险阈值未知期参与，能否改善真实净收益？',
            '三个冷却对照隔离相同计划入场时点与改变周期时点；一个mom未知放行对照只改EX050原入场门的未知政策；唯一联合项沿用C4607止损参数，只将入场溢价改为.02，检验叠加而不预期正贡献。',
            ('净CAGR>=净BuyHold1.5倍、回撤幅度<BuyHold、闭合*60/1535>=5同时成立。',
             '收益第一、回撤第二、真实频率第三；研究筛选与正式FULL均保留失败。'),
            date(2026,9,30),config['seed'],
            tuple(x.value for x in (Dataset.STRATEGY_FEATURE_EVIDENCE,Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,
                                   Dataset.ETF_UNADJUSTED_INTRADAY,Dataset.TRADING_CALENDAR)),
            ExperimentProtocol(ExperimentStage.PROTOTYPE,
                ('全部开发池已见，实际Jun8至Sep30共1534执行日，原频率分母1535。',),
                ('EX050八完整FULL及EX051195 COMPLETE回执后冻结原始基线；仅5个前瞻控制，不重跑基线，无Optuna。',),
                ('收益、回撤、128真实CLOSED原三门保持；稳定性、相位及风险分组不成为新接受门。',),
                ('同a190模型、8ed特征、4c334来源说明；不存在新模型或输入边界；全部参数显式固定。',),
                ('T17/20:31/T+1日有效限价买入、市价全退出，10万元、100份、每侧10bp。',
                 '首1自动prepare，真实shared.execution_data后余4并行；max4/native1，无显式jointbindings/retry/fallback。',
                 'numpy/pandas两依赖生成真实内容身份；研究Optuna来源仅留引用，不借旧content/gate credit。',
                 '阶段四另批准；04结论执行后补，不绑定初始source。'),
                predecessor_experiment_ids=('EX048_20261006','EX050_20261006','EX051_20261006')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=False,selects_parameters=True,creates_candidate=True))

    def synthetic_precheck(self):
        root=Path.cwd().resolve();exp=Path(__file__).resolve().parent
        config=read(exp/'full_config.json')
        require(config['worker_cap']==4 and config['native_threads']==1 and config['actual_sessions']==1534
                and config['frequency_denominator']==1535 and config['candidate_start']==4700,'fixed witness resource/profile contract differs')
        configs=read(exp/'witness_plan.json')
        require(len(configs)==5 and len({digest(g['parameters']) for g in configs})==5,'5 unique controls required')
        for g in configs:
            S012PlannedCycle(ParameterSet({**g['parameters'],'rule':{'data_source':{'package':'strategy_runtime',
                'path':'resources/features.csv','sha256':FEATURE_SHA}}}))
        return ExperimentPrecheckResult((ExperimentPreflightCheck('EX052_FOCUSED_PUBLIC_PARAMETER_LEGALITY',
            ExperimentPreflightStatus.PASS,'5 unique valid parameters; no market computation or repeated large synthetic suite'),),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE,{'unique_valid_configs':5},{'scope':'parameter-only synthetic'}))

    def execute(self,context):
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        context.record_capability(ExperimentCapability.CREATE_CANDIDATE)
        root=Path.cwd().resolve();exp=Path(__file__).resolve().parent
        config=read(exp/'full_config.json');selection=read(exp/'witness_options.json');metadata=read(exp/'source_metadata.json')
        require(digest(selection)==metadata['selection_content_sha256'],'bound selection changed')
        for eid,expected in metadata['predecessor_receipts'].items():
            require(context.predecessors[eid].receipt_sha256==expected,'formal predecessor differs')
        groups=authenticate(root,selection)
        require(digest(groups)==digest(read(exp/'witness_plan.json')),'frozen witness plan changed')
        proof={'status':'PASS','groups':groups,'selected_rows':3,'unique_full_configs':5}
        package=exp/'strategy_runtime';implementation=implementation_sha256(SOURCE_FILES,source_root=package)
        require(implementation==metadata['source']['implementation_sha256'],'local clone runtime bytes changed')
        groups=proof['groups'];requests=[];plans=[]
        for i,group in enumerate(groups):
            params=group['parameters']
            parameters={**params,'rule':{'data_source':{'package':'strategy_runtime','path':'resources/features.csv',
                                                        'sha256':metadata['source']['feature_sha256']}}}
            payload={'runtime':{'module':'strategy_runtime.strategies.s012','qualname':'S012PlannedCycle',
                'contract_version':1,'source_sha256':implementation,'source_files':SOURCE_FILES},'parameters':parameters}
            candidate=StrategyCandidate('S012',f"C{config['candidate_start']+i:04d}",payload,package)
            request=EvaluationRequest(root,config['experiment_id'],candidate,
                {'candidate_id':candidate.reference_id,'source_files':SOURCE_FILES,'implementation_sha256':implementation},
                '518850.SH','etf',(EvaluationWindow('DEVELOPMENT',date(2020,6,8),date(2026,9,30)),),
                date(2026,9,30),100000.,(EvaluationCost('BASE',.001,'FORMAL'),),
                benchmark=EvaluationBenchmark(execution=NextOpenBuyHold(lot_size=100)),workers=1,execution_mode='FULL')
            requests.append(request);plans.append((group,payload))
        write(context.workspace.path('selection_authentication.json'),proof)
        rows=[];shared=None;stop_reason='All selected unique configurations attempted via FULL'
        starts=planned_batches(len(requests))
        require(config['worker_cap']<=context.resources.max_workers,'declared batch cap exceeds formal resources')
        for offset,end in starts:
            batch=tuple(replace(req,execution_data=shared) for req in requests[offset:end])
            outcomes=context.evaluation.evaluate_many(batch)
            require(len(outcomes)==len(batch),'FULL batch returned incomplete attempt records')
            for req,(group,payload),out in zip(requests[offset:end],plans[offset:end],outcomes):
                if offset==0 and out.result is not None:shared=out.result.execution_data
                metrics=None if out.result is None else summarize(out.result.runs[0])
                row={'candidate_id':req.strategy.candidate_id,'parameters':group['parameters'],'payload':payload,
                     'source_root':package.relative_to(root).as_posix(),'hypothesis':self.definition.research_question,
                     'implementation_sha256':implementation,'feature_sha256':metadata['source']['feature_sha256'],
                     'control_kind':group['kind'],'control_label':group['label'],'prospective_delta':group['delta'],
                     'source_selection_ids':group['source_selection_ids'],'record':out.record.to_dict(),
                     'metrics':metrics,'passed_all':bool(metrics and metrics['passed_all']),
                     'preflight_path':(exp/'artifacts/preflight.json').relative_to(root).as_posix(),
                     'gate_credit':'NONE; actual FULL six-field scope/compatible sidecar must be separately derived'}
                rows.append(row)
                print('SELECTED_FULL',req.strategy.candidate_id,metrics if metrics else out.record.error_message,flush=True)
            write(context.workspace.path('trials.json'),rows)
            if offset==0 and shared is None:
                stop_reason='First FULL supplied no genuine execution_data; stopped explicitly without retry or fallback'
                break
        write(context.workspace.path('verification.json'),{'planned_unique_configs':len(requests),'attempted':len(rows),
            'unattempted_candidate_ids':[r.strategy.candidate_id for r in requests[len(rows):]],
            'source_selected_rows':proof['selected_rows'],'stop_reason':stop_reason,'mode':'ACTUAL_FULL',
            'qualified_candidates':[r['candidate_id'] for r in rows if r['passed_all']],'gate_credit':'NONE'})
        artifacts=tuple(context.workspace.register_artifact(name,'selected_frontier_actual_full')
                        for name in ('trials.json','verification.json','selection_authentication.json'))
        succeeded=sum(r['record']['status']=='SUCCEEDED' for r in rows)
        qualified=sum(r['passed_all'] for r in rows)
        return ExperimentResult(ExperimentOutcome.PASS if qualified and len(rows)==len(requests) and succeeded==len(rows)
                                else ExperimentOutcome.FAIL,
            {'planned_accounts':len(requests),'formal_trials':len(rows),'successful_accounts':succeeded,'qualified':qualified},
            {'mode':'ACTUAL_FULL','stop_reason':stop_reason,'frequency_denominator':1535,'all_input_data_seen':True},artifacts)
