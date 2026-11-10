"""Close the authorized stage after validating its public delivery receipts."""
import json
from hashlib import sha256
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, get_research_overview,
    update_research_intent,
)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    publication = read(WORK / 'others/assessment_publication.json')
    assert publication['report_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['scope'] == 'INTEGRITY'
    report_ref = d.EvidenceRef.from_dict(publication['report'])
    report_bytes = report_ref.resolve(ROOT).read_bytes()
    assert sha256(report_bytes).hexdigest() == report_ref.sha256
    assert json.loads(report_bytes)['report_sha256'] == sha256((WORK / 'report.md').read_bytes()).hexdigest()
    accounts = read(WORK / 'others/account_results.json')
    assert accounts['status'] == 'COMPLETE' and len(accounts['accounts']) == 90
    summary = read(WORK / 'others/account_summary.json')
    assert all(not row['parameter_acceptance'] and row['all_risk_limits_pass']
               for row in summary['groups'].values())
    handoff = ROOT / 'research/S019/HANDOFF.md'
    old = handoff.read_text(encoding='utf-8')
    assert '## 指定双候选阶段四成果' not in old, 'Inspect already updated handoff before retry'
    prefix, rest = old.split('## 目标与授权', 1)
    assert '阶段四尚未启动' in prefix
    assert old.count('## 下一步\n\n') == 1
    assert '正式回放已通过DFLS' in old.split('## 下一步\n\n', 1)[1]
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent = read(ROOT / 'research/registrations/S019/family.json')['research_intent']
    assert intent['joint_search_budget']['remaining_rounds'] == 7
    intent.update(stage='STAGE_FOUR', stage_four_status='COMPLETE',
        stage_four_delivery=publication['assessment'], active_experiment=None,
        stage_four_research_acceptance='FAILED',
        next_action='阶段四已完成，两个指定中心均未通过原目标。建议复用不利路径研究仓位和退出协作，等待用户决定后续阶段；7轮优化额度保留。')
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='指定两个对象的完整阶段四检查及正式交付完成，原目标与剩余额度保持。')
    overview = get_research_overview(repo, batch).to_dict()
    (WORK / 'others/closing_overview.json').write_bytes(
        (json.dumps(overview, ensure_ascii=False, indent=2) + '\n').encode())
    prefix = ('# S019 独立MU研究交接\n\n'
        '2026-11-10，RSCH，分支 `codex/mu-independent-research`。用户指定C0224与C0135进入阶段四，暂停后明确恢复；'
        '最新[EX039](experiments/EX039_20261110/report.md)已完成五项稳健性自检及[ASSESSMENT/1](deliveries/ASSESSMENT/1/report.md)交付，'
        'INTEGRITY校验PASS。两中心Calmar、参数邻域和费用压力均未通过，S019原目标仍待达成。'
        '本轮新增90策略及4买持，复用两原中心与历史研究族；新增优化搜索0，已用3/10轮、剩余7轮，等待用户决定后续研究阶段。\n\n')
    old = prefix + '## 目标与授权' + rest
    before, after = old.split('## 下一步\n\n', 1)
    _, assumptions = after.split('正式回放已通过DFLS', 1)
    rates = [100 * summary['groups'][cid]['joint_pass_rate'] for cid in ('C0135', 'C0224')]
    stage = ('## 指定双候选阶段四成果\n\n'
        '- [用户授权](experiments/EX039_20261110/protocols/authorization.md)、[事前方案](experiments/EX039_20261110/protocols/plan.md)'
        '固定原目标、连续已见样本和80%参数联合通过率，承接CANDIDATES/5与MANDATE/2。\n'
        f'- C0135与C0224完整合法邻域分别8点、80点，联合通过率分别{rates[0]:.2f}%、{rates[1]:.2f}%，均低于80%；全部点有效等权且MDD≤25%。'
        '整数期限最小变化超过5%，在本项固定，期限风险继续披露。\n'
        '- 双倍费用Calmar分别3.9747、4.4667，均低于压力门槛4.5；标准中心Calmar分别4.4387、4.9562，原中心目标保持5。\n'
        '- C0224较低MDD的配对95%区间支持较稳定；收益及Calmar差区间跨零。两者滚动NAR分别21/46、18/46窗口优于买持，'
        '增长集中于2025及2026截至10月底，最大单笔盈利贡献分别14.44%、12.26%。\n'
        '- 历史238份标准账户归并236个精确实现；按原硬门后NAR选型的4组年度回看中，两组无合格项，另两组后期均未达原门。'
        'Sharpe代理PBO/DSR单列，实际NAR加硬门的人工自适应选择偏差仍待量化。\n'
        '- [正式发布回执](experiments/EX039_20261110/others/assessment_publication.json)记录ASSESSMENT/1及实验报告校验PASS。'
        '92份账户事实、88个派生点绑定完整；代表性业务重建和统计绑定核验通过。两个对象均TARGET_NOT_MET，无达标排名。\n\n'
        '## 下一步\n\n'
        '建议返回结构研究，优先复用低Calmar与高MDD邻域账本解释ATR退出和低参与仓位的协作问题，提出有路径依据的对照后再优化。'
        '可用优化额度仍为7轮，等待用户决定后续阶段。原NAR≥55%、Calmar≥5、MDD和频率要求保持。\n\n')
    handoff.write_bytes((before + stage + '正式回放已通过DFLS' + assumptions).encode())
    print('STAGE_FOUR_CLOSED', flush=True)


if __name__ == '__main__':
    main()
