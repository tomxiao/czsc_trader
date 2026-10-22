"""Publish stage-five inspection and a concrete pending freeze decision."""
import argparse
from hashlib import sha256
from time import perf_counter

from inspect_selected import (
    ROOT, EROOT, EXPERIMENT, ASSESSMENT, CONTENT, context, read, save, material,
)
from czsc_trader.application import assemble_delivery, publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope, ResearchBatchRef,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f

LABELS = {
    'CONTENT': '登记内容、源码与依赖', 'PACKAGE': '发布包源码和安装闭包',
    'RUNTIME': '候选及拟冻结运行契约', 'COVERAGE': '原账户覆盖',
    'REPRODUCTION': '原账户重放', 'LEDGER_AUDIT': '账本审计',
    'LEDGER_EQUIVALENCE': '经济账本等价', 'SIGNAL_EQUIVALENCE': '信号等价',
}


def inputs():
    report = f.CandidateInspectionReport.from_dict(read(EROOT / 'others/inspection_report.json'))
    assert report.origin.content_sha256 == CONTENT
    assert report.reference.resolve(ROOT).is_file()
    assert f.CandidateInspectionReport.from_dict(read(report.reference.resolve(ROOT))) == report
    source = d.DeliveryReceipt.from_dict(read(ROOT / 'research/S015/deliveries/ASSESSMENT/1/receipt.json')).reference
    assert source.content_sha256 == ASSESSMENT
    assert report.selection == f.DecisionReference.from_dict(read(EROOT / 'others/selection_ref.json'))
    return report, source


def report_text(report):
    passing = report.status is f.InspectionStatus.PASS
    lines = [
        '# S015阶段五：C0031技术检验与待批准冻结方案', '',
        f'技术检验结果：**{report.status.value}**。'
        + ('C0031原内容与拟冻结v1在声明的两个原账户场景中通过技术一致性检查。' if passing else
           '原样保留失败或未完成检查，当前不能批准冻结。'),
        '本次完成用户已授权的技术检验及方案准备；尚未执行冻结，PTE、部署及生产也未启动。', '',
        '## 选型、内容与精确冻结对象', '',
        '用户原文：“确认选择C0031进入阶段五，请你主导执行”。选型独立记录于公共决定API，'
        '关联已审阅的[ASSESSMENT/1](../../deliveries/ASSESSMENT/1/report.md)。', '',
        '| 对象 | 精确身份 |', '|---|---|',
        '| 候选 | S015-C0031 |', f'| 候选内容SHA256 | `{report.origin.content_sha256}` |',
        f'| 选型决定 | `{report.selection.decision_id}` |',
        f'| 来源ASSESSMENT/1内容SHA256 | `{ASSESSMENT}` |',
        f'| 技术检验报告SHA256 | `{report.sha256}` |',
    ]
    if report.plan:
        plan = report.plan
        lines.extend([
            f'| 冻结计划SHA256 | `{plan.sha256}` |', f'| 拟冻结版本 | S015-{plan.version}，首次版本，无父版本 |',
            f'| 选择数据截止 | {plan.selection_data_cutoff} |',
            f'| 前瞻数据分界 | {plan.forward_start} |', '',
            '前瞻数据分界仅表示截止日之后的信息，不是PTE或生产实际启用日期。'
            '当前没有读取该分界之后的行情；后续实际运行及观察期需独立留证。', '',
            '精确对象见[机器检验报告](others/inspection_report.json)、[冻结计划](others/freeze_plan.json)'
            '和[待批准对象](others/freeze_approval_subject.json)。冻结执行前须再次核验原件身份。',
        ])
    lines += ['', '## 策略表达与执行合同', '',
        '压力信号为收盘价除以日成交额/成交量，再减1。空仓意图且压力≤0时入场；'
        '持有意图下，前一日信号年龄已达3日或压力≥0.5%时退出，否则延续。'
        '退出当日不重入；振幅门关闭。参数保持entry=0、exit=0.005、max_days=3、range_cap=0。', '',
        '沿用full_available_cash周期目标：入场按可用现金建立周期目标，后续可补齐原目标；'
        '不逐日重新计算权益比例。年龄按信号意图而非实际成交计数。10万元初始资金、只做多、'
        '不杠杆、100份整数手、0.001价格步长；T日决策、T+1执行，买限价为信号收盘价上浮1%，卖市价，'
        '单笔上限100万份、名义涨跌幅界10%。不强制期末平仓。', '',
        '## 技术检验范围与结果', '',
        '事前[检验协议](protocols/inspection.json)固定标准单边费用0.1%与翻倍费用0.2%两个场景。'
        '二者均覆盖2025-01-02至2026-10-21共434个交易日，另有75日预热。'
        '标准账户来自EX003，压力账户来自EX005；不搜索新参数、不增加样本。', '',
        '原始request、数据fingerprint、输入绑定与费用字段先行核对，随后公共inspect_candidate认证'
        '原账户属于所选阶段四交付，并重跑候选及拟冻结版本。协议容差为0；账本比较采用平台ECONOMIC语义，'
        '排除运行身份等非经济标识，不宣称整份结果文件字节相同。', '',
        '| 检查 | 状态 | 实际检查说明 |', '|---|---|---|',
    ]
    for check in report.checks:
        lines.append(f'| {LABELS[check.check.value]} | {check.status.value} | {check.detail.replace(chr(10), " ").replace("|", "/")} |')
    lines += ['', '检验原始明细、绑定、信号与账本对照由机器报告中的ResearchEvidenceRef关联；'
              '报告与计划均为公共API实际返回值，不手工改写检查结论。', '',
              '## 既有绩效与研究边界', '',
              '以下数值沿用阶段四，不是新增收益发现：标准净年化47.9331%、最大回撤15.0687%、'
              '104笔闭合交易；滚动60日交易数中位数15，375/375窗口至少3笔。基准净年化16.9387%、'
              '最大回撤36.2900%。32/32满足参数联合经济条件，且32/32满足绝对回撤上限，费用翻倍净年化31.2489%。'
              'C0031/C0200为事前政策首层首档；用户已选择C0031。', '',
              '技术通过说明身份、输入和执行一致性在声明范围内成立，不增加独立统计证据。', '']
    lines += [f'- {risk}' for risk in report.remaining_risks]
    lines += ['', '## 交付状态与下一步', '',
              '本次待批准检验交付业务状态为' + ('COMPLETE' if passing else 'BLOCKED') +
              '；COMPLETE表示本轮检验交付完整，不表示策略已冻结。'
              '发布成功意味着assemble_delivery完成本节点FULL内容检查、前驱INTEGRITY递归检查及发布一致性检查。'
              '本轮未另行调用validate_delivery(FULL)，没有重复运行已保留的阶段四统计复算。'
              '实验REPORT_PUBLICATION结果和发布回执另存于发布校验文件；实际状态以回执为准。', '',
              '按[RSCH阶段五规则](../../../RSCH_AGENT.md#45-阶段五技术检验与获批冻结)：'
              '“执行冻结要求完整计划、检验通过，并取得用户对候选、内容、检验报告、计划及版本的精确批准”。'
              + ('建议批准本报告列出的C0031原内容、检验报告、冻结计划及S015-v1后执行冻结，并发布INSPECTION新修订；部署和PTE另行批准。'
                 if passing else '本次不可冻结，下一步须依据保留的失败检查处理后再行检验。'), '',
              '正式数据、重放请求、检验资产、决定与不可变交付须独立保留。Git只覆盖源码、协议和公开报告等部分材料。', '']
    return '\n'.join(lines)


def preview():
    report, _ = inputs()
    if (EROOT / 'report_ref.json').exists():
        raise RuntimeError('Published report cannot be changed')
    if report.plan:
        subject = f.FreezeSubject(report.origin.candidate, report.origin.content_sha256,
                                 report.reference, report.plan.sha256, report.plan.version)
        save(EROOT / 'others/freeze_approval_subject.json', subject.to_dict())
    text = report_text(report)
    (EROOT / 'report.md').write_text(text, encoding='utf-8', newline='\n')
    save(EROOT / 'others/publication_precheck.json', {
        'status': 'READY_FOR_REVIEW', 'inspection_status': report.status.value,
        'inspection_sha256': report.sha256, 'report_sha256': sha256(text.encode()).hexdigest(),
        'freeze': 'PENDING_EXACT_USER_APPROVAL',
    })
    print({'preview': report.status.value, 'report': 'research/S015/experiments/EX006_20261022/report.md'}, flush=True)


def publish():
    report, source = inputs()
    if (ROOT / 'research/S015/deliveries/INSPECTION/1').exists():
        raise RuntimeError('INSPECTION/1 already published')
    precheck = read(EROOT / 'others/publication_precheck.json')
    raw_report = (EROOT / 'report.md').read_bytes()
    assert sha256(raw_report).hexdigest() == precheck['report_sha256']
    assert precheck['inspection_sha256'] == report.sha256
    final_checks = read(EROOT / 'others/final_checks.json')
    assert final_checks['status'] == 'PASS'
    for name, digest in final_checks['source_hashes'].items():
        assert sha256((EROOT / 'src' / name).read_bytes()).hexdigest() == digest
    ctx = context()
    refs = {name: EvidenceRef.from_dict(value) for name, value in read(EROOT / 'others/prepared.json')['references'].items()}
    for path in sorted((EROOT / 'src').glob('*.py')):
        refs['source_' + path.stem] = material(ctx, 'source_' + path.stem, path, 'text/x-python', 'py')
    names = ['inspection_report', 'inspection_summary', 'selection_ref', 'publication_precheck',
             'final_checks', 'method_review', 'original_audit_precheck']
    if report.plan:
        names += ['freeze_plan', 'freeze_approval_subject']
    for name in names:
        refs[name] = material(ctx, name, EROOT / 'others' / f'{name}.json')
    for index, item in enumerate(read(EROOT / 'protocols/inspection.json')['references']):
        refs[f'original_account_{index}'] = d.EvaluationEvidenceRef.from_dict(item).evidence
    outcome = ExperimentOutcome.COMPLETED if report.status is f.InspectionStatus.PASS else ExperimentOutcome.INCOMPLETE
    report_ref = publish_evidence(ctx, ExperimentReportWrite(EXPERIMENT, sha256(raw_report).hexdigest(), outcome, tuple(refs.values())))
    pending = (('是否批准冻结S015-C0031原内容、指定技术检验报告、精确计划及S015-v1；PTE及部署另行批准。',)
               if report.status is f.InspectionStatus.PASS else
               ('技术检验未通过；请审阅失败或未完成检查，决定修复补证后重新检验或暂不推进，当前不可冻结。',))
    payload = d.CandidateInspectionDelivery(source, report, refs['inspection_report'], (report.selection,), None, pending)
    status = d.DeliveryStatus.COMPLETE if report.status is f.InspectionStatus.PASS else d.DeliveryStatus.BLOCKED
    facts = (d.FactValue('technical_checks_passed', sum(x.status is f.InspectionStatus.PASS for x in report.checks),
                        'checks', d.FactStatus.AVAILABLE, (refs['inspection_report'],)),)
    text = raw_report.decode('utf-8').replace('](others/', '](../../../experiments/EX006_20261022/others/')
    text = text.replace('](protocols/', '](../../../experiments/EX006_20261022/protocols/')
    text = text.replace('](../../deliveries/ASSESSMENT/', '](../../ASSESSMENT/')
    text = text.replace('](../../../RSCH_AGENT.md', '](../../../../RSCH_AGENT.md')
    start = perf_counter()
    receipt = assemble_delivery(ctx.repository,
        d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.INSPECTION, 1, (source,)),
        d.DeliveryContent(payload, status, facts, (), () if status is d.DeliveryStatus.COMPLETE else ('技术检验未通过',),
                          report=text, evidence=(*refs.values(), report_ref)))
    assembly_seconds = perf_counter() - start
    experiment = validate_experiment(ctx.repository, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT / 'others/delivery_validation.json', {
        'delivery': receipt.reference.to_dict(),
        'assembly': {'status': 'PASS', 'entrypoint': 'assemble_delivery',
                     'scope': 'new-node FULL content, predecessor INTEGRITY recursion, published manifest/support/recheck',
                     'elapsed_seconds': assembly_seconds},
        'separate_validate_delivery_full': 'NOT_REPEATED',
        'experiment': experiment.to_dict(), 'report': report_ref.to_dict(),
        'material_refs': {key: value.to_dict() for key, value in refs.items()},
    })
    assert experiment.status.value == 'PASS'
    print({'delivery': receipt.reference.to_dict(), 'assembly': 'PASS', 'experiment': experiment.status.value}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preview', 'publish'))
    args = parser.parse_args()
    {'preview': preview, 'publish': publish}[args.mode]()
