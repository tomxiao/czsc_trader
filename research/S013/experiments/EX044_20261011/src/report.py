"""Deterministic full-population descriptive summary, no policy profits."""
from common import ROOT, SRC, PROTOCOLS, RUNS, OUTPUT, read, write
from contrasts import CATEGORIES


def main():
    result = read(OUTPUT)
    assert result['status'] == 'PASS' and result['new_account_evaluations'] == 0
    summaries = {}
    for label in ('B0-TIME', 'N0'):
        points = [result['same_kind'][label + f'-P{i:02d}'] for i in range(32)]
        sums = {outcome: {category: sum(row['outcomes'][outcome]['partitions']['signal_year']['ALL']['counts'][category]
                      for row in points) for category in CATEGORIES} for outcome in ('target', 'target_reason')}
        memory = sum(row['state_propagation']['partitions']['signal_year']['ALL']['counts']['physical_equal_decision_different'] for row in points)
        summaries[label] = {'points': 32, 'days': 32 * 1636, 'outcomes': sums, 'memory_only_state_days': memory}
    probes = list(result['fixed120_probe'].values())
    probe = {'accounts': len(probes), 'rows': len(probes) * 1636,
        'accounts_next_state_identical': sum(row['all_next_states_identical'] for row in probes),
        **{key: sum(row['partitions']['signal_year']['ALL'][key] for row in probes)
           for key in ('target_different', 'target_reason_different', 'next_state_different')}}
    comparison = read(ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_analysis.json')['summaries']
    economics = {label: {key: comparison[label][key] for key in
                        ('q10_cagr', 'q90_drawdown', 'return_degradation', 'drawdown_degradation')} for label in ('B0-TIME', 'N0')}
    decision = {'status': 'DIAGNOSIS_COMPLETE', 'objective_achieved': False,
        'new_account_evaluations': 0, 'diagnostic_summaries': summaries, 'fixed120_probe_summary': probe,
        'unchanged_existing_economic_comparison': economics,
        'next_action': ('Current fixed120 decoupling changes no full next state across33inputs; reject target/state-path change on exact existing panel by induction. Final reason equality additionally needs zero target_reason_different. Select another mechanism source.'
                        if probe['next_state_different'] == 0 else
                        'Fixed120 decoupling changes observed steps; this is a mechanism lead only. Next controlled successor should preserve13domain/coordinates, activate confirmationL only in original score, keep baseline120 fixed structurally; first full center4gates then all32matched points if qualified. No profit claim from probe.'),
        'limits': result['limits']}
    write(PROTOCOLS / 'decision.json', decision)
    write(RUNS / 'conclusion.json', decision)
    lines = ['# EX044 完整参数路径的触发与状态传播诊断', '',
        '本轮诊断完成；改善参数敏感性的总目标尚未达成。66个不同已有原生账户全部精确复用，零新增账户、零资金重放。', '',
        '## 已有经济反证', '', '| 完整32点指标 | 原策略 | EX043新策略 |', '|---|---:|---:|']
    for key, title in (('q10_cagr', '较差一端年化收益（Q10）'), ('q90_drawdown', '较差一端全期回撤（Q90）'),
                       ('return_degradation', '相对中心收益下降'), ('drawdown_degradation', '相对中心回撤增加')):
        lines.append(f"| {title} | {100*economics['B0-TIME'][key]:.4f}% | {100*economics['N0'][key]:.4f}% |")
    lines += ['', '新中心虽然四项目标达标，绝对尾部更差；相对中心下降较少不能代替尾部改善。既有收益未重跑。', '',
        '## 当天触发与此前状态', '',
        '把当天条件与决策前状态各自换一次，观察能否复现参数扰动账户当天决定。A为中心条件/中心状态；B为扰动条件/中心状态；C为中心条件/扰动状态；D为真实扰动条件/扰动状态。只算一步，B/C不向下一天传播。', '',
        '| 目标仓位分类 | 原策略32点天数 | 新策略32点天数 |', '|---|---:|---:|']
    names = {'equal': '四种决定都相同', 'input_only': '换当日条件足以复现D', 'state_only': '换已有状态足以复现D',
             'either_sufficient': '任选一种替换都足以复现D', 'joint_interaction': '两种合用才复现D或多值残差',
             'cancellation': '实际A=D但单次替换有差异'}
    for category in CATEGORIES:
        lines.append(f"| {names[category]} | {summaries['B0-TIME']['outcomes']['target'][category]} | {summaries['N0']['outcomes']['target'][category]} |")
    lines += ['', '每日完整target及target/reason分类、信号年2019—2026、执行年2020—2026、空类别、连续区间、首分歧和尾状态都在正式诊断材料中保留。原32点和新32点是同一路市场的依赖路径，不是64个独立样本。', '',
        f"持仓/路线/持有天数相同、决策所需完整状态不同的天数：原策略{summaries['B0-TIME']['memory_only_state_days']}，新策略{summaries['N0']['memory_only_state_days']}。新策略自带入场价格锚与退出类别记忆，不能从物理持仓相同直接推断后续决定相同。这个计数描述记忆状态，不证明其造成盈利或亏损。", '',
        '“当日条件足以复现D”并不表示状态完全无影响；target/reason有多个取值。13项参数一起扰动，本轮不能确定某一个参数的单独收益因果。', '',
        '## 共用历史窗口检查', '',
        f"33条新策略路径共{probe['rows']}天，只把下跌自相关历史均值窗口固定为中心120天。目标仓位改变{probe['target_different']}天；仓位或最终原因改变{probe['target_reason_different']}天；完整下一状态改变{probe['next_state_different']}天；{probe['accounts_next_state_identical']}条账户完整下一状态始终不变。", '',
        '买入确认窗口仍是原13维中的有效参数；固定120天为结构选择，不删除参数维度。未搜索窗口、未延长数据、未计算修改后的账户利润。每条路径全部下一状态相同才可用归纳法排除该面板上的目标仓位/状态路径改变；最终原因还须独立核对。存在变化只能作为后续对照线索。', '',
        '## 结论与下一步', '', decision['next_action'], '',
        '仍沿用四项经济目标、完整13维参数域及原32点共同坐标，不新增经济否决条件。总目标继续；技术PASS仅表示材料/身份/完整路径核验通过。RSCH S013阶段三，不涉及生产、PTE、冻结、推送或阶段推进。', '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print({'summary': summaries, 'probe': probe}, flush=True)


if __name__ == '__main__':
    main()
