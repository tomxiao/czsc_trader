"""Publish the technical result and the separate RSCH chart review."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (RepositoryContext, assemble_delivery, create_research_context,
    publish_evidence, validate_experiment)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader import research_tools as d
from czsc_trader.research_tools import delivery as deliveries
from dataflows import ProviderConfig
from strategy_manager import freeze_contracts as f

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / '.tmp/s018-v1-stage5'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, d.ResearchBatchRef('S018'), providers=ProviderConfig(bindings={}))
    experiment = d.ExperimentRef.from_dict(read(WORK/'experiment.json'))
    exp = experiment.resolve(ROOT)
    latest = read(WORK/'latest.json')
    report = validate_inspection(ROOT, f.ResearchEvidenceRef.from_dict(latest['inspection']))
    assert report.status is f.InspectionStatus.PASS
    browser_path = exp/'others/browser_review.json'
    browser = read(browser_path)
    assert browser['status'] == 'PASS'
    chart, = [case for case in report.pte_runtime.cases if case.case_id == 'pte-forward-chart']
    outcomes = read(chart.evidence[0].resolve(ROOT))
    verified = read(report.behavior_equivalence.evidence[0].resolve(ROOT))
    counts = {key: len(rows) for key, rows in verified['candidate']['facts'].items()}
    elapsed = read(report.measurements.resolve(ROOT))['elapsed_seconds']
    rows = '\n'.join(
        f"| {name} | {value['signal_date']} | {value['snapshot']['basis'][0]['text']} | {value['action']} / {value['target_quantity']} 股 |"
        for name, value in browser['samples'].items()
    )
    pending = ('审议 S018-v1 原地升级。实际升级须另行准备并核验保留历史来源和版本号的精确计划，再取得审批。',)
    text = f"""# S018-v1 决策解释修订阶段五检验

**平台技术检验通过。RSCH 前瞻图解释核验通过。原地升级待审批。**

## 平台技术检验

C9397 候选与隔离待检包在同一历史输入和账户规则下精确一致。历史窗口为 2023-01-03 至 2026-10-30，共核对 {counts['decisions']} 个决策、{counts['orders']} 笔订单、{counts['fills']} 笔成交、{counts['account_daily']} 个日末账户及 {counts['trades']} 个闭合周期。C9396 与解释修订稿的旧新交易行为对照已单独完成，只剔除文案及实现身份派生字段，其余逐字段一致。

隔离 PTE 的 {len(outcomes['scenarios'])} 个渠道场景全部通过，新增空仓等待且无订单场景，保留原渠道回报、重启、拒单、过期和对账阻断场景。平台前瞻图检验通过，生成 {len(outcomes['forward_chart']['scenarios'])} 份含决策的可独立打开图表。对账阻断场景没有持久化决策。正式检验用时 {elapsed:.2f} 秒。

## RSCH 前瞻图核验

从实际生成的隔离图表抽样。桌面 1440 像素与窄屏 390 像素均检查默认视图的结论、关键理由和下一步关注。展开同日解释，对照保存的条件、数值、目标及有效交易日。

| 样例 | 信号日 | 默认视图判断依据 | 渠道动作及目标股数 |
| --- | --- | --- | --- |
{rows}

空仓样例的三次后复权收盘为 1,482.65、1,753.97、1,650.71。最后一日下跌，但前一日上涨，连续两日收跌条件不成立，账本决策为等待且无订单。入场样例的三次收盘连续下降，首次目标为账户权益的 50%。持有样例维持 50% 目标，渠道按权益和价格变化做再平衡卖出，解释正确区分目标与实际股数。加仓样例已到第 3 个持有日，MU 和 SOXX 均高于各自确认线，目标升至 37.5%。价格退出样例已到复核期且 1,833.2100 未超过 2,072.9632。到期样例由第 5 个交易日的时间条件触发。

门槛边界、已进入退出状态但仍有余仓等另由先前 10 个受控策略样例核验。实际浏览器样例使用留存开发池内的日期；隔离券商回报用于验证执行链路。此前 11 月 6 日的已保存决策用于独立视觉预览。平台 PASS 与上述 RSCH 对金融含义及可读性的判断分别留证。

## 待审批范围

- 候选内容 \\`{report.origin.content_sha256}\\`
- 阶段五报告 \\`{report.reference.sha256}\\`
- 隔离待检发布 \\`{report.release.release_sha256}\\`
- 隔离待检包 \\`{report.release.package_sha256}\\`

本次隔离包证明 C9397 的代码和行为。后续原地升级计划须以当前生效的 S018-v1 为基线，保留 v1、原始研究来源和历史证据，并绑定本次检验和 RSCH 核验。原地升级与 PTE 发布分别审批。
"""
    (exp/'report.md').write_text(text, encoding='utf-8')
    materials = [(browser_path, 'browser-review'),
                 (ROOT/latest['attempt']/'report.json', 'technical-report'),
                 (ROOT/latest['attempt']/'protocol.json', 'technical-protocol'),
                 (exp/'protocols/authorization.json', 'authorization'),
                 (ROOT/'.tmp/s018-v1-decision-explanation/result.json', 'old-new-equivalence')]
    refs = tuple(publish_evidence(context, d.MaterialEvidenceWrite(
        experiment, name, path.read_bytes(), 'application/json', 'json')) for path, name in materials)
    report_ref = publish_evidence(context, d.ExperimentReportWrite(
        experiment, sha256((exp/'report.md').read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED, refs))
    artifacts = tuple(d.ExperimentArtifactRef(experiment, path.relative_to(exp).as_posix(),
        sha256(path.read_bytes()).hexdigest()) for path, _ in materials if path.is_relative_to(exp))
    validated = validate_experiment(repo, d.ExperimentValidationRequest(
        experiment, d.ExperimentValidationScope.REPORT_PUBLICATION, artifacts))
    assert validated.status.value == 'PASS', validated.issues
    result = assemble_delivery(repo, deliveries.DeliveryDefinition(d.ResearchBatchRef('S018'),
        deliveries.DeliveryStage.INSPECTION, 6), deliveries.DeliveryContent(
            deliveries.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending),
            deliveries.DeliveryStatus.PARTIAL, (), (), pending, report=text, evidence=(*refs, report_ref)))
    assert result.validation.status.value == 'PASS', result.validation.issues
    print(json.dumps({'report_sha256': report_ref.sha256, 'delivery': result.receipt.reference.to_dict(),
                      'inspection': report.reference.sha256, 'elapsed_seconds': elapsed}, ensure_ascii=False))


if __name__ == '__main__':
    main()
