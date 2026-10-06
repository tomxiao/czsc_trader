"""Current formal-witness-equivalent screening; execution requires a new gate."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from importlib.metadata import version
from hashlib import sha256
import multiprocessing
import os
from pathlib import Path
import shutil
import sys

import optuna
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentDependency, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentCapability,
)
from strategy_runtime import ParameterSet
from .scope_contract import read, canonical, require, verify_gate, proposal_scope, parameter_domains, parameter_proposals, reference, delivery_contract
from .managed_market import load
from .s012_bound_model import S012PlannedCycle, synthetic_selfcheck
from . import s012_bound_model as bound_model

def write(path,value):
    import json
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def grid(config):
    require(config['schema_version']==1 and config['adaptive_budget']==0,
            'this fixed-route template does not silently enable adaptive search')
    allowed={'opportunity','hold_days','entry_premium','confirm_o01','cooldown','risk_gate','risk_exit',
             'trailing_stop','allocation','exit_policy','min_hold','risk_unknown_policy','momentum_lookback'}
    declared=parameter_proposals(config)
    proposed=[row['parameters'] for row in declared]
    require({'opportunity','hold_days','entry_premium'}<=set(proposed[0])<=allowed, 'wrong public parameter fields')
    require(all(p['opportunity'] in {'momentum','momentum_union','m05','o01_m05','n09','all_union','always','o01','union','n09_m05'} for p in proposed),
            'opportunity outside initial new-equivalence route')
    require(all(type(p['hold_days']) is int and 1<=p['hold_days']<=60 for p in proposed), 'invalid holding domain')
    require(all(-.05<=p['entry_premium']<=.05 for p in proposed) and any(p['entry_premium']==0. for p in proposed),
            'invalid limit domain or missing zero-premium control')
    require(all(type(p.get('momentum_lookback',3)) is int and 3<=p.get('momentum_lookback',3)<=120 for p in proposed),
            'momentum lookback must be integer 3..120')
    require(all(p.get('momentum_lookback',3)==3 or p['opportunity'] in {'momentum','momentum_union'} for p in proposed),
            'inactive momentum lookback must be explicitly fixed to3')
    require(not any(p['opportunity']=='always' and p.get('exit_policy','fixed')!='fixed' for p in proposed),
            'always route is permitted only with fixed exit; declare separate opportunity-loss domain')
    require(type(config['proposal_budget']) is int and 0<config['proposal_budget']<=len(proposed),
            'budget must be a positive prospective prefix of declared grid')
    return proposed[:config['proposal_budget']]

def frontier(rows):
    completed=[r for r in rows if r['status']=='COMPLETE']
    def vector(r):
        m=r['metrics'];return (m['net_cagr'],-abs(m['max_drawdown']),m['frequency'])
    result=[]
    for row in completed:
        v=vector(row)
        if not any(all(a>=b for a,b in zip(vector(other),v)) and any(a>b for a,b in zip(vector(other),v))
                   for other in completed):
            result.append(row['proposal_id'])
    feasible=[r for r in completed if r['metrics']['frequency']>=5.
              and abs(r['metrics']['max_drawdown'])<abs(r['metrics']['benchmark']['max_drawdown'])]
    best=max(feasible,key=lambda r:r['metrics']['net_cagr'],default=None)
    ranked=sorted(completed,key=lambda r:(-r['metrics']['net_cagr'],abs(r['metrics']['max_drawdown']),
                                        -r['metrics']['frequency'],r['proposal_id']))
    return {'nondominated_proposals':result,'qualified':[r['proposal_id'] for r in completed if r['passed_all']],
            'rank_primary':[r['proposal_id'] for r in ranked],
            'best_primary':None if not ranked else ranked[0]['proposal_id'],
            'ranking_rule':'net_cagr descending > absolute max_drawdown ascending > actual closed frequency descending',
            'best_frequency_drawdown_feasible':None if best is None else best['proposal_id'],
            'feasible_selection_role':'diagnostic only; never replaces return-priority primary ranking'}

def frontier_checkpoint(rows, *, final_checkpoint=False, compute=frontier):
    """Running persistence never evaluates or carries a stale frontier."""
    return {'frontier':compute(rows) if final_checkpoint else None,
            'frontier_status':'COMPUTED_FINAL' if final_checkpoint else 'NOT_COMPUTED'}

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        config=read(Path(__file__).with_name('search_config.json'))
        scope=read(Path(__file__).with_name('scope.json'))
        require(isinstance(config['experiment_id'],str) and config['experiment_id'].startswith('EX'),
                'construction must bind a real allocated experiment id first')
        proposals=grid(config)
        return ExperimentDefinition(2,config['experiment_id'],'S012',ExperimentMode.FORMAL,
            '原生M05、全域动量及既有机会组合的持有期与限价能否共同满足收益、回撤和128闭合目标？',
            f"逐项分解触发密度、成交率、费用与现金空置；以{scope['witness_experiment_id']}完整{scope['witness_contract']['expected_configs']} FULL和8合成等价约束研究加速。",
            ('净CAGR>=基准1.5倍、回撤幅度<基准、闭合*60/1535>=5同时成立。',
             '预算与固定网格完成仅为检查点，达标和有依据的前沿必须后继FULL。'),
            date(2026,9,30),config['seed'],
            tuple(x.value for x in (Dataset.STRATEGY_FEATURE_EVIDENCE,Dataset.ETF_OHLCV,
                                   Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY,Dataset.TRADING_CALENDAR)),
            ExperimentProtocol(ExperimentStage.PARAMETER_SEARCH,
                ('整个窗口为已见开发池，无未见表现声明。',),
                (f'预先声明{len(proposals)}固定网格，主进程InMemory Optuna enqueue/ask/tell；Windows spawn/native1/最多半CPU。',),
                ('Optuna单目标净CAGR最大；推荐顺序为净CAGR降序、回撤幅度升序、真实闭合频率降序。原三硬门保持，Pareto仅诊断，不因容量排除长持有。',),
                (f'本次全部参数域由绑定search_config声明；默认固定全仓、无风险与确认门、冷却0。显式后继可声明早退与风险未知政策。',),
                (f"仅{scope['witness_experiment_id']}完整{scope['witness_contract']['expected_configs']} FULL与当前8合成等价及全scope SHA通过后启用。",
                 '全部提案状态和信号、计划、账户、订单、成交、开放周期完整gzip保存。',
                 '保持原1535分母和实际1534执行日，未成交周期不计闭合，无未来标签成熟删行或质量遮罩。',
                 '持有年龄以信号日为准；早退与未知风险政策由绑定域明确声明。T17截止、20:31计划、T+1日有效限价重报、市价全退出、每侧10bp。'),
                predecessor_experiment_ids=(scope['witness_experiment_id'],)),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','optuna')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,searches_parameters=True,
                                               selects_parameters=True,creates_candidate=False))

    def synthetic_precheck(self):
        config=read(Path(__file__).with_name('search_config.json'))
        proposed=grid(config)
        facts=synthetic_selfcheck()
        if any(name in proposed[0] for name in ('exit_policy','min_hold','risk_unknown_policy')):
            require(hasattr(bound_model,'synthetic_policy_selfcheck'),
                    'new exit/unknown policy route requires its public synthetic policy selfcheck')
            facts={**facts,'exit_policy_selfcheck':bound_model.synthetic_policy_selfcheck()}
        if 'momentum_lookback' in proposed[0]:
            require(hasattr(bound_model,'synthetic_trend_selfcheck'),'trend route requires its public synthetic trend selfcheck')
            facts={**facts,'trend_selfcheck':bound_model.synthetic_trend_selfcheck()}
        source={'package':'strategy_runtime','path':'resources/features.csv','sha256':'0'*64}
        for p in proposed:
            S012PlannedCycle(ParameterSet({**p,'rule':{'data_source':source}}))
        return ExperimentPrecheckResult((ExperimentPreflightCheck('SYNTHETIC_STRATEGY_AND_FIXED_DOMAIN',
            ExperimentPreflightStatus.PASS,str(facts)),),ExperimentResult(ExperimentOutcome.INCONCLUSIVE,
                {**facts,'declared_proposals':len(proposed)},{'scope':'synthetic only; no real gate asserted'}))

    def execute(self,context):
        for capability in (ExperimentCapability.SEARCH_PARAMETERS,ExperimentCapability.SELECT_PARAMETERS):
            context.record_capability(capability)
        root,exp=Path.cwd().resolve(),Path(__file__).resolve().parent
        scope,gate=verify_gate(exp,root)
        gate_sha256=sha256((exp/'gate.json').read_bytes()).hexdigest()
        require(context.predecessors[scope['witness_experiment_id']].receipt_sha256==scope['witness_receipt_sha256'],
                'formal predecessor differs from witness gate')
        config=read(exp/'search_config.json');proposed=grid(config)
        declared_domains=parameter_domains(config)
        require(gate['covered_domains_sha256']==delivery_contract(exp/'delivery_contract.py').search_domain_sha256(declared_domains),
                'actual search domains differ from scoped gate')
        declared_proposals=parameter_proposals(config)
        require(gate['covered_parameter_grid_sha256']==canonical(declared_proposals),
                'actual conditional grid differs from new gate')
        features,daily,intraday,source=load(context,scope)
        copied=[]
        for name in ('scope.json','gate.json','search_config.json','proofs/real_comparison.json','proofs/synthetic_comparison.json'):
            target=context.workspace.path('gate_evidence/'+name)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(exp/name,target)
            copied.append('gate_evidence/'+name)
        write(context.workspace.path('screening_provenance.json'),{'status':'PASS','scope':scope,'gate':gate,
            'mode':'RESEARCH_SCREENING_EQUIVALENT_SUBSET_NOT_FULL','requires_successor_FULL':True})
        maximum=max(1,(os.cpu_count() or 1)//2)
        cap=config['worker_cap']
        require(cap is None or type(cap) is int and 1<=cap<=maximum,'worker cap exceeds half CPU')
        workers=min(context.resources.max_workers,maximum,cap or maximum)
        for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
            os.environ[name]='1'
        if str(exp) not in sys.path:sys.path.insert(0,str(exp))
        import s012_search_worker as worker
        study=optuna.create_study(storage=optuna.storages.InMemoryStorage(),
            sampler=optuna.samplers.TPESampler(seed=config['seed']),direction='maximize')
        for p in proposed:study.enqueue_trial(p)
        proposals=[]
        domains={name:list(dict.fromkeys(p[name] for p in proposed)) for name in proposed[0]}
        def snapshot(reason, *, final_checkpoint=False):
            result={'schema_version':1,'search_id':config['experiment_id']+'_SCREENING',
                    'method':'Optuna fixed enqueue/ask/tell main process InMemoryStorage',
                    'method_version':optuna.__version__,'seed':config['seed'],'domains':declared_domains,
                    'declared_budget':config['proposal_budget'],'gate_evidence':reference(root,exp/'gate.json'),
                    'objective':'single net_cagr maximize; drawdown and actual frequency are secondary ranking diagnostics',
                    'conditional_grid_sha256':gate['covered_parameter_grid_sha256'],
                    'conditional_blocks':config.get('blocks',[]),
                    'scope_sha256':gate['scope_sha256'],'config':config,'proposals':proposals,
                    'scheduling':f'main-process Optuna; spawn {workers} workers/native1; deterministic tell in ask order',
                    'resource_plan':{'workers':workers,'start_method':'spawn','native_threads':1,'tell_order':'ask order'},
                    **frontier_checkpoint(proposals,final_checkpoint=final_checkpoint),
                    'stop_reason':reason,
                    'mode':'RESEARCH_SCREENING_EQUIVALENT_SUBSET_NOT_FULL','candidate':None,
                    'requires_successor_FULL':True,'research_closure':False}
            write(context.workspace.path('search.json'),result)
            return result
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
                initializer=worker.initialize,initargs=(features,daily,intraday,source,str(context.workspace.root),
                                                        scope['benchmark']['metrics'],scope['delivery_scope_base'],gate_sha256)) as pool:
            for offset in range(0,len(proposed),workers):
                pending=[]
                for index,expected_parameters in enumerate(proposed[offset:offset+workers],start=offset):
                    trial=study.ask()
                    p={name:trial.suggest_categorical(name,values) for name,values in domains.items()}
                    require(canonical(p)==canonical(expected_parameters),'queued proposal differs from explicit conditional recipe')
                    strategy=S012PlannedCycle(ParameterSet({**p,'rule':{'data_source':source}}))
                    case_scope=proposal_scope(strategy,scope['delivery_scope_base'],gate_sha256)
                    row={'proposal_id':f'OPTUNA_{trial.number:04d}','trial_number':trial.number,'phase':'FIXED',
                         'parameters':p,'parameter_sha256':canonical(p),'scope':case_scope,
                         'conditional_block':declared_proposals[index]['block'],
                         'status':'RUNNING','candidate':None,'passed_all':False,
                         'reason':'Submitted new scoped research screening account'}
                    proposals.append(row);snapshot('RUNNING; submitted account not terminal')
                    pending.append((trial,row,pool.submit(worker.evaluate,trial.number,p)))
                for trial,row,future in pending:
                    try:result=future.result()
                    except Exception as error:result={'status':'FAILED','reason':repr(error),'candidate':None,'passed_all':False}
                    if result['status']=='COMPLETE':
                        require(result.get('scope')==row['scope'],'worker scope differs from parent public execution policy')
                    row.update(result)
                    if row['status']=='COMPLETE':
                        m=row['metrics'];row['passed_all']=m['passed_all']
                        study.tell(trial,m['net_cagr'])
                    else:study.tell(trial,state=optuna.trial.TrialState.FAIL)
                    snapshot('BATCH_PROGRESS; declared route not research closure')
                    print('SCREENING',row['proposal_id'],row['status'],flush=True)
        search=snapshot(config['stop_policy'],final_checkpoint=True)
        artifacts=[]
        for name in copied:
            artifacts.append(context.workspace.register_artifact(name,'current_scope_and_complete_equivalence_evidence'))
        for name in ('search.json','screening_provenance.json'):
            artifacts.append(context.workspace.register_artifact(name,'equivalence_gated_research_screening'))
        for path in sorted(context.workspace.path('screening_ledgers').rglob('*')):
            if path.is_file():artifacts.append(context.workspace.register_artifact(path.relative_to(context.workspace.root).as_posix(),
                                                                                  'complete_raw_screening_ledger'))
        failures=sum(r['status']!='COMPLETE' for r in proposals)
        return ExperimentResult(ExperimentOutcome.FAIL if failures else ExperimentOutcome.PASS,
            {'proposals':len(proposals),'failed':failures,'screening_qualified':len(search['frontier']['qualified'])},
            {'screening_only':True,'requires_successor_FULL':True,'research_closure':False},tuple(artifacts))
