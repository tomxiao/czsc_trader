"""Publish fixed price-path findings, preserving unsuccessful and uncertain uses."""
import argparse
from hashlib import sha256
import pandas as pd
from study import ROOT,HERE,EX,read,save,context,material
from czsc_trader.application import RepositoryContext,publish_evidence,assemble_delivery,validate_experiment,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope,ResearchBatchRef
from czsc_trader.research_tools import delivery as d

def pct(v):return '不可计算' if v is None else f'{100*v:.4f}%'
def ci(v):return '不可计算' if v is None else '['+', '.join(pct(x) for x in v)+']'
def report():
    r=read(HERE/'others/results.json');x=pd.read_csv(HERE/'others/features.csv');g=pd.read_csv(HERE/'others/labeled_events.csv')
    ret=g[g.label_key.eq('net_h5')&g.retest&g.status.eq('CLOSED')]
    desc={'scope':'仅对固定样本的时段、集中性和确认前价格变化做事后描述；没有新分组、标签、模型或参数搜索。',
      'retest_h5_periods':{str(k):{'n':len(z),'mean_return':float(z.net.mean()/100000),'net_yuan':float(z.net.sum())} for k,z in ret.groupby('period')},
      'retest_h5_top1_positive_fraction':float(ret.net.max()/ret.net.clip(lower=0).sum()),
      'confirmation_mean_change':{str(k):float(z.confirmation_change.mean()) for k,z in x[x.anchor].groupby('accepted')}}
    save(HERE/'others/descriptive_summary.json',desc)
    text='''# S015 价格路径固定对照：站稳确认未改善入场，结构退出损害后续收益

Status: COMPLETED

用户批准的1轮阶段二固定对照EX034已完成，额度1/1、余额0。本轮没有新增有充分证据支持的可交易组件，当前合格候选、待选型和待冻结均为0。已完成本轮诊断目标，产出合格策略的总体目标尚未达成。

主假设“突破后被接受，比跌回区间有更好的后续可交易空间”在这套固定定义下不获支持。回踩再启动的5日子集保留正向线索，但短期限不佳、机会稀少，不能升级为已确认有效组件。结构失效退出也未改善同事件收益。结果限于本次定义、原执行条件和已见开发池，不否定所有价格行为方法，更不证明反向买入跌回事件就能达标。

## 授权、时序和固定方法

沿用MANDATE/3、159326.SZ、2024-09-09起75日预热及2025-01-02至2026-10-21共434日开发池。415日比较窗仍为2025-02-06至2026-10-21，净收益必须严格超过91.5802915%、最大回撤严格低于7.2486637491%；434日收益、回撤、双频率、32点扰动及费用压力标准全部保持。没有新外部源、刷新数据、连续账户、参数搜索或阶段推进。本轮原434日内的分组和时间段均已参与开发，不能称独立验证。

在计算条件与结果前发布[固定协议](protocols/price_path.json)和[src/study.py](src/study.py)。现有分支沿用已授权范围。与EX026不同，本轮用此前20日最高价边界，并观察突破后的两天路径；不是只测当日突破，也没有把先前失败结果改名重新宣称成功。

- b日收盘价严格超过此前20日最高价U；U在b日形成后固定，不随后续行情移动。
- 统一在T=b+2日观察结束。b+1和b+2收盘都高于U为“站稳”，任一次低于或等于U为“跌回”。T+1才尝试买入，两组等待时间相同。
- 次级“回踩再启动”要求站稳，并且两天最低价触及U上方0.25个事前ATR以内，T收盘高于前一天。ATR是此前20日真实波幅均值，用于把触及距离换算成通常日波动；不使用未来确认拐点。
- 独立10万元事件复用EX026公共TXE标签：原1%限价买、T+h决定次日市场卖、双侧0.1%费、原tick/lot/限价保护、HFQ_RESEARCH及DAILY_RANGE_V3。主期限h3，h1/h5为事前固定诊断；入场日只用唯一h1的成交后收盘损益并扣买入费。
- 结构退出仅比较站稳事件：买入日收盘起，首次收盘跌至U或以下，则次日市场退出；最长T+5决定退出。5日是退出决策期限，实际卖出受原市场单重试规则约束，可能更晚。没有入场当天即时止损。h2/h4仅补齐事件退出标签，与同事件h5配对。

历史调整价版本与17:30供应商可得性未认证；撮合为日区间模型，不含成交容量。两个相邻突破可能属于同一行情，事件相互重叠；金额、均值和频率上界都不是连续账户收益、回撤或真实交易频率。

## 实际成交后是否还有空间

434日中共有42个突破锚点：站稳28个、跌回14个；各有1个次日限价未成交，实际可比较为27与13。回踩子集14个、成交13个。上述选中事件全部完成退出，没有右截尾被悄悄当作零收益。全434日标签中的未成交与末端截尾仍保留原状态。

下表为每个独立事件相对初始10万元的平均净收益。完整事件扣双侧费用；入场日仅扣买入费，不能与完整交易混称。

| 标签 | 站稳27个 | 跌回13个 | 站稳减跌回 | 相近背景匹配后差 |
| --- | ---: | ---: | ---: | ---: |
'''
    names={'net_h1':'1日完整事件','net_h3':'3日完整事件（主）','net_h5':'5日完整事件','entry_net_h1':'入场当天'}
    for k,v in r['targets'].items():
        a=v['acceptance'];text+=f"| {names[k]} | {pct(a['in']['mean_return'])} | {pct(a['out']['mean_return'])} | {pct(a['delta'])} | {pct(v['matched']['delta'])} |\n"
    text+='''
四个标签的站稳组均低于跌回组；主3日差为−1.1542个百分点，匹配后仍为−1.1457个百分点。匹配为同一固定时期内，过去5日涨幅相差不超过5个百分点、20日日收益波动率比在0.5—2之间，再按预声明距离找最近跌回对照，允许复用。27个站稳事件中23个有对照，仅10个独立跌回事件被使用，4个未匹配事件不能外推。

匹配不是严格因果控制：匹配后站稳组过去5日收益仍高1.5365个百分点、日波动率低0.2623个百分点，确认阶段涨幅高1.9020个百分点，突破幅度相差−0.0261个ATR。不能说已经排除了所有行情背景。各时间段结果不一致，首尾两段都各只有1对成交事件。

站稳组在两天确认期平均已经上涨1.2177%，跌回组平均下跌1.8163%；这些变化发生在研究入场决定之前，不是可获得收益。本轮没有构建“同一次突破立即入场”账户，因此不能单凭此事实断言全部劣势都是等待确认造成。

## 能否识别入场当天亏损，会错过多少盈利

把“跌回”当作应避开的信号，以全部40个可成交突破事件为比较集合：

| 标签 | 被排除事件数 | 其中亏损/盈利笔数 | 识别亏损金额占比 | 错过盈利金额占比 |
| --- | ---: | ---: | ---: | ---: |
'''
    for k in ('entry_net_h1','net_h3'):
        a=r['targets'][k]['acceptance'];b=a['out']
        text+=f"| {names[k]} | {b['n']} | {b['negative_n']}/{b['positive_n']} | {pct(a['rejected_loss_fraction'])} | {pct(a['missed_profit_fraction'])} |\n"
    text+='''
入场当天只识别18.6775%的亏损金额，却遗漏35.7781%的盈利金额；按笔数是识别6/21笔亏损、错过7/19笔盈利。保留下来的站稳组仍有15笔入场日亏损、12笔盈利，平均入场日净收益−0.1961%。这不能支持把“站稳确认”用作有效的入场日亏损过滤器。

主3日完整事件只识别17.2339%的亏损金额，却遗漏39.4419%的盈利金额。不能将这些事件金额称作账户实际可避免或必然错过的损益，因为独立事件重叠、取消交易会改变后续资金和持仓路径。

若把分母扩大到全434日所有可成交机会，仅选站稳会遗漏95.1404%的入场日盈利金额；虽然同时排除92.4396%的亏损金额，但主要因为只留下27个事件。这与上述“同类突破内部是否有辨别力”是不同问题，不能用高排除比例包装预测能力。

## 回踩再启动与结构退出

| 标签 | 回踩13个 | 站稳但非回踩14个 | 回踩减非回踩 |
| --- | ---: | ---: | ---: |
'''
    for k,v in r['targets'].items():
        a=v['retest'];text+=f"| {names[k]} | {pct(a['in']['mean_return'])} | {pct(a['out']['mean_return'])} | {pct(a['delta'])} |\n"
    text+='''
回踩子集5日平均净收益+1.4079%，相对非回踩高1.6644个百分点，是应保留的正向线索；但1日为−0.7593%，3日仅+0.1110%，入场当天−0.3359%，没有改善短期入场风险。5日共7赢6亏，最大盈利事件占全部正盈利21.1275%；固定五段样本数为1/3/4/5/0，净金额分别−979.88/+7896.46/+11433.27/−46.76/无样本。它不是单个交易独占，但时段与样本覆盖明显有限。

站稳事件用“跌回边界则次日退出、最长5日”的结构退出，27个相同成交事件平均净收益从固定5日的+0.5449%降至−0.3822%，每事件减少0.9271个百分点。12个事件提前退出，其中2个改善、10个变差。它在本轮已实现样本中没有增加收益，不能因名称是“结构止损”就假设有保护作用。此处没有连续账户，无法据此证明账户回撤变大或变小。

## 机会数量与原频率要求

每个完整滚动60日窗口内，按实际入场/退出日期求互不重叠事件的最大数量；允许同日卖后买，因此这是比实际策略宽松的上界。不同窗口可以选不同事件，不代表存在同一个策略同时达到全部上界。

| 选择/退出标签 | 最大可闭合数中位数 | 至少3笔的窗口数/375 | 原频率是否仍可能通过此上界 |
| --- | ---: | ---: | --- |
'''
    for k,z in r['frequency'].items():
        for m,a in z.items():text+=f"| {m}/{k} | {a['max_nonoverlap_median']:.0f} | {a['windows_at_least3']}/375 | {'尚未排除，非实际通过' if a['not_ruled_out_by_bound'] else '本固定事件集合已不足'} |\n"
    text+='''
原标准为中位数至少6笔，且至少338/375个窗口有3笔。连包含站稳和跌回的全部突破事件，在最短h1口径下也只有263/375个窗口达到3笔；站稳h3中位数上界3笔、228/375，回踩h5只有1笔、63/375。这个稀疏事件集合不能单独承担原频率目标。结论仅针对固定入场与退出标签；不同的机会生成机制须另行研究，不能用反复拆单或放宽目标补足。

## 不确定性与组件判断

以下为完整434日轴上20交易日块重抽样499次的探索性95%区间，未校正历史选择和多项比较，不作为新增经济硬门。

| 对比 | 区间（收益率差） |
| --- | --- |
'''
    for k,v in r['targets'].items():
        text+=f"| 站稳−跌回/{names[k]} | {ci(v['acceptance_bootstrap']['ci95'])} |\n"
        text+=f"| 回踩−非回踩/{names[k]} | {ci(v['retest_bootstrap']['ci95'])} |\n"
    text+=f"| 结构退出−固定5日 | {ci(r['structure']['bootstrap']['ci95'])} |\n"
    text+='''
COMPONENTS/11继承23条历史记录并新增3条用途记录，总计26条；新增8项站稳对比（4个原始、4个匹配）、4项回踩对比、1项结构退出对比，共13项相关检验，历史156+13=169。组件记录数与检验数不代表独立信息数量。

- 站稳确认：本固定表达的后续收益优势与入场日过滤用途INEFFECTIVE，限定于本次检验，不声称已证明所有总体效应为零。
- 回踩再启动：1/3日及入场日用途INEFFECTIVE；5日用途INSUFFICIENT_DATA，保留正向观察，但不足以确认可交易增量。样本不足指支持范围与独立性不足，不是遗漏已有数据。
- 结构退出：本固定表达改善事件净收益的用途INEFFECTIVE。没有回撤账户证据。

本轮没有新增SUPPORTED组件。此前中期份额状态有限预测辅助结论与其交易原型失败均保留；候选集合CANDIDATES/4不改写，合格策略仍为0。

## 验证、交付及下一步

主脚本通过434日前缀特征核对；对42个锚点在h1/h3/h5共126条历史事件逐字段复算；新增h2/h4共84条事件仅服务结构退出。独立审计通过33,554项核对：434日标量特征、全部1,386条新旧事件的公共TXE执行和损益、28条结构退出、全部分组与匹配、9×499次重抽样，以及用动态规划核验11×375个频率上界窗口。详见[审计证据](others/independent_audit.json)。审计仍共用公共执行引擎与认证数据加载器，没有独立验证引擎内部。正式发布验证只证明材料身份与技术契约，不代表策略合格。没有仓库级回归、完整账户或稳健性验收。

建议停止把这套“20日突破加两天确认”推进为策略，也不围绕20/2/0.25做邻近参数寻优。价格行为路线可以继续，但优先问题应转为：在覆盖多数交易日的固定观察窗口里，同等涨跌幅下，30分钟路径的持续推进与反复回吐是否提供次日仍可兑现的信息。现有八根30分钟行情允许提出这一新问题，但EX026尾盘延续已失败，下一方案必须检验完整路径的增量，不能重复尾盘同向条件。

该下一问题只是建议，尚未执行或预支实验额度。也不因本轮跌回组均值更高就立即转向买跌回，否则容易重新落回S011反弹机制。先取得新的组件证据再讨论阶段三；不建议将13个回踩事件的5日正均值直接升级为策略。

已完成本轮授权任务，1轮额度已用完。未新增账户、候选、外部数据、平台修改、合并master、推送、tag、冻结或PTE/生产操作。成果依赖既有DFLS数据资产及正式证据，Git不替代资产备份。

明细见[全部结果](others/results.json)、[事件表](others/labeled_events.csv)、[结构退出配对](others/exit_pairs.csv)、[固定特征](others/features.csv)、[核对](others/checks.json)、[描述性分解](others/descriptive_summary.json)。
'''
    (HERE/'report.md').write_text(text,encoding='utf-8',newline='\n')

def publish():
    assert not (HERE/'others/delivery_validation.json').exists()
    assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    report();refs=[];materials={};inp=read(HERE/'others/input_refs.json')
    for value in [inp['prior_source'],inp['prior_labels'],*inp['source_inputs'].values()]:refs.append(EvidenceRef.from_dict(value))
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    refs=list(dict.fromkeys(refs))
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)));refs.append(rr)
    repo=RepositoryContext.discover(ROOT)
    check=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert check.status.value=='PASS',check.issues
    receipt=read(ROOT/'research/S015/deliveries/COMPONENTS/10/receipt.json');p=ROOT/'research/S015/assets/deliveries/COMPONENTS/10/delivery.json'
    assert sha256(p.read_bytes()).hexdigest()==next(v['sha256'] for v in receipt['files'] if v['path']=='delivery.json')
    old=d.ComponentPanel.from_dict(read(p)['content']['payload']);assert len(old.components)==23
    assert sum(len(c.tests) for c in old.components)==156
    frozen=read(HERE/'others/protocol_refs.json');src=EvidenceRef.from_dict(frozen['study.py']);proto=EvidenceRef.from_dict(frozen['price_path.json'])
    evidence=tuple(EvidenceRef.from_dict(materials[f'others/{name}']) for name in ('results.json','independent_audit.json','checks.json','descriptive_summary.json'))
    entries=[]
    for name in ('acceptance','retest','structure'):
        tests=[]
        labels=['net_h1','net_h3','net_h5','entry_net_h1'] if name!='structure' else ['paired_h5']
        methods=['raw','matched'] if name=='acceptance' else ['raw']
        for label in labels:
            for method in methods:
                uncertain=name=='retest' and label=='net_h5'
                tests.append(d.ComponentTestResult(f'price-path-{name}-{label}-{method}',EX.experiment_id,proto,
                  d.ComponentTestStatus.INSUFFICIENT_DATA if uncertain else d.ComponentTestStatus.INEFFECTIVE,
                  '5日回踩有正向观察，但只有13成交事件且覆盖不足；尚不支持可交易有效，不新增统计硬门。' if uncertain else '本次固定用途的组间收益差为负或结构退出降低事件净收益；不推广为所有价格行为无效，不声称账户回撤结果。',evidence))
        entries.append(d.ComponentEntry(f'price_path_{name}_ex034',d.ExperimentDefinitionRef(src,'features' if name!='structure' else 'run'),
          {'acceptance':'突破两天站稳确认的后续收益/入场风险用途','retest':'回踩后再启动的延续用途','structure':'收盘跌回固定边界、次日退出的收益用途'}[name],
          '公共TXE独立10万元事件净收益及唯一入场日净损益','h3主、h1/h5和入场日次；结构最长5日',
          '同等待期跌回组/相近时期涨幅波动匹配；回踩比非回踩；结构与同事件h5配对',
          '只用T及以前OHLC，T+1买；失效当日收盘决定次日卖；原数据历史发布修订未认证',
          'HFQ_RESEARCH，原1%限价、双侧0.1%费，既有认证数据与公共TXE',
          '已见434日、相关且稀疏事件，非连续账户；不变更原频率或双窗口经济门槛',
          '无新增SUPPORTED；回踩5日保留待证线索，所有固定事件集合频率上界不足，资格0',tuple(tests)))
    panel=d.ComponentPanel((*old.components,*entries),'EX034完成：站稳确认及结构退出用途不获支持；回踩5日正向线索不足以确认交易有效，无新增SUPPORTED或合格策略。')
    txt=(HERE/'report.md').read_text(encoding='utf-8')
    for sub in ('src','protocols','others'):txt=txt.replace(f']({sub}/',f'](../../../experiments/{HERE.name}/{sub}/')
    assembled=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.COMPONENTS,11,(d.DeliveryReference.from_dict(receipt['reference']),)),d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=txt,evidence=tuple(refs)))
    assert assembled.validation.status.value=='PASS',assembled.validation.issues
    save(HERE/'others/delivery_validation.json',{'delivery':assembled.receipt.reference.to_dict(),'assembly':assembled.validation.to_dict(),'experiment':check.to_dict(),'report':rr.to_dict(),'materials':materials})
    intent=read(ROOT/'research/registrations/S015/family.json')['research_intent']
    intent.update(current_components=assembled.receipt.reference.to_dict(),current_experiment=EX.to_dict(),
      experiment_budget={'authorized':1,'completed':1,'remaining':0,'source':proto.to_dict()},
      current_phase='阶段二价格路径固定对照完成：站稳与结构退出未获支持，回踩5日有限线索，合格候选0',
      qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,
      next_gate='本轮额度0；不推进阶段三。可另议覆盖多数交易日的30分钟完整路径增量诊断，区别于已失败尾盘同向，未经批准不执行。')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='已执行用户批准的1轮价格行为阶段二对照；完整保留负面证据与回踩5日待证线索，无新增有效组件或合格候选。')
    print({'delivery':'COMPONENTS/11','experiment':check.status.value,'assembly':assembled.validation.status.value,'components':26,'tests':169,'qualified':0,'budget_remaining':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['report','publish']);{'report':report,'publish':publish}[p.parse_args().mode]()
