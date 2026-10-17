"""Render audited complementary first-break profit-state account evidence."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
B, R = 'support_entry_H10', 'support_exit_reserve_H10'
P, N = 'support_first_profit_exit_H10', 'support_first_nonprofit_exit_H10'
LABELS = {B: 'B：从不提前退出', R: 'R：支撑破坏全部提前退出',
          P: 'P：首次破坏仍浮盈才退出', N: 'N：首次破坏浮亏或持平才退出'}
NEXT_STEP = (
    '继续已公开锁定的[第6轮EX025](../../../experiments/EX025_20261018/protocols/comparison_lock.json)：'
    '在原支撑入场条件上增加当日收盘严格高于开盘的阳线确认，分别与B固定期限、R全部支撑破坏退出、'
    'C0057首次破坏浮盈才退出组合；新增3账户，复用对应3原账户，形成2种入场×3种退出的完整六格对照。'
    '原C0056标签中阳线入场92笔、其他46笔，但后者在2021/2023也有收益，阳线组在2024/2025仍亏损；'
    '因此只把它作为待检验入场确认，不视为已能修复年度缺口。不选择年度切换或新增持有期阈值，'
    '费用、执行和全部原目标保持。第6轮已分配，尚未分配4轮；不自动进入阶段四。'
)


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    found = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(found) == 1, where
    return found[0]


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    maturity = read('others/maturity_diagnostics.json')
    maturity_review = read('others/maturity_review.json')
    route = read('others/research_route_review.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == pre['status'] == 'PASS'
    assert maturity['status'] == maturity_review['status'] == 'PASS'
    assert route['status'] == 'PASS'
    assert comp['new_accounts'] == comp['reused_accounts'] == 2 and comp['account_count'] == 4
    assert len(trials) == 2 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 8
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret audited evidence before rendering.'
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第5轮：首次支撑破坏时的浮盈状态', '',
        comp['conclusion'], '',
        '## 两个互补构造与固定边界', '',
        '本轮新增C0057、C0058两个账户，复用B（C0034）与R（C0056）两个原账户，共4个对照；不复用原C为本轮对照。继承前46个候选后累计48个唯一账户候选，交付拟为CANDIDATES/8承接CANDIDATES/7。本轮为10轮自主预算的第5轮，第6轮已另行锁定，尚未分配4轮；新增上游调用0，公告追溯继续暂缓。', '',
        '保持原支撑入场：评价区间60交易日启动后，空仓且当日后复权收盘不低于此前5个评价交易日最低收盘时计划买入。真实买入日E起，E+9收盘必须发出原10日到期卖出，计划E+10执行；每个真实入场保留到E+10收盘的重新入场界限，即使提前卖出也不立即重新参与。', '',
        '只在持仓后首次支撑破坏且严格早于E+9收盘时判断一次：浮盈P=当晚后复权收盘÷（实际后复权买入成交价×1.001）−1。已付买入费用计入，未发生卖出费用不扣，零归入非盈利状态；当晚浮盈不保证次日实际卖出盈利。', '',
        '- C0057：首次破坏时P>0才提前退出，否则本周期忽略后续支撑破坏，持有到原期限。',
        '- C0058：首次破坏时P≤0才提前退出，否则本周期持有到原期限。',
        '- 首次判断被拒绝后不逐日翻转，实际新买入才重置；首次破坏发生在E+9时按到期退出，不计提前分支。已发出的卖出受阻后继续锁存，不撤销。', '',
        'B代表从不提前退出，R代表全部支撑破坏提前退出。两个状态标签互补，但真实账户受到现金、后续入场、失败订单和复利影响，收益不能简单相加，也不能视为独立样本。', '',
        '构造依据是EX023的100笔同入场且双闭合早退比较：浮盈15笔平均增量+2.629个百分点，浮亏或持平85笔−0.869个百分点。反证同时保留：浮盈组去掉最大5个增量转负；非盈利早退在2021、2023有保护；2024没有浮盈早退样本，不能预期仅靠本规则修复全部亏损年。诊断标签只是待检验线索，本轮使用完整连续账户检验。', '',
        '沿用600722.SH、名义2020-01-01至2026-10-15、实际1642交易日、10万元初始资金、单边0.1%费用、后复权研究口径、100股整数手和原全仓限价买入／开盘卖出约定。跌停开盘加一价位卖出仍须区间触及；没有新增滑点、排队或部分成交。跨年连续、无年度重置及期末强平，固定BuyHold证据一致。', '',
        '每年BuyHold正收益时策略收益至少为其1.5倍，否则严格正收益；每年最大回撤严格小于BuyHold。2026截至10月15日不年化，回撤包含年初衔接净值；60×闭合交易数÷1642≥3。没有新增诊断硬门。Optuna仅记录事前锁定的两个配置，无自由采样、阈值搜索、剪枝或年度切换。', '',
        '## 全部账户与原目标', '',
        '| 构造 | 候选 | 全期收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in (B, R, P, N):
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/4。固定BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '## 逐年收益与新构造回撤', '',
        '| 年份 | B收益 | R收益 | C0057收益 | C0058收益 | 收益门槛 | C0057／C0058回撤 | BuyHold回撤 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        b, r, p, n = [select(comp['annual'], variant=v, year=year) for v in (B, R, P, N)]
        threshold = f"≥{b['required_return']:.2%}" if b['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {b['return']:.2%} | {r['return']:.2%} | {p['return']:.2%} | {n['return']:.2%} | {threshold} | {p['max_drawdown']:.2%}／{n['max_drawdown']:.2%} | {b['buyhold_drawdown']:.2%} |")
    for v in (P, N):
        rr = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{rows[v]['candidate']}收益未过年份：{'、'.join(rr) or '无'}；回撤未过年份：{'、'.join(dd) or '无'}。"]
    lines += ['', 'C0057相对B改善2021收益及回撤、2022收益和2025收益，但2025仍低于40.19%目标，2023和2024亏损、2026也不足1.5倍BuyHold。相对R，C0057修复2022和2025收益，却丢失2023、2026收益目标及2024回撤目标；全期略高不等于更接近全部目标。C0058虽保留4个年度收益通过，但2021、2025回撤未过，整体收益和回撤也弱于R，不能将非盈利退出单独提升为优先构造。']
    lines += ['', '## 去2026、暴露与费用', '',
        '| 构造 | 截至2025年末收益 | 全期收盘持仓日数 | 全期闭合／未平仓 | 全期实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in (B, R, P, N):
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '截至2025年末使用当时实际净值，未平仓只按市值计价，无假想卖出费；费用绝对值受成交频率和复利后资金规模共同影响。全部已见数据，不把截窗诊断称为新样本外验证。', '',
        '## 共同入场与改变后的路径', '',
        '| 对照／窗口 | 共同入场数／log贡献 | 原路径独有数／log贡献 | 新路径独有数／log贡献 | 总log差 |',
        '|---|---:|---:|---:|---:|']
    for window in ('ALL', 'WITHOUT2026'):
        for base, changed, label in ((B, P, 'C0057−B'), (B, N, 'C0058−B'), (R, P, 'C0057−R'), (R, N, 'C0058−R')):
            q = select(paths['decompositions'], window=window, entry_cohort='ALL', baseline=base, changed=changed)
            cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
            lines.append(f"| {label}／{'全期' if window == 'ALL' else '截至2025年末'} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', 'C0057与B全期138笔实际入场全部对齐，log增量+0.404814全部来自共同入场；截至2025年末122笔也全部对齐、增量+0.365365。这支持浮盈时保护退出的有限账户增量，而不是仅靠新增交易日期获得全期优势。C0058与R全期138笔同样全部对齐，但log增量−0.403421，去2026仍为负，表明删除浮盈状态的退出保护整体有损。', '',
        'C0057相对R仅略增全期收益：共同134笔log增量+0.485833，几乎被2026各4笔独有路径的净差抵消。C0057去2026累计279.98%明显高于R的144.54%，但没有复现R在2026特殊执行路径上的全部收益，因此不能把二者视为单调替代关系。', '',
        '按真实买入日期匹配，资金周期log收益差可加总到净值log差，不是百分比点；遗漏原路径项取相反数。即使首次状态互补，各自后续实际买卖仍可能不同；不能从旧标签直接合成新账户，也不能把路径分解当作独立因果效应。', '',
        '## 首次判断与退出锁存核验', '',
        '| 构造 | 首次判断数 | 浮盈／非盈利 | 接受／拒绝早退 | 拒绝后忽略后续破坏日数 | 卖出未成交次数 |',
        '|---|---:|---:|---:|---:|---:|']
    for v in (P, N):
        q = select(audit['accounts'], variant=v)
        lines.append(f"| {rows[v]['candidate']} | {q['first_break_evaluations']} | {q['first_break_positive']}／{q['first_break_nonpositive']} | {q['first_break_selected']}／{q['first_break_rejected']} | {q['later_predeadline_breaks_ignored_after_rejection']} | {q['failed_sell_orders']} |")
    lines += ['', '判定只使用当晚可知价格与真实买入成本。拒绝后本周期不再选择另一状态，卖出受阻继续锁存；完整逐节点及每日状态核对在审计中保留。真实停牌日仍为0，停牌边界由合成预检覆盖。', '',
        '## 结果后的期限线索：暂不扩大持有期', '',
        '另用原C0056到期交易完成0新增账户的标签诊断，作为本轮结果之后的下一方向边界，不作为本轮已锁定两配置的前因。35个原到期周期中31个支撑完整，31个全部浮盈，因此浮盈状态在这里没有区分力。', '',
        '固定延至H20的平均增量+1.117个百分点，但去掉前三笔后为−3.388个百分点，前三笔均在2026；2026以前作出到期决策的25笔均值为−1.275个百分点。延长后遇支撑破坏再退出且以H20为上限，仅8笔正、23笔负，中位−1.340个百分点，去掉前三笔均值也转负；取消上限仍集中于少数样本。', '',
        '上述是相同原入场的假想每仓退出标签，忽略改变后的机会、股数及资金路径，不是完整账户收益；“2026前决策队列”也不是净值截窗。独立核验105个标签及18项汇总，无实际右删失、假想卖出也未出现延后成交。暂不据正均值或全期收益扩大期限，见[到期诊断](../../../experiments/EX024_20261018/others/maturity_diagnostics.json)及[独立核验](../../../experiments/EX024_20261018/others/maturity_review.json)。', '',
        '## 验证和下一步', '',
        f"因果与公共输入预检{pre['check_count']}项PASS，独立账户审计{audit['check_count']}项PASS；4账户全期及去2026共8项复利核对，最大绝对收益误差{max_error:.3g}。复用账户只核验原正式证据，未重复回放。", '',
        '以下相对链接以正式交付报告为基准：[事前锁定](../../../experiments/EX024_20261018/protocols/comparison_lock.json)、[账户及年度目标](../../../experiments/EX024_20261018/others/comparison.json)、[路径诊断](../../../experiments/EX024_20261018/others/path_diagnostics.json)、[独立审计与完整指纹](../../../experiments/EX024_20261018/others/account_audit.json)、[预检](../../../experiments/EX024_20261018/others/precheck.json)。', '',
        '后续入场分组也有明确反例：2024非阳线入场的B、C0057队列log贡献约+0.0635、+0.0637，R却为−0.2506；2023非阳线入场在三者均有正贡献。因此新一轮检验的是入场确认与退出规则的交互，而不是已证实可以删除所有非阳线交易。分组为入场年队列，不等同年度净值贡献，见[后续路线评审](../../../experiments/EX024_20261018/others/research_route_review.json)。', '',
        NEXT_STEP, '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 2, 'reused_accounts': 2, 'registered_candidates': 48}))


if __name__ == '__main__':
    main()
