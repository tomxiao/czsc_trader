"""Publish all role/model comparisons before adaptive follow-up selection."""
import argparse
from hashlib import sha256
from validate import ROOT,HERE,EX,read,save,context,material,TARGETS
from czsc_trader.application import RepositoryContext,publish_evidence,validate_experiment
from czsc_trader.research_tools import EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
def pct(x):return '不可计算' if x is None else f'{100*x:.3f}%'
def report():
    r=read(HERE/'others/results.json');counts=read(HERE/'others/design_counts.json')
    out=['# S015 六维价格信息的多职责验证','', 'Status: COMPLETED','',
      '执行已批准的不限轮数阶段二计划。此实验覆盖6家族24个表达与9种职责标签，保留全部90个模型规格、360个前推拟合、216组单信号三分位诊断。没有连续账户或候选登记；原目标和资格不变。','',
      '## 事前方法','',
      '先完成EX035无收益筛选的普查，再发布[协议](protocols/component_validation.json)与[源码](src/validate.py)。每个标签独立使用100:184、184:268、268:352、352:434四个测试段；训练标签实际可知日期严格早于测试首日，标准化与三分位只用训练数据。既有434日已经反复观察，本研究的前推是防泄露检查，不能声称独立样本验证。','',
      '纯价格基线为过去1/5日收益、20日波动和振幅；历史量价基线额外含当日close/VWAP-1。各家族只增加4个价格表达；all增加24个。所有Ridge固定正则10、截距不惩罚。成交概率显式投影[0,1]，采用Brier误差。没有超参数搜索。','',
      'net1/3/5为原公共TXE独立10万元事件完整净收益，entry只含入场日收盘损益减买费；loss3为3日完整事件的亏损额，drawdown3为实际买入后至退出之前日收盘最差浮亏。风险不是盘中最差价格，也不是账户最大回撤。','',
      'hold1/hold3分别是D日已持有1/3日的同一原事件：D+1卖与D+3卖的净金额差，使用D已知价格特征和浮盈亏；原买入成本抵消、卖出费用保留，实际卖出仍按原重试结果。仅纳入D以前已买入且两条退出标签完整的事件。fill只检验原限价合同是否成交；没有修改订单或证明执行改善。','',
      '## 全部模型误差增量','', '下表为相对纯价格基线的均方误差下降比例，正数为改善。它不是策略收益或资格分数。constant和legacy是参考，六家族和all是被检验表达。','',
      '| 标签/前推n | constant | legacy | 方向效率 | 上下不对称 | 位置响应 | 波动转换 | 时间顺序 | 尺度关系 | 全部 |',
      '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    names=['constant','legacy','direction_efficiency','up_down_asymmetry','location_response','volatility_transition','temporal_order','scale_relationship','all']
    for t in TARGETS:out.append('| '+f"{t}/{r[t]['models']['price']['n']} | "+' | '.join(pct(r[t]['models'][m]['mse_gain_vs_price']) for m in names)+' |')
    out+=['','## 固定规则和机会代价','',
      '对有正负含义的收益和持有标签，预测<0表示排除/提前卖出；以下展示纯价格、历史量价和全部24列表达。金额分母分别是相同事件中所有亏损金额和所有盈利金额，独立事件不可累加为账户收益。风险模型没有被强行用零阈值买卖。','',
      '| 标签/模型 | 排除n | 识别亏损金额 | 遗漏盈利金额 | 保留事件均值 |','| --- | ---: | ---: | ---: | ---: |']
    for t in TARGETS:
        for m in ('price','legacy','all'):
            u=r[t]['models'][m]['utility'].get('zero_rule')
            if u:out.append(f"| {t}/{m} | {u['reject_n']} | {pct(u['caught_loss_fraction'])} | {pct(u['missed_profit_fraction'])} | {pct(u['retained']['mean'])} |")
    out+=['','每折相同参与数量的排序对比存于完整结果。它需要整段预测分布，是事后诊断，不能称可实时执行的策略。固定零阈值规则不使用该分布。风险/成交用途及相同数量排序仅报告点估计，不能误称已获得用途置信区间。','',
      '## 不确定性与选择边界','',
      '所有模型保留各折贡献、去掉最大绝对标签5项后的结果、相对price及legacy的20日块499次误差差区间；有符号标签另给零阈值保留事件金额增量区间。这些区间未校正历史选择和多项比较，不是新增经济硬门。','',
      '单信号三分位的方向由训练期选择，全部测试分组和样本数量均保留；同源表达及多目标不构成独立证据。某个模型变差不能直接证明信息本身无用，某个误差改善也不直接证明有交易价值。','',
      '本实验作为第一轮用途验证，后续研究按全部结果识别值得做表达、消融或条件反证的方向；在后续实验开始前先保存本轮证据。未进入阶段三。','',
      '技术核验见[独立审计](others/independent_audit.json)。证据：[结果](others/results.json)、[前推预测](others/predictions.csv)、[全部单信号分组](others/univariate_bins.csv)、[标签](others/labels.csv)、[训练日期](others/folds.json)、[规模](others/design_counts.json)。']
    (HERE/'report.md').write_text('\n'.join(out)+'\n',encoding='utf-8',newline='\n')
def publish():
    assert not (HERE/'others/published_refs.json').exists()
    assert read(HERE/'others/independent_audit.json')['status']=='PASS';report();refs=[];materials={}
    inp=read(HERE/'others/input_refs.json')
    for v in inp['evidence'].values():refs.append(EvidenceRef.from_dict(v))
    proto=read(HERE/'protocols/component_validation.json')
    refs.append(EvidenceRef.from_dict(proto['plan']))
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    check=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert check.status.value=='PASS',check.issues
    save(HERE/'others/published_refs.json',{'report':rr.to_dict(),'materials':materials,'validation':check.to_dict()});print('COMPONENT_VALIDATION_PUBLISHED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['report','publish']);{'report':report,'publish':publish}[p.parse_args().mode]()
