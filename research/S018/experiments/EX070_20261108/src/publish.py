"""Publish the bounded C9396 verification; no frozen-package transaction."""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import os
import re

import run_inspection as a
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    validate_experiment, assemble_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader import research_tools as d
from czsc_trader.research_tools import delivery as deliveries
from strategy_manager import freeze_contracts as f
from dataflows import ProviderConfig


def main():
    repo = RepositoryContext.discover(a.ROOT)
    experiment = d.ExperimentRef('S018',a.EXP.name)
    report = f.CandidateInspectionReport.from_dict(a.read(a.EXP/'others/attempt01/report.json'))
    assert report.status is f.InspectionStatus.PASS
    assert validate_inspection(a.ROOT,report.reference) == report
    assert not (a.EXP/'report_ref.json').exists(), 'Reuse the published receipt instead of publishing twice'
    behavior = a.read(report.behavior_equivalence.evidence[0].resolve(a.ROOT))
    pte = a.read(report.pte_runtime.evidence[0].resolve(a.ROOT))
    assert behavior['passed'] and behavior['candidate'] == behavior['release']
    assert not pte['coverage']['missing'] and all(s['status']=='PASS' for s in pte['scenarios'])
    counts = {key:len(value) for key,value in behavior['candidate']['facts'].items()}
    measurements = a.read(report.measurements.resolve(a.ROOT))
    old = a.read(a.EXP/'others/old_package_readiness.json')
    assert sha256((a.ROOT/'strategies/S018/versions/v1.json').read_bytes()).hexdigest() == old['version_file_sha256']
    summary = {'status':'TECHNICAL_PASS_MIGRATION_PENDING','candidate_content':report.origin.content_sha256,
        'behavior_counts':counts,'candidate_package_exactly_equal':True,'runtime':pte['runtime'],
        'pte_coverage':pte['coverage'],'scenarios':[{'id':s['case_id'],'status':s['status'],
            'decisions':len(s['facts']['decisions']),'fills':len(s['facts']['fills']),
            'account_health':s['facts']['account']['health']} for s in pte['scenarios']],
        'measurements':measurements,'inspection_reference':report.reference.to_dict(),
        'release_hash':report.release.release_sha256,'package_hash':report.release.package_sha256,
        'plan_hash':report.plan.sha256,'old_frozen_package_unchanged':True,
        'migration_status':'NOT_APPLIED','old_package_readiness':old,
        'production_writes':0,'qualification_grant':False}
    a.save(a.EXP/'others/technical_summary.json',summary)
    rows='\n'.join(f"| {s['case_id']} | {s['status']} | {len(s['facts']['decisions'])} | {len(s['facts']['fills'])} |" for s in pte['scenarios'])
    text=f'''# C9396正式执行链路补验

Status: TECHNICAL_PASS_MIGRATION_PENDING

## 结果

固定C9396内容、参数及原数据，在平台ab11bc620上正式调用`inspect_candidate`，候选与待检包行为等价、正式PTE组件运行两个目标均PASS。首轮完成，实际耗时{measurements['elapsed_seconds']:.2f}秒，最多2个worker；没有追加搜索或更改策略。报告及正式证据已核验。

本轮承接用户批准的RSCH适配与验证，使用[EX069](../EX069_20261108/report.md)已经登记的当前账户权益目标版本。原金融条件验证复用旧证据，不把当前权益比例模型解释成旧锁定入场现金模型的订单或绩效完全等价。

## 完整历史技术等价

复用DFLS管理的MU/SOXX后复权输入与MU独立未复权执行参考价。历史窗口2023-01-03至2026-10-30，初始资金100000、单边费用0.1%；历史账户使用HFQ报价、成交和估值。技术比较覆盖{counts['decisions']}个决策、{counts['orders']}笔订单、{counts['fills']}笔成交、{counts['trades']}个闭合周期及{counts['account_daily']}个日末账户。候选与待检包全部保存事实、输入及最终状态精确一致，容差为零。

这项检验比较当前候选与其包实现，不是重新搜索、旧新经济等价、阶段四自检或未来收益证明。EX069的经济结果与研究限制保持原样。

## 正式PTE组件验证

实际链路为`FormalV4AdviceClient → AccountEngine → ChannelExecution → PaperStore`。策略使用HFQ，EC独立使用RAW执行参考价。外部券商采用合成记录型网关，没有连接富途或提交真实模拟盘订单。

| 场景 | 结果 | 决策数 | 增量成交数 |
| --- | --- | ---: | ---: |
{rows}

必要覆盖无缺失。两个独立连续窗口分别为2026-08-03至08-21的15日、09-01至10-30的43日，合计58日、17笔成交，覆盖持有、目标提升、再平衡和退出。预期现金、股数和成交取自原RAW隔离证据，本轮正式组件逐场景核对通过。

明确拒单、未提交过期和正常撤余均保留健康账户，未知提交保持阻断和资金预占；对账异常由渠道阻断后续执行。部分成交、重复回报和重启不重复入账。原数据可用时点、可交易状态等研究假设继续披露，不以技术PASS声称取得真实历史停牌证据或完成富途联网验收。

## 精确身份与原地升级边界

| 身份 | SHA256 |
| --- | --- |
| C9396候选内容 | `{report.origin.content_sha256}` |
| 技术检验报告 | `{report.reference.sha256}` |
| 待检包计划 | `{report.plan.sha256}` |
| 待检发布版本 | `{report.release.release_sha256}` |
| 待检包 | `{report.release.package_sha256}` |

本次普通候选待检包在隔离目录按v1构造，来源候选为C9396；不能把它等同于未来保留旧历史来源字段的原地升级包。没有调用冻结或升级写入入口，也没有授予模拟交易资格。现有S018-v1版本文件哈希保持`{old['version_file_sha256']}`。

已知旧冻结包迁移事项仍未完成：当前公开读取入口拒绝原S018-v1，报错`{old['message']}`。现有升级准备入口会先使用该读取入口，因此正式组件补验通过不等于升级事务已可提交。这属于此前分开的旧包迁移事项，不是本轮新增交易规则要求。RSCH负责新策略实现、差异解释及研究验证；平台迁移入口需能在核对旧包原始身份后接受当前候选，不能要求待迁移的旧定义先满足新运行合同。

## 交付与下一步

本轮C9396适配后的正式链路验证目标已达成。INSPECTION/4记录技术PASS、迁移待完成，不覆盖或撤销旧交付。下一步先落实旧包读取与原地升级事务边界，再准备保留历史字段的精确升级包；不能将普通候选包直接覆盖真实v1。生产部署和账户重绑属于后续DEV停机维护工作。

[技术摘要](others/technical_summary.json) · [检验报告](others/attempt01/report.json) · [协议](others/attempt01/protocol.json) · [只读旧包核对](others/old_package_readiness.json) · [范围](protocols/scope.md)
'''
    (a.EXP/'report.md').write_text(text,encoding='utf-8',newline='\n')
    context=create_research_context(repo,d.ResearchBatchRef('S018'),providers=ProviderConfig(bindings={},equity_bindings={}))
    refs=[]
    artifacts=[]
    for folder in ('src','protocols','others'):
        for path in sorted((a.EXP/folder).rglob('*')):
            if not path.is_file() or path.suffix not in ('.py','.json','.md') or path.name=='publication_receipt.json':
                continue
            label=path.relative_to(a.EXP).with_suffix('').as_posix().replace('/','-')
            refs.append(publish_evidence(context,d.MaterialEvidenceWrite(experiment,label,path.read_bytes(),
                {'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[path.suffix],path.suffix[1:])))
            artifacts.append(d.ExperimentArtifactRef(experiment,path.relative_to(a.EXP).as_posix(),sha256(path.read_bytes()).hexdigest()))
    report_ref=publish_evidence(context,d.ExperimentReportWrite(experiment,
        sha256((a.EXP/'report.md').read_bytes()).hexdigest(),d.ExperimentOutcome.COMPLETED,tuple(refs)))
    validation=validate_experiment(repo,d.ExperimentValidationRequest(experiment,d.ExperimentValidationScope.REPORT_PUBLICATION,tuple(artifacts)))
    assert validation.status.value=='PASS', validation.issues
    destination=a.ROOT/'research/S018/deliveries/INSPECTION/4'
    assert not destination.exists()
    def rebase(match):
        value=match.group(1)
        path,sep,anchor=value.partition('#')
        target=(a.EXP/path).resolve()
        assert target.is_relative_to(a.ROOT) and target.exists()
        return ']('+Path(os.path.relpath(target,destination)).as_posix()+(sep+anchor if sep else '')+')'
    pending=('旧冻结包读取与原地升级事务尚未完成；需准备保留历史元数据的精确升级包。本普通候选待检包不得直接覆盖现有v1。',)
    payload=deliveries.CandidateInspectionDelivery(report.reference,(report.selection,),None,pending)
    result=assemble_delivery(repo,deliveries.DeliveryDefinition(d.ResearchBatchRef('S018'),deliveries.DeliveryStage.INSPECTION,4),
        deliveries.DeliveryContent(payload,deliveries.DeliveryStatus.PARTIAL,(),(),pending,
            report=re.sub(r'\]\(([^)]+)\)',rebase,text),evidence=tuple([*refs,report_ref])))
    assert result.validation.status.value=='PASS'
    a.save(a.EXP/'others/publication_receipt.json',{'report':report_ref.to_dict(),
        'validation':asdict(validation),'delivery':result.to_dict()})
    print(json.dumps({'report_publication':validation.status.value,'delivery_validation':result.validation.status.value,
        'report':report_ref.sha256,'delivery':result.receipt.reference.to_dict()},ensure_ascii=False))


if __name__=='__main__':
    main()
