"""Public failed-centre search closeout; cannot finalize passing centres."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402


def pct(value):
    return '不可得' if value is None else f'{100*value:.4f}%'


def close(number,folder,*, title,judgment,explanation,positive_evidence,counterevidence,next_direction,caller):
    exp,path,plan,method_refs=g.stage(number)
    out=ROOT/f'.tmp/s013-new-goal/result{number:03}'
    audit=g.read(out/'verification.json')
    if audit['status']!='PASS' or audit['qualified'] or audit['objective_achieved']:
        raise ValueError('Failed-centre closeout only: a passing centre still requires actual32/fee')
    if audit['new_accounts']!=1 or audit['technical_financial_repeats']!=0:
        raise ValueError('Exactly one new centre; no hidden financial repeats')
    e,b=audit['economics'],audit['baseline_economics']
    v,bv=audit['gates_v2'],audit['baseline_gates_v2']
    refs=dict(method_refs)
    for filename in ('prepare_references.json','audit_references.json'):
        refs.update(g.read(path/'protocols'/filename))
    refs['native.json']=g.read(out/'execution.json')['native_ref']
    ctx=g.base.common().context(1)
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'objective_achieved':False,
        'new_accounts':1,'qualified_new_v2':False,'new32':0,'new_fee':0,
        'positive_evidence':positive_evidence,'counterevidence':counterevidence,'next_direction':next_direction,
        'economic_facts':e,'new_four':v,'full_pool_frequency':'diagnostic_only','source':refs['verification.json']}
    g.write(out/'root_review.json',review)
    g.write(out/'statistics.json',{'status':'ACTUAL_FULL_ACCOUNT_ECONOMICS','center':e,'baseline':b,
        'new_four':v,'baseline_new_four':bv,'parameter32':audit['parameter32'],'fivechecks':audit['three_ledger_checks']})
    budget={'started':number-88,'completed':number-88,'remaining':98-number,'last_completed':exp.experiment_id,
        'next_allowed':f'EX{number+1:03}' if number<98 else None,'authority':refs['renewal_authorization.json'],
        'pause_after_EX098':True,'objective_achieved':False,'new_accounts_this_round':1,'financial_repeats':0}
    g.write(path/'protocols/budget_receipt.json',budget)
    for name,file in {'root_review.json':out/'root_review.json','statistics.json':out/'statistics.json',
        'budget_receipt.json':path/'protocols/budget_receipt.json',
        'native_failure_closeout.py':Path(__file__),'closeout_driver.py':Path(caller)}.items():
        refs[name]=g.put(ctx,exp,file)
    report=f'''# {exp.experiment_id[:5]}：{title}

{judgment}

{explanation}

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前{number-88}/10轮完成，剩余{98-number}，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：{plan['question']}

依据：{plan['basis']}

最强事前反证：{plan['strongest_counter']}

机制职责：{plan['role_of_component']}。{plan['horizon']}

对照：{plan['controls']}

可得性：{plan['availability']}

价格及执行：{plan['price_basis']}。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：{plan['limitations']}

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
'''
    for name,facts,gates in (('C8880原规则',b,bv),(plan['candidate_id'],e,v)):
        report+=f"|{name}|{pct(facts['net_cagr'])}|{pct(facts['full_drawdown'])}|{facts['closed_trades']}|{gates['positive_closed_cycles']}/{gates['positive_sessions']}|{gates['positive_frequency60']:.6f}|{gates['all_year_frequency60']:.6f}|{pct(facts['annual']['2022']['return'])}|{pct(facts['annual']['2023']['return'])}|{gates['gates']}|\n"
    report+=f'''
同口径buyhold净年化{pct(e['benchmark_cagr'])}，收益门槛{pct(1.5*e['benchmark_cagr'])}。盈利年份为{v['positive_years']}，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
'''
    for year,row in e['annual'].items():
        bh=e['benchmark_annual'][year]
        report+=f"|{year}|{pct(bh['return'])}|{pct(bh['drawdown'])}|{pct(b['annual'][year]['return'])}|{pct(row['return'])}|{pct(row['drawdown'])}|{row['closed_cycles']}|{row['sessions']}|{row['drawdown']<bh['drawdown']}|\n"
    report+=f'''
## 有利结果与必要反证

有利事实：{positive_evidence}

必要反证：{counterevidence}

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
'''
    for row in audit['three_ledger_checks']['rows']:
        for diagnostic in row.get('diagnostics',[]):
            report+=f"|{diagnostic.get('metric')}|{diagnostic.get('value')}|{diagnostic.get('status',diagnostic.get('evidence_status','见关联正式SE状态'))}|\n"
        interval=row['uncertainty']
        report+=f"|策略减buyhold净年化差的成对bootstrap95%描述区间|[{pct(interval['lower_95'])}, {pct(interval['upper_95'])}]|{interval['status']}|\n"
    for diagnostic in audit['three_ledger_checks']['family_diagnostics']:
        report+=f"|{diagnostic['name']}|{diagnostic['value']}|{diagnostic['status']}：{diagnostic['reason']}|\n"
    report+='''
仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。本轮是新的学习策略，原C8880只作经济及执行对照，没有进行父OFF等价核验。新策略自身的预测、完整策略状态、真实决策及会计账本已独立核验。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。
'''
    report+=f'''
## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。{next_direction}

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。
'''
    report+='\n\n正式证据（项目根目录相对路径）：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(ref) for ref in (*refs.values(),*plan['input_references'].values())))
    summary=m.SearchSummary(exp.experiment_id+'-fixed-centre',plan['question'],
        '原完整开发池与执行合同；固定机制一个原生中心；原C8880只读控制；没有新数据或参数优化',1,1,
        judgment,('中心新版四门失败，新增合格集合空；旧资格不修改',
            '标准32/双费未运行，其数值不可得，三账本诊断不冒充完整五项',
            '同开发池适应性研究，未校正全部历史选择'),evidence)
    revisions=[int(p.name) for p in (ROOT/'research/S013/deliveries/CANDIDATES').iterdir() if p.name.isdigit()]
    revision=max(revisions)+1
    predecessor=m.DeliveryReference.from_dict(g.read(ROOT/'research/S013/assets/deliveries/MANDATE/7/receipt.json')['reference'])
    receipt=assemble_delivery(ctx.repository,m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        m.DeliveryContent(m.CandidateSet((),(),(summary,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    g.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    g.write(path/'protocols/delivery_validation.json',validation.to_dict())
    g.write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise ValueError(validation.to_dict())
    formal=ROOT/f'research/S013/deliveries/CANDIDATES/{revision}/report.md'
    copy=path/'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    if copy.read_bytes()!=formal.read_bytes():
        raise ValueError('Report copy differs')
    g.write(path/'protocols/report_copy_verification.json',{'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),
        'experiment_report':copy.relative_to(ROOT).as_posix(),'formal_sha256':g.digest(formal),'copy_sha256':g.digest(copy),
        'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,'exact_bytes':True})
    recovery=path/'src'/folder/'closeout'
    recovery.mkdir(parents=True,exist_ok=True)
    for file in (Path(__file__),Path(caller)):
        with (recovery/file.name).open('xb') as stream:
            stream.write(file.read_bytes())
    assert not g.base.common().SOURCE_CALLS
    print({'experiment':exp.experiment_id,'CANDIDATES':revision,'FULL':'PASS','report_copy':'EXACT','completed':number-88,'remaining':98-number,'new_accounts':1},flush=True)
    return receipt.reference
