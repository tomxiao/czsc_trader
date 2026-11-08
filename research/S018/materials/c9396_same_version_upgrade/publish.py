"""Publish same-version upgrade completion without rewriting prior inspection evidence."""
from pathlib import Path
import json
import os
import re

import upgrade as a
from czsc_trader.application import assemble_delivery, create_research_context, publish_evidence
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import EvidenceRef, MaterialEvidenceWrite, ResearchBatchRef
from czsc_trader.research_tools import delivery as d
from dataflows import ProviderConfig
from strategy_manager.freeze_contracts import ResearchEvidenceRef


def main():
    repo = a.RepositoryContext.discover(a.ROOT)
    result = a.read(a.HERE / 'result.json')
    assert result['status'] == 'COMMITTED' and all(result['checks'].values())
    reference = ResearchEvidenceRef.from_dict(result['inspection'])
    inspection = validate_inspection(a.ROOT, reference)
    candidate = a.load_candidate(repo, a.CandidateKey('S018', 'C9396'))
    manifest, version = a.check_package(repo, candidate)
    assert manifest['package_hash'] == result['migrated']['package_hash']
    assert version.release_hash == result['migrated']['release_hash']
    ResearchEvidenceRef.from_dict(result['evidence']).resolve(a.ROOT)
    prepared = a.read(a.HERE / 'prepared.json')
    receipt_path = a.ROOT / result['receipt_path']
    receipt = a.read(receipt_path)
    assert receipt['status'] == 'COMMITTED' and receipt['migrated'] == result['migrated']
    text = f'''# S018-v1 同版本原地升级完成

Status: COMMITTED

2026-11-08，根据用户对“切回RSCH，完成已授权的S018-v1原地升级”的确认，已通过平台同版本升级API将S018-v1替换为C9396实现。版本号仍为v1，原始研究来源C9380、EX063_20261104、父版本及历史日期保持。新实现身份为C9396，发布哈希和包哈希已更新。

## 完成情况

- 新包源码、策略定义及候选内容哈希与已验证的C9396精确一致，当前运行合同加载通过。
- 准备包、实际发布包与DEV隔离演练的预期身份一致。
- 原冻结包、版本记录和原本地安装记录完整保存在升级归档中；提交回执核验通过。
- 同一升级重复调用返回同一已完成结果；历史字段核对通过。
- 本地安装记录随包同步更新；没有修改PTE prod、渠道账户、账户绑定或生命周期授权记录。新发布身份资格为RESEARCH，未自动继承旧身份的模拟交易许可。

## 验证依据与边界

复用[EX069适配及金融条件验证](../../experiments/EX069_20261108/report.md)和[EX070正式组件技术检验](../../experiments/EX070_20261108/report.md)：961个决策、444笔订单、418笔成交、95个闭合周期的候选与待检包事实精确一致；9个隔离PTE场景通过，包括两个合计58个交易日的连续窗口。本次未新增参数搜索、账户绩效评价或阶段四自检。

EX070普通候选待检包与本次保留历史元数据的升级包具有不同的发布身份。本次确认其策略源码、定义和候选内容一致，没有将旧待检包哈希冒称为升级包哈希。金融条件及参数保持；旧入场锁定现金与当前账户权益目标比例之间的再平衡、目标提升和退出状态差异继续按EX069解释，不宣称新旧经济等价。

平台修复c4ac86237已完成57项聚焦测试及真实S018旧包/C9396隔离升级和回滚演练。本次实际升级成功并核验重复调用，没有对正式冻结版本注入故障或执行回滚。

## 精确身份

| 项目 | SHA256 |
| --- | --- |
| C9396内容 | `{result['candidate_content_sha256']}` |
| 原发布 | `{result['original']['release_hash']}` |
| 新发布 | `{result['migrated']['release_hash']}` |
| 新包 | `{result['migrated']['package_hash']}` |
| 升级计划 | `{prepared['plan_sha256']}` |
| 既有技术检验报告 | `{reference.sha256}` |

[升级结果](result.json) · [精确计划](prepared.json) · [平台提交回执](../../../../{result['receipt_path']})

本次原地升级目标已完成。[INSPECTION/4](../../deliveries/INSPECTION/4/report.md)及EX069、EX070原报告保留；本修订补充升级已完成的事实。同版本升级回执通过独立升级API产生，以材料证据关联，不伪造首次冻结流程的FreezeReceipt。后续由DEV安排获批的部署与账户重绑；本次不自动启动生产变更。
'''
    report_path = a.HERE / 'report.md'
    report_path.write_text(text, encoding='utf-8', newline='\n')
    context = create_research_context(repo, ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    refs = []
    for path in (a.HERE / 'upgrade.py', a.HERE / 'publish.py', a.HERE / 'prepared.json',
                 a.HERE / 'result.json', receipt_path, report_path):
        media = {'.py': 'text/x-python', '.json': 'application/json', '.md': 'text/markdown'}[path.suffix]
        refs.append(publish_evidence(context, MaterialEvidenceWrite(a.EXPERIMENT,
            'c9396-upgrade-' + path.stem, path.read_bytes(), media, path.suffix[1:])))
    refs.append(EvidenceRef.from_dict(a.read(a.EXP / 'report_ref.json')['report']))
    destination = a.ROOT / 'research/S018/deliveries/INSPECTION/5'
    assert not destination.exists(), 'Read existing publication before any retry'

    def rebase(match):
        target = (a.HERE / match.group(1)).resolve()
        assert target.is_relative_to(a.ROOT) and target.exists()
        return '](' + Path(os.path.relpath(target, destination)).as_posix() + ')'

    delivery = assemble_delivery(repo,
        d.DeliveryDefinition(ResearchBatchRef('S018'), d.DeliveryStage.INSPECTION, 5),
        d.DeliveryContent(d.CandidateInspectionDelivery(reference, (inspection.selection,), None, ()),
            d.DeliveryStatus.COMPLETE, (), (), report=re.sub(r'\]\(([^)]+)\)', rebase, text),
            evidence=tuple(refs)))
    assert delivery.validation.status.value == 'PASS'
    a.save('publication.json', {'delivery': delivery.to_dict(), 'evidence': [r.to_dict() for r in refs]})
    print(json.dumps({'status': 'COMMITTED', 'delivery': delivery.receipt.reference.to_dict(),
        'validation': delivery.validation.status.value}, ensure_ascii=False))


if __name__ == '__main__':
    main()
