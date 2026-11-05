"""Publish the passed technical inspection and exact pending freeze subject."""
from pathlib import Path
from hashlib import sha256
import ast
import os
import re

import run_inspection as a
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, validate_experiment, assemble_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope, ExecutionResources)
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f


def main():
    repo = RepositoryContext.discover(a.ROOT)
    experiment = ExperimentRef('S018', a.EXP_ROOT.name)
    ctx = create_research_context(repo, ResearchBatchRef('S018'), resources=ExecutionResources(2, 1, 17))
    report = f.CandidateInspectionReport.from_dict(a.read(a.EXP_ROOT / 'others/inspection_report.json'))
    assert validate_inspection(repo.root, report.reference) == report
    assert report.status is f.InspectionStatus.PASS
    assert report.origin.content_sha256 == '186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    assert report.plan.version == 'v1' and report.plan.parent_version is None
    assert not (repo.strategy_root/'S018/versions/v1.json').exists()
    destination = a.ROOT/'research/S018/deliveries/INSPECTION/2'
    assert not destination.exists() and not (a.EXP_ROOT/'report_ref.json').exists()
    behavior = a.read(report.behavior_equivalence.evidence[0].resolve(a.ROOT))
    pte = a.read(report.pte_runtime.evidence[0].resolve(a.ROOT))
    measurements = a.read(report.measurements.resolve(a.ROOT))
    assert behavior['candidate'] == behavior['release'] and behavior['passed']
    facts = behavior['candidate']['facts']
    assert len(facts['decisions']) == 961
    assert len(pte['scenarios']) == 6 and not pte['coverage']['missing']
    assert all(x['status'] == 'PASS' for x in pte['scenarios'])
    continuous, = [x for x in pte['scenarios'] if x['case_id']=='recorded-two-cycles-with-add']
    assert len(continuous['facts']['fills']) == 5
    subject = f.FreezeSubject(report.origin.candidate,report.origin.content_sha256,
        report.reference,report.plan.sha256,'v1')
    a.save('protocols/freeze_approval_plan.json',{
        'status':'PENDING_USER_APPROVAL', 'subject':subject.to_dict(),
        'plan':report.plan.to_dict(),'plan_sha256':report.plan.sha256,
        'release':report.release.to_dict(), 'inspection_status':report.status.value,
        'authorized_next_action':'用户精确批准后提交本检验包为S018-v1；不部署或生效到任何生产账户。',
        'current_freeze_status':'NOT_EXECUTED'})
    a.save('others/technical_summary.json',{
        'behavior_status':report.behavior_equivalence.status.value,
        'pte_status':report.pte_runtime.status.value,
        'counts':{key:len(value) for key,value in facts.items()},
        'scenario_statuses':[{k:s[k] for k in ('case_id','status','code')} for s in pte['scenarios']],
        'coverage':pte['coverage'], 'continuous_cycle_fill_count':5,
        'measurements':measurements,'freeze':'NOT_EXECUTED','production':'NOT_TOUCHED'})
    scenario_rows = '\n'.join(f"| {s['case_id']} | {s['status']} |" for s in pte['scenarios'])
    text = f'''# S018/C9380 阶段五：技术通过，等待精确冻结批准

Status: TECHNICAL_PASS_AWAITING_FREEZE_APPROVAL

## 结论

在平台提交 `57f925496` 上，固定 C9380 的定义、参数及执行合同，正式调用公开 `inspect_candidate`，候选与最终格式包行为等价、隔离 PTE 运行两个目标均为 **PASS**。已形成可供批准的 S018-v1 精确冻结计划；尚未执行冻结，阶段五待用户批准后完成冻结事务及收口。

本次为 EX067 原生 V4 能力缺口修复后的新实验；[原失败报告](../EX067_20261105/report.md)与 INSPECTION/1 保留。阶段四 [ASSESSMENT/2](../../deliveries/ASSESSMENT/2/report.md)、C9380 参数、候选登记及历史资格不变。本次没有搜索或重新选优。

## 固定输入与检验范围

- 复用 EX064 中心账户已准备的 8 个数据角色，逐项核对内容哈希，未访问新行情或供应商。
- 开发窗口仍为 2023-01-03 至 2026-10-30。MU/SOXX 后复权辅助价格用于策略观察；MU 未复权价格用于报价、成交和账户估值，公司行动进入真实数量及现金/应收账。
- 每侧费用仍为成交额 0.1%。PTE 金额预期采用四位小数及累计费用差额，修正原协议的金额精度；没有更改费率。
- 原有 5 个场景补齐决策前已知且生效的公司行动和到期支付；增加连续两周期、包含补仓和退出的场景，逐次成交后重启，保留无订单决策日。
- PTE 回报由既有历史模型成交录制并注入，属于隔离合成通道事实，不是券商真实成交或独立前瞻业绩。
- 使用最多 2 个工作进程、240 秒总预算；本次实际 {measurements['elapsed_seconds']:.2f} 秒。

协议见 [inspection_protocol.json](protocols/inspection_protocol.json)，输入见 [inspection_inputs.json](others/inspection_inputs.json)，精确合同见 [inspection_scope.json](protocols/inspection_scope.json)。

## 技术结果

行为等价覆盖 {len(facts['decisions'])} 个决策点、{len(facts['orders'])} 个订单、{len(facts['fills'])} 笔成交及 {len(facts['trades'])} 个闭合周期，候选与最终格式包的观察、决策、订单、成交、公司行动、账户和最终策略状态精确一致，容差为 0。该结论是技术实现等价，不是新增经济验收。

| PTE 场景 | 结果 |
| --- | --- |
{scenario_rows}

标准覆盖项无缺失，连续两周期场景实际覆盖 5 笔成交及状态恢复。完整结果见 [technical_summary.json](others/technical_summary.json)、[inspection_report.json](others/inspection_report.json)及 [inspection_validation.json](others/inspection_validation.json)。

## 待批准的精确冻结计划

拟首次冻结为 **S018-v1**，无父版本，初始资格为 RESEARCH。选型数据截止日为 2026-10-30，计划元数据中的前瞻起始日为 2026-11-06；该日期不代表生产启动承诺。

| 身份 | SHA256 |
| --- | --- |
| 候选 C9380 内容 | `{report.origin.content_sha256}` |
| 候选登记 | `{report.origin.registration_sha256}` |
| 本次技术检验报告 | `{report.reference.sha256}` |
| 精确冻结计划 | `{report.plan.sha256}` |
| 待冻结发布版本 | `{report.release.release_sha256}` |
| 待冻结包 | `{report.release.package_sha256}` |

[freeze_approval_plan.json](protocols/freeze_approval_plan.json)完整列出待批准对象、计划、运行绑定和包内文件。批准后只提交检验保存的同一发布字节，并核对真实 COMMITTED 回执；当前没有生成正式冻结版本。

## 剩余边界与下一步

技术检验仅覆盖已声明历史窗口与 6 个隔离场景。阶段四披露的开发样本复用、时点可得性及跨时期稳定性限制保持，不能将技术 PASS 解释为未来收益保证。

当前检验执行支持限价买入及限价/市价卖出；市价买入、带前置依赖的订单明确拒绝，C9380 不使用这两类表达。富途美股模拟通道、旧冻结策略原地升级、生产版本升级及账户绑定仍是后续独立实施事项，本次未部署或修改生产。

根据 [RSCH 指南第 3.5 节](../../../RSCH_AGENT.md#35-阶段五技术检验与获批冻结)：“冻结必须具备完整计划、通过检查，并取得用户对候选、内容、检验报告、计划及版本的精确批准。”本轮“同意”授权继续正式阶段五检验，发生于上述新报告与计划生成之前；因此下一步呈请用户批准本计划冻结为 S018-v1。

本次技术检验目标已达成；阶段五等待精确冻结批准。正式交付 INSPECTION/2 标记 PARTIAL，待冻结项明确列出，原交付保留。
'''
    (a.EXP_ROOT/'report.md').write_text(text,encoding='utf-8',newline='\n')
    paths = [a.EXP_ROOT/'notes.md', *sorted((a.EXP_ROOT/'src').glob('*.py')),
        *sorted((a.EXP_ROOT/'protocols').glob('*')), *sorted((a.EXP_ROOT/'others').glob('*.json'))]
    refs=[]
    for path in paths:
        if path.suffix=='.py':
            ast.parse(path.read_text(encoding='utf-8'))
        media={'.json':'application/json','.py':'text/x-python','.md':'text/markdown'}[path.suffix]
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(experiment,path.stem,
            path.read_bytes(),media,path.suffix[1:])))
    raw=(a.EXP_ROOT/'report.md').read_bytes()
    def rebase(match):
        original=match.group(1)
        path,sep,anchor=original.partition('#')
        target=(a.EXP_ROOT/path).resolve()
        assert target.is_relative_to(a.ROOT) and target.exists(),original
        return ']('+Path(os.path.relpath(target,destination)).as_posix()+(sep+anchor if sep else '')+')'
    rebased=re.sub(r'\]\(([^)]+)\)',rebase,text)
    report_ref=publish_evidence(ctx,ExperimentReportWrite(experiment,sha256(raw).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(refs)))
    validation=validate_experiment(repo,ExperimentValidationRequest(experiment,
        ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value=='PASS'
    pending=(f'批准C9380按检验报告{report.reference.sha256}及计划{report.plan.sha256}首次冻结为S018-v1；不部署。',)
    payload=d.CandidateInspectionDelivery(report.reference,(report.selection,),None,pending)
    result=assemble_delivery(repo,d.DeliveryDefinition(ResearchBatchRef('S018'),d.DeliveryStage.INSPECTION,2),
        d.DeliveryContent(payload,d.DeliveryStatus.PARTIAL,(),(),('待用户精确批准并提交冻结事务。',),
            report=rebased,evidence=tuple([*refs,report_ref])),resources=ExecutionResources(2,1,17))
    assert result.validation.status is d.ValidationStatus.PASS
    a.save('others/publication_receipt.json',{'technical_status':report.status.value,
        'report':report_ref.to_dict(),'experiment_validation':validation.to_dict(),
        'assembly':result.to_dict(),'freeze':'NOT_EXECUTED','production':'NOT_TOUCHED'})
    print({'technical':report.status.value,'delivery':result.receipt.reference.to_dict(),
        'publication_validation':result.validation.status.value,'scope':result.validation.scope.value},flush=True)


if __name__=='__main__':
    main()
