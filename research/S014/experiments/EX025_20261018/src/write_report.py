"""Render complete candle-entry by exit-mechanism contrasts after audit."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
BASES = ('support_entry_H10', 'support_exit_reserve_H10', 'support_first_profit_exit_H10')
NEW = ('support_up_entry_H10', 'support_up_exit_reserve_H10', 'support_up_first_profit_exit_H10')
NAMES = ('B：固定10日', 'R：全部支撑破坏退出', 'P：首次破坏浮盈才退出')
LABELS = {v: ('原入场／' if v in BASES else '阳线入场／') + name
          for variants in (BASES, NEW) for v, name in zip(variants, NAMES, strict=True)}


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
    frequency = read('others/frequency_feasibility.json')
    route = read('others/research_route_review.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == pre['status'] == 'PASS'
    assert frequency['status'] == 'PASS'
    assert route['status'] == 'PASS'
    assert comp['new_accounts'] == comp['reused_accounts'] == 3 and comp['account_count'] == 6
    assert len(trials) == 3 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 12
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret evidence before rendering.'
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第6轮：阳线入场确认与退出规则交互', '',
        comp['conclusion'], '',
        '## 六格完整对照，只有一个新增入场条件', '',
        '本轮新增C0059至C0061三个账户，复用B（C0034）、R（C0056）、P（C0057）三个对应原账户，共6个对照。继承前48个候选后累计51个唯一账户候选，交付拟为CANDIDATES/9承接CANDIDATES/8。本轮为10轮自主预算的第6轮，第7轮已另行锁定，尚未分配3轮；新增上游调用0，公告追溯继续暂缓。', '',
        '原支撑入场在60个评价交易日启动后，要求收盘不低于此前5个评价交易日最低收盘；新条件只在空仓新买入决策时额外要求当日后复权收盘严格高于开盘，即日内收阳，平盘不通过。信号仍在已完成日收盘形成、下一交易日按原限价执行；持仓期间出现阴线不会单独触发卖出。', '',
        '分别保留对应退出：B固定真实入场E后的10日；R在支撑破坏时提前退出、最晚原10日；P仅在首次严格早于E+9收盘的支撑破坏且含买费浮盈>0时提前退出，否则本周期持有到期。R/P仍保留原E+10收盘重新入场时钟；失败买入重置、失败卖出锁存均不变。没有新增低开、高环境、初始偏移、期限或仓位条件。', '',
        '每个新账户先与对应原退出机制比较，以检验阳线条件的作用；再比较该作用是否随退出机制改变。这是2种入场×3种退出的六格对照，不是从中挑全期最高收益再事后解释。原非盈利提前退出方案已保留历史证据，本轮不重复交叉它。', '',
        '设计前的分组反例已保留：原R阳线入场92笔、其他46笔；非阳线入场在2021、2023也有收益，阳线组在2024、2025仍亏损。2024非阳线入场对B/P为正、对R为负，因此只把入场确认视为待检验机制；旧交易分组不能直接加总成过滤后账户收益。', '',
        '仍用600722.SH、名义2020-01-01至2026-10-15、实际1642交易日、初始10万元、单边0.1%费用、后复权研究口径、100股整数手和原全仓限价买入／开盘卖出约定。跌停开盘加一价位卖出须区间触及；无新增排队、部分成交或滑点。跨年连续，无年度重置和期末强平，固定BuyHold完全一致。', '',
        '每年BuyHold正收益时策略至少达到其1.5倍，否则严格正收益；每年最大回撤严格小于BuyHold。2026截至10月15日不年化，年度回撤包含年初衔接净值；平均频率60×闭合交易数÷1642≥3。没有新增诊断硬门。Optuna仅记录事前锁定的3配置，无自由搜索、阈值优化、剪枝或年度切换。', '',
        '## 全部账户及原目标', '',
        '| 构造 | 候选 | 全期收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in BASES + NEW:
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/6。固定BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '## 新构造逐年缺口', '',
        '| 年份 | C0059收益 | C0060收益 | C0061收益 | 收益门槛 | C0059／60／61回撤 | BuyHold回撤 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        b, r, p = [select(comp['annual'], variant=v, year=year) for v in NEW]
        threshold = f"≥{b['required_return']:.2%}" if b['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {b['return']:.2%} | {r['return']:.2%} | {p['return']:.2%} | {threshold} | {b['max_drawdown']:.2%}／{r['max_drawdown']:.2%}／{p['max_drawdown']:.2%} | {b['buyhold_drawdown']:.2%} |")
    for v in NEW:
        ret = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{rows[v]['candidate']}收益未过年份：{'、'.join(ret) or '无'}；回撤未过年份：{'、'.join(dd) or '无'}。"]
    lines += ['', '## 同一退出机制下，阳线入场带来的变化', '',
        '| 范围 | B收益差（百分点） | R收益差（百分点） | P收益差（百分点） |',
        '|---|---:|---:|---:|']
    for scope, label in [('ALL', '全期')] + [(str(y), str(y)) for y in range(2020, 2027)] + [('EXCLUDING_2026', '截至2025年末')]:
        diffs = [select(comp['contrasts'], base=b, changed=n, scope=scope)['return_delta'] * 100 for b, n in zip(BASES, NEW, strict=True)]
        lines.append(f"| {label} | {' | '.join(f'{v:+.2f}' for v in diffs)} |")
    lines += ['', '阳线条件在B、R的2024年把收益分别修复为13.94%、10.64%，但P仍亏11.25%；三种新构造在2022都亏损，且2021、2023、2025表现普遍退化。局部年度改善不能掩盖完整目标退步，也不能据此按年份切换入场条件。', '',
        '每列均为新增阳线条件的账户减去其原对应账户；不同列之间的差说明作用随退出规则改变，不是相互独立的收益来源。年度差与全期复利差不能直接相加。', '',
        '## 去2026、暴露和费用', '',
        '| 构造 | 截至2025年末收益 | 全期持仓日数 | 闭合／未平仓 | 全期实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in BASES + NEW:
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '截到2025年末以当时真实净值计算，未平仓按当日市值计价，无虚构卖出费。费用率完全相同，绝对费用还受到资金规模与换手共同影响。', '',
        '## 入场匹配与路径变化', '',
        '| 对照／窗口 | 共同入场数／log贡献 | 原路径独有数／log贡献 | 新路径独有数／log贡献 | 总log差 |',
        '|---|---:|---:|---:|---:|']
    for window in ('ALL', 'WITHOUT2026'):
        for base, changed, name in zip(BASES, NEW, NAMES, strict=True):
            q = select(paths['decompositions'], window=window, entry_cohort='ALL', baseline=base, changed=changed)
            cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
            lines.append(f"| {name}新增阳线／{'全期' if window == 'ALL' else '截至2025年末'} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', 'B/R/P分别仅保留40、36、40个共同实际入场，共同入场的log差都接近零；被遗漏的原路径总体为正，而新增路径总体为负。去2026三种新账户也全部亏损。因此主要损伤来自删去盈利参与和改变后续入场日期，而非同一笔交易的退出被阳线条件改善。旧R阳线分组表现较强，没有转化为可交易的统一入场过滤收益。', '',
        '三种新增阳线账户之间则共有全部130个实际入场。阳线P退出相对阳线B固定持有的log增量为−0.431983，去2026仍为−0.468834；这与原无阳线过滤时C0057相对B的正增量相反。浮盈保护退出的有效性依赖入场所形成的具体交易集合，不能当作通用正收益组件直接移植。', '',
        '共同入场按真实买入日期匹配。新条件既会删去某次机会，也会把之后的持有、卖出和重新参与日期改变；原交易分组中的阳线收益并不等于新账户结果。资金周期log差用于净值算术核对，没有百分比点单位，也不是独立因果贡献。', '',
        '## 期限研究的既有频率约束', '',
        '现有频率目标要求闭合数K≥ceil(3×1642÷60)=83。完成60日预热后最早第61个评价交易日买入；统一固定持有H日且卖出后下一日才可买入时，第k笔最早卖出日为60+k(H+1)，所以理想闭合上界为floor(1582÷(H+1))。H20最多75笔、每60日2.74056笔；H19最多79笔；H18最多83笔，整数H必要上限为18，真实等待和失败只会减少笔数。', '',
        '即便允许提前卖出，只要每周期仍保留E+H收盘才可重新入场，理想上界也仅为1+floor(1580÷(H+1))；H20最多76笔、频率2.77710，仍不达标。此为既有目标的结构推导，不是新增硬门，也不证明任何较短期限有效。它不排除部分短周期且时钟不同的“最长20日”混合规则；不据此锁新实验或改预算，详见[频率可行性与来源指纹](../../../experiments/EX025_20261018/others/frequency_feasibility.json)。', '',
        '## 验证与下一步', '',
        f"因果及公共输入预检{pre['check_count']}项PASS，独立账户审计{audit['check_count']}项PASS。6账户全期及去2026共12项复利核对，最大绝对收益误差{max_error:.3g}。复用账户只核验原证据，不重复执行。", '',
        '审计分别确认阳线条件阻止62、64、62个符合其余入场条件的信号日；这是日期数，不是原本必定成交的交易笔数。三个新增账户各实际买入130次，信号等待改变后续节奏，不能只按少买了几笔解释收益差。C0061首次破坏判定99次，18次浮盈接受、81次拒绝，拒绝后125个再次破坏日未重新选择；卖出受阻继续锁存。真实停牌日为0，停牌边界仅由合成预检覆盖。', '',
        '以下链接以正式交付报告为基准：[事前锁定](../../../experiments/EX025_20261018/protocols/comparison_lock.json)、[全部账户与年度目标](../../../experiments/EX025_20261018/others/comparison.json)、[路径诊断](../../../experiments/EX025_20261018/others/path_diagnostics.json)、[独立审计及完整指纹](../../../experiments/EX025_20261018/others/account_audit.json)、[预检](../../../experiments/EX025_20261018/others/precheck.json)。全部数据已见，截窗与分组都不是独立样本外验证。', '',
        '后续完整周期对照也会改变提前退出分支的可用范围：原R的103次早退若只按原轨迹位置标记，H3严格到期前范围内仅38次、H5为63次。因此缩短周期不只是减少空仓等待，还会改变持有段和条件退出机会；这些旧轨迹数量不是新策略的成交预测。原窗口内空仓预约等待为620日，未裁切的末端期外距离不能计入。详见[后续路线评审](../../../experiments/EX025_20261018/others/research_route_review.json)。', '',
        comp['next_step'], '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 3, 'reused_accounts': 3, 'registered_candidates': 51}))


if __name__ == '__main__':
    main()
