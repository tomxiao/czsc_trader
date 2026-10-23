"""Publish the completed funding rounds and preserve the current zero-candidate state."""
from hashlib import sha256
import argparse
from funding_study import ROOT,BASE,HOME,FEATURES,SEGMENTS,read,save,folder,ctx,material
from czsc_trader.application import RepositoryContext,publish_evidence,validate_experiment,assemble_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import EvidenceRef,ExperimentRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope,ResearchBatchRef
from czsc_trader.research_tools import delivery as d

def pct(x):return '不可计算' if x is None else f'{100*x:.4f}%'
def heading(title):
    return f'# {title}\n\nStatus: COMPLETED\n\n'
def report_all():
    survey=read(HOME/'others/survey_results.json');r2=read(folder(2)/'others/results.json');r3=read(folder(3)/'others/results.json');r4=read(folder(4)/'others/results.json');r5=read(folder(5)/'others/results.json')
    text=heading('S015 五轮资金信息研究：发现中期份额状态线索，尚未形成可用组件')
    text+='''本批用户授权5轮，EX027—EX031全部完成，余额0。阶段二信息与组件诊断目标完成；产出合格策略的总体目标尚未达成。新目标下合格候选仍为0，待选型与待冻结均为0。没有新增已确认有效组件、连续策略账户、参数搜索或候选登记。

事前先固定[五轮协议](../EX027_20261023/protocols/funding_five_rounds.json)，再查询资金数据、执行竞争假设检验。原434日开发池、415日比较窗及MANDATE/3全部目标不变。434日原收益、回撤、频率、32点扰动及费用压力要求仍适用；415日净收益必须严格超过91.5802915%，最大回撤严格低于7.2486637491%。本轮没有账户，因此没有进行这些资格验收，事件收益不能替代它们。

## 五轮问题与回答

| 轮次 | 问题 | 实际回答 |
| --- | --- | --- |
| EX027 | 资金数据可用吗？ | 自身ETF份额可作有发布时间假设的研究输入；历史发布修订未认证。同指数历史对照和融资正式输入未具备。 |
| EX028 | 份额增长是否对应可参与收益？ | 20日份额正增长有较强全期分组差；1/5日和持续性证据较弱。分组关联尚未证明独立信息。 |
| EX029 | 追涨、逆势配置还是同类搬家？ | 5日份额增长配合价格上涨的短期表现好于配合下跌；不能解释为普遍的下跌后资金抄底。产品搬家仍未知。 |
| EX030 | 加入资金能否改善量价预测？ | 固定模型的3个持有期限及入场日标签，整体误差全部增大。单变量关联未被本模型兑现为预测增量。 |
| EX031 | 延迟、极端值与亏损过滤反证？ | 延迟2/3日后中期份额分组线索仍在；预测误差仍全部恶化，入场亏损过滤损益取舍不稳定。 |

## 信息普查与准入边界

新增来源为同一Tushare的ETF份额信息和固定元数据探测，未读取其他研究批次。正式统计只使用现有DFLS ETF_SHARE_SIZE契约的Date、TotalShare；原ETF量价和事件标签按身份复用。原准备要求509条失败，供应商覆盖探测定位到仅缺上市首日2024-09-09；在收益关联计算前发布[范围修正](../EX027_20261023/protocols/coverage_resolution.json)，改为2024-09-10至2026-10-21的严格508条请求并READY。74个份额预热日足够20日回看加3日延迟，434个开发日特征缺失0。没有填零、前向填充或绕过DFLS失败。

份额单位万份，不能当作实际现金流金额。164次相邻记录不变、343次变化；最大单日份额增幅约52.87%。没有因变化大就自动修正或删除，历史份额拆分/口径修订还未取得独立证明。当前目录返回159326.SZ跟踪931994.CSI，以及尚无上市日期、状态P的562720.SH；不能由当前目录证明历史只有这一只产品，也没有可用同指数对照篮子。

融资明细在固定2025-02-06探测为空，2026-10-21有记录。它仅证明两个日期的响应，不能据此认定首日不可融资或全期覆盖；现有DFLS没有融资明细契约，本轮未将其作为正式标签解释输入。NAV/规模/折溢价不在现有份额适配器输出中，订单大小划分的买卖统计也不能自动等同新增资金或机构资金。因此这5轮检验的是ETF份额变化，不是全部“资金面”。

份额可得时间采用供应商及DFLS声明的下一交易日上午08:30假设。T日17:30只使用T−1及以前的份额记录；另检验T−2/T−3。没有历史逐笔发布时间和修订版本，延迟敏感性不能替代历史时点认证。官方接口说明：[ETF份额](https://tushare.pro/document/2?doc_id=408)、[ETF目录](https://tushare.pro/document/2?doc_id=385)、[融资明细](https://tushare.pro/document/2?doc_id=59)。申购可包含证券篮子，套利也会增加份额，因而“份额增加=看多现金进入”不成立，见[交易所ETF问答](https://www.sse.com.cn/assortment/fund/etf/question/)与[套利机制](https://etf.sse.com.cn/fund/learning/strategy/c/5704303.shtml)。

## 固定定义与收益标签

f1/f5/f20分别为当时已知的1/5/20交易日份额增长率；persist5为最近5次份额变化中增长次数占比减0.5。persist5小于0表示增长日不占多数，含份额不变日，不能称为净赎回。四项来自同一条份额序列，不是四种独立信息。全部按正、负、零分组，不按收益调阈值。

复用EX026已认证1302个日—期限事件，h=1/3/5闭合分别425/423/421。每个独立事件10万元，T+1原收盘上方1%限价买，T+h+1起市场卖，使用原HFQ_RESEARCH和TXE成交事实，双边0.1%费用。未成交、无下一日、未退出单列，退出不强制。重叠事件不是一个可执行资金账户，金额加总仅用于归因。入场日净损益=入场日收盘毛损益−买入费，未扣将来卖出费，不是完整交易净收益。

## 主口径全部12项条件结果

下表是每个独立事件净损益/10万元的均值；正/负/零指特征取值，非事件盈亏。

| 特征/h | 正组n | 正组均值 | 负组n | 负组均值 | 零组n | 零组均值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for h,z in r2.items():
        for f,a in z.items():
            p,n,v=(a['groups'][s] for s in ('positive','negative','zero'))
            text+=f"| {f}/{h} | {p['n']} | {pct(p['mean_return'])} | {n['n']} | {pct(n['mean_return'])} | {v['n']} | {pct(v['mean_return'])} |\n"
    text+='''
20日份额增长正组217个闭合事件在h=3/5均值约0.6374%/1.1701%，负组约−0.5197%/−0.7411%。h=5正组捕获全部事件正金额67.81%，承担负金额36.84%，遗漏正金额32.19%；这不是可实现账户收益。h=5正组入场日毛损益82212.50元、后续毛损益214835.70元，存在入场后继续收益的线索。

其全期分组差不能直接解释为“资金带来独立优势”：第184—267位置段全部84个决策日都在f20正组，没有同段负组反事实；后一个时间段正组表现反而弱于负组。固定分段及所有定义的完整正反证见[时段明细](../EX031_20261023/others/period_tables.md)。最后一段f20/h5正组24事件均值0.4594%，负组51事件−4.2491%，全期差异包含市场时段差异。

## 价格与份额四格

下表限定5日份额变化与信号日过去5日价格方向。零变化/平价格完整保留在结构化结果中，不并入负组。

| 5日份额/价格 | h1 n/均值 | h3 n/均值 | h5 n/均值 |
| --- | ---: | ---: | ---: |
'''
    for key in ('positive_up','positive_down','negative_up','negative_down'):
        text+=f'| {key} | '+' | '.join(f"{r3[h]['cells'][key]['n']} / {pct(r3[h]['cells'][key]['mean_return'])}" for h in ('1','3','5'))+' |\n'
    text+='''
份额增长且价格上涨有较好的条件表现；份额增长但价格下跌在h1/h3均负，h5才正。零份额变化且价格上涨的h5均值还高于增长且上涨组，样本不同，不能把分组差直接归因为份额增长。这弱化了“看到申购就抄底”的简单解释，但不能确证持续需求驱动，也尚未排除申赎套利。

## 量价之外的前推预测增量

固定基线为r1/r5/vol20/pressure/range20；资金模型一次加入f1/f5/f20/persist5。Ridge alpha=10，训练期标准化，4个固定测试段，训练收益标签实际结束日严格早于测试首日。前推指时间顺序训练和预测；全部仍在已见开发池，不是新独立样本。入场日只用一个不重复标签，另有三个完整交易标签。

下表“误差增加”越大越差，使用均方误差；不是收益损失百分比。

| 标签 | 预测n | T−1误差增加 | T−2误差增加 | T−3误差增加 |
| --- | ---: | ---: | ---: | ---: |
'''
    for key,a in r4.items():
        text+=f"| {key} | {a['n']} | {pct(-a['relative_mse_gain'])} | {pct(-r5['2']['models'][key]['relative_mse_gain'])} | {pct(-r5['3']['models'][key]['relative_mse_gain'])} |\n"
    text+='''
12项整体比较全部恶化。主口径入场日模型四个测试段均恶化；完整交易h1/h3也四段均恶化，h5仅末段有小幅改善。去掉绝对标签最大的5个事件、各段误差和成对块抽样区间全部保留，没有用删样本结果替代原结果。

独立审查发现资金变量有明显训练外推：第三固定时间段f20最高约730.5%，而该段前的训练数据最高约77%。标准化线性模型可能把极端份额扩张外推成过大的收益预测。这是可观察的失败机制之一；“这个固定模型没有利用好资金”不能推出“资金没有价值”，也不能反向宣称换模型必能成功。单变量f20全期分组较强、线性联合模型失败，是下一步需区分的竞争解释。

## 能识别入场当天亏损吗，错过多少盈利？

仅在入场日净损益的326个前推事件上，把预测值小于0视为建议避开；阈值事前固定，不是已执行账户。亏损金额与盈利金额分别作分母。预测为负中实际盈利的事件即误拒。

| 模型/资金延迟 | 建议避开n | 其中亏损/盈利n | 识别亏损金额占比 | 错过盈利金额占比 |
| --- | ---: | ---: | ---: | ---: |
'''
    for name,a in [('量价基线',r4['entry_net_h1']['filters']['base']),('资金T−1',r4['entry_net_h1']['filters']['fund']),('资金T−2',r5['2']['models']['entry_net_h1']['filters']['fund']),('资金T−3',r5['3']['models']['entry_net_h1']['filters']['fund'])]:
        text+=f"| {name} | {a['reject_n']} | {a['rejected_negative_n']}/{a['rejected_positive_n']} | {pct(a['caught_negative_fraction'])} | {pct(a['missed_positive_fraction'])} |\n"
    text+='''
主口径资金模型避开124个事件，其中70个实际亏损、54个实际盈利；捕获亏损83071.16元，遗漏盈利52330.43元。相对量价模型，它少错过盈利，但也少识别亏损；两者避开事件数量不同，不能宣称固定参与率下的识别优势。没有从旧账户扣除这些金额再冒充反事实收益。

结论是：本轮有一定亏损区分现象，但尚未证明能稳定改进入场日亏损识别。入场日总体预测误差增大10.09%，延迟敏感性更差，不推荐直接部署为亏损过滤器。

## 延迟反证与不确定性

| 延迟/期限 | f20正组均值 | f20负组均值 | 正减负20日块95%区间 |
| --- | ---: | ---: | --- |
'''
    for lag,rows in [(1,r2),(2,r5['2']['conditions']),(3,r5['3']['conditions'])]:
        for h,z in rows.items():
            a=z['f20'];ci=a['bootstrap']['positive_minus_negative_ci95']
            text+=f"| T−{lag}/h{h} | {pct(a['groups']['positive']['mean_return'])} | {pct(a['groups']['negative']['mean_return'])} | [{pct(ci[0])}, {pct(ci[1])}] |\n"
    text+='''
长一些的事件标签中，f20组间差对额外延迟仍保持正方向，支持保留中期状态线索。499次20日块抽样是在完整434日轴上先抽样再筛选，保持缺失/未闭合状态；区间是探索性描述，未校正多项与历史选择，不是新的资格硬门，也不消除趋势时段混杂。

## 交付、核验及下一步

正式交付COMPONENTS/9继承COMPONENTS/8的16条记录，新增4个份额定义和1个联合模型用途，共21条；新增36项条件检验及12项模型比较，共48项相关检验。历史76+48=124项的计数不是独立信息数量。价格/份额四格是3套描述表，单列、不冒充独立组件。融资及同类篮子未接入，不计成功资金特征。

4个份额组件均记录INSUFFICIENT_DATA，指独立可用性证据不足，不指开发期缺行；联合模型用途记录INEFFECTIVE，严格限定为本固定alpha和连续资金特征组合的预测用途。没有证据说明所有资金机制无效，没有把诊断阈值升级为经济硬门。

固定实现的5208项标量特征核对通过；独立审计采用不同岭回归解法检查训练、预测、损失金额与四格分母，见[独立审计](../EX031_20261023/others/independent_audit.json)。技术发布PASS只说明身份、材料及契约核验通过。未运行仓库全量回归、完整账户、自检32点或费用压力，未新增候选。原117个登记身份保留，当前资格0。

建议下一步聚焦“中期份额扩张是否是可交易的持续市场状态”，把状态分组与本轮连续数值外推区分开，并在相同价格背景与固定时段内检验；同时保留市场趋势和份额口径变化作为竞争解释。先固定一轮状态机制对照，再据结果决定是否进入阶段三。融资接口建设需另行DEV授权，当前不把它作为继续研究的必选前提。五轮额度已用完，本报告不自动开第六轮或改变双窗口目标。

正式证据由各实验report_ref和材料引用绑定；份额内容身份8cddcd1727f8583aa1701040c7f22748b6f580ec1b92e4a1ab71bc07da386627。原509条失败及范围修正、原源码与列名冲突修正版均保留；修正发生在R4任何预测产生之前，R2/R3结果保留未重算。必要DFLS数据资产与assets/evidence、assets/deliveries应独立保存，Git不替代数据备份。无合并master、推送、tag、冻结、PTE或生产变更。
'''
    # All experiment reports use sibling paths for easy adaptation to the delivery.
    for n in range(1,6):
        if n==5:body=text
        else:
            body=heading(f'S015 资金研究第{n}轮')
            body+=f'本轮按事前五轮协议执行并完成；主问题、方法、正反证及预算收口见[五轮总报告](../EX031_20261023/report.md)。\n\n'
            link='survey_results.json' if n==1 else 'results.json'
            body+=f'本轮全部结构化结果：[结果](others/{link})。复用原434日开发池和事件，不生成策略账户，当前合格候选0。\n\n'
            if n==1:body+='508条ETF份额正式准入，开发特征缺失0；原上市首日缺失不在任何开发特征依赖范围。融资和同类篮子仍为能力/身份缺口，未作为正式收益输入。\n'
            if n==2:body+='12项固定份额定义—期限检验完整保留。20日份额增长有明显全期关联，分段缺乏同向/反向共存反事实，尚未确认独立可用性。\n'
            if n==3:body+='3个期限均保留正/负/零份额×上涨/下跌/平价九格。不能将组间差解释为因果；同指数历史篮子不可用，产品搬家解释未解决。\n'
            if n==4:body+='4个目标的资金增量模型整体预测MSE均增加。入场日过滤错过盈利更少，但识别亏损也更少，不能据此宣布识别改善。\n'
        (folder(n)/'report.md').write_text(body,encoding='utf-8',newline='\n')
    appendix=heading('全部固定时段、条件、价格份额四格与模型诊断')
    for lag,rows in [(1,r2),(2,r5['2']['conditions']),(3,r5['3']['conditions'])]:
        appendix+=f'\n## 资金滞后{lag}交易日\n\n| h/定义/位置段 | 正n/均值 | 负n/均值 | 零n/均值 |\n| --- | --- | --- | --- |\n'
        for h,z in rows.items():
            for f,a in z.items():
                for period,q in a['periods'].items():
                    appendix+=f'| {h}/{f}/{period} | '+' | '.join(f"{q['groups'][k]['n']}/{pct(q['groups'][k]['mean_return'])}" for k in ('positive','negative','zero'))+' |\n'
    appendix+='\n## 主口径量价资金四格（含零/平格）分段\n\n| h/格/段 | n | 均值 |\n| --- | ---: | ---: |\n'
    for h,z in r3.items():
        if h=='interpretation':continue
        for key,a in z['cells'].items():
            for period,v in a['periods'].items():appendix+=f"| {h}/{key}/{period} | {v['n']} | {pct(v['mean_return'])} |\n"
    appendix+='\n## 模型完整折与去极值诊断\n\n| 延迟/目标/折 | n | MSE改善（负为恶化） |\n| --- | ---: | ---: |\n'
    for lag,models in [(1,r4),(2,r5['2']['models']),(3,r5['3']['models'])]:
        for key,a in models.items():
            for fold,v in {**a['folds'],'去绝对值最大5':a['omit_largest5_absolute_label']}.items():appendix+=f"| {lag}/{key}/{fold} | {v['n']} | {pct(v['relative_mse_gain'])} |\n"
    (folder(5)/'others/period_tables.md').write_text(appendix,encoding='utf-8',newline='\n')

def publish():
    assert not (folder(5)/'others/delivery_validation.json').exists()
    audit=read(folder(5)/'others/independent_audit.json');assert audit['status']=='PASS',audit
    report_all()
    protocolrefs=read(HOME/'others/round_refs.json');refs=[]
    for k,v in protocolrefs.items():
        if isinstance(v,dict) and v.get('type')=='EvidenceRef':refs.append(EvidenceRef.from_dict(v))
    extra=read(HOME/'others/input_refs.json')
    refs+=[EvidenceRef.from_dict(v) for v in extra['prior'].values()];refs.append(EvidenceRef.from_dict(extra['events']))
    refs.append(EvidenceRef.from_dict(read(HOME/'others/coverage_resolution_ref.json')))
    per={};checks={}
    for n in range(1,6):
        here=folder(n);ex=ExperimentRef('S015',here.name);materials={}
        for sub in ('src','protocols','others'):
            for p in sorted((here/sub).glob('*')):
                if p.suffix not in ('.json','.csv','.py','.md'):continue
                if p.name in ('published_refs.json','delivery_validation.json'):continue
                r=material(ex,p);refs.append(r);materials[f'{sub}/{p.name}']=r.to_dict()
        refs=list(dict.fromkeys(refs))
        rr=publish_evidence(ctx(),ExperimentReportWrite(ex,sha256((here/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)))
        refs.append(rr);check=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(ex,ExperimentValidationScope.REPORT_PUBLICATION))
        assert check.status.value=='PASS',check.issues
        save(here/'others/published_refs.json',{'materials':materials,'report':rr.to_dict()});per[str(n)]={'materials':materials,'report':rr.to_dict()};checks[str(n)]=check.to_dict()
    receipt=read(ROOT/'research/S015/deliveries/COMPONENTS/8/receipt.json')
    p=ROOT/'research/S015/assets/deliveries/COMPONENTS/8/delivery.json'
    assert sha256(p.read_bytes()).hexdigest()==next(v['sha256'] for v in receipt['files'] if v['path']=='delivery.json')
    panel=d.ComponentPanel.from_dict(read(p)['content']['payload']);assert len(panel.components)==16
    source=EvidenceRef.from_dict(protocolrefs['source']);proto=EvidenceRef.from_dict(protocolrefs['protocol'])
    evidence=tuple(EvidenceRef.from_dict(per[str(n)]['materials']['others/results.json']) for n in range(2,6))+(EvidenceRef.from_dict(per['5']['materials']['others/independent_audit.json']),)
    new=[]
    for f in FEATURES:
        tests=[]
        for lag in (1,2,3):
            for h in (1,3,5):
                ex=folder(2 if lag==1 else 5).name
                tests.append(d.ComponentTestResult(f'funding-{f}-lag{lag}-h{h}',ex,proto,d.ComponentTestStatus.INSUFFICIENT_DATA,'固定条件关联已计算；可用性、时段混杂与历史时点认证证据不足，不指开发期缺行。f20保留中期状态线索。',evidence))
        new.append(d.ComponentEntry(f'funding_{f}_ex028',d.ExperimentDefinitionRef(source,'load_inputs'),f'ETF份额{f}固定状态；申赎份额不等于现金流',
            '原独立10万元事件扣双边费用净损益；不是完整资金账户','h1/3/5，T-1主口径及T-2/T-3敏感性','正/负/零及5日价格方向对照，完整分段',
            '仅用当时假设可得的前交易日份额；历史发布修订未认证','原量价/事件身份复用，单位万份的增长比值',
            '原434日已见开发池，508份额日中74预热日；当前同指数对照不可用','有方向性线索但未确认有效；当前不直接进入阶段三',tuple(tests)))
    tests=[]
    for lag in (1,2,3):
        for target in ('net_h1','net_h3','net_h5','entry_net_h1'):
            tests.append(d.ComponentTestResult(f'funding-model-lag{lag}-{target}',folder(4 if lag==1 else 5).name,proto,d.ComponentTestStatus.INEFFECTIVE,'此固定连续资金特征联合Ridge模型整体预测MSE均差于量价基线；不外推为所有资金机制无效。',evidence))
    new.append(d.ComponentEntry('funding_joint_ridge_ex030',d.ExperimentDefinitionRef(source,'round4'),'量价基线+四项资金连续变量联合模型',
        '事件净收益或入场日扣买费净收益的前推MSE及零阈值亏损过滤','4固定折、4目标、3时点口径','同样本量价基线，alpha10，训练期标准化及标签purge',
        '资金主口径T-1，标签结束严格早于测试起点；历史PIT假设未认证','原量价、份额和公共TXE事件身份固定',
        '已见开发池，训练外推及时间混杂明显；入场损益非完整净收益','该固定模型用途无效，不能宣称资金信息整体无效',tuple(tests)))
    content=d.ComponentPanel((*panel.components,*new),'五轮资金研究完成：新增中期份额状态线索，未确认有效组件；连续资金联合预测用途失败，合格候选0。')
    text=(folder(5)/'report.md').read_text(encoding='utf-8').replace('](../EX','](../../../experiments/EX')
    assembled=assemble_delivery(RepositoryContext.discover(ROOT),d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.COMPONENTS,9,(d.DeliveryReference.from_dict(receipt['reference']),)),d.DeliveryContent(content,d.DeliveryStatus.COMPLETE,(),(),report=text,evidence=tuple(dict.fromkeys(refs))))
    assert assembled.validation.status.value=='PASS',assembled.validation.issues
    save(folder(5)/'others/delivery_validation.json',{'delivery':assembled.receipt.reference.to_dict(),'assembly':assembled.validation.to_dict(),'experiments':checks,'rounds':per})
    intent=dict(read(ROOT/'research/registrations/S015/family.json')['research_intent'])
    intent.update(current_components=assembled.receipt.reference.to_dict(),current_experiment=ExperimentRef('S015',folder(5).name).to_dict(),current_phase='阶段二资金信息五轮完成；中期份额状态有线索，未确认有效组件，合格候选0',experiment_budget={'authorized':5,'completed':5,'remaining':0,'source':proto.to_dict()},qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,selected_candidate=None,next_gate='预算已用完；建议另批中期份额状态与价格/时段对照，解决连续外推和背景混杂后再决定阶段三，不自动新增实验或DEV接入')
    intent['proposal_path']='research/S015/experiments/EX027_20261023/protocols/funding_five_rounds.json'
    intent['funding_scope_authorization']=proto.to_dict()
    update_research_intent(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户授权五轮资金研究完成并正式交付；保留中期份额状态线索与预测负面证据；当前资格0，余额0。')
    print({'COMPONENTS':9,'status':assembled.validation.status.value,'experiments':len(checks),'qualified':0,'remaining':0},flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['report','publish']);{'report':report_all,'publish':publish}[p.parse_args().mode]()
