"""Retain the data gate and its assumptions before starting mechanism research."""
from hashlib import sha256
from pathlib import Path
import json
from dataflows import ProviderConfig
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    validate_experiment, update_research_intent, ResearchIntentUpdate)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXPERIMENT = ExperimentRef('S017', WORK.name)


def main():
    data = json.loads((WORK/'others/data_readiness.json').read_text(encoding='utf-8'))
    if data['research_gate'] != 'READY_WITH_EXPLICIT_RAW_PRICE_AND_AVAILABILITY_ASSUMPTIONS':
        raise ValueError('auxiliary data gate has not passed')
    report = '''# S017辅助数据核验完成，可以恢复阶段二

2026-10-29，RSCH。工作完成，数据可得性通过；本轮未评价任何策略，不构成收益结论。
公共概览已确认6个原型交付、0个登记候选。新增20轮额度保守包含本数据实验：已完成1轮，余19轮。

|输入|频率|记录数|交易日|缺失/零量|
|---|---|---:|---:|---|
|SPY、QQQ、XLK各自|日线|1800|1800|0/0|
|SPY、XLK各自|30分钟|23298|1800|0/0|
|LITE既有主行情|30分钟|23298|1800|0/0|

范围为2018-11-01至2025-12-31，包含原预热与2019—2025开发池。全部14项产品通过公共DFLS联合准备，
原LITE四项内容哈希逐项相同。精确准备引用、元数据、下载分页与哈希见[核验记录](others/data_readiness.json)。
没有读取2026 LITE保留价格或策略绩效。

## 必须随研究保留的限制

- XLK在2025-12-05的2:1拆股已被官方公告和原价约0.504的跨日比例共同识别。XLK只用同会话开盘至收盘变化，
  或已完成会话Close/Open的滞后累计，不用跨日原价比或跨拆股原始股数构造趋势/相对量。
- SPY、QQQ未出现本核验阈值下的大幅价格不连续，不代表完整公司行动历史已独立认证；分红原价影响仍保留。
- 供应商日频与RTH分钟聚合不是完全一致的产品：SPY有142日OHLC任一字段差逾0.01美元，XLK有7日；
  最大Close差分别0.11/0.02美元，SPY最大High/Low差7.7123/8.5552美元，不能混用日频高低价做RTH区间。
  背景研究若使用日频，仅按供应商已完成日线Close/Open定义；日内研究只按RTH分钟序列定义。
- 收盘可用、日历当日开盘可用仍为研究假设，未核验历史逐次发布时间；此技术READY不证明真实盘中可执行性。
- 代理含义、拆股来源、论文适用限制及已见信息见[方法来源](others/method_sources.md)。基本面不作为交易事件条件。

第一次联合准备10项辅助产品成功、4项主产品因调用方漏配来源绑定失败；补齐原绑定后显式复用重试成功。
失败记录保留于[data_readiness_attempt1.json](others/data_readiness_attempt1.json)，没有改数据或静默换源。

## 下一步

依据用户条件授权恢复阶段二。分别固定市场/行业持仓选择、开盘突破相对量及抗跌恢复参与的对照。
原基准、2019—2025样本、0.1%单边费用、固定1%溢价及全部目标保持；不推进阶段三。
后续实验逐项记录额度、配置和正式账户数量，不把开发内再次选择称为独立验证。
'''
    (WORK/'report.md').write_bytes(report.encode('utf-8'))
    repository = RepositoryContext.discover(ROOT)
    batch = ResearchBatchRef('S017')
    context = create_research_context(repository, batch, providers=ProviderConfig(bindings={}))
    refs = []
    for name, relative in (('authorization','protocols/authorization.md'),('design','protocols/design.md'),
            ('data-readiness','others/data_readiness.json'),('failed-call','others/data_readiness_attempt1.json'),
            ('method-sources','others/method_sources.md'),('preparation-source','src/prepare.py'),('publication-source','src/publish.py')):
        path = WORK/relative
        refs.append(publish_evidence(context,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),
            'application/json' if path.suffix=='.json' else 'text/plain',path.suffix[1:])))
    reference = publish_evidence(context,ExperimentReportWrite(EXPERIMENT,sha256(report.encode()).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(refs)))
    validation = validate_experiment(repository,ExperimentValidationRequest(EXPERIMENT,ExperimentValidationScope.REPORT_PUBLICATION))
    if validation.status.value!='PASS':
        raise ValueError(validation)
    (WORK/'others/publication.json').write_text(json.dumps({'report':reference.to_dict(),
        'validation':validation.to_dict(),'evidence':[ref.to_dict() for ref in refs]},ensure_ascii=False,indent=2),encoding='utf-8')
    path = ROOT/'research/registrations/S017/family.json'
    intent = json.loads(path.read_text(encoding='utf-8'))['research_intent']
    auth = intent['expanded_stage_two_authorization']
    auth.update(status='ACTIVE_STAGE_TWO',completed_new_rounds=1,research_started=True,
        auxiliary_data_gate={'status':data['research_gate'],'experiment':WORK.name,'report':reference.to_dict(),'prepared':data['reference']})
    intent['stage']='STAGE_2_AUXILIARY_AND_INTRADAY_RESEARCH'
    update_research_intent(repository,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='辅助数据可得性及原主数据身份核验通过，依据用户条件授权恢复阶段二；数据核验计1/20轮')
    print('EX009 REPORT_PUBLICATION PASS; DATA GATE READY; RESEARCH RESUMED',flush=True)


if __name__=='__main__':
    main()
