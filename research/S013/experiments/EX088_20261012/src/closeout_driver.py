"""EX088 formal final-round delivery and bounded ten-round completion audit."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery,validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_strength_driver as d  # noqa: E402


def run():
    exp,plan=d.stage()
    path,c=exp.resolve(ROOT),d.base.common()
    ctx=c.context(1)
    refs={**d.read(path/'protocols/method_references.json'),**d.read(path/'protocols/result_references.json'),
          'verification.json':d.read(path/'protocols/audit_reference.json')}
    s,audit=d.read(d.public(refs['statistics.json'])),d.read(d.public(refs['verification.json']))
    assert audit['status']=='PASS' and audit['new_annual_models']==s['new_annual_models']==0
    assert audit['new_accounts']==s['new_accounts']==0 and audit['historical_controls']=='EXACT'
    assert audit['result_references']==d.read(path/'protocols/result_references.json') and audit['plan_reference']==refs['plan.json']
    assert audit['schedules']==36 and audit['causal_windows']==3270 and audit['bootstrap_checks']==5000
    definition=d.base.load('strength_review_definition',d.WORK/'kernel.py')
    core=s['bootstrap']['summary']
    assert tuple(core)==definition.QUANTITIES
    assert all(row['valid_replicates']==500 and row['ci95'][0]<0<row['ci95'][1] for row in core.values())
    for family in definition.FAMILIES:
        rows=s['schedules'][family+'_record4']
        assert all(not all(r['panels']['year_'+str(year)]['compound_net_proxy']>0 for year in (2022,2023)) for r in rows.values())
        assert rows['greedy']['panels']['year_2022']['compound_net_proxy']<0 and rows['greedy']['panels']['year_2023']['compound_net_proxy']<0
    authority=d.read(d.public(plan['continuation_budget_reference']))
    assert authority['maximum_additional_experiments']==10 and '暂停' in authority['human_message']
    previous_rounds=[]
    for number in range(79,88):
        old=ROOT/f'research/S013/experiments/EX{number:03}_20261012'
        old_refs=d.read(old/'protocols/closeout_references.json')
        budget=d.read(d.public(old_refs['budget_receipt.json']))
        assert budget['completed']==budget['started']==number-78 and budget['remaining']==88-number
        assert budget['authorization_reference']==plan['continuation_budget_reference'] and not budget['objective_achieved']
        validation=d.read(old/'protocols/delivery_validation.json')
        assert validation=={'type':'DeliveryValidation','status':'PASS','scope':'FULL','issues':[]}
        copy_proof=d.read(old/'protocols/report_copy_verification.json')
        original,copy=ROOT/copy_proof['formal_report'],ROOT/copy_proof['experiment_report']
        assert copy_proof['status']=='PASS' and original.read_bytes()==copy.read_bytes()
        assert d.digest(original)==d.digest(copy)==copy_proof['formal_sha256']==copy_proof['copy_sha256']
        refs[f'prior_EX{number:03}_budget.json']=old_refs['budget_receipt.json']
        refs[f'prior_EX{number:03}_report.md']=d.put(ctx,exp,original)
        previous_rounds.append({'experiment':old.name,'quota_slot':number-78,'delivery_reference':d.read(old/'protocols/delivery_reference.json'),
            'stored_FULL_validation':'PASS_NOT_RERUN','report_copy_live':'EXACT','report_sha256':d.digest(copy),'report_bytes':copy.stat().st_size,
            'budget_reference':old_refs['budget_receipt.json'],'actual_new_accounts':budget.get('actual_new_accounts_this_round',budget.get('new_accounts_this_round',0))})
    assert sum(row['actual_new_accounts'] for row in previous_rounds)==1
    old_sources={'baseline_latest_five_checks_report.md':'research/S013/deliveries/CANDIDATES/60/report.md',
                 'baseline_parameter_rates_report.md':'research/S013/deliveries/CANDIDATES/57/report.md',
                 'original_opportunity_capacity_report.md':'research/S013/deliveries/COMPONENTS/5/report.md'}
    for name,source in old_sources.items():
        refs[name]=d.put(ctx,exp,ROOT/source)
    d.write(d.OUT/'prior_round_validation.json',{'status':'PASS','previous_completed_rounds':9,'rounds':previous_rounds,
        'legacy_report_copies_live_verified':True,'legacy_FULL_reexecuted':False,'current_round_ready_for_FULL':True,
        'authority':plan['continuation_budget_reference'],'objective_achieved':False,'pause_pending_current_FULL_and_copy':True})
    refs['prior_round_validation.json']=d.put(ctx,exp,d.OUT/'prior_round_validation.json')
    judgment='已知净预测强度门提高重叠机会均值但减少机会，所有十项区间跨零；两族原贪心2022/2023仍亏，全部六时钟均未两下跌年同正。保留2026改善和赚幅信息，停止当前record4路线，不升级新账户。十轮已收尾，总目标未达成，按用户额度要求暂停。'
    def pct(value):
        return '不可得' if value is None else f'{100*value:.4f}%'
    report=f'''# EX088：更强的净预测能否避免较弱入场占用机会

{judgment}

通俗说，本轮只在“当前预计扣费后的收益，比此前4个交易日都高”时考虑买入。确实少买了一些弱机会，剩下机会平均看起来更好；但2022仍买到了亏损机会，2023按原入场时钟也仍亏。2026有明显改善，不能隐藏；它没有转化为跨下跌年份、跨入场安排的稳定达标能力。

## 与历史等待机制的区别及反证

EX010使用原确认分单日升降，EX017确认原raw上涨/下跌状态，两者都有交易数量和收益代价，本轮不重复那些规则。EX087原14概率＋赚幅获得有限净选择增量，贪心选中机会均值低于被持仓占用的正预测机会，提示需要核对因果可得强度，而非事后挑phase_1。确认族的被占用机会均值却更低，是必须保留的竞争解释。

本轮输入只有EX087两族110净预测，均由过去严格成熟训练产生，0新拟合、0新市场数据。确认族预测仍是旧确认分及年度系数的函数，不称新独立市场信息；原14预测含多个原价量信息的概率与赚幅组合。本轮只是预声明的入场资格表达，不是又证明新预测器。

## 固定因果规则和匹配支持

仅原510500.SH已见开发池、原1635T标签轴、原h4扣费HFQ OPEN价格标签。原HFQ锚、无现金分红叠加、资金费用整手及1%合同、只做多、四经济硬门保持。

当前预测严格>0并严格高于此前4个实际交易T已经发布预测的最大值才通过。完整4个过去值和当前值均需有限；缺失不通过，平值不通过，过去窗口不含当前T，也不看未来4日。4固定对应入场后会占用的h4决策跨度，是强度代理，不保证未来竞争信号更弱；没有窗口、方向、阈值或相位扫描。

每族三个表达：历史原控制（全部原预测）、匹配控制（当前及过去4值完整才允许）、record4（同一完整支持再加严格强度门）。主比较使用匹配控制，不能把刚开始少4个T的暖启动差当门的收益。历史控制全部时钟与EX087精确相等，过去窗口3270条逐条独立核对。

实际历史预测1392T、匹配支持1388T，首4个预测的历史信息不全，明确不可用；2020无预测，尾部未来标签缺失仍保留已知决策。跨年继续比较当时实际发布的净预测，不年度重置或用新模型回填旧预测；模型更新的跳变是潜在混淆。每族5个跨年窗口通过强度门，完整位置已留证。

原净预测保持不变。decision_scores.csv只是入场资格适配器：完整支持但不通过时0代表拒绝，而不是“预计收益为零”；信息不足为NaN，不用0兜底。没有把资格适配器当新收益预测计算MSE。所有数值/资格均只用T已知输入。

合成8类检查、4类显式拒绝通过；真实原标签比值和成熟日、3270因果窗口、匹配控制、36时钟及5000个重抽样量由独立标量实现复算PASS。合成前的pandas只读数组/混合NaN断言修复不改变科学规则，未读真实输入；实际统计1次，0新拟合、0账户/provider。

## 全部十项固定净选择诊断

共享原1635T轴500次重叠40日块seed13，固定实际资格和全窗时钟选择，不在拼接块内重新模拟时钟；原始/重抽样至少20、至少400有效、LINEAR95%区间。全部500有效，十项区间均跨零，未经研究历史与多重比较校正。均值差是百分点，非实际账户年化差或新经济硬门。

|固定数量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key,row in core.items():
        report+=f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report+='''
## 全窗及年度的全部重叠机会

四日扣费OPEN价格代理允许重叠，不是连续账户收益。

|表达|可用T|正资格数|成熟数|平均净代理|实际盈利比例|
|---|---:|---:|---:|---:|---:|
'''
    for name,row in s['panels']['all'].items():
        report+=f"|{name}|{row['forecasts']}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['hit_rate'])}|\n"
    report+='''
确认成熟机会625→208，均值+0.1424%→+0.4171%；原14为626→229，均值+0.1593%→+0.4033%。它减少约三分之二的重叠机会，不是保留相同数量后的无成本收益提高；均值增量区间均跨零。

每格为成熟正资格数量/平均净代理，不足20时均值不可得。

|年份|确认历史|确认匹配|确认record4|14历史|14匹配|14record4|
|---|---:|---:|---:|---:|---:|---:|
'''
    for year in range(2020,2027):
        cells=[]
        for name in definition.MODELS:
            row=s['panels']['year_'+str(year)][name]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report+=f'|{year}|'+ '|'.join(cells)+'|\n'
    report+='''
2022门后确认/14均值约−0.3562%/−0.7195%，比匹配控制更差。2023均值仍正但都低于匹配控制。2024门后均值大幅增至+1.8594%/+2.2248%；2026原14从负转正，是重要有利结果。不能用2024大涨或2026改善掩盖2022失败。

## 全部36时钟、年度复合与盈利集中

精确复用EX083原贪心及i%5五组，h4、冷却和退出优先规则保持，不年度重置。不同组机会数量和持仓不同，非等笔数比较，非32标准参数扰动；按入场年归组的价格代理不等于自然年账户净收益/回撤。未包含原生限价未成交、整手资金及最终浮盈亏。

|表达/时钟|成熟数|全窗复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for name,rows in s['schedules'].items():
        for clock,row in rows.items():
            a=row['panels']['all']
            report+=f"|{name} / {clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|"+'|'.join(pct(row['panels']['year_'+str(y)]['compound_net_proxy']) for y in range(2020,2027))+'|\n'
    report+='''
确认原贪心匹配177→121个成熟意图，全窗复合+27.42%→+27.64%；原14为192→147个，全窗+14.20%→+18.49%。均值虽增加，复合经济改善很小，机会减少明显。原贪心2022门后分别−13.46%、−18.08%，2023−1.85%、−1.22%，仍未解决下跌年份；2026分别从−5.40%/−7.66%转为+5.60%/+20.09%，保留此改善。

两个record4表达全部六时钟都没有同时2022/2023正复合代理。确认phase_4的2022+7.23%但2023负，原14各组2022全部负；不根据结果换组选规则。

原频率要求为完整1636执行T平均每60日至少4实际闭合交易，即至少110次。121/147是原贪心成熟价格意图供给，不能写成账户频率已达标；固定五组各只有35–56个成熟意图，不能借相位比较说数量问题已解决。

|record4/时钟|最大约10%盈利机会占全部正盈利|去掉这些机会的全窗复合代理|
|---|---:|---:|
'''
    clock_summary={}
    for family in definition.FAMILIES:
        name=family+'_record4'
        rows=s['schedules'][name]
        for clock,row in rows.items():
            a=row['panels']['all']
            report+=f"|{name} / {clock}|{pct(a['top_positive_contribution'])}|{pct(a['compound_without_top10pct_positive'])}|\n"
        clock_summary[name]={'both_down_years_positive':0,'greedy_mature_intents':rows['greedy']['panels']['all']['mature'],
            'greedy_full_proxy':rows['greedy']['panels']['all']['compound_net_proxy'],
            'greedy_2022_proxy':rows['greedy']['panels']['year_2022']['compound_net_proxy'],
            'greedy_2023_proxy':rows['greedy']['panels']['year_2023']['compound_net_proxy']}
    report+='''
两族各六时钟，事后去掉最大约10%正盈利机会的复合代理全部为负，说明存在集中盈利依赖。该算术删项不是新策略、新账户或新硬门，也不证明未来必然错过这些机会；全部原正盈利均保留。

## 为什么本轮不进入账户

有利证据是门后重叠均值增加、2026改善；反证是十项区间跨零、数量减少、2022更差、全部时钟没有两下跌年同正及集中盈利。综合尚不足以升级本固定强度表达，未追加完整账户、费用或32点救援；不由单个统计诊断自动淘汰，也不宣称账户结果已由代理证明失败。停止record4，保留此前赚幅信息的有限支持。

## 追加十轮的成果与未达成项

EX079–EX088共10个研究编号；同轮技术修正/独立核验不另算实验。本轮逐一核对前9轮预算回执、已有FULL记录、正式report与实验副本的当前字节及哈希；未重新跑旧FULL、旧账户或旧统计。本轮另实际执行正式FULL校验。

|轮次|问题|主要结果|
|---|---|---|
|EX079|原确认及14项识别四日扣费机会|确认有有限筛选线索，未稳定盈利|
|EX080|确认净预测落实完整账户|C9080仅频率达标，年化2.4529%，2022/2023亏损|
|EX081|确认结合涨跌方向|固定主效应/交互未增加可用净机会|
|EX082|自然月内第一谐波|总体预测无稳定增量，局部时钟代理有利|
|EX083|日期机会时钟与集中度|对入场时钟不稳、2022余量依赖大赚机会|
|EX084|盈利概率与固定平均盈亏|概率线索有限，合成净选择均值仍负|
|EX085|近期已成熟20机会状态|无稳定净增量，未解决2022|
|EX086|条件赚幅和亏幅|保留14赚幅预测局部支持，合成机制失败|
|EX087|概率/赚幅/亏幅拆项|赚幅净选择增量保留，当前亏幅抵消改善|
|EX088|因果净预测强度入场|均值增加伴随数量减少，下跌年仍未解决|

十轮实际新完整账户1个（EX080），技术上的账户前失败不算账户；其他以信息与经济余量反证收口，未用无新依据的账户凑额度。新候选四门未同时通过，因此没有新增合格策略进入标准32点与双费检验，未产出绝对Q10收益更高、Q90回撤更低且硬门达标的新策略。新的Q10/Q90/32逐项及联合率不可得，不填0或通过。

## 既有研究对照的绝对稳健性仍未改善

以下明确复用原C8880旧完整账本/最新五项口径的已发布结果，本轮仅核对关联正式报告字节与身份，没有重放。中心达标不等于抗扰动已解决。

|指标|原C8880历史结果|
|---|---:|
|中心净年化 / 全窗回撤|17.1346% / 13.6187%|
|闭合交易 / 每60日平均|116 / 4.2543|
|2022 / 2023净收益|19.5931% / 0.9181%|
|标准扰动绝对收益Q10 / 回撤Q90|6.3981% / 28.3508%|
|32点整体收益达标|7/32（21.875%）|
|32点逐年回撤达标|32/32（100%）|
|32点交易频率达标|27/32（84.375%）|
|32点两个下跌年均严格盈利|2/32（6.25%）|
|32点四门联合达标|0/32（0%）|
|126/21滚动超额Q10|−19.0202%|
|最大约10%正盈利交易贡献|43.8056%|
|独立双费年化 / 全窗回撤|13.0446% / 17.2963%|
|超额收益95%描述区间|[−7.1562%,+25.2493%]|

双费2023收益−3.3833%，没有通过下跌年盈利。PBO/DSR完整研究族矩阵缺失，仍不可得而非0。标准32点为有效参数域归一化L2总距离5%、seed13、整数HALF_EVEN，回撤Q90是全窗诊断，硬门仍逐自然年严格比较；时间/集中/双费/不确定性按最新定义互相独立，不交叉叠加。组件500×40块区间不同于五自检2000次平均20日配对平稳重抽样，不能混用。

## 通俗结论、保留/放弃与暂停

机会并非完全没有：EX066理想开盘及未来信息的容量计算已有供给，但那不是可执行策略。本次十轮最大的障碍仍是“当时不能稳定挑对、净余量不够厚、入场与持有使好机会互相占用”，不是仅靠提高胜率、减少交易或更复杂预测就能解决。只做多、频率、下跌年盈利有现实张力，本轮没有证明三者逻辑上不可能兼容，也没有把硬门改宽。

保留原可执行账户与确认作为研究对照、真实扣费/资金路径检验、以及盈利幅度的有限信息支持。原确认曾改善中心收益，但未修复下跌过滤/退出敏感性的历史反证保持。放弃已失败的固定日期路线、当前条件亏幅搭配、把全池正预测直接按h4贪心交易的表达和本record4补救；不选择好相位、翻符号、改期限/窗口或阈值救援。

总体目标没有达成，原标准扰动低端收益/高端回撤及联合达标问题仍在。建议暂停后先复盘“怎样在当时识别下跌环境的亏损风险及需要什么新增信息”，再决定是否恢复研究；当前不继续原价量阈值微调。若需要新增信息来源，必须另行确认范围，本轮没有访问或扩展。新方向是待评审研究问题，不承诺已有Alpha。

额度10/10已使用并完成收尾；按用户“额度使用完毕请暂停研究”执行暂停，目标不得标为完成，不创建EX089，不追加统计/账户。每轮others/report.md均为正式报告精确副本，最终总表再次核对全部十轮字节与SHA256。
'''
    review={'status':'ROOT_SCIENTIFIC_REVIEWED','judgment':judgment,'objective_achieved':False,'new_annual_models':0,'new_accounts':0,
        'original_four_hard_gates_changed':False,'new_economic_hard_gates':False,'append_account':False,'clock_summary':clock_summary,
        'favorable_counterevidence':'higher overlapping selected means and positive2026 greedy both families; retained',
        'prior_round_validation_reference':refs['prior_round_validation.json'],'pause_required_after_delivery':True,
        'next_action':'Pause after current full closeout under direct human ten-round authority; noEX089',
        'evidence_references':{k:refs[k] for k in ('plan.json','statistics.json','verification.json')},'report_markdown':report}
    d.write(d.OUT/'root_review.json',review)
    refs['root_review.json']=d.put(ctx,exp,d.OUT/'root_review.json')
    refs['closeout_driver.py']=d.put(ctx,exp,Path(__file__))
    budget={'status':'ROUND10_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT','authorization_reference':plan['continuation_budget_reference'],
        'maximum_additional_experiments':10,'started':10,'completed':10,'remaining':0,'completed_experiment':exp.to_dict(),
        'next_allowed':None,'last_allowed':'EX088','pause_after_EX088':True,'new_accounts_this_round':0,'objective_achieved':False,
        'actual_new_accounts_in_ten_rounds':1,'no_EX089_authorization':True}
    d.write(d.OUT/'budget_receipt.json',budget)
    refs['budget_receipt.json']=d.put(ctx,exp,d.OUT/'budget_receipt.json')
    for value in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference']):
        d.public(value)
    evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(),*plan['input_references'].values(),plan['continuation_budget_reference'])))
    tests=tuple(m.ComponentTestResult('ENTRY-STRENGTH-'+family,exp.experiment_id,EvidenceRef.from_dict(refs['plan.json']),m.ComponentTestStatus.INEFFECTIVE,
        '强度门提高重叠均值/2026局部表现，但数量减少，十项区间跨零，2022/2023原贪心仍负，各6时钟都未两年同时正，未获稳定经济支持',
        tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json','verification.json','root_review.json'))) for family in definition.FAMILIES)
    entry=m.ComponentEntry('CAUSAL-H4-NET-FORECAST-RECORD',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-entry-strength/kernel.py']),'decisions'),
        '冻结概率+赚幅净预测的过去四T严格record入场资格及匹配对照',
        '原h4扣费HFQ OPEN价格代理，资格/占用/净选择职责，不是新收益预测或完整账户','h4持有/固定此前4T强度，0新拟合',
        '每族历史/相同四T支持匹配/record三表达，全部36时钟和年度/相位，原控制精确复用',
        '当前及过去4个实际发布预测，完整有限，不含未来T，不以测试truth改门，跨年不回填或重置',
        '原510500开发池HFQ锚/无现金分红叠加/资金费用整手/1%合同，0账户/provider',
        '预测强度可能是波动/年度重拟合跳变，减少数量/集中盈利；拒绝0是资格标记非收益预测；未新增硬门',judgment,tests)
    report+='\n\n正式证据：\n\n'+''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name,ref in refs.items())
    receipt=assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'),m.DeliveryStage.COMPONENTS,22,tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])),
        m.DeliveryContent(m.ComponentPanel((entry,),judgment),m.DeliveryStatus.COMPLETE,(),(),report=report,evidence=evidence))
    d.write(path/'protocols/delivery_reference.json',receipt.reference.to_dict())
    validation=validate_delivery(ctx.repository,receipt.reference,scope=m.DeliveryValidationScope.FULL)
    d.write(path/'protocols/delivery_validation.json',validation.to_dict())
    d.write(path/'protocols/closeout_references.json',refs)
    if validation.status.value!='PASS':
        raise RuntimeError(validation.to_dict())
    formal,copy=ROOT/'research/S013/deliveries/COMPONENTS/22/report.md',path/'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes()==copy.read_bytes() and formal.stat().st_size==copy.stat().st_size
    copy_proof={'status':'PASS','formal_report':formal.relative_to(ROOT).as_posix(),'experiment_report':copy.relative_to(ROOT).as_posix(),
        'formal_sha256':d.digest(formal),'copy_sha256':d.digest(copy),'formal_bytes':formal.stat().st_size,'copy_bytes':copy.stat().st_size,
        'exact_bytes':True,'human_instruction':'RSCH，请在后续的每个实验目录下保存一份report副本'}
    d.write(path/'protocols/report_copy_verification.json',copy_proof)
    with (path/'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    current={'experiment':exp.experiment_id,'quota_slot':10,'delivery_reference':receipt.reference.to_dict(),
        'stored_FULL_validation':'PASS_CURRENT_EXECUTED','report_copy_live':'EXACT','report_sha256':d.digest(copy),
        'report_bytes':copy.stat().st_size,'budget_reference':refs['budget_receipt.json'],'actual_new_accounts':0}
    d.write(path/'protocols/continuation_completion.json',{'status':'TEN_ROUNDS_DELIVERED_AND_REPORT_COPIES_VERIFIED',
        'authority':plan['continuation_budget_reference'],'human_pause_instruction':authority['human_message'],
        'started':10,'completed':10,'remaining':0,'rows':previous_rounds+[current],
        'actual_new_accounts':1,'objective_achieved':False,'next_allowed':None,'EX089_started':False,
        'pause_required_now':True,'goal_pause_tool_status':'PENDING_POST_COMMIT'})
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'COMPONENTS':22,'FULL':'PASS','report_copy':'EXACT','completed':10,'remaining':0,'pause_required':True})


if __name__=='__main__':
    run()
