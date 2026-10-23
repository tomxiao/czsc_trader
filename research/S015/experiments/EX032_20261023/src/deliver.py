"""Bound the positive finding to its actual developmental evidence and publish."""
import argparse
from hashlib import sha256
import pandas as pd
from study import ROOT,HERE,BASE,EX,read,save,context,material
from czsc_trader.application import RepositoryContext,publish_evidence,assemble_delivery,validate_experiment,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope,ResearchBatchRef
from czsc_trader.research_tools import delivery as d
def pct(v):return '不可计算' if v is None else f'{v*100:.4f}%'
def ci(v):return '不可计算' if v is None else '['+', '.join(pct(x) for x in v)+']'
def report():
    r=read(HERE/'others/results.json');p=pd.read_csv(HERE/'others/predictions.csv');audit=read(HERE/'others/independent_audit.json')
    pooled={}
    for (lag,target),g in p.groupby(['lag','target']):
        z=g[g.position<352];be=((z.base-z.y)**2).mean();se=((z.funded-z.y)**2).mean()
        pooled[f'{lag}/{target}']={'n':len(z),'relative_mse_gain':float(1-se/be)}
    save(HERE/'others/fold_contribution.json',{'purpose':'对已固定四折的前三折进行汇总归因，不是新增模型、试验或独立验证','first_three_folds':pooled})
    text='''# S015 中期份额状态对照：存在有限预测辅助证据，尚未证明可交易有效

Status: COMPLETED

本次用户追加1轮，EX032完成、余额0。阶段二针对性验证目标已完成，产出合格策略的总体目标尚未达成：当前合格候选、待选型及待冻结仍为0，未新增连续账户或候选登记。

结论有所推进：把20日份额变化表达成扩张/收缩状态后，固定量价模型在原已见开发池的3/5日前推预测出现小幅增量；同时间、同价格方向内的条件收益差仍为正。可将它保留为**有依据但支持有限的预测辅助组件**。这不是已确认稳定有效的交易组件，也不是资金因果或双窗口资格证明。此前连续资金变量模型失败仍保留，不因本轮结果改写历史。

## 授权与事前方法

执行用户批准的[固定状态对照协议](protocols/state_control.json)，先发布协议和源码再计算。根据EX028—31已见结果选定f20及此问题，存在选择历史；前推切分不等于新独立验证。159326.SZ、原434日开发池、415日比较窗和2026-10-21截止日保持不变。MANDATE/3原收益、回撤、频率、扰动及费用压力要求不变；415日净收益严格超过91.5802915%、回撤严格低于7.2486637491%。本轮没有账户，未检验这些经济硬门，也未增加置信区间或分段一致性硬门。

主状态为当时可知的20日份额增长率：大于0为扩张、小于0为收缩、等于0单列。主口径使用T−1及以前记录，固定T−3敏感性。只有508条份额的既有认证快照，开发特征完整；未查询新数据。历史发布与修订版本仍未认证，T+1可得是既有声明假设，额外延迟不能代替认证。

复用EX026独立10万元事件：T+1原1%限价买，T+h+1起市场卖，双侧0.1%费用，HFQ_RESEARCH及公共TXE成交事实不变。完整净收益只用CLOSED：h1/3/5分别425/423/421个；入场日唯一标签用h1全部已买入且有收盘标记的426个事件，包括末端未退出记录，只扣买入费，不混作完整交易净收益。事件重叠，不能连乘或加总成连续账户。

三套对照在观察结果前固定：

1. 原五个固定时间段×过去5日价格涨跌方向。
2. 上述格再按日内买卖压力方向细分。
3. 从开发池起点划分固定21交易日块×过去5日价格方向。

同一格必须同时出现份额扩张和收缩，才能估计组间差；零状态不归入收缩。每格差为扩张组均值减收缩组均值，用n正×n负/(n正+n负)加权。报告无法对照的时期和样本；粗价格方向相同不意味着价格幅度、波动率及所有条件完全相同。

## 同时间与价格背景内，收益差是否保留

下表单位是独立事件净收益率差的**百分点**。主对照分母排除了一个零状态事件；不是全部完整事件数。括号为有正负两组共同支持的事件数/可比较正负事件数。

| 标签 | T−1原全期差 | T−1主对照差/覆盖 | T−1细时间差/覆盖 | T−3主对照差 | T−3细时间差 |
| --- | ---: | --- | --- | ---: | ---: |
'''
    for target,a in r['1']['conditions'].items():
        main=a['primary'];local=a['local_time_sensitivity'];s=r['3']['conditions'][target]
        text+=f"| {target} | {pct(main['crude_delta'])} | {pct(main['delta'])} ({main['support_n']}/{main['eligible_n']}) | {pct(local['delta'])} ({local['support_n']}/{local['eligible_n']}) | {pct(s['primary']['delta'])} | {pct(s['local_time_sensitivity']['delta'])} |\n"
    text+='''
全部24项固定条件差均为正；在同时间格和同价格方向内，原始优势没有完全消失。h3主对照差约0.8845个百分点，细时间差约0.7508个百分点；h5分别1.4572和1.0015个百分点。可以削弱“全期优势完全由原粗时间段及价格方向解释”的说法，不能排除更细背景和未观察因素。

h3主对照覆盖337/422；h5覆盖335/420。细时间仅155/422与155/420，T−3为165/422和165/420。其余时期没有足够的两种状态共存，不能据此估计反事实，也不能把这部分样本的效果填0或推广已有估计。原第184—267段全部处于扩张状态，仍不能作同段正负比较。

背景差异未完全消除：h3主对照扩张与收缩组的波动率、振幅仍相差约0.224和0.274个共同样本标准差；细时间虽改善这两项，但5日收益幅度仍有约0.188个标准差差异。因此本轮是粗分层观察性比较，不是随机实验或严格因果识别。

## 离散状态能否改善原量价模型

量价基线沿用r1/r5/vol20/pressure/range20。仅加入扩张、零状态两个指示变量，收缩为基准；不再直接线性外推份额增长数值。固定Ridge alpha10、训练期标准化及四个测试段；训练标签的实际结束日必须早于测试首日。没有阈值或超参数搜索。

表中正数为预测均方误差下降，负数为恶化。它衡量预测误差，不能解释为账户收益提高。

| 标签 | n | T−1整体改善 | T−1前三折合计改善 | T−1去最大绝对值5标签 | T−3整体改善 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
    for target,a in r['1']['models'].items():
        text+=f"| {target} | {a['n']} | {pct(a['relative_mse_gain'])} | {pct(pooled[f'1/{target}']['relative_mse_gain'])} | {pct(a['omit_largest5']['relative_mse_gain'])} | {pct(r['3']['models'][target]['relative_mse_gain'])} |\n"
    text+='''
8项整体模型比较均有正改善。主口径h3/h5改善3.0655%/4.6303%，T−3仍改善1.6517%/3.7467%；去掉最大绝对值5个标签后h3/h5两个时点口径仍为正。相较此前连续份额数值的错误外推，这支持把资金信息作为离散背景状态继续研究。

**最强反证是改善集中在最后一折。** 主口径前三折合计h3/h5误差反而增加0.4782%/0.9747%；最后一折分别改善10.3187%/14.4281%。T−3前三折h3/h5同样整体恶化。全期正增量尚不能说明稳定跨阶段有效。该分解只是已固定四折结果的归因，没有新拟合、选择新测试窗口或另立分段硬门。

## 入场当天识别亏损与遗漏盈利

在相同326个前推入场事件上，预测值小于0视为建议避开，门槛未搜索。亏损金额和盈利金额分别作分母；金额来自独立事件，并非账户可避免/可获得损益。

| 模型 | 建议避开n | 其中实际亏损/盈利n | 识别亏损金额 | 遗漏盈利金额 |
| --- | ---: | ---: | ---: | ---: |
'''
    for name,a in [('原量价',r['1']['models']['entry_net_h1']['filters']['base']),('状态T−1',r['1']['models']['entry_net_h1']['filters']['funded']),('状态T−3',r['3']['models']['entry_net_h1']['filters']['funded'])]:
        text+=f"| {name} | {a['reject_n']} | {a['negative_n']}/{a['positive_n']} | {pct(a['caught_loss_fraction'])} | {pct(a['missed_profit_fraction'])} |\n"
    text+='''
入场当天主口径只从47.9790%识别亏损变为48.0308%，而遗漏盈利从32.6240%增至32.7800%，几乎没有实际改善。不能把1.2262%的预测误差下降包装成已经能有效规避入场日亏损。T−3识别亏损略降、遗漏盈利略降，仍是取舍。

较有用的线索在3日完整事件：相同323个前推事件中，主口径识别亏损金额从30.7591%提高至42.9089%，遗漏盈利从34.7930%降至32.8213%；T−3仍为42.5621%与33.6185%。这是该固定预测筛选规则在已见开发池的有利结果。两模型避开事件数量不同，不能当作固定参与率比较，更不能由此推出账户回撤下降。

## 不确定性与状态持续性

499次20交易日块重抽样均在完整434日轴上进行，再计算分格共同支持及权重。保留原时间格身份，抽样后的支持集会变化；这是条件差和预测损失的探索性不确定性描述，未校正历史选择或多项比较。

| 延迟/标签 | 主对照差95%范围 | 细时间差95%范围 | 模型MSE改善原始单位95%范围 |
| --- | --- | --- | --- |
'''
    for lag,z in r.items():
        for target,a in z['conditions'].items():
            m=z['models'][target]['paired_mse_improvement_ci95']
            text+=f"| {lag}/{target} | {ci(a['primary']['bootstrap']['ci95'])} | {ci(a['local_time_sensitivity']['bootstrap']['ci95'])} | [{m[0]:.8g}, {m[1]:.8g}] |\n"
    text+='''
多数条件区间、全部模型损失改善区间跨0，提示效应仍不确定；这不是新增经济硬门。有限支持的判断结合离散表达修正、两种滞后整体增量、3日筛选金额改善，也同时保留共同支持不足和末折集中反证。

两种时点口径均只有13段连续状态、12次状态变化，主口径最长扩张连续132日。它适合作为慢变化的决策背景，不宜直接把每次状态切换当作完整交易策略。13段不是13笔闭合交易；若进入策略构造，必须首先检验原滚动60日频率约束，并说明背景状态如何与实际交易机会衔接，不能靠拆单或更改标准达标。

## 组件判断、交付与下一步

COMPONENTS/10继承此前21条组件记录，新增2条用途记录：条件状态诊断及离散状态预测辅助。新增24项条件比较、8项模型比较，共32项相关检验；历史124+32=156，绝非156份独立证据。

- 条件状态诊断：INSUFFICIENT_DATA，指独立可用性/因果与背景控制证据不足，不是数据缺行。
- 离散状态预测辅助：h3/h5两种时点共4项记录SUPPORTED，**严格限定为本已见开发池、固定模型及前推设置中的预测辅助证据**；不是已确认稳定有效、可交易或达到双窗口要求。h1和入场日用途证据有限，保留INSUFFICIENT_DATA。
- 这是研究员对明确用途的有限支持判断，不以“区间必须不跨0”“每段必须改善”新增统一硬门。0个合格策略、0个新增登记不变；此前EX030/031连续模型的负面结论不改写。

独立审计通过18,725项核对：24组全部分格估计、权重、样本和金额、控制差异及块重抽样；8组模型32个折独立增广最小二乘复算，最大预测差约1.84×10⁻¹⁶；868个状态重算和3825项标签金额关系。源代码及输入均按正式引用认证。发布核验只证明材料身份与契约一致，不代表策略经济合格；未执行全仓回归、完整连续账户、32点扰动或压力费用验收。

建议结束这一轮组件追问，**下一步转入有明确预算的阶段三最小原型验证**：把中期份额状态作为背景输入，明确独立于超跌反弹的交易假设，优先验证机会密度及实际账户兑现；使用原双窗口门槛及执行合同，与去掉状态的原型做消融对照。现有证据足够支持这种受控尝试，尚不足以预言成功。不能直接把本轮事件均值变成策略收益，也不建议继续无界扩大资金指标扫描。

建议下一步预算为1轮固定原型对照：同一非超跌交易假设，有/无份额状态两个规则，各跑434日与415日独立初始账户，共4个中心账户；先锁定实际规则和频率可行性，不做参数网格搜索。若中心值得继续，再另行安排阶段四32点扰动和费用压力，不将4个中心账户当作完整资格验收。本次1轮额度已用完；此阶段三方案须用户另批。

未修改平台、引入新数据、合并master、推送、打tag、冻结或操作PTE/生产。必要资产仍由DFLS及assets/evidence、assets/deliveries保存，Git不能替代其备份。

完整数据见[结果](others/results.json)、[各格和各折明细](others/detail_tables.md)、[独立审计](others/independent_audit.json)、[前三折归因](others/fold_contribution.json)。
'''
    (HERE/'report.md').write_text(text,encoding='utf-8',newline='\n')
    detail='# 全部对照格、模型折和状态段\n\n所有结果为既有开发池观察性诊断。\n'
    for lag,z in r.items():
        detail+=f'\n## 滞后{lag}日\n'
        for target,schemes in z['conditions'].items():
            for scheme,a in schemes.items():
                detail+=f'\n### {target}/{scheme}\n\n| 格 | 首/尾日期 | 正n/均值 | 负n/均值 | 零n/均值 | 双方共存 |\n| --- | --- | --- | --- | --- | --- |\n'
                for v in a['cells']:
                    detail+=f"| {v['cell']} | {v['first_date']} / {v['last_date']} | "+' | '.join(f"{v[s]['n']}/{pct(v[s]['mean'])}" for s in ('positive','negative','zero'))+f" | {v['both_states']} |\n"
        detail+='\n### 模型折\n\n| 目标/折 | n | MSE改善 |\n| --- | ---: | ---: |\n'
        for target,a in z['models'].items():
            for fold,v in a['folds'].items():detail+=f"| {target}/{fold} | {v['n']} | {pct(v['relative_mse_gain'])} |\n"
        detail+='\n### 连续状态段\n\n| 起点 | 终点不含 | 状态 | 长度 | 左/右截尾 |\n| ---: | ---: | ---: | ---: | --- |\n'
        for v in z['runs']:detail+=f"| {v['start']} | {v['end_exclusive']} | {v['state']} | {v['length']} | {v['left_censored']}/{v['right_censored']} |\n"
    (HERE/'others/detail_tables.md').write_text(detail,encoding='utf-8',newline='\n')
def publish():
    assert not (HERE/'others/delivery_validation.json').exists()
    assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    report();materials={};refs=[]
    inp=read(HERE/'others/input_refs.json')
    for v in inp.values():
        for item in v if isinstance(v,list) else [v]:refs.append(EvidenceRef.from_dict(item))
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix not in ('.py','.json','.csv','.md'):continue
            ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    refs=list(dict.fromkeys(refs));rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)));refs.append(rr)
    repo=RepositoryContext.discover(ROOT);check=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert check.status.value=='PASS',check.issues
    receipt=read(ROOT/'research/S015/deliveries/COMPONENTS/9/receipt.json');path=ROOT/'research/S015/assets/deliveries/COMPONENTS/9/delivery.json'
    assert sha256(path.read_bytes()).hexdigest()==next(f['sha256'] for f in receipt['files'] if f['path']=='delivery.json')
    panel=d.ComponentPanel.from_dict(read(path)['content']['payload']);assert len(panel.components)==21
    src=EvidenceRef.from_dict(read(HERE/'others/source_ref.json'));proto=EvidenceRef.from_dict(read(HERE/'others/protocol_ref.json'));ev=tuple(EvidenceRef.from_dict(materials[f'others/{n}']) for n in ('results.json','independent_audit.json','fold_contribution.json'))
    tests=[]
    for lag in (1,3):
        for target in ('net_h1','net_h3','net_h5','entry_net_h1'):
            for scheme in ('primary','price_sensitivity','local_time_sensitivity'):
                tests.append(d.ComponentTestResult(f'state-conditional-{lag}-{target}-{scheme}',EX.experiment_id,proto,d.ComponentTestStatus.INSUFFICIENT_DATA,'24项共同支持内的差为正，但粗控制残差、无对照时期与不确定性仍在；不主张独立资金因果。',ev))
    a=d.ComponentEntry('funding_state_conditional_ex032',d.ExperimentDefinitionRef(src,'matched'),'20日份额状态在固定时间/价格格内的条件关联',
        '独立事件完整净损益或扣买费的入场日净损益','h1/3/5及唯一入场日；lag1/3','五固定段×价格方向；加压力方向；21日块×价格方向',
        '份额T-1或T-3，沿用历史可得假设；缺少发布修订认证','原EX026公共TXE事件及EX027认证份额派生特征',
        '共同支持样本的观察性比较，已见434日，不推广无反事实时期','存在有限正关联，尚不能认定独立因果或可交易有效',tuple(tests))
    tests=[]
    for lag in (1,3):
        for target in ('net_h1','net_h3','net_h5','entry_net_h1'):
            supported=target in ('net_h3','net_h5')
            tests.append(d.ComponentTestResult(f'state-model-{lag}-{target}',EX.experiment_id,proto,d.ComponentTestStatus.SUPPORTED if supported else d.ComponentTestStatus.INSUFFICIENT_DATA,
                '有限支持：仅已见开发池固定3/5日前推预测辅助证据；两滞后和去极端标签仍有整体增量，但末折集中，非稳定交易有效或资格通过。' if supported else '小幅整体预测增量未形成明确入场日亏损识别改善；用途支持有限，未新增经济硬门。',ev))
    b=d.ComponentEntry('funding_state_predictive_ex032',d.ExperimentDefinitionRef(src,'models'),'有限SUPPORTED：已见开发池固定3/5日预测辅助状态；不是已确认有效交易组件',
        '固定量价基线加扩张/零状态指示变量的前推MSE及零预测阈值过滤','4折、4目标、lag1/3，alpha10不调参','同样本量价基线，严格标签purge；原连续资金结果仅作历史背景',
        '只用决策时假设可得信息，训练标签严格早于测试首日','原1%限价、双侧0.1%费的独立事件，无连续账户',
        '原434日已见开发池，存在选择历史，末折集中；历史发布修订未认证','可进入获批最小原型的输入假设；当前资格0，入场日过滤无实质提升',tuple(tests))
    final=d.ComponentPanel((*panel.components,a,b),'EX032完成：新增一个用途受限的中期份额状态预测辅助组件；3/5日已见池有小幅增量，尚未确认可交易有效，合格策略0。')
    txt=(HERE/'report.md').read_text(encoding='utf-8').replace('](protocols/',f'](../../../experiments/{HERE.name}/protocols/').replace('](others/',f'](../../../experiments/{HERE.name}/others/')
    assembled=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.COMPONENTS,10,(d.DeliveryReference.from_dict(receipt['reference']),)),d.DeliveryContent(final,d.DeliveryStatus.COMPLETE,(),(),report=txt,evidence=tuple(refs)))
    assert assembled.validation.status.value=='PASS',assembled.validation.issues
    save(HERE/'others/delivery_validation.json',{'delivery':assembled.receipt.reference.to_dict(),'assembly':assembled.validation.to_dict(),'experiment':check.to_dict(),'report':rr.to_dict(),'materials':materials})
    intent=read(ROOT/'research/registrations/S015/family.json')['research_intent']
    intent.update(current_components=assembled.receipt.reference.to_dict(),current_experiment=EX.to_dict(),experiment_budget={'authorized':1,'completed':1,'remaining':0,'source':proto.to_dict()},current_phase='阶段二状态固定对照完成：新增有限预测辅助证据，尚未验证交易有效，合格候选0',qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,next_gate='本轮额度0；建议另批阶段三最小原型与去状态消融，优先机会密度和连续账户兑现；未自动推进或扩大搜索')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户批准的1轮中期资金状态对照已完成；正式保留限定用途支持与末折集中反证；资格0，预算用完。')
    print({'delivery':'COMPONENTS/10','validation':assembled.validation.status.value,'experiment':check.status.value,'qualified':0,'remaining':0})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['report','publish']);{'report':report,'publish':publish}[p.parse_args().mode]()
