"""Render audited H3/H5 complete-cycle contrasts with three H10 controls."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
KINDS = ('support_entry', 'support_exit_reserve', 'support_first_profit_exit')
NAMES = ('B固定到期', 'R全部破坏退出', 'P首次破坏浮盈退出')
BASES = tuple(f'{k}_H10' for k in KINDS)
NEW = tuple(f'{k}_H{h}' for h in (3, 5) for k in KINDS)


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    found = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(found) == 1, where
    return found[0]


def label(variant):
    kind, h = variant.rsplit('_H', 1)
    return f'H{h}／{NAMES[KINDS.index(kind)]}'


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == pre['status'] == 'PASS'
    assert read('others/research_route_review.json')['status'] == 'PASS'
    assert comp['new_accounts'] == 6 and comp['reused_accounts'] == 3 and comp['account_count'] == 9
    assert len(trials) == 6 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 18
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret actual audited evidence before rendering.'
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第7轮：缩短完整交易周期', '', comp['conclusion'], '',
        '## 固定对照范围', '',
        '新增C0062至C0067六个账户：H3/H5分别与B、R、P退出交叉；复用三个原H10账户，共9格。继承前51个候选后累计57个唯一账户候选，交付拟为CANDIDATES/10承接CANDIDATES/9。本轮是10轮自主预算第7轮，新增上游调用0，公告追溯仍暂缓。', '',
        '回到原支撑入场，不加阳线或高环境条件：完成60个评价交易日后，空仓且当日后复权收盘不低于此前5日最低收盘时计划买入。支撑回看仍为5日；H只改变完整持有和再次入场的时钟。实际买入E后，到期决策为E+H−1收盘，计划E+H卖出；R/P提前卖出仍须等E+H收盘才可重新计划买入。新买入重设自己的时钟。', '',
        'B只按到期退出；R支撑破坏就提前退出；P只在首次严格早于E+H−1收盘的破坏时，以含买费浮盈>0判断一次是否退出，否则等到期。拒绝后不重新判定，已发出卖出继续锁存至成交。缩短H同时改变可提前退出的日数和后续参与机会，不能只解释为少等几天。', '',
        'H3来自既有短修复研究尺度，H5为一交易周尺度；其他机制曾用这些尺度不代表它们在本支撑入场下有收益。两种粗粒度期限事前固定，不逐整数优化，不把边界值称为最优。Optuna仅记录6个固定新配置，3原账户精确复用，无自由采样或剪枝。', '',
        '保持600722.SH、名义2020-01-01至2026-10-15、实际1642交易日、初始10万元、单边费用0.1%、后复权研究口径、100股整数手及原全仓限价买入／开盘卖出约定。失败买入重置、失败卖出锁存；跌停开盘加一价位须区间触及，无排队或部分成交。跨年连续，无年度重置或期末强平，固定BuyHold证据一致。', '',
        '每年BuyHold正收益时策略至少达到其1.5倍，否则严格正收益；每年最大回撤严格低于BuyHold。2026截至10月15日不年化，回撤含年初衔接净值；60×闭合交易数÷1642≥3。所有原目标不变，没有新增诊断硬门。', '',
        '## 全部账户与目标状态', '',
        '| 构造 | 候选 | 全期收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in BASES + NEW:
        q = rows[v]
        lines.append(f"| {label(v)} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/9。固定BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '## 新构造逐年收益与剩余缺口', '',
        '| 年份 | H3-B | H3-R | H3-P | H5-B | H5-R | H5-P | 收益门槛 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        values = [select(comp['annual'], variant=v, year=year) for v in NEW]
        q = values[0]
        threshold = f"≥{q['required_return']:.2%}" if q['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {' | '.join(f'{v["return"]:.2%}' for v in values)} | {threshold} |")
    for v in NEW:
        ret = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{label(v)}收益未过：{'、'.join(ret) or '无'}；回撤未过：{'、'.join(dd) or '无'}。"]
    lines += ['', '逐年回撤数值与BuyHold门槛完整保留在账户比较文件。不能用某期限的盈利年替换另一期限亏损年，以事后拼接制造通过。', '',
        '六个新构造都只通过2020、2024两年的收益目标，其余五年未通过。H3-R把2024收益修复为41.55%，但2022、2023分别亏23.52%、22.59%；H5-R虽通过7/7年度回撤目标，2021至2023仍连续亏损，2025也微亏。局部年度改善没有形成能替代H10的完整策略。', '',
        '## 周期与退出的作用', '',
        '| 新构造减对应H10 | 全期收益差（百分点） | 截至2025年末收益差（百分点） |',
        '|---|---:|---:|']
    for v in NEW:
        base = v.rsplit('_H', 1)[0] + '_H10'
        full = select(comp['contrasts'], base=base, changed=v, scope='ALL')
        early = select(comp['contrasts'], base=base, changed=v, scope='EXCLUDING_2026')
        lines.append(f"| {label(v)} | {full['return_delta']*100:+.2f} | {early['return_delta']*100:+.2f} |")
    lines += ['', '| 同周期退出对照 | 全期收益差（百分点） | 截至2025年末收益差（百分点） |',
        '|---|---:|---:|']
    for h in (3, 5):
        for k, name in zip(KINDS[1:], NAMES[1:], strict=True):
            base, new = f'support_entry_H{h}', f'{k}_H{h}'
            full = select(comp['contrasts'], base=base, changed=new, scope='ALL')
            early = select(comp['contrasts'], base=base, changed=new, scope='EXCLUDING_2026')
            lines.append(f"| H{h}／{name}减B | {full['return_delta']*100:+.2f} | {early['return_delta']*100:+.2f} |")
    lines += ['', '这些比较同时包含持有段、提前破坏分支、买卖日期和复利变化，不是互相独立或可以简单叠加的收益来源。', '',
        '同一期限内，B/R/P真实入场完全对齐：H3各352次，H5各245次，因此这里的退出差异可沿共同入场直接比较。R减B的全期周期log差分别为+0.140598、+0.407318，但H3-R在2020、2022、2023、2025收益反而低于H3-B，不能称为普遍保护。H5-P减B为+0.106165，也未增加任何年度收益通过数。', '',
        'H3-P的108次首次破坏判断全部为非正浮盈，实际提前退出0次，后续25个破坏日被忽略。C0064与C0062的实际经济账本逐值相同：这是本窗口没有触发P分支，不能据此声称两个机制独立重复验证，也不代表H3在结构上不可能触发。H5-P有119次首次判断，其中仅3次正浮盈并退出、116次拒绝，另81个后续破坏日被忽略；接受的3次都发生在入场当晚或E+1，差异也来自实际入场路径，样本很少。因此6个固定配置只形成5条不同经济路径，仍使用同一已见样本。', '',
        '## 资金路径、频率和费用', '',
        '| 构造 | 截至2025年末收益 | 收盘持仓日数 | 闭合／未平仓 | 实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in BASES + NEW:
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {label(v)} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '| 新构造减H10 | 共同入场数／log贡献 | H10独有数／log贡献 | 新独有数／log贡献 | 全期log差 |',
        '|---|---:|---:|---:|---:|']
    for v in NEW:
        base = v.rsplit('_H', 1)[0] + '_H10'
        q = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=base, changed=v)
        cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
        lines.append(f"| {label(v)} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', '共同入场按真实买入日期匹配，周期log差用于核对净值复利，没有百分比点单位。提前退出或重新参与改变路径，不能把单笔标签直接加总成新账户。截到2025年末以真实净值计算，未平仓只按市值计价；费用率不变，绝对费用同时受换手和资金规模影响。', '',
        '缩短周期后的损失主要不能解释为同一批交易更早退出。以R为例，H3与H10仅43次共同入场，其log差+0.113692；H10独有95次的贡献在差分中为−2.454518，新增309次为+1.287725，合计仍落后−1.053101。H5-R与H10的共同41次差−0.254984，也没由新增参与补回。H3的闭合交易增至352次，费用约10万元；费用已经计入收益，不应再扣一遍，也不能用费用总额直接归因全部收益差。', '',
        'H3全期收益均高于对应H5，但不是逐年单调：H5-B在2023、2026高于H3，H5-P在2022、2023、2026高于H3，H5-R在2022、2023高于H3。H3-R比H5-R全期更高的收益还伴随更少年度回撤通过（5/7对7/7）。因此更短期限只是待核对的边界问题，不能外推越短越好。', '',
        '## 验证与下一步', '',
        f"因果及公共输入预检{pre['check_count']}项PASS，独立账户审计{audit['check_count']}项PASS；9账户全期及去2026共18项复利核对，最大绝对收益误差{max_error:.3g}。复用账户只核验原正式证据，未重新执行。", '',
        'H3-R/H5-R实际提前退出108/119次，预约空仓等待170/330日，其中原本符合入场条件但被预约阻止107/207日；H5-P为等待11日、阻止9日。这些都是收盘状态日数，不是可成交交易笔数。H3每个账户各2次卖出失败、H5各1次，均继续锁存退出；全部真实停牌日为0，停复牌边界由预检合成样本覆盖。日频区间触及成交仍是既定简化约定，未验证真实排队成交。', '',
        '以下链接以正式交付报告为基准：[固定设计](../../../experiments/EX026_20261018/protocols/comparison_lock.json)、[账户与全部年度目标](../../../experiments/EX026_20261018/others/comparison.json)、[路径诊断](../../../experiments/EX026_20261018/others/path_diagnostics.json)、[独立审计与完整指纹](../../../experiments/EX026_20261018/others/account_audit.json)、[预检](../../../experiments/EX026_20261018/others/precheck.json)、[边界研究路线及反证](../../../experiments/EX026_20261018/others/research_route_review.json)。全部数据已见，本轮及截窗诊断不构成独立样本外验证。', '',
        comp['next_step'], '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 6, 'reused_accounts': 3, 'registered_candidates': 57}))


if __name__ == '__main__':
    main()
