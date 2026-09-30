"""New five-domain decision package from sealed ledgers; no new evaluation."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from math import ceil
import argparse
import json
import shutil
import sys
import platform
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from ranking import Metric,pareto,order
from czsc_trader.experiment_archive import validate_experiment_archive

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
SOURCE=Path(__file__).resolve().parent.parent
OLD=ROOT/'research/S011/stage4/iteration_03';INTAKE=ROOT/'research/S011/stage4/iteration_02'
PERTURB=ROOT/'research/S011/stage4/perturbation_01'
sys.path.append(str(INTAKE/'src'))
from contracts import Registry,Decision,document_schema,validate_document

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def dump(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
def authenticate(p):
    manifest=read(p/'manifest.json')
    for name,h in manifest['files'].items():
        if digest(p/name)!=h:raise ValueError('sealed file changed: '+str(p/name))
def records(f):return json.loads(f.to_json(orient='records',force_ascii=False,double_precision=15))

def account_metrics(a,t,initial):
    eq=a.equity.to_numpy(float);n=len(a);count=int(t.status.eq('CLOSED').sum())
    return {'cagr':float((eq[-1]/initial)**(252/n)-1),
            'drawdown_magnitude':float(-(eq/np.maximum.accumulate(np.r_[initial,eq])[1:]-1).min()),
            'closed_trades':count,'frequency':60*count/n,'end_equity':float(eq[-1])}

def temporal(eq,bh,settings):
    initial=settings['initial_cash'];r=eq/np.r_[initial,eq[:-1]]-1;br=bh/np.r_[initial,bh[:-1]]-1
    w=settings['rolling_window'];step=settings['rolling_step']
    sr=pd.Series(1+r).rolling(w,min_periods=settings['rolling_min_periods']).apply(np.prod,raw=True)-1
    b=pd.Series(1+br).rolling(w,min_periods=settings['rolling_min_periods']).apply(np.prod,raw=True)-1
    excess=(sr-b).dropna().iloc[::step]
    if excess.empty:raise ValueError('insufficient rolling coverage')
    return excess,float(excess.quantile(.1,interpolation=settings['quantile_method']))

def concentration(fills,trades,fraction):
    closed=trades.loc[trades.status.eq('CLOSED'),'cycle_id']
    if closed.duplicated().any():raise ValueError('duplicate closed cycle')
    flows=fills.quantity*fills.price*np.where(fills.side.eq('BUY'),-1,1)-fills.fees
    pnl=flows.groupby(fills.cycle_id).sum().reindex(closed)
    if pnl.isna().any():raise ValueError('closed cycle missing fills')
    wins=pnl[pnl>0].sort_values(ascending=False);k=ceil(fraction*len(wins))
    share=float(wins.head(k).sum()/wins.sum()) if len(wins) else None
    open_ids=trades.loc[~trades.status.eq('CLOSED'),'cycle_id']
    return pnl,{'positive_trades':len(wins),'top_count':k,'top10pct_positive_pnl_share':share,
                'positive_pnl_sum':float(wins.sum()),'closed_net_pnl':float(pnl.sum()),
                'open_cycle_count':len(open_ids),'open_net_cash_flow':float(flows.groupby(fills.cycle_id).sum().reindex(open_ids).fillna(0).sum())}

class Sources:
    def __init__(self):self.hashes={};self.archives=set()
    def record(self,p):
        p=Path(p);name=p.relative_to(ROOT).as_posix();h=digest(p)
        if name in self.hashes and self.hashes[name]!=h:raise ValueError('changing input')
        self.hashes[name]=h;return p
    def csv(self,p):return pd.read_csv(self.record(p),float_precision='round_trip')
    def parquet(self,p):return pd.read_parquet(self.record(p))
    def archive(self,folder):
        root=next(p for p in folder.parents if (p/'experiment_manifest.json').is_file())
        if root not in self.archives:validate_experiment_archive(root);self.record(root/'experiment_manifest.json');self.archives.add(root)

def calculations(settings,policy):
    sources=Sources()
    for package in (OLD,INTAKE,PERTURB):authenticate(package);sources.record(package/'manifest.json')
    registry=Registry.model_validate(read(sources.record(PERTURB/'configurations.json'))).model_dump()
    lookup={c['config_id']:c for c in registry['configurations']}
    old_metrics=sources.parquet(OLD/'ranking_metrics.parquet');ids=sorted(old_metrics.config_id)
    evaluations=sources.parquet(INTAKE/'evaluations.parquet')
    original=evaluations[evaluations.qualified.eq(True)&evaluations.scope.eq('COMPARABLE_DEVELOPMENT')]
    assert set(original.config_id)==set(ids) and len(ids)==36
    benchmark_dir=ROOT/'experiments/S011/20260930_S011_EX16/artifacts'
    sources.archive(benchmark_dir)
    bh=sources.csv(benchmark_dir/'benchmark_account_daily.csv.gz');bt=sources.csv(benchmark_dir/'benchmark_trades.csv.gz')
    benchmark=account_metrics(bh,bt,settings['initial_cash'])
    previous_diag=sources.parquet(OLD/'diagnostics.parquet')
    bootstrap=sources.parquet(INTAKE/'bootstrap.parquet')
    perturb=sources.parquet(PERTURB/'diagnostics.parquet')
    main=perturb[perturb.kind.eq(settings['parameter_module'])&perturb.scenario.eq(settings['parameter_cost_scenario'])&perturb.holding_stratum.eq('ALL')].set_index('center_config_id')
    cost_table=sources.parquet(INTAKE/'cost_evaluations.parquet')
    rows=[];diags=[];audit=[];rolling=[];profits=[];qualified=[];cost_records=[]
    for cid in ids:
        e=original[original.config_id.eq(cid)].iloc[0];folder=ROOT/e.evidence;sources.archive(folder)
        payload=read(sources.record(ROOT/e.payload_path));assert payload==lookup[cid]['definition']
        source_root=ROOT/lookup[cid]['source_root']
        for name in payload['runtime']['source_files']:sources.record(source_root/name)
        frames={name:sources.csv(folder/(name+'.csv.gz')) for name in ('decisions','orders','fills','account_daily','trades')}
        a=frames['account_daily'];t=frames['trades'];m=account_metrics(a,t,settings['initial_cash'])
        assert len(a)==settings['sessions'] and a.date.equals(bh.date)
        assert a.cash.ge(-1e-8).all() and a.quantity.mod(100).eq(0).all()
        np.testing.assert_allclose(a.cash+a.quantity*a.close,a.equity,atol=1e-8,rtol=0)
        old=old_metrics[old_metrics.config_id.eq(cid)].iloc[0]
        np.testing.assert_allclose([m[k] for k in ('cagr','drawdown_magnitude','frequency')],[old[k] for k in ('cagr','drawdown_magnitude','frequency')],atol=1e-10,rtol=0)
        flags={'return_pass':m['cagr']>=1.5*benchmark['cagr'] and (benchmark['cagr']>0 or m['cagr']>max(0,benchmark['cagr'])),
               'drawdown_pass':m['drawdown_magnitude']<benchmark['drawdown_magnitude'],'frequency_pass':4<=m['frequency']<=6}
        qualified.append({'config_id':cid,'source_evaluation_ids':original[original.config_id.eq(cid)].evaluation_id.tolist(),**flags,'qualified':all(flags.values()),**m})
        assert all(flags.values()),'original qualified account no longer reconstructs'
        excess,q10=temporal(a.equity.to_numpy(),bh.equity.to_numpy(),settings)
        for index,value in excess.items():rolling.append({'config_id':cid,'end_date':str(a.date.iloc[index]),'sessions':settings['rolling_window'],'excess':float(value)})
        assert np.isclose(excess.min(),old.worst_rolling60_excess,atol=1e-10,rtol=0)
        pnl,c=concentration(frames['fills'],t,settings['concentration_positive_trade_fraction'])
        open_mark=float(a.equity.iloc[-1]-settings['initial_cash']-c['closed_net_pnl'])
        # Reconcile all closed profit plus any open inventory/cash flow, never erase it.
        expected_open=float(a.quantity.iloc[-1]*a.close.iloc[-1]+c['open_net_cash_flow'])
        assert np.isclose(open_mark,expected_open,atol=1e-7,rtol=0)
        for cycle,value in pnl.items():profits.append({'config_id':cid,'cycle_id':cycle,'net_pnl':float(value),'status':'CLOSED'})
        pressure=None;cost_evidence=None
        dd=previous_diag[previous_diag.config_id.eq(cid)&previous_diag.metric.eq('cost_cagr')&previous_diag.scenario.eq(settings['pressure_scenario'])]
        assert len(dd)==1
        if dd.iloc[0].status=='COMPLETE':
            cost_evidence=dd.iloc[0].evidence;cost_folder=ROOT/cost_evidence;sources.archive(cost_folder)
            ca=sources.csv(cost_folder/'account_daily.csv.gz');ct=sources.csv(cost_folder/'trades.csv.gz')
            pressure=account_metrics(ca,ct,settings['initial_cash'])
            assert ca.date.equals(a.date) and np.isclose(pressure['cagr'],dd.iloc[0].value,atol=1e-10,rtol=0)
            cost_refs=cost_table[cost_table.config_id.eq(cid)&cost_table.scenario.eq(settings['pressure_scenario'])].evaluation_id.tolist()
            cost_records.append({'config_id':cid,'scenario':settings['pressure_scenario'],'evidence':cost_evidence,'evaluation_ids':cost_refs,**pressure})
        param_loss=param_dd=None
        if cid in main.index:
            d=main.loc[cid];assert d.positions==16
            param_loss=max(0.,m['cagr']-float(d.cagr_q10));param_dd=max(0.,float(d.drawdown_magnitude_q90)-m['drawdown_magnitude'])
        loss=None if pressure is None else m['cagr']-pressure['cagr']
        row={'config_id':cid,'config_fingerprint':lookup[cid]['config_fingerprint'],'first_reference':lookup[cid]['first_reference'],
             'behavior_id':old.behavior_id,'standard_evidence':e.evidence,'pressure_evidence':cost_evidence,
             'parameter_cagr_loss':param_loss,'parameter_drawdown_increase':param_dd,'rolling60_excess_q10':q10,
             'pressure_cagr_loss':loss,**m,**c,'open_marked_pnl':open_mark,'fee20_cagr':None if pressure is None else pressure['cagr']}
        rows.append(row)
        for domain,metric,value,evidence in [('PARAMETER','parameter_cagr_loss',param_loss,'research/S011/stage4/perturbation_01/diagnostics.parquet'),
            ('PARAMETER','parameter_drawdown_increase',param_dd,'research/S011/stage4/perturbation_01/diagnostics.parquet'),
            ('TIME','rolling60_excess_q10',q10,e.evidence),('CONCENTRATION','top10pct_positive_pnl_share',c['top10pct_positive_pnl_share'],e.evidence),
            ('EXECUTION','pressure_cagr_loss',loss,cost_evidence)]:
            diags.append({'config_id':cid,'domain':domain,'metric':metric,'value':value,
                'unit':'fraction' if domain=='CONCENTRATION' else 'return','status':'COMPLETE' if value is not None else ('NOT_APPLICABLE' if domain=='CONCENTRATION' else 'MISSING'),
                'base_value':m['cagr'] if metric in ('parameter_cagr_loss','pressure_cagr_loss') else (m['drawdown_magnitude'] if metric=='parameter_drawdown_increase' else None),
                'evidence':evidence if value is not None else None})
        audit.append({'config_id':cid,'account_metrics':'PASS','cash_inventory_equity':'PASS','original_three_goals':'PASS',
                      'closed_and_open_pnl_reconciliation':'PASS','standard_evidence':e.evidence})
    for cid in ids:
        sample=bootstrap[bootstrap.config_id.eq(cid)]
        assert sorted(sample.block)==[10,20,40]
        for b in sample.itertuples():
            diags.append({'config_id':cid,'domain':'STATISTICAL','metric':'inherited_annual_log_excess_bootstrap_median',
                'value':b.median,'unit':'annual_log_return','status':'COMPLETE_REPORT_ONLY','base_value':None,
                'scenario':f'block_{b.block}','lower':b.lower,'upper':b.upper,
                'positive_share':b.positive_share,'repetitions':b.repetitions,
                'evidence':'research/S011/stage4/iteration_02/bootstrap.parquet'})
    metrics=[Metric(**v) for v in policy['pareto_metrics']];sequence=[Metric(**v) for v in policy['recommendation_order']]
    layers=pareto(rows,metrics);ranked,pairs=order(rows,layers['layers'],sequence)
    ranking=pd.DataFrame(ranked).merge(pd.DataFrame(rows),on='config_id',validate='one_to_one')
    sensitivity={}
    for name,factor,shift in [('fine_10dec',None,False),('finer_half_steps',Decimal('.5'),False),('coarser_double_steps',Decimal('2'),False),('half_cell_shift',Decimal('1'),True)]:
        def altered(v):
            step=Decimal('0.0000000001') if factor is None else Decimal(v['resolution'])*factor
            return Metric(v['name'],v['direction'],str(step),str(step/2) if shift else '0')
        pm=[altered(v) for v in policy['pareto_metrics']];seq=[altered(v) for v in policy['recommendation_order']]
        lp=pareto(rows,pm);rr,pp=order(rows,lp['layers'],seq)
        sensitivity[name]={'layers':lp['layers'],'rankings':rr,'pair_comparisons':pp}
    for i in range(len(sequence)-1):
        seq=sequence.copy();seq[i],seq[i+1]=seq[i+1],seq[i];rr,pp=order(rows,layers['layers'],seq)
        sensitivity[f'priority_swap_{i+1}_{i+2}']={'diagnostic_only':True,'metric_order':[v.name for v in seq],
              'layers':layers['layers'],'rankings':rr,'pair_comparisons':pp}
    return {'sources':sources,'registry':registry,'metrics':pd.DataFrame(rows),'ranking':ranking,'pareto':layers,'pairs':pairs,
        'diagnostics':pd.DataFrame(diags),'account_audit':pd.DataFrame(audit),'rolling':pd.DataFrame(rolling),'profits':pd.DataFrame(profits),
        'qualified':qualified,'costs':pd.DataFrame(cost_records),'sensitivity':sensitivity,'benchmark':benchmark}

def report(output,result,assessment):
    r=result['ranking'];front=r[r.pareto_layer.eq(1)].sort_values(['rank_min','config_id'])
    lines=['# S011阶段四迭代04','',
        '按新四小节合同复算原36个达标配置；第一层核验收益、回撤、频率后按收益/回撤分层，第二层仅收益优先。全部为已见开发池，名次不构成候选晋升。','',
        '## 第一层与收益优先顺序','',
        '| 配置 | 同层推荐名次 | 标准年化 | 回撤幅度 | 每60日频率 | 联合年化退化 | 联合回撤恶化 | 滚动超额Q10 | 20bp年化损失 | 盈利前10%贡献 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for x in front.itertuples():
        lines.append(f'| {x.config_id} | {int(x.recommendation_rank) if pd.notna(x.recommendation_rank) else str(x.rank_min)+"—"+str(x.rank_max)} | {x.cagr:.2%} | {x.drawdown_magnitude:.2%} | {x.frequency:.3f} | {x.parameter_cagr_loss:.2%} | {x.parameter_drawdown_increase:.2%} | {x.rolling60_excess_q10:.2%} | {x.pressure_cagr_loss:.2%} | {x.top10pct_positive_pnl_share:.2%} |')
    lines+=['', '退化、恶化及成本损失以收益率差表示，例如14.94%表示14.94个百分点；盈利贡献为正净损益占比。名次为同一绩效层内的序位。','',
        '## 复算与覆盖','',
        f"- 原36配置均重构原三项目标；基准绩效层大小为{[len(v['config_ids']) for v in result['pareto']['layers']]}。",
        '- 000193标准账户完整，现可参加第一层；20bp同源码证据仍缺失，不借用同参数其他源码结果。',
        '- 参数主模块为EX28固定2天16点六参数联合设计；四中心覆盖完整，其他32配置明确缺失，旧不均匀近邻仅作辅助。',
        '- 36配置均补算60交易日、步长1的滚动超额Q10及盈利交易前10%贡献；闭合和未平仓损益与账户对账。',
        '- 单边10bp/20bp成本采用既有完整账户；未测盘口、容量、冲击和延迟。',
        '- 旧配置重抽样与旧研究族PBO/DSR原样留证；新增搜索台账记录EX28，旧统计不宣称覆盖它。未新增回测或参数提议。','',
        '## 比较限制与研究判断','',
        '- 推荐使用七项逐项比较，第一处已知且不同的档位决定先后；若更早的相同前缀之后遇到缺失，该对配置不可比。',
        '- 缺少后续指标不一定阻止已有较早指标决定先后；全部指标的缺失仍逐项披露。',
        f"- 第一层四配置当前证据足以排序；全36配置中{assessment['configs_with_unresolved_pairs']}个配置涉及{assessment['incomparable_pairs']}对不可比关系，保留可能名次区间。补测请求按实际不可比对象和缺失指标列出。",
        '- 收益组优先于低回撤组由标准年化决定；组内由联合年化退化决定。这是登记的收益优先规则，不表示全面稳健或统计显著优势。',
        '- 四种精度/分箱敏感性及相邻优先级交换见敏感性文件；交换收益/回撤优先级或两种参数退化优先级时可换位，属于偏好依赖。主规则不因此调整。',
        '- 全四配置的20bp联合扰动均未达原收益目标；较差60日仍可能落后买入持有，反复搜索及已见行情风险保留。','',
        '## 机器产物','',
        '[排序合同](ranking_policy.json)、[排序结果](rankings.parquet)、[成对解释](ranking_explanations.json)、[敏感性](ranking_sensitivity.json)、[补测需求](additional_checks.json)、[自检面板](diagnostics.parquet)、[指标重叠审查](metric_audit.json)、[搜索台账](search_ledger.json)、[完整评估](assessment.json)。原对照和全部证据由manifest锁定。','',
        '用户决定仍为[待确认](decision.json)。复算从仓库根执行本包`src/build.py build --output <新.tmp目录>`；校验用`validate --package <包目录>`。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')

def build(output):
    if output.exists() or not output.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp output required')
    settings=read(SOURCE/'protocol.json');policy=read(SOURCE/'ranking_policy.json')
    result=calculations(settings,policy);sources=result['sources'];output.mkdir(parents=True)
    for name in ('protocol.json','ranking_policy.json'):shutil.copyfile(SOURCE/name,output/name)
    shutil.copytree(SOURCE/'src',output/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(SOURCE/'tests',output/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (output/'inputs').mkdir()
    shutil.copyfile(sources.record(ROOT/'research/RSCH_AGENT.md'),output/'inputs/RSCH_AGENT.md')
    for name,frame in [('ranking_metrics',result['metrics']),('rankings',result['ranking']),('diagnostics',result['diagnostics']),
        ('account_audit',result['account_audit']),('rolling_windows',result['rolling']),('closed_trade_pnl',result['profits']),('cost_evaluations',result['costs'])]:frame.to_parquet(output/(name+'.parquet'),index=False)
    comparisons=sources.parquet(INTAKE/'comparisons.parquet').copy();comparisons['coverage_role']='LEGACY_NONUNIFORM_AUXILIARY_ONLY'
    new=sources.parquet(PERTURB/'design_positions.parquet').copy();new['config_id']=new.center_config_id;new['kind']='EX28_'+new.kind;new['coverage_role']='BALANCED_PRESPECIFIED_DESIGN'
    pd.concat([comparisons,new],ignore_index=True).to_parquet(output/'comparisons.parquet',index=False)
    dump(output/'configurations.json',result['registry']);dump(output/'qualified_configurations.json',{'original_contract':settings['original_goals'],'configurations':result['qualified']})
    dump(output/'pareto.json',{**result['pareto'],'original_hard_goal_results':result['qualified'],'metrics':policy['pareto_metrics']})
    dump(output/'ranking_explanations.json',{'policy':'lexicographic partial order; first decisive or missing metric','pairs':result['pairs']})
    dump(output/'ranking_sensitivity.json',result['sensitivity']);dump(output/'decision.json',Decision().model_dump())
    bootstrap=sources.parquet(INTAKE/'bootstrap.parquet');bootstrap.to_parquet(output/'bootstrap.parquet',index=False)
    shutil.copyfile(sources.record(OLD/'diagnostics.parquet'),output/'legacy_diagnostics.parquet')
    shutil.copyfile(sources.record(INTAKE/'family_statistics.json'),output/'family_statistics.json')
    prev_settings=read(sources.record(INTAKE/'protocol.json'))
    ex28=ROOT/'experiments/S011/20260930_S011_EX28/artifacts';sources.archive(ex28)
    states=read(sources.record(ex28/'trial_states.json'));assert len(states)==184 and all(v['state']=='COMPLETE' for v in states)
    dump(output/'search_ledger.json',{'old_dsr_count_conventions':prev_settings['search_bias']['dsr_counts'],
        'old_statistics_scope':'Original EX13—EX27 search family; no coverage of EX28 or all prior S010/mechanism research claimed',
        'appended_experiment':'S011_EX28','appended_trials':184,'appended_standard_accounts':184,'appended_stress_accounts':184,
        'new_configurations_registered':172,'reused_configurations_in_design':12,'trial_states':states,
        'configuration_bootstrap_reused':True,'pbo_dsr_recomputed':False,'pbo_dsr_cover_ex28':False,
        'independent_validation':False,'counting_note':'Evaluation calls, unique configs, behaviors and trials are different units; do not sum them as independent hypotheses.'})
    r=result['ranking'];unresolved=[v for v in result['pairs'] if v['relation']=='INCOMPARABLE']
    names=[v['name'] for v in policy['recommendation_order']]
    correlations=[]
    for i,a in enumerate(names):
        for b in names[i+1:]:
            pair=r[[a,b]].dropna();usable=len(pair)>=3 and pair[a].nunique()>1 and pair[b].nunique()>1
            correlations.append({'metric_a':a,'metric_b':b,'paired_configs':len(pair),
                'pearson':float(pair[a].corr(pair[b])) if usable else None,
                'spearman':float(pair[a].corr(pair[b],method='spearman')) if usable else None,
                'status':'DESCRIPTIVE_ONLY' if usable else 'INSUFFICIENT_OR_CONSTANT',
                'warning':'Shared behaviors and four-center parameter coverage; correlations are not independent evidence or weights.'})
    dump(output/'metric_audit.json',{'formula_identities':[
        'Pressure CAGR = standard CAGR - pressure loss; pressure absolute CAGR is omitted from Pareto to avoid repeated level objective.',
        'Parameter degradation includes the center level but ranks loss under the same joint geometry, not absolute perturbed CAGR.',
        'Frequency is an original hard interval, not an additional maximize/minimize objective.',
        'Bootstrap/family bias do not rank configurations; old auxiliary diagnostics are not additional ranking votes.'
    ],'all_metric_directions_explicit':True,'common_denominators':['Positive closed net PnL denominator used only by concentration',
        'Same initial cash and session length for all CAGR comparisons'],
        'overlap_judgment':'Economic domains separated; correlations and shared data remain, no claim of statistical independence.',
        'correlations':correlations})
    missing_parameters=r[r.parameter_cagr_loss.isna()].config_id.tolist()
    dump(output/'additional_checks.json',{'balanced_joint_missing_config_ids':missing_parameters,
        'missing_cost_config_ids':r[r.pressure_cagr_loss.isna()].config_id.tolist(),'unresolved_pairs':unresolved,
        'front_needs_new_backtest':False,'policy':'Requests only; no extra evaluations launched. Prioritize actual unresolved decisions, keep other coverage gaps visible.'})
    assessment={'status':'SELF_CHECK_AND_PARTIAL_RANKING_COMPLETE_PENDING_USER_DECISION','new_backtests':0,'new_parameter_proposals':0,
        'original_qualified_configs':36,'registered_config_snapshot_entries':len(result['registry']['configurations']),
        'baseline_layer_sizes':[len(v['config_ids']) for v in result['pareto']['layers']],
        'balanced_parameter_configs':36-len(missing_parameters),'missing_parameter_configs':len(missing_parameters),
        'incomparable_pairs':len(unresolved),'configs_with_unresolved_pairs':int(r.comparison_status.eq('PARTIAL_ORDER').sum()),
        'statistical_evidence_scope':'Old configuration bootstrap and old-family PBO/DSR; expanded history disclosed but family statistics not recomputed.',
        'original_negative_evidence_retained':True,'new_economic_gates':False,'automatic_promotion':False,
        'scope':'Fixed original36 contender set; EX28 probes diagnostic only; changed ranking is posthoc development evidence.',
        'unmeasured':['Balanced joint geometry for32 other contenders','Queue/capacity/impact/latency','Independent forward data','Updated expanded-family PBO/DSR']}
    dump(output/'assessment.json',assessment)
    groups=[]
    for behavior,g in r.groupby('behavior_id'):
        groups.append({'behavior_id':behavior,'config_ids':g.config_id.tolist(),'equivalence_scope':'STANDARD_ACCOUNT_ONLY',
            'members':records(g[['config_id','pareto_layer','recommendation_rank','rank_min','rank_max','comparison_status','fee20_cagr']])})
    dump(output/'behavior_groups.json',{'groups':groups})
    front=r[r.pareto_layer.eq(1)].sort_values(['rank_min','config_id'])
    dump(output/'recommendations.json',{'preference':'RETURN_FIRST_ONLY','automatic_promotion':False,
        'items':records(front),'reason':'Follow declared first decisive metric; preserve downside, statistical scope and missingness in assessment.',
        'all_configurations_remain_selectable':True})
    report(output,result,assessment)
    documents={p.name:document_schema(read(p)) for p in output.glob('*.json') if p.name!='manifest.json'}
    dump(output/'schemas/documents.json',documents)
    schemas={p.name:[{'name':f.name,'type':str(f.type),'nullable':f.nullable} for f in pq.read_schema(p)] for p in output.glob('*.parquet')}
    dump(output/'schemas/tables.json',schemas)
    sources.record(INTAKE/'src/contracts.py')
    for path,h in sources.hashes.items():assert digest(ROOT/path)==h,path
    files={p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}
    dump(output/'manifest.json',{'files':files,'inputs':sources.hashes,'input_hash_policy':'RAW_SHA256; sealed source archives authenticated; old contract preserved in old snapshots',
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
            'dependency_contract':'Repository .venv research environment; contracts.py in immutable iteration_02 is an explicit dependency.',
            'resources':'Single-process deterministic ledger computation; no service, new data fetch, sampling or backtest.'},
        'entrypoints':{'build':'src/build.py build --output <fresh .tmp directory>','validate':'src/build.py validate --package <package>',
            'independent_verify':'src/verify.py --package <package>','tests':'python -m unittest discover -s <package>/tests'},
        'decision_authority':'USER_ONLY','new_backtests':0})
    validate(output)

def validate(package):
    authenticate(package);manifest=read(package/'manifest.json')
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p!=package/'manifest.json' and '__pycache__' not in p.parts}
    assert actual==set(manifest['files'])
    for name,h in manifest['inputs'].items():assert digest(ROOT/name)==h,name
    Registry.model_validate(read(package/'configurations.json'));decision=Decision.model_validate(read(package/'decision.json')).model_dump()
    assert decision['status']=='PENDING_USER_DECISION' and not decision['selected_config_ids'] and not decision['stage_five_started']
    for name,schema in read(package/'schemas/documents.json').items():validate_document(read(package/name),schema)
    for name,expected in read(package/'schemas/tables.json').items():assert expected==[{'name':f.name,'type':str(f.type),'nullable':f.nullable} for f in pq.read_schema(package/name)]
    settings=read(package/'protocol.json');policy=read(package/'ranking_policy.json');result=calculations(settings,policy)
    for key,name in [('metrics','ranking_metrics'),('ranking','rankings'),('diagnostics','diagnostics'),('rolling','rolling_windows'),('profits','closed_trade_pnl')]:
        pd.testing.assert_frame_equal(result[key],pd.read_parquet(package/(name+'.parquet')))
    stored=read(package/'pareto.json');assert all(stored[k]==v for k,v in result['pareto'].items())
    assert result['pairs']==read(package/'ranking_explanations.json')['pairs']
    assert result['sensitivity']==read(package/'ranking_sensitivity.json')
    print(json.dumps({'status':'PASS','qualified':len(result['qualified']),'layer_sizes':[len(v['config_ids']) for v in result['pareto']['layers']],
        'incomparable_pairs':sum(v['relation']=='INCOMPARABLE' for v in result['pairs']),'new_backtests':0}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('build').add_argument('--output',required=True,type=Path)
    sub.add_parser('validate').add_argument('--package',required=True,type=Path)
    args=parser.parse_args();build(args.output.resolve()) if args.command=='build' else validate(args.package.resolve())
