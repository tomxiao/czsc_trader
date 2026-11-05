"""Publish stage-five completion from the committed exact-package receipt."""
from hashlib import sha256
from pathlib import Path
import os
import re

import freeze as a
from czsc_trader.application import (RepositoryContext, create_research_context, get_freeze_result,
    publish_evidence, validate_experiment, assemble_delivery, get_research_overview)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest,
    ExperimentValidationScope, ExecutionResources)
from czsc_trader.research_tools import delivery as d
from strategy_manager import StrategyRegistry, freeze_contracts as f


def main():
    repo=RepositoryContext.discover(a.ROOT)
    experiment=ExperimentRef('S018',a.EXP.name)
    batch=ResearchBatchRef('S018')
    ctx=create_research_context(repo,batch,resources=ExecutionResources(2,1,17))
    report=f.CandidateInspectionReport.from_dict(a.read(a.EXP/'others/inspection_report.json'))
    request=f.FreezeCandidateRequest.from_dict(a.read(a.EXP/'others/freeze_01/request.json'))
    receipt=f.FreezeReceipt.from_dict(a.read(a.EXP/'others/freeze_01/receipt.json'))
    assert get_freeze_result(repo,request.request_id)==receipt
    assert receipt.status is f.FreezeStatus.COMMITTED
    assert receipt.version.package_hash==report.release.package_sha256
    qualification=StrategyRegistry(repo.strategy_root).current_qualification('S018','v1').value
    assert qualification=='RESEARCH'
    previous=EvidenceRef.from_dict(a.read(a.EXP/'report_ref.json')['report'])
    assert previous.sha256=='be747d8361a769cb0a5170633bbffa1150d4369a48740961770a77b70f5e4edd'
    destination=a.ROOT/'research/S018/deliveries/INSPECTION/3'
    assert not destination.exists()
    a.save_new(a.EXP/'others/freeze_01/previous_report_reference.json',previous.to_dict())
    summary=a.read(a.EXP/'others/technical_summary.json')
    text=f'''# S018/C9380 阶段五完成：已冻结 S018-v1

Status: COMPLETE_FROZEN

## 结论

用户在精确计划呈现后明确回复“同意冻结”。RSCH 记录该批准，按原技术检验通过的计划提交同一发布包，冻结事务返回 **COMMITTED**，随后通过同一请求查询核对真实回执，并校验冻结包与受检包身份完全一致。**S018/C9380 阶段五目标已达成。**

正式版本为 **S018-v1**，原生 V4（ACCOUNT_REPLAY），初始资格 **{qualification}**。本次是研究版本冻结，未部署、未绑定账户、未升级生产代码或启动交易。前瞻起始日 2026-11-06 仍是已批准版本元数据，不代表生产生效日期。

## 批准、冻结及核验

| 项目 | 结果 |
| --- | --- |
| 用户批准 | 同意冻结；见 [批准原文及精确对象](protocols/freeze_01/user_approval.json) |
| 冻结请求 | `{request.request_id.value}` |
| 事务状态 | COMMITTED |
| 候选内容 | `{report.origin.content_sha256}` |
| 技术检验报告 | `{report.reference.sha256}` |
| 获批计划 | `{report.plan.sha256}` |
| 版本哈希 | `{receipt.version.release_hash}` |
| 发布包哈希 | `{receipt.version.package_hash}` |

[事务回执](others/freeze_01/receipt.json)、[包核验结果](others/freeze_01/verification.json)、[批准决定引用](others/freeze_01/approval_reference.json)和[实际请求](others/freeze_01/request.json)保留完整关联；没有更换候选、参数或包内容。

实际版本见 [v1.json](../../../../strategies/S018/versions/v1.json)，包清单见 [release_manifest.json](../../../../strategies/S018/releases/v1/release_manifest.json)。源实验 EX063 是候选产生来源，EX068 是本次技术检验及冻结事务来源，二者职责不同。

## 沿用的技术证据

本次冻结复用已经完成的正式技术检验，不重跑策略：候选及最终格式包在原窗口的 {summary['counts']['decisions']} 个决策点、{summary['counts']['orders']} 个订单、{summary['counts']['fills']} 笔成交、{summary['counts']['trades']} 个闭合周期及最终策略状态精确一致；6 个隔离 PTE 场景全部 PASS，覆盖部分成交、重复回报、重启、拒单、结果未知、过期、对账阻断及连续两周期补仓/退出。

MU/SOXX 后复权辅助价格用于信号观察，MU 未复权价格用于报价、成交和估值；每侧 0.1% 费用及公司行动合同保持不变。全部正式技术输入和场景见 [原技术检验交付](../../deliveries/INSPECTION/2/report.md)。PTE 录制回报仍是隔离合成通道事实，不是券商真实成交。

## 历史保留、边界与下一步

- [INSPECTION/1](../../deliveries/INSPECTION/1/report.md)保留原平台阻断事实；[INSPECTION/2](../../deliveries/INSPECTION/2/report.md)保留通过检验但等待批准时的原报告及精确计划；本次新增 INSPECTION/3，状态 COMPLETE，无待决定的冻结事项。
- 本实验研究报告显式引用前一报告版本，旧材料和证据不覆盖；阶段四 ASSESSMENT/2 及候选资格不变，没有新增搜索或经济验收。
- 独立前瞻业绩与阶段四披露的样本复用、时点可得性、跨时期稳定性限制保持。技术通过及冻结不意味着未来经济表现已验证。
- 当前 V4 隔离路径支持限价买入及限价/市价卖出。市价买入和带前置依赖的订单明确拒绝，C9380 不使用这些表达。
- 富途美股模拟通道、旧冻结策略原地升级及生产停机升级/重绑/部署仍是后续独立事项。本次不更新生产配置或账户。

建议下一步由 DEV 推进第 2 项富途美股模拟交易渠道，使后续生产维护与部署具备渠道条件；具体实施和生产变更分别按授权执行。
'''
    raw=text.encode('utf-8')
    (a.EXP/'report.md').write_bytes(raw)
    paths=[a.EXP/'src/freeze.py',a.EXP/'src/closeout_freeze.py',
        *sorted((a.EXP/'protocols/freeze_01').glob('*.json')),
        *sorted((a.EXP/'others/freeze_01').glob('*.json'))]
    refs=[previous]
    for path in paths:
        media='text/x-python' if path.suffix=='.py' else 'application/json'
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(experiment,'freeze-'+path.stem,
            path.read_bytes(),media,path.suffix[1:])))
    report_ref=publish_evidence(ctx,ExperimentReportWrite(experiment,sha256(raw).hexdigest(),
        ExperimentOutcome.COMPLETED,tuple(refs),previous=previous))
    validation=validate_experiment(repo,ExperimentValidationRequest(experiment,ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value=='PASS'
    def rebase(match):
        target=(a.EXP/match.group(1)).resolve()
        assert target.is_relative_to(a.ROOT) and target.exists(),match.group(1)
        return ']('+Path(os.path.relpath(target,destination)).as_posix()+')'
    rebased=re.sub(r'\]\(([^)]+)\)',rebase,text)
    result=assemble_delivery(repo,d.DeliveryDefinition(batch,d.DeliveryStage.INSPECTION,3),
        d.DeliveryContent(d.CandidateInspectionDelivery(report.reference,(report.selection,request.approval),receipt,()),
            d.DeliveryStatus.COMPLETE,(),(),report=rebased,evidence=tuple([*refs,report_ref])),
        resources=ExecutionResources(2,1,17))
    assert result.validation.status is d.ValidationStatus.PASS
    a.save_new(a.EXP/'others/freeze_01/publication_receipt.json',{
        'report':report_ref.to_dict(),'experiment_validation':validation.to_dict(),
        'assembly':result.to_dict(),'freeze':receipt.to_dict(),'qualification':qualification,
        'deployment':'NOT_EXECUTED','production':'NOT_TOUCHED'})
    overview=get_research_overview(repo,batch).to_dict()
    latest,=[x for x in overview['deliveries'] if x['stage']=='INSPECTION']
    assert latest['revision']==3 and latest['reference']==result.receipt.reference.to_dict()
    print({'freeze':receipt.status.value,'delivery':latest['reference'],
        'integrity':result.validation.status.value,'qualification':qualification},flush=True)


if __name__=='__main__':
    main()
