"""Analyze and explicitly publish the completed joint-search continuation."""
# ruff: noqa: E402
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
os.environ['MPLCONFIGDIR']=str(Path(__file__).resolve().parents[5]/'.tmp/matplotlib-s015')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, register_candidate,
    CandidateRegistrationRequest, load_candidate, assemble_delivery, validate_experiment,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency

ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
BASE=HOME.parent
EX=ExperimentRef('S015',HOME.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def dominates(a,b):
    av=[a['runs'][w][k]*(1 if k=='net_return' else -1) for w in ('full','s011_common') for k in ('net_return','dd')]
    bv=[b['runs'][w][k]*(1 if k=='net_return' else -1) for w in ('full','s011_common') for k in ('net_return','dd')]
    return all(x>=y for x,y in zip(av,bv)) and any(x>y for x,y in zip(av,bv))


def inactive_parameter_aliases(result, oldpanel):
    """Reuse an existing center when only source-proven inactive fields differ."""
    eligible={x.identity.key.candidate_id for x in oldpanel.candidates}
    active=('mode','exit_mode','lookback','hold','allocation','start','center_kind','rearm_mode')
    aliases={}
    for number in (61,62):
        folder=BASE/f'EX{number:03}_20261024'
        assert (folder/'src/strategy_runtime/strategies/price_process.py').read_bytes()==(HOME/'src/strategy_runtime/strategies/price_process.py').read_bytes()
        for old in read(folder/'others/results.json')['rows']:
            if old['candidate_id'] not in eligible or old['parameters']['exit_mode']!='fixed':
                continue
            for row in result['rows']:
                if row['identity']['content_sha256']==old['identity']['content_sha256']:
                    continue
                if all(row['parameters'][key]==old['parameters'][key] for key in active):
                    assert row['runs']==old['runs']
                    aliases.setdefault(row['candidate_id'],old['candidate_id'])
    return aliases


def assemble_analysis():
    result=read(HOME/'others/results.json')
    assert read(HOME/'others/audit.json')['status']=='ARITHMETIC_CHECKS_PASS'
    assert len(read(HOME/'others/audit.json')['accounts'])==result['formal_accounts']
    checker=mod(BASE/'EX062_20261024/src/publish_candidates.py','independent_gate')
    historical={}
    for number in range(58,63):
        for row in read(BASE/f'EX{number:03}_20261024/others/results.json')['rows']:
            historical[row['candidate_id']]=row
    rows=result['rows']
    for row in rows:
        assert checker.center_pass(row)==row['both_center_pass']
    passing=[r for r in rows if r['both_center_pass']]
    fullgrid=[t for t in result['optuna'][:126]]
    assert {(t['params']['lookback'],t['params']['hold']) for t in fullgrid}=={(n,h) for n in range(2,11) for h in range(1,15)}
    assert len(result['optuna'])==224
    assert all(t['completed_before_ask']==i//8*8 for i,t in enumerate(result['optuna']))
    oldpanel=d.DeliveryContent.from_dict(read(ROOT/'research/S015/assets/deliveries/CANDIDATES/6/delivery.json')['content']).payload
    oldids={e.identity.key.candidate_id for e in oldpanel.candidates}
    inactive_aliases=inactive_parameter_aliases(result,oldpanel)
    old_hashes={e.identity.content_sha256 for e in oldpanel.candidates}
    novel_passes=[r['candidate_id'] for r in passing if r['candidate_id'] not in inactive_aliases and r['identity']['content_sha256'] not in old_hashes]
    relevant=[historical[k] for k in oldids]+rows
    nondominated=[r for r in relevant if not any(dominates(x,r) for x in relevant)]
    new_front={r['candidate_id'] for r in nondominated if r['candidate_id'] not in historical}
    selected={r['candidate_id'] for r in passing}|new_front
    anchor=historical['C6105']
    boundary=[r['candidate_id'] for r in rows if (r['parameters']['lookback']==10 or r['parameters']['hold']==14 or r['parameters']['allocation']==.6)
              and (r['both_center_pass'] or dominates(r,anchor))]
    summary={
        'status':'COMPLETE_PENDING_PUBLICATION', 'trials':224, 'fixed_trials':128,'adaptive_trials':96,
        'unique_configurations':len(rows),'duplicate_trial_reuses':224-len(rows),'formal_accounts':result['formal_accounts'],'technical_accounts':2,
        'passing_new_evaluations':len(passing),'passing_ids':[r['candidate_id'] for r in passing],
        'new_passing_configuration_count':len(novel_passes),'new_passing_ids':novel_passes,
        'passing_time_pairs':sorted({(r['parameters']['lookback'],r['parameters']['hold']) for r in passing}),
        'passing_structures':sorted({r['parameters']['rearm_mode'] for r in passing}),
        'dominate_C6105':[r['candidate_id'] for r in passing if dominates(r,anchor)],
        'new_frontier':sorted(new_front),'selected_new_evaluations':sorted(selected),
        'boundary_improvement':boundary,'historical_handoff_retained':len(oldpanel.handoff),
        'old_C6105_equivalent':result['old_C6105_equivalent'],'serial_equal':result['serial_equal'],
        'source_proven_inactive_parameter_aliases':inactive_aliases,
        'stage4':'NOT_EXECUTED_NOT_AUTHORIZED','new_fully_qualified':0,
    }
    save(HOME/'others/summary.json',summary)
    table=[]
    for row in rows:
        table.append({'candidate':row['candidate_id'],**row['parameters'],
            **{w+'_'+k:row['runs'][w][k] for w in ('full','s011_common') for k in ('net_return','cagr','dd','frequency_median','frequency_good')},
            'passed':row['both_center_pass'],'frontier':row['candidate_id'] in new_front})
    pd.DataFrame(table).to_csv(HOME/'others/search_grid.csv',index=False,encoding='utf-8')
    grid_lookup={r['candidate_id']:r for r in rows}
    matrix=pd.DataFrame(index=range(2,11),columns=range(1,15),dtype=float)
    for trial in fullgrid:
        p=trial['params']
        matrix.loc[p['lookback'],p['hold']]=grid_lookup[trial['candidate_id']]['runs']['s011_common']['net_return']
    matrix.index.name='lookback'
    matrix.to_csv(HOME/'others/joint_grid_415_return.csv')
    drawdowns=matrix.copy()
    for trial in fullgrid:
        p=trial['params']
        drawdowns.loc[p['lookback'],p['hold']]=grid_lookup[trial['candidate_id']]['runs']['s011_common']['dd']
    figure,axes=plt.subplots(1,2,figsize=(14,4.8),layout='constrained')
    for axis,data,title,cmap in zip(axes,(matrix,drawdowns),('415-session net return (%)','415-session maximum drawdown (%)'),('RdYlGn','RdYlGn_r')):
        img=axis.imshow(data.to_numpy(float)*100,cmap=cmap,aspect='auto')
        axis.set_xticks(range(14),range(1,15))
        axis.set_yticks(range(9),range(2,11))
        axis.set_xlabel('Holding intent age (sessions)')
        axis.set_ylabel('Lookback (sessions)')
        axis.set_title(title)
        figure.colorbar(img,ax=axis,shrink=.8)
        for trial in fullgrid:
            row=grid_lookup[trial['candidate_id']]
            if row['both_center_pass']:
                p=trial['params']
                axis.add_patch(Rectangle((p['hold']-1.5,p['lookback']-2.5),1,1,fill=False,edgecolor='#111111',linewidth=2))
    figure.suptitle('S015: complete joint grid at 100% allocation / positive-step rearm\nOutlined cells pass all stage-three gates; development samples only',fontsize=12)
    figure.savefig(HOME/'others/joint_parameter_map.png',dpi=170)
    plt.close(figure)
    lines=[
        '# S015 EX065：阶段三联合参数重新寻优','',
        'Status: COMPLETED','',
        f"完成128次固定联合网格/对照及96次自适应TPE提议，共{len(rows)}个实际配置、{result['formal_accounts']}个正式窗口账户、2个串行技术账户。{len(passing)}个评价配置通过阶段三中心目标，排除旧配置复算后新增达标配置为{len(novel_passes)}。阶段四尚未执行，完整新资格为0。",'',
        '## 目标、方法与证据','',
        '沿用原434/415日已见窗口、10万元独立空仓账户、0.1%单边费用、开仓周期现金比例、1%限买和市价卖出。经济与频率门槛逐项保持，不加权抵消。新MANDATE/5改变后续局部自检适用性，不降低阶段三目标。',
        '先完成lookback2..10与hold1..14的126个联合配置（100%投入、正步重新许可），加3/3即时许可的95%和100%对照；随后采用Optuna4.9.0多变量约束TPE，对真实lookback、hold、allocation与rearm_mode分批提出96次建议。每批8次，全部回填后再生成下一批；重复配置使用本轮相同参数的证据，不重复账户。',
        'allocation搜索0.6..1.0、步长0.025；其他参数固定，max_hold30在固定退出中不生效，未作为搜索维度。先用完整中心复算验证与旧C6105相同经济路径；串并行五张账表逐项一致。全部正式账户另做现金、费用、资金预算、闭合交易和指标算术核验。',
        '约束用于采样引导，最终采用独立精确硬门判断，包括434日经济/双频率及415日净收益严格大于91.5802915%、回撤严格小于7.2486637491%。全部trial提议及反馈先后保留，不把固定网格称作自适应搜索。','',
        '## 通过配置与对照','',
        '![联合时间参数网格：左为415日净收益，右为最大回撤；黑框为通过全部阶段三目标的配置](others/joint_parameter_map.png)','',
        '| 身份 | 观察/持有 | 投入 | 再许可 | 434收益/回撤 | 415收益/回撤 |',
        '|---|---|---|---|---|---|',
    ]
    for r in [anchor]+passing:
        p,a,b=r['parameters'],r['runs']['full'],r['runs']['s011_common']
        lines.append(f"| {r['candidate_id']} | {p['lookback']}/{p['hold']} | {p['allocation']:.3f} | {p['rearm_mode']} | {a['net_return']:.4%}/{a['dd']:.4%} | {b['net_return']:.4%}/{b['dd']:.4%} |")
    lines+=['','未达标的新增四目标前沿：','',
        '| 身份 | 观察/持有 | 434收益/回撤 | 415收益/回撤 | 未满足的中心条件 |',
        '|---|---|---|---|---|']
    for r in rows:
        if r['candidate_id'] in new_front and not r['both_center_pass']:
            p,a,b=r['parameters'],r['runs']['full'],r['runs']['s011_common']
            failed=[k for k,v in a['checks'].items() if not v]
            if not b['return_superior']:
                failed.append('415收益')
            if not b['dd_superior']:
                failed.append('415回撤')
            lines.append(f"| {r['candidate_id']} | {p['lookback']}/{p['hold']} | {a['net_return']:.4%}/{a['dd']:.4%} | {b['net_return']:.4%}/{b['dd']:.4%} | {', '.join(failed)} |")
    lines+=['','## 停止与局限','',
        f"联合过线时间组合为{summary['passing_time_pairs']}；同时在四目标上支配原C6105的本轮过线配置为{summary['dominate_C6105']}。边界改善触发项为{boundary}。完整逐配置表见[search_grid.csv](others/search_grid.csv)，联合网格见[joint_grid_415_return.csv](others/joint_grid_415_return.csv)。",
        '本轮完成预定联合覆盖和96次自适应提议。停止依据仅限该收益机制、固定退出结构与声明参数范围内的收益/风险/频率证据；不宣称全局最优、所有结构已优化或独立验证通过。若边界改善触发非空，必须先完成预留扩边再正式交付。',
        '新增前沿只改善415日收益，434日收益反而低于C6105，且回撤及交易频率不达标；不能称为整体改善。达标区域仍集中于3/3日，尚未获得宽泛时间参数区间内的稳健支持。新规则允许局部自检不扰动超限整数参数，不意味着这一已知选择风险消失，也不据此追加否决门槛。',
        '原CANDIDATES/6的全部16个阶段三过线中心继续保留；同内容重复评价，以及相同源码、相同生效参数且账户结果完全一致、仅失活字段不同的技术复算，均保留旧候选而不重复登记。新复算账户保持自身身份，不冒充旧候选账户证据。原EX064及ASSESSMENT/3失败事实保留，新参数适用性规则不自动改变其历史资格。',
        '434/415高度重叠且反复用于选择。全部旧结构/标签/组件搜索历史和末期依赖、三日尺度敏感性等负面证据继续有效。本轮增加的配置数不是独立信息数，也不能证明可精确识别入场亏损。',
        '后续阶段四须纳入EX065的新增选择历史，区分提议次数、实际配置、历史内容重复及收益路径重复；不能直接沿用旧176列家族统计而遗漏本轮，也不能把重复提议当成独立试验。选择偏差诊断仍为报告项，不新增经济否决条件。',
        '下一步建议按MANDATE/5对新交接集合执行阶段四自检；当前尚未获准本轮阶段四，不选型、不冻结、不操作PTE或生产。',
    ]
    (HOME/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return result,summary,oldpanel


def publish():
    result,summary,oldpanel=assemble_analysis()
    assert not summary['boundary_improvement'], 'Boundary extension required before closeout'
    assert not (HOME/'others/publication_receipt.json').exists()
    repo=RepositoryContext.discover(ROOT)
    ctx=create_research_context(repo,ResearchBatchRef('S015'),resources=ExecutionResources(8,1,13))
    refs=[EvidenceRef.from_dict(x) for x in read(HOME/'others/protocol_refs.json')]
    for path in (HOME/'others/results.json',HOME/'others/summary.json',HOME/'others/audit.json',HOME/'others/search_grid.csv',HOME/'others/joint_grid_415_return.csv',HOME/'others/joint_parameter_map.png',Path(__file__)):
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(EX,path.stem,path.read_bytes(),
            {'.json':'application/json','.csv':'text/csv','.py':'text/x-python','.png':'image/png'}[path.suffix],path.suffix[1:])))
    entries=list(oldpanel.candidates)
    handoff=list(oldpanel.handoff)
    by_hash={e.identity.content_sha256:e for e in entries}
    runtime=StrategyRuntime()
    registered=[]
    aliases=[]
    for row in result['rows']:
        if row['candidate_id'] not in summary['selected_new_evaluations']:
            continue
        if row['candidate_id'] in summary['source_proven_inactive_parameter_aliases']:
            key=summary['source_proven_inactive_parameter_aliases'][row['candidate_id']]
            old=next(x for x in oldpanel.candidates if x.identity.key.candidate_id==key)
            aliases.append({'evaluated':row['candidate_id'],'retained':key,'kind':'INACTIVE_PARAMETERS','reason':'Same source and active parameters; only inactive fields differ; both account metric/path hashes identical.'})
            if row['both_center_pass'] and old.identity.key not in handoff:
                handoff.append(old.identity.key)
            continue
        if row['identity']['content_sha256'] in by_hash:
            old=by_hash[row['identity']['content_sha256']]
            aliases.append({'evaluated':row['candidate_id'],'retained':old.identity.key.candidate_id,'kind':'CONTENT_IDENTITY','content_sha256':old.identity.content_sha256})
            if row['both_center_pass'] and old.identity.key not in handoff:
                handoff.append(old.identity.key)
            continue
        candidate=StrategyCandidate('S015',row['candidate_id'],read(HOME/f"others/{row['candidate_id']}_payload.json"),HOME/'src/strategy_runtime')
        deps=tuple(ImplementationDependency(**x) for x in row['dependencies'])
        identity=runtime.identify(candidate,dependencies=deps)
        assert identity.content_sha256==row['identity']['content_sha256']
        evidence=EvidenceRef.from_dict(row['evidence'])
        registration=register_candidate(repo,CandidateRegistrationRequest(candidate,EX,(evidence,),deps))
        loaded=load_candidate(repo,CandidateKey('S015',row['candidate_id']))
        assert runtime.identify(loaded,dependencies=deps)==identity
        entry=d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S015',row['candidate_id']),identity.content_sha256),
            '上移价格中心中的折让修复；时间参数、投入比例及再入场许可联合选择。',
            '阶段三全部中心目标通过，阶段四待执行。' if row['both_center_pass'] else '四目标非支配前沿，但阶段三完整目标未通过；不交接为达标中心。',
            (d.EvaluationEvidenceRef(evidence,()),))
        entries.append(entry)
        by_hash[identity.content_sha256]=entry
        if row['both_center_pass']:
            handoff.append(entry.identity.key)
        registered.append({'candidate':row['candidate_id'],'content_sha256':identity.content_sha256,'registration':registration.to_dict()})
    save(HOME/'others/registration_summary.json',{'new':registered,'retained_identity_aliases':aliases,'handoff':[asdict(x) for x in handoff]})
    refs.append(publish_evidence(ctx,MaterialEvidenceWrite(EX,'registration_summary',(HOME/'others/registration_summary.json').read_bytes(),'application/json','json')))
    report_bytes=(HOME/'report.md').read_bytes()
    report_ref=publish_evidence(ctx,ExperimentReportWrite(EX,sha256(report_bytes).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs),None))
    check=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status.value=='PASS'
    previous=d.DeliveryReceipt.from_dict(read(ROOT/'research/S015/deliveries/CANDIDATES/6/receipt.json')).reference
    mandate=d.DeliveryReference.from_dict(read(HOME/'others/mandate_reference.json'))
    search=d.SearchSummary('EX065-joint-adaptive','126-point joint grid +2 controls;96 multivariate constrained TPE proposals in feedback batches8',
        'Existing434/415windows; fixed mean-center entry/fixed intent-age exit; lookback/hold/allocation/rearm',result['formal_accounts'],len(result['rows']),
        'Retain all historical16 center passes plus all new exact center passes; retain new nondominated four-objective frontier; deduplicate registered content identity.',
        ('Repeatedly seen development samples; not independent validation.','Out-of-cap prior negative sensitivity remains.','Stage4 not executed under new mandate.'),tuple(refs))
    conclusion=f"阶段三联合参数重新寻优完成。共{len(result['rows'])}个实际配置、{result['formal_accounts']}个正式账户，本轮{summary['passing_new_evaluations']}个中心评价通过；去除内容重复并保留旧16中心后，共{len(handoff)}个中心交接阶段四。完整新规则资格仍未评价。"
    panel=d.CandidateSet(tuple(entries),tuple(handoff),tuple((*oldpanel.searches,search)),conclusion)
    delivery_report=report_bytes.decode('utf-8').replace('(others/',f'(../../../experiments/{EX.experiment_id}/others/')
    delivery=assemble_delivery(repo,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,7,(mandate,previous)),
        d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=delivery_report,evidence=tuple((*refs,report_ref))),resources=ExecutionResources(8,1,13))
    assert delivery.validation.status.value=='PASS'
    save(HOME/'others/publication_receipt.json',{'reference':delivery.receipt.reference.to_dict(),'validation':delivery.validation.to_dict(),
        'report':report_ref.to_dict(),'report_validation':check.to_dict(),'handoff_count':len(handoff),'new_registrations':len(registered),'retained_identity_aliases':aliases})
    print('CANDIDATES7_FULL_PASS',delivery.receipt.reference.content_sha256,flush=True)


if __name__=='__main__':
    if sys.argv[1]=='analyze':
        assemble_analysis()
    elif sys.argv[1]=='publish':
        publish()
    else:
        raise ValueError('analyze or publish required')
