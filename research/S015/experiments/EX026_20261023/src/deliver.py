"""Publish the complete fixed study, including negative and feasibility evidence."""
import argparse
from hashlib import sha256
from study import ROOT, HERE, EX, read, save, sources, context, material
from czsc_trader.application import RepositoryContext, publish_evidence, assemble_delivery, validate_experiment, update_research_intent, ResearchIntentUpdate
from czsc_trader.research_tools import EvidenceRef, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope, ResearchBatchRef
from czsc_trader.research_tools import delivery as d

NAMES = {'A':'区间突破','B':'收敛后突破','C':'盘中方向一致'}


def pct(v):
    return '不可计算' if v is None else f'{v:.4%}'


def report():
    r, s = read(HERE/'others/results.json'), read(HERE/'others/supplement.json')
    text = '''# S015 延续机制诊断：发现有限线索，当前固定形式不足以支持合格策略

Status: COMPLETED

RSCH，2026-10-23。用户批准的新增1轮阶段二诊断已完成，额度1/1，剩余0。**当前目标下合格候选、待选型候选及待冻结候选仍为0。** 本轮没有新增完整连续策略账户、搜索配置或登记候选，未执行阶段三、自检或冻结。

收敛后突破在3日和5日持有下出现扣费后正收益线索，且收益主要发生在实际买入后；但样本少、时间差异大，当前固定持有方式的交易频率上限已低于原目标。它还不是证据充分的可用组件。盘中同向上涨三个期限均弱于条件外机会，暂不支持该入场方式。区间突破的较长期平均收益为正，但未建立足以推进策略构造的稳定优势。

## 当前目标与授权

沿用[MANDATE/3](../../deliveries/MANDATE/3/report.md)：434日原经济、频率、32点扰动及费用压力要求，另加415日累计净收益严格大于0.9158029150000013、最大回撤严格小于0.07248663749114126。没有新增显著性、分段盈利或集中度经济硬门；互补性也不替代双优验收。

[原86个候选补证](../EX013_20261023/report.md)在新目标下全部不合格；[十轮收口](../../deliveries/CANDIDATES/3/report.md)同样没有合格策略。保存旧登记及历史通过记录不代表当前仍有合格候选。上批10轮额度独立保留，本次是用户另批的1轮。

本轮执行[获批方案](../../materials/mechanism_reorientation_20261023.md)和[事前协议](protocols/fixed_mechanisms.json)，用现有ETF日线与30分钟数据，检验3种定义×3个期限。原开发池434日、75日预热及截止日不变；没有扩展指数、海外、供应商或验证样本。

## 定义与标签

- A：T日收盘严格超过此前20个交易日收盘最高值，历史区间不含T。
- B：A成立，且T日前5日平均相对日内振幅小于T日前20日平均值，两者均排除T。B是A的子集，不能把两者视作独立机制。
- C：13:30收盘高于10:00首根柱开盘，15:00收盘高于13:30收盘。10:00是9:30至10:00柱结束时点，13:30包含午后第一根柱，不能称为纯上午分段。

20日、5日和时点均事前固定。旧EX024的正压力规则是收盘高于成交均价，不等于上述A/B/C；C与旧正压力的重合另用相同标签对照，不能拿旧账户收益直接代替。

T日17:30决策，T+1按原收盘上方1%限价、整手及价格约束买入。h=1/3/5时，在T+h收盘发出卖出决策，T+h+1首次按市场价规则尝试卖出；失败后逐交易日重试，实际延期和未退出单列。h=1最早也在买入后的下一交易日卖出。每个事件独立10万元，双边实际成交额各扣0.1%，使用公共TXE resolve_fill与DAILY_RANGE_V3，不模拟成交量容量。

下表均值为每个独立事件扣费损益/10万元；事件重叠，不能连乘、加总成策略收益，不能据此宣布收益或回撤达标。

## 全部9项结果

| 定义 | 持有h | 闭合事件 | 组内平均净收益 | 条件外平均净收益 | 组内中位数 | 正/负事件 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for h,z in r['horizons'].items():
        for name in NAMES:
            q=z['comparisons'][name]; a,b=q['in'],q['out']
            text+=f"| {NAMES[name]} | {h} | {a['n']} | {pct(a['net_mean_return'])} | {pct(b['net_mean_return'])} | {pct(a['net_median_return'])} | {a['positive_n']}/{a['negative_n']} |\n"
    text+='''
## 收益发生在哪里

所有金额是重叠独立事件的账面金额加总，用于分解，不能当作一个账户赚到的钱。买前变化单列为价格变动；不计入策略利润。入场日毛损益加后续持有毛损益，再减双边实际费用，等于闭合净损益。日范围模型不能支持入场后的精确最低价推断。

| 定义/h | 买前平均价格变化 | 入场日毛损益/元 | 后续毛损益/元 | 双边费用/元 | 闭合净损益/元 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
    for h,z in r['horizons'].items():
        for name in NAMES:
            a=z['comparisons'][name]['in']
            text+=f"| {name}/{h} | {pct(a['before_entry_mean_change'])} | {a['entry_gross_yuan']:.2f} | {a['subsequent_gross_yuan']:.2f} | {a['fees_yuan']:.2f} | {a['net_yuan']:.2f} |\n"
    text+='''
B/5的入场日毛损益10008.00元、后续持有毛损益47189.40元、费用7768.72元；约82.50%的毛损益发生在入场日收盘以后。因此该线索不是把买入前上涨冒充利润。B/1毛损益3610.30元低于费用7715.14元，不能支持短持有。C在三个期限的入场日损益均为负，延长持有后的改善并未使组内均值超过条件外。

## 捕获盈利与机会代价

分母为同期限全部闭合事件的正净金额总和或负净金额绝对总和，两者不同。遗漏盈利是条件外正金额，不是策略若参与就能获得的利润；没有可部署的资金路径或组合。

| 定义/h | 组内正金额/元 | 组内负金额/元 | 捕获正金额 | 承担负金额 | 错过正金额/元 | 错过正金额比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for h,z in r['horizons'].items():
        for name in NAMES:
            a=z['comparisons'][name]['in']
            text+=f"| {name}/{h} | {a['positive_yuan']:.2f} | {a['negative_yuan']:.2f} | {pct(a['captured_positive_fraction'])} | {pct(a['borne_negative_fraction'])} | {a['missed_positive_yuan']:.2f} | {pct(a['missed_positive_fraction'])} |\n"
    text+='''
B/5捕获12.61%的正金额，承担6.47%的负金额，同时遗漏87.39%的正金额。这说明它选择少量机会后的得失结构较有利，不说明它能承载完整收益目标。B相对A非B在h=3平均净收益为0.4915%对−0.0873%，h=5为1.2674%对−0.0192%；h=1反而更差。所有期限均报告，不把最高均值的期限当作独立验证。

## 时间反证与不确定性

固定时间段按信号日位置划分，前100日单列，后四段沿用旧研究边界；全部是已见历史，不是新样本外验证。完整A/B/C组内外、B对A非B及C正压力四格分段见[分段与对照](others/temporal_controls.md)和[结构化汇总](others/supplement.json)。

| 决策位置 | B事件数 | B/1均值 | B/3均值 | B/5均值 | A非B/5均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
    for period,v in s['horizons']['5']['periods'].items():
        a=v['B_increment']['B']; b=v['B_increment']['A_not_B']
        text+=f"| {period} | {a['n']} | {pct(s['horizons']['1']['periods'][period]['B_increment']['B'].get('net_mean_return'))} | {pct(s['horizons']['3']['periods'][period]['B_increment']['B'].get('net_mean_return'))} | {pct(a.get('net_mean_return'))} | {pct(b.get('net_mean_return'))} |\n"
    text+='''
B/5前100日平均−0.8719%，中间三段为正，最后一段4个事件全部亏损、平均−5.1483%；最后一段没有A非B事件，因此不存在可比较的同期组间差值，不能填0。全期B/5最大盈利事件占正金额15.83%，前5个占45.25%；一些事件来自相邻交易日，不能当作39份独立市场经历。

以下为组内减条件外的平均净收益差，以及B减A非B的差值，按完整434个交易日轴进行10/20日块联合重抽样499次、种子13。抽样后才筛条件及闭合标签；没有先把稀疏事件排成相邻交易日。区间为探索性95%范围，未校正多项和历史选择，不能解释为未来成功概率，也不是新增资格门。

| 对照/h | 10日块差值区间 | 20日块差值区间 | 有效次数10/20 |
| --- | --- | --- | ---: |
'''
    for h,z in r['horizons'].items():
        for name in ('A','B','C','B_vs_A_not_B'):
            a,b=z['intervals']['10'][name],z['intervals']['20'][name]
            interval=lambda v: '['+', '.join(pct(t) for t in v['interval95'])+']' if v['interval95'] else '不可计算'
            text+=f"| {name}/{h} | {interval(a)} | {interval(b)} | {a['valid_draws']}/{b['valid_draws']} |\n"
    text+='''
B/5相对A非B的20日块区间约为[−0.8865%,3.6239%]，方向仍有较大不确定性。没有仅因区间跨0判经济失败；当前不推进的判断还结合时间反证、机会密度及固定结构的频率不相容。

## 固定形式的频率上限

先把所有重叠事件都视作独立交易，再计算更实际的单持仓乐观上限：每个完整60日窗口可独立选择退出落在窗口内的最多互不重叠事件，入场可以在窗前；允许同日卖出再买入、忽略资金约束，不要求全程统一选择规则。以最早退出贪心求解，并用独立动态规划核对。

这已放宽真实交易条件。任何仅从这些固定事件选取子集、保持相同入场及退出日、一次只持有一个完整周期的策略，其每窗闭合数都不能超过此上限。上限仍达不到原标准时，可排除这种特定结构；上限通过不表示存在全程可执行规则达标。结论不适用于修改退出、增加入场或不同组合的策略。

| 定义/h | 全重叠事件60日中位数 | 非重叠乐观中位上限 | 非重叠至少3笔窗口上限/375 |
| --- | ---: | ---: | ---: |
'''
    for h,z in s['horizons'].items():
        for name,a in z['density'].items():
            text+=f"| {name}/{h} | {a['all_overlapping_events_closed_60_median']:.0f} | {a['nonoverlap_optimistic_60_median_upper_bound']:.0f} | {a['nonoverlap_optimistic_windows_at_least3_upper_bound']}/375 |\n"
    text+='''
原门槛是中位数至少6、至少338/375窗口有3笔。B/3与B/5的中位上限均3，达3笔窗口上限分别302和199，**当前固定形式无法达到已有频率要求**。A/5也被该上限排除；A/3未被上限排除，但不能由此证明它可执行或合格。没有新增频率要求，也没有用事件总数冒充实际闭合交易数。

## 解释、组件状态与下一步

本轮得到的是有限的机制线索：在部分时段，收敛后的突破存在入场后延续；并未证明资金行为解释、独立收益来源或未来持续性。三种定义属于同一延续族，B与A嵌套，不能声称发现3种独立收益机制。

- A/1、B/1：当前用途净收益为负，记录INEFFECTIVE。A/3、A/5和B/3、B/5：存在方向性线索，但确认可用性所需证据不足，记录INSUFFICIENT_DATA，保留完整正反证。
- C三个期限：均弱于条件外，记录INEFFECTIVE。h5自身正均值不能单独证明该条件提供增量。
- 上述为RSCH对研究用途的判断，不是统一数值经济硬门；INSUFFICIENT_DATA在此指机制可用性证据不足，并非行情缺失（实际缺失0）。没有将旧组件全部重判，也没有将新的不确定性诊断替代MANDATE/3。

**建议暂不进入阶段三，更不直接构造B/3或B/5并期望达标。** 保留B为后续研究线索；若继续，先评审“趋势形成后是否存在持续的可参与状态”，区分突破首日事件与后续持续状态，明确新增观察和可能增加机会的原因，再决定最小对照。不能通过强行拆单、扩大窗口或默改频率标准促成通过。若真正需求是低频互补策略，应另行明确目标；当前按独立双优策略执行。

## 覆盖、核验与交付

509行日线=75预热+434开发日；3472行30分钟=434×8完整时点，实际输入缺失0。实现遇缺柱明确失败，不把未知当作条件外。历史供应商17:30前可得与后复权发布时间未认证，时间因果检查只支持所声明市场观察假设。

| h | 闭合 | 买入未成交 | 已买但退出越界 | 无下一买入日 | 实际延迟退出 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
    for h,z in r['horizons'].items():
        c=z['coverage']
        text+=f"| {h} | {c.get('CLOSED',0)} | {c.get('BUY_UNFILLED',0)} | {c.get('EXIT_RIGHT_CENSORED',0)} | {c.get('NO_NEXT_SESSION',0)} | {z['delayed_exits']} |\n"
    text+='''
共1302行日—期限事件，1269条闭合标签，共享给9项比较；不是1302个策略账户或独立假设。另有串行/3进程预检各12条、共24条技术重复；独立核验的历史标签复算及合成成交调用另记在检查文件，不计新研究配置。没有参数搜索，也没有使用独立保留样本。

当前实际延迟退出0；合成场景验证首次卖出受阻后成功及一直受阻。右端先计算买入事实，再保留入场日估值和期末未退出净估值，闭合净标签保持缺失；不将未成交、未退出填零。事件源表保存逐次成交原因和时间精度。

必要核验包括全部434决策日的独立条件复算、434点75日前缀输入裁剪等价、433点下一日扰动（末日没有未来），另在5个固定分段起点做完整前缀和全部未来数据扰动；各期限434条买入事实与EX015对齐；旧h1/h3闭合标签对齐；费用及分段金额恒等式；9项统计和全部固定分段核验；非重叠上限独立动态规划；原117个候选登记哈希不变。原计划逐点全历史重复解析分钟柱耗时较高，未完成的初次核验已停止，改用上述有限依赖检查，见[实际核验范围](others/verification_scope_note.json)，不声称完成434点全历史扰动。详情见[主核验](others/audit.json)、[汇总核验](others/summary_audit.json)及[串并行检查](others/execution_checks.json)。未执行仓库全量回归或完整策略资格检验。

执行源码初次发布后、任何事件计算前，仅补齐成交原因及时间精度字段；初版和实际执行版均保留正式引用，见[留证字段补充](protocols/source_metadata_supplement.json)。固定分段完整对照和频率上限由已有事件汇总，不重跑标签、不追加新策略或调参。

本轮正式阶段交付为COMPONENTS/8，继承COMPONENTS/7原13条记录并追加3条条件用途记录、9项检验，总计16条记录；累计检验口径67+9=76，相关且共享数据，不是76份独立证据。没有新增已确认有效组件或合格候选。技术发布PASS仅支持材料身份与一致性。

Git保存研究源码、报告及引用；正式证据assets/evidence/EX026_20261023和交付assets/deliveries/COMPONENTS/8须独立保留。复用同工作段已认证概览，核对本轮增量及登记；未重新执行旧全量自检。没有合并master、推送、tag或生产变更。
'''
    (HERE/'report.md').write_text(text,encoding='utf-8',newline='\n')
    appendix = '# 固定时间分段与压力重合对照\n\n全部为已有事件聚合，不是新实验或连续账户。位置区间左含右不含；空组标为不可计算。\n'
    for h,z in s['horizons'].items():
        appendix+=f'\n## h={h}\n\n| 位置 | 对照组 | 事件数 | 平均净收益 | 正金额/元 | 负金额/元 |\n| --- | --- | ---: | ---: | ---: | ---: |\n'
        for period,v in z['periods'].items():
            groups={'all':v['all']}
            groups.update({f'{k}_{which}':st for k,pair in v['groups'].items() for which,st in pair.items()})
            groups.update({f'Bcompare_{k}':st for k,st in v['B_increment'].items()})
            groups.update({f'{p}_{k}':st for p,cells in v['C_pressure_cells'].items() for k,st in cells.items()})
            for name,a in groups.items():
                money=lambda key: f'{a[key]:.2f}' if key in a else '不可计算'
                appendix+=f"| {period} | {name} | {a['n']} | {pct(a.get('net_mean_return'))} | {money('positive_yuan')} | {money('negative_yuan')} |\n"
    (HERE/'others/temporal_controls.md').write_text(appendix,encoding='utf-8',newline='\n')
    return text


def publish():
    assert not (HERE/'others/delivery_validation.json').exists()
    assert read(HERE/'others/audit.json')['status'] == 'PASS'
    assert read(HERE/'others/summary_audit.json')['status'] == 'PASS'
    text = report()
    protocols=read(HERE/'others/protocol_refs.json')
    refs=[EvidenceRef.from_dict(v) for v in protocols.values()]+list(sources().values())
    materials={}
    for folder in ('src','others'):
        for p in sorted((HERE/folder).iterdir()):
            if p.suffix not in ('.py','.csv','.json','.md') or p.name in ('protocol_refs.json',):
                continue
            ref=material(p); refs.append(ref); materials[p.name]=ref.to_dict()
    refs=list(dict.fromkeys(refs))
    report_ref=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)))
    refs.append(report_ref)
    save(HERE/'others/published_refs.json',{'references':[v.to_dict() for v in refs]})
    receipt=read(ROOT/'research/S015/deliveries/COMPONENTS/7/receipt.json')
    path=ROOT/'research/S015/assets/deliveries/COMPONENTS/7/delivery.json'
    assert sha256(path.read_bytes()).hexdigest()==next(v['sha256'] for v in receipt['files'] if v['path']=='delivery.json')
    panel=d.ComponentPanel.from_dict(read(path)['content']['payload'])
    assert len(panel.components)==13
    source=EvidenceRef.from_dict(protocols['study.py'])
    protocol=EvidenceRef.from_dict(protocols['fixed_mechanisms.json'])
    evidence=tuple(EvidenceRef.from_dict(materials[n]) for n in ('results.json','supplement.json','audit.json','summary_audit.json'))
    entries=[]
    for name in NAMES:
        tests=[]
        for h in (1,3,5):
            state=d.ComponentTestStatus.INEFFECTIVE if h==1 or name=='C' else d.ComponentTestStatus.INSUFFICIENT_DATA
            explanation=('本用途未支持净收益及相对机会改善；保留所有负面结果。' if state==d.ComponentTestStatus.INEFFECTIVE else
                '已有条件性正收益线索，但可用性证据不足；时间差异与重叠样本明显，频率可行性另按原要求报告。')
            tests.append(d.ComponentTestResult(f'ex026-{name}-h{h}',EX.experiment_id,protocol,state,explanation,evidence))
        entries.append(d.ComponentEntry(f'continuation_{name.lower()}_ex026',d.ExperimentDefinitionRef(source,'features'),
            f'{NAMES[name]}的延续用途；同一机制族的固定条件，不是独立信息来源',
            '独立10万元事件，T+1限价买、T+h+1起市场卖，实际双边费用后的损益',
            'h=1/3/5；未成交与未退出单列','全机会/条件外；B对A非B；C对正压力四格',
            '只用T日及以前行情；历史供应商17:30可得未认证','信号使用未复权量价，执行HFQ_RESEARCH及原1%合同',
            '159326.SZ原434日已见开发池；事件重叠，不能替代账户验收',
            '线索或负面结果，当前不推荐直接进入阶段三；保持新目标合格候选0。',tuple(tests)))
    final=d.ComponentPanel((*panel.components,*entries),'独立延续机制固定诊断完成：3条件9检验；B较长期有条件性线索但固定形式频率不相容，未新增已确认有效组件，当前合格候选0。')
    adapted=text.replace('](protocols/',f'](../../../experiments/{EX.experiment_id}/protocols/').replace('](others/',f'](../../../experiments/{EX.experiment_id}/others/')
    adapted=adapted.replace('](../../deliveries/','](../../').replace('](../../materials/','](../../../materials/').replace('](../EX013_','](../../../experiments/EX013_')
    repo=RepositoryContext.discover(ROOT)
    assembled=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.COMPONENTS,8,(d.DeliveryReference.from_dict(receipt['reference']),)),
        d.DeliveryContent(final,d.DeliveryStatus.COMPLETE,(),(),report=adapted,evidence=tuple(refs)))
    assert assembled.validation.status.value=='PASS',assembled.validation.issues
    check=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status.value=='PASS',check.issues
    save(HERE/'others/delivery_validation.json',{'delivery':assembled.receipt.reference.to_dict(),'assembly_validation':assembled.validation.to_dict(),
        'experiment_publication':check.to_dict(),'report':report_ref.to_dict(),'materials':materials})
    intent=dict(read(ROOT/'research/registrations/S015/family.json')['research_intent'])
    previous_budget=intent['experiment_budget']
    intent.update(current_components=assembled.receipt.reference.to_dict(),current_experiment=EX.to_dict(),selected_candidate=None,
        qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,
        current_phase='阶段二延续机制诊断1/1完成：存在有限线索，未确认有效组件，当前目标合格候选0',
        experiment_budget={'authorized':1,'completed':1,'remaining':0,'source':protocol.to_dict()},
        previous_experiment_budget=previous_budget,
        proposal_path='research/S015/materials/mechanism_reorientation_20261023.md',
        next_gate='暂不进入阶段三；先评审趋势持续状态的新机制方案及范围，不自动新增实验、降低频率目标、冻结或PTE')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='用户批准1轮固定延续机制诊断已完成；正式交付全部9项及频率反证，新目标合格候选明确为0。')
    print({'delivery':'COMPONENTS/8','assembly':assembled.validation.status.value,'report':check.status.value,'qualified':0,'remaining':0},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('report','publish'))
    {'report':report,'publish':publish}[p.parse_args().mode]()
