"""Retain the failed overview refresh without changing platform code or prior deliveries."""
from inspect_selected import ROOT, EROOT, context, material, read, save


def main():
    validation = read(EROOT / 'others/delivery_validation.json')
    summary = read(EROOT / 'others/inspection_summary.json')
    assert validation['assembly']['status'] == validation['experiment']['status'] == 'PASS'
    assert summary['status'] == read(EROOT / 'others/publication_checks.json')['status'] == 'PASS'
    issue = {
        'status': 'FAILED', 'operation': 'get_research_overview',
        'exception': 'ResearchOverviewError', 'code': 'INVALID_RETAINED_RECORD',
        'reported_path': 'research/S015/batch.json',
        'message': 'published evidence must be files',
        'trigger_path': 'research/S015/assets/evidence/EX006_20261022/inspection',
        'cause': 'research_overview_service._accounts rejects every evidence-owner child directory; public inspect_candidate legitimately stores ResearchEvidenceRef objects in inspection/.',
        'source': 'src/czsc_trader/application/research_overview_service.py:270-281',
        'impact': 'Fresh overview unavailable. No replacement overview or inferred counters produced. Passing inspection and immutable INSPECTION/1 remain retained.',
        'platform_changes': 'NONE', 'freeze': 'NOT_EXECUTED',
        'required_followup': 'DEV review of nested inspection-evidence compatibility and repeated cross-operation authentication costs.',
        'timing': {
            'selection_process_start_local': '2026-10-22T10:55:00+08:00',
            'inspection_process_start_local': '2026-10-22T11:12:54+08:00',
            'inspection_first_evidence_written_local': '2026-10-22T11:30:42.7690395+08:00',
            'inspection_report_written_local': '2026-10-22T11:30:52.9500340+08:00',
            'technical_evidence_write_interval_seconds': 10.1809945,
            'technical_interval_basis': 'File last-write timestamps, an estimate of the technical body, not an instrumented function benchmark.',
            'publication_seconds': validation['assembly']['elapsed_seconds'],
            'publication_observed_working_set_bytes': 24839118848,
            'mechanism': 'Each public decision/inspection/publication invocation starts its own validation session; decoded/certified account cache is not shared across invocations.',
        },
    }
    save(EROOT / 'others/overview_failure.json', issue)
    ctx = context()
    evidence = material(ctx, 'overview_closeout_failure', EROOT / 'others/overview_failure.json')
    source = material(ctx, 'source_record_closeout_issue', EROOT / 'src/record_closeout_issue.py', 'text/x-python', 'py')
    save(EROOT / 'others/overview_failure_refs.json', {'failure': evidence.to_dict(), 'source': source.to_dict()})
    path = ROOT / 'research/S015/HANDOFF.md'
    text = path.read_text(encoding='utf-8')
    marker = '\n## 阶段五检验交付完成、概览刷新失败（EX006，2026-10-22）\n'
    if marker in text:
        raise RuntimeError('Closeout issue already recorded; do not overwrite')
    text = text.replace('- 身份RSCH；标的159326.SZ；分支`codex/159326-new-research`。用户已完成阶段三补充授权，并以“同意，这是合理的做法”批准阶段四机制覆盖与比较。',
        '- 身份RSCH；标的159326.SZ；分支`codex/159326-new-research`。用户已明确选择C0031进入阶段五；技术检验及INSPECTION/1交付完成，精确冻结计划待批准；收尾概览刷新失败，详见文末。')
    text = text.replace('最新交付为[ASSESSMENT/1]', '阶段四交付为[ASSESSMENT/1]')
    text += marker + f'''
- 用户明确选择C0031进入阶段五，公共决定`S015-select-C0031-20261022`关联ASSESSMENT/1与原候选内容；没有记录冻结批准。
- [INSPECTION/1](deliveries/INSPECTION/1/report.md)已发布，8项技术检查全部PASS。标准费用及费用翻倍两个434日坐标覆盖齐全；4组信号比较、4组经济账本比较与4次账本审计全部通过，容差0。原源码、参数及输入绑定保持不变。
- 候选内容：`{summary['content_sha256']}`；技术报告：`{summary['inspection_sha256']}`；冻结计划：`{summary['plan_sha256']}`；INSPECTION/1：`{validation['delivery']['content_sha256']}`。
- 拟冻结S015-v1，无父版本；选择截止2026-10-21，前瞻数据分界2026-10-22，后者不是PTE或生产启动日期。未读取分界之后行情。
- [精确批准对象](experiments/EX006_20261022/others/freeze_approval_subject.json)、[冻结计划](experiments/EX006_20261022/others/freeze_plan.json)、[实际检查](experiments/EX006_20261022/others/inspection_report.json)、[发布验证](experiments/EX006_20261022/others/delivery_validation.json)、[公开报告核验](experiments/EX006_20261022/others/publication_checks.json)。assemble_delivery完成本节点FULL内容、前驱INTEGRITY及发布一致性检查，REPORT_PUBLICATION通过；未另行重复validate_delivery(FULL)或阶段四统计复算。
- 收尾get_research_overview失败：`INVALID_RETAINED_RECORD / published evidence must be files`。概览账户计数器拒绝任何证据子目录，与inspect_candidate合法生成的`inspection/`布局不兼容。[失败记录](experiments/EX006_20261022/others/overview_failure.json)及[公共证据引用](experiments/EX006_20261022/others/overview_failure_refs.json)已保留；没有伪造替代概览或当前计数。旧EX005概览只代表阶段四历史时点。
- 本轮耗时主要来自三个公共入口分别认证完整历史交付链，缓存仅在单次调用中复用，各次约17至18分钟；发布实际耗时{validation['assembly']['elapsed_seconds']:.3f}秒。技术检验主体首末证据落盘间隔约10.18秒，仅为文件时间估算；发布末期观测内存约25GB。平台实现未修改，建议DEV独立处理重复认证开销及概览布局兼容。
- 已见样本、选择偏差、区间跨零、持有天数未扰动、日范围成交模型、历史17:30数据链未认证及周期资金合同等限制全部保留。技术通过不增加独立收益证据。
- 实际资产：`assets/evidence/EX006_20261022/inspection/`及该实验其他evidence、`assets/runs/EX006_20261022/replay_requests.pkl`、`assets/deliveries/INSPECTION/1/`；用户决定位于`decisions/`，确认源位于`decisions/objects/`。须独立保留Git忽略的资产。
- 当前状态：技术检验和待批准交付完成；概览刷新失败；尚未冻结。下一步由用户决定精确冻结批准及DEV修复安排。冻结、PTE、部署、生产、合并master、tag及推送均未执行；前文未选型/未开始阶段五等为历史时点。
'''
    path.write_text(text, encoding='utf-8', newline='\n')
    save(EROOT / 'others/closeout.json', {
        'status': 'INSPECTION_DELIVERED_OVERVIEW_FAILED', 'delivery': validation['delivery'],
        'overview': 'FAILED', 'failure_evidence': evidence.to_dict(),
        'freeze': 'PENDING_EXACT_USER_APPROVAL',
    })
    print({'inspection': 'PASS', 'publication': 'PASS', 'overview': 'FAILED_RETAINED', 'freeze': 'PENDING_EXACT_USER_APPROVAL'}, flush=True)


if __name__ == '__main__':
    main()
