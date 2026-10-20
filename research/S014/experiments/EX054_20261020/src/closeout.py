"""Update current research navigation only after both formal FULL checks pass."""
from copy import deepcopy
from hashlib import sha256

from czsc_trader.application import RepositoryContext, ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from run_stage4 import ROOT, EX, context, publish, read, write


def main():
    succession = read(EX / 'others/candidate_succession.json')
    assessment = read(EX / 'others/assessment_delivery.json')
    assert succession['validation']['status'] == assessment['validation']['status'] == 'PASS'
    assert succession['validation']['scope'] == assessment['validation']['scope'] == 'FULL'
    comparison = assessment['comparison']
    assert comparison['rows'][0]['status'] == 'RANKED'
    assert comparison['rows'][0]['candidate']['candidate_id'] == 'S014-C9524'
    assert all(x['value'] is not None and x['status'] == 'AVAILABLE'
               for x in read(EX / 'others/assessment_panel.json')['rows'][0]['diagnostics'])
    assert read(EX / 'protocols/report_copy_verification.json')['byte_equal']
    report = ROOT / 'research/S014/deliveries/ASSESSMENT/1/report.md'
    assert report.read_bytes() == (EX / 'others/report.md').read_bytes()
    ctx = context()
    evidence = {name: publish(ctx, EX / name, 'ex054-closeout-' + (EX / name).stem).to_dict()
                for name in ('others/assessment_delivery.json', 'others/candidate_succession.json',
                             'protocols/report_copy_verification.json', 'others/report.md')}
    family_path = ROOT / 'research/registrations/S014/family.json'
    before = read(family_path)
    intent = deepcopy(before['research_intent'])
    intent.update(stage='阶段四自检已完成，建议暂缓冻结，待用户决定新时段验证或阶段五选型',
        candidates=succession['delivery']['reference'], assessment=assessment['receipt']['reference'],
        strategy_accounts=70, all_targets_pass_count=1, phase_four_approved=True,
        phase_four_complete=True, phase_five_approved=False,
        conclusion='C9524与原C9521经济等价且原目标仍达标；32个固定扰动全部原目标通过0/32，参数和时段稳健性不足，建议暂缓冻结。',
        pending=['请用户决定先制定新时段前向验证方案，或明确选择C9524仅进入阶段五技术检验；新增窗口和精确冻结另行批准。'])
    intent['stage4_20261020'] = {
        'authorization': '验收通过，请合并当前分支到研究分支，继续完成S014的后续工作',
        'status': 'COMPLETE_PHASE_FOUR_NOT_FROZEN',
        'original_candidate': 'S014-C9521', 'equivalent_successor': 'S014-C9524',
        'registered_candidates': 70, 'distinct_qualified_economic_centers': 1,
        'new_valid_accounts': 34, 'retained_technical_rejections': 2,
        'new_market_calls': 0, 'new_model_fits': 0, 'production_writes': 0,
        'parameter_points': 32, 'parameter_all_original_targets_pass': 0,
        'family_paths': 157, 'recovered_raw_attempts': 178,
        'candidate_delivery': succession['delivery']['reference'],
        'assessment_delivery': assessment['receipt']['reference'], 'evidence': evidence,
        'all_history_seen': True, 'freeze_authorized': False, 'pte_ready': False,
    }
    update_research_intent(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'),
        ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='用户验收DEV并授权合并返回研究继续；正式完成C9524等价接续及阶段四五项自检，原达标不撤销，建议暂缓冻结，未推进阶段五或生产。')
    after = read(family_path)
    changed = {key for key in set(before['research_intent']) | set(after['research_intent'])
               if before['research_intent'].get(key) != after['research_intent'].get(key)}
    allowed = {'stage', 'candidates', 'assessment', 'strategy_accounts', 'all_targets_pass_count',
               'phase_four_approved', 'phase_four_complete', 'phase_five_approved',
               'conclusion', 'pending', 'stage4_20261020'}
    assert changed <= allowed
    handoff = ROOT / 'research/S014/HANDOFF.md'
    original = handoff.read_bytes()
    prefix = '''# S014当前入口：阶段四已完成，建议暂缓冻结

## 2026-10-20阶段四收口

- 身份RSCH，研究分支`codex/s014-jinniu-research`；已按用户授权合并验收通过的DEV提交至`b02fbceb`，本轮不涉及master、tag、推送或生产。
- 最新阶段三为[CANDIDATES/15](deliveries/CANDIDATES/15/report.md)，保留原69条并登记C9524，共70条；C9524为C9521窗口契约2及10数值接口的精确经济等价接续，唯一阶段四交接中心。C9521原身份/达标/账本不改，不算两项独立发现。
- 最新阶段四为[ASSESSMENT/1](deliveries/ASSESSMENT/1/report.md)，两项交付FULL校验均PASS。原七年收益与严格回撤均7/7、92闭合/1642×60=3.3617539586仍达标。
- 标准净年化51.8799%、全期回撤25.6133%；固定32组5%域宽总距离扰动，年化Q10为13.0635%、回撤Q90为48.3793%，全部原目标通过0/32，2025收益失败30点。诊断不新增硬门，不撤销中心资格。
- 滚动一年超额Q10为−12.4046个百分点；盈利46笔中的前5笔贡献正利润66.4055%；费用加倍年化损失4.2107个百分点；重抽样年化超额95%区间−2.8431至70.7935个百分点。157条恢复路径、178次尝试及全部历史已见限制明确。
- 34个有效账户场景及2次保留的输入身份拒绝，0新行情/拟合/生产；全部持仓日期与模拟/真实资金持仓对齐。详细方法、原目标逐年核验、两份独立审计及来源见[EX054](experiments/EX054_20261020/others/report.md)。
- 建议保留证据、暂缓冻结和交易，停止同一已见历史反复微调，先设计固定规则的新时段前向验证。下一步须用户决定新窗口或明确选择C9524进入阶段五；冻结另批精确计划。
- C9524声明SIMULATED_FILL_FEEDBACK，股票PTE目前不支持该反馈；没有PTE上线或生产变更。原窗口仍截至2026-10-15，已看过的10月19日不冒充新验证。
- `assets/candidates`、`assets/evidence`及`assets/deliveries`为必要本地资产，须与Git文档一起保留。后续耗时复盘另行处理，不在本轮修改平台。

## 以下为此前入口及历史记录，原文保留

'''.encode('utf-8')
    assert not original.startswith(prefix)
    handoff.write_bytes(prefix + original)
    assert handoff.read_bytes().endswith(original)
    result = {'status': 'COMPLETE_PHASE_FOUR', 'intent_changed_keys': sorted(changed),
        'candidate_delivery': succession['delivery']['reference'],
        'assessment_delivery': assessment['receipt']['reference'],
        'handoff_old_sha256': sha256(original).hexdigest(),
        'handoff_new_sha256': sha256(handoff.read_bytes()).hexdigest(),
        'prior_handoff_exact_suffix_preserved': True,
        'freeze_performed': False, 'production_writes': 0, 'evidence': evidence}
    write(EX / 'others/closeout.json', result)
    receipt = publish(ctx, EX / 'others/closeout.json', 'ex054-current-research-closeout')
    write(EX / 'others/closeout_ref.json', receipt.to_dict())
    print('CLOSEOUT_COMPLETE', assessment['receipt']['reference'], flush=True)


if __name__ == '__main__':
    main()
