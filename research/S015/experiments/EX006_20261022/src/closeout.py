"""Close the authorized inspection scope while preserving the pending freeze gate."""
from inspect_selected import ROOT, EROOT, read, save
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, update_research_intent, get_research_overview,
)
from czsc_trader.research_tools import ResearchBatchRef


def main():
    validation = read(EROOT / 'others/delivery_validation.json')
    assert validation['assembly']['status'] == validation['experiment']['status'] == 'PASS'
    assert read(EROOT / 'others/final_checks.json')['status'] == 'PASS'
    summary = read(EROOT / 'others/inspection_summary.json')
    assert summary['status'] == 'PASS'
    reference = validation['delivery']
    assert reference['stage'] == 'INSPECTION' and reference['revision'] == 1
    repository = RepositoryContext.discover(ROOT)
    batch = ResearchBatchRef('S015')
    intent = read(ROOT / 'research/registrations/S015/family.json')['research_intent']
    intent.update(
        current_phase='阶段五C0031技术检验通过，INSPECTION/1已交付，等待精确冻结批准',
        next_gate='用户批准C0031内容、检验报告、冻结计划及S015-v1后方可冻结；PTE及部署另批',
        selected_candidate='C0031', inspection_delivery_sha256=reference['content_sha256'],
        inspection_sha256=summary['inspection_sha256'], freeze_plan_sha256=summary['plan_sha256'],
    )
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent),
                           actor='RSCH', reason='用户明确选型后完成公共技术检验与待批准精确冻结方案交付')
    overview = get_research_overview(repository, batch)
    overview_value = overview.to_dict()
    save(EROOT / 'others/overview_after.json', overview_value)
    assert len(overview_value['candidates']) == 117
    assert any(row['reference'] == reference and row['status'] == 'COMPLETE'
               for row in overview_value['deliveries'])
    selected = [row for row in overview_value['candidates'] if row['key']['candidate_id'] == 'C0031']
    assert len(selected) == 1 and selected[0]['content_sha256'] == summary['content_sha256']
    path = ROOT / 'research/S015/HANDOFF.md'
    text = path.read_text(encoding='utf-8')
    marker = '\n## 阶段五技术检验完成、冻结待批准（EX006，2026-10-22）\n'
    if marker in text:
        raise RuntimeError('Phase-five closeout already appended')
    text = text.replace('- 身份RSCH；标的159326.SZ；分支`codex/159326-new-research`。用户已完成阶段三补充授权，并以“同意，这是合理的做法”批准阶段四机制覆盖与比较。',
        '- 身份RSCH；标的159326.SZ；分支`codex/159326-new-research`。用户已明确选择C0031进入阶段五；技术检验通过，精确冻结计划待批准。')
    text = text.replace('最新交付为[ASSESSMENT/1]', '阶段四交付为[ASSESSMENT/1]')
    text += marker + f'''
- 用户原文“确认选择C0031进入阶段五，请你主导执行”，公共决定`S015-select-C0031-20261022`独立关联ASSESSMENT/1与原内容。没有将选型批准扩张为冻结批准。
- [INSPECTION/1报告](deliveries/INSPECTION/1/report.md)已发布，技术8项检查全部PASS；本轮交付COMPLETE表示检验交付完整，尚未冻结。公共assemble_delivery完成本节点FULL内容、前驱INTEGRITY及发布一致性校验，实验REPORT_PUBLICATION通过；没有另行重复validate_delivery(FULL)或阶段四统计复算。
- 原标准费用及费用翻倍账户共2个完整434日坐标，使用原数据绑定；零容差下原账户重放、账本审计、候选及拟冻结运行的信号/经济账本均通过。未修改候选、参数、原证据，也未增加行情或搜索。
- 候选内容：`{summary['content_sha256']}`；技术检验报告：`{summary['inspection_sha256']}`；冻结计划：`{summary['plan_sha256']}`；INSPECTION/1：`{reference['content_sha256']}`。
- 拟冻结S015-v1，无父版本；选择截止2026-10-21，前瞻数据分界2026-10-22。后者不是PTE或生产启用日期，没有读取分界之后行情。
- [精确批准对象](experiments/EX006_20261022/others/freeze_approval_subject.json)、[冻结计划](experiments/EX006_20261022/others/freeze_plan.json)、[检验明细](experiments/EX006_20261022/others/inspection_report.json)、[发布验证](experiments/EX006_20261022/others/delivery_validation.json)、[研究概览](experiments/EX006_20261022/others/overview_after.json)。
- 已见样本、选择偏差、重抽样区间跨零、持有天数未扰动、日范围成交不计量、历史17:30数据链未认证、周期资金合同等风险全部保留。技术检验不增加独立收益证据或未来风险保证。
- 正式资产位于`assets/evidence/EX006_20261022/inspection/`、该实验其他evidence、`assets/decisions/`和`assets/deliveries/INSPECTION/1/`，必须独立保留。原账户及原候选资产继续保留；仅Git不足以恢复。
- 当前下一步：请用户对上述候选、内容、检验报告、计划及S015-v1精确批准，获批后执行冻结并交付新修订。PTE、部署、生产、合并master、tag及推送均未执行。前文尚未选型/阶段五未开始等表述仅为历史时点。
'''
    path.write_text(text, encoding='utf-8', newline='\n')
    save(EROOT / 'others/closeout.json', {'status': 'COMPLETE_PENDING_FREEZE_APPROVAL', 'delivery': reference})
    print({'closed_out': reference, 'freeze': 'PENDING_EXACT_USER_APPROVAL'}, flush=True)


if __name__ == '__main__':
    main()
