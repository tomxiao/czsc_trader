"""Render audited single-horizon H15 full-account contrasts."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
KINDS = ('support_entry', 'support_exit_reserve', 'support_first_profit_exit')
NAMES = ('B固定到期', 'R全部破坏退出', 'P首次破坏浮盈退出')
BASES = tuple(f'{k}_H10' for k in KINDS)
NEW = tuple(f'{k}_H15' for k in KINDS)


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
    assert comp['new_accounts'] == 3 and comp['reused_accounts'] == 3 and comp['account_count'] == 6
    assert len(trials) == 3 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 12
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret audited evidence first.'
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第9轮：H15完整交易周期对照', '', comp['conclusion'], '',
        '## 固定范围', '',
        '新增C0072至C0074三个H15账户，分别保持B/R/P退出；精确复用三个H10账户，共6格。继承61个候选后累计64个唯一账户候选，交付拟为CANDIDATES/12承接/11。本轮是10轮自主预算第9轮，新增上游调用0，公告追溯仍暂缓。', '',
        '维持原60评价日启动、此前5日最低收盘支撑入场。实际买入E后，E+14收盘到期决策、E+15起卖出；R/P提前退出仍保留E+15收盘才能重新计划入场的预约。B只到期退出，R支撑破坏即退出，P仅在首次严格提前破坏时以含买费浮盈>0判断一次；拒绝后不重判，卖出失败锁存。支撑回看仍5日，不随持有期限变更。', '',
        '前轮H15同入场标签只是集中于少数赢家的有限平均改善，未包含新路径；容量96/97只是乐观上界。故本轮检验完整资金路径能否保留增量，未把B标签当R/P先验有效证据。仅一个H15期限、3个事前固定Optuna配置，无自由搜索、剪枝或H11至H17网格；H18已因原频率约束排除。', '',
        '保持600722.SH、2020-01-01至2026-10-15、实际1642交易日、初始10万元、单边0.1%费率、后复权研究、整数手全仓、原限价买入及开盘／跌停开盘加一价位卖出、同一BuyHold。跨年连续，无年度重置或期末强平。逐年收益须达到正BuyHold的1.5倍，否则严格正收益；逐年最大回撤严格低于BuyHold，2026截至10月15日不年化；60×闭合交易数÷1642≥3。原目标全部不变。', '',
        '## 全部结果与年度缺口', '',
        '| 构造 | 候选 | 全期收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in BASES + NEW:
        q = rows[v]
        lines.append(f"| {label(v)} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/6；BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '| 年份 | H15-B | H15-R | H15-P | 收益门槛 |', '|---|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        values = [select(comp['annual'], variant=v, year=year) for v in NEW]
        q = values[0]
        threshold = f"≥{q['required_return']:.2%}" if q['buyhold_return'] > 0 else '>0%'
        returns = ' | '.join(format(v['return'], '.2%') for v in values)
        lines.append(f'| {year} | {returns} | {threshold} |')
    for v in NEW:
        ret = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{label(v)}收益未过：{'、'.join(ret) or '无'}；回撤未过：{'、'.join(dd) or '无'}；频率达标={rows[v]['frequency_pass']}。"]
    lines += ['', 'B/P只通过2020、2024收益目标，R只通过2022。R把2022改善为+11.93%，却在2025亏43.12%；P把2024收益改善为+8.14%，该年回撤仍未低于BuyHold。三者2026虽明显上涨，仍未达到196.46%的原收益门槛。单个亏损年的修复没有覆盖其他年度代价。']
    lines += ['', '## 完整路径与费用', '',
        '| 构造 | 截至2025年末收益 | 全期持仓收盘日数 | 闭合／未平仓 | 实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in BASES + NEW:
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {label(v)} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '| H15减对应H10 | 共同入场数／log贡献 | H10独有数／log贡献 | H15独有数／log贡献 | 全期log差 |',
        '|---|---:|---:|---:|---:|']
    for v, base in zip(NEW, BASES, strict=True):
        q = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=base, changed=v)
        cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
        lines.append(f"| {label(v)} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', '共同入场按实际买入日匹配；log贡献用于核对账户复利，不是百分点。期限同时改变卖出、再入场及资金规模，完整账户不能由每仓标签相加或相乘替代。去2026为截至2025年末真实净值；未平仓按市值计价，未假设期末成交。费用已包含在收益中，绝对费用总额不直接等于费率的因果影响。', '',
        'H15与H10每个对应方案仅17次共同入场，另有121次H10独有、80次H15独有。以B为例，共同持有差−0.079654 log、被替换的H10机会差分−2.321652、新机会+1.571421，合计落后−0.829885。原138个H10入场的H15标签不是实际H15选择的97个入场，因此前轮每仓标签的正平均未转化为完整路径收益优势。R/P的同样三部分也均未补回原H10独有路径的贡献。', '',
        '同H15内三者97次实际入场完全对齐。R减B全期log差−0.578474，P减B+0.290047；P有退出增量，但年度收益通过数仍与B同为2/7，不能当作已达标组件。R相对B的回撤改善也伴随收益损失，2025就是明确反例。', '',
        '实际B/P闭合96笔、R闭合97笔，均超过频率目标至少83笔，说明本次容量没有阻止验收；它不能替代收益证据。三者实付费用均低于对应H10，完整收益仍更低，故不能将失败简单归咎于过度换手。H15-B截至2025年末仅+3.34%、R−48.24%、P+48.61%，均低于对应H10，劣势并非只由2026决定。', '',
        '## 验证与下一步', '',
        f"预检{pre['check_count']}项PASS、独立账户审计{audit['check_count']}项PASS；12项复利核对最大绝对收益误差{max_error:.3g}。三个H10账户只核对原正式证据，未重新执行。", '',
        '三账户均97次真实入场。R提前退出88次，预约空仓等待905日，其中666日原本符合入场条件但被预约阻止；P首次破坏88次，17次正浮盈选择退出、71次拒绝，后续193个破坏日不重判，等待96日、阻止合条件信号64日。上述等待及阻挡是日数，不是可成交交易笔数。本轮真实卖出失败及停牌日均为0，相关锁存和停复牌边界由预检合成样本覆盖。', '',
        '所有数据已见，跨期限及退出对照相关，不能称独立样本外验证。日频区间触及全量成交是固定研究约定，不代表真实排队撮合已得到验证；全期高收益也不能替代每个自然年的原目标。', '',
        '以下链接以正式交付报告为基准：[固定设计](../../../experiments/EX028_20261018/protocols/comparison_lock.json)、[全部年度及账户比较](../../../experiments/EX028_20261018/others/comparison.json)、[实际路径分解](../../../experiments/EX028_20261018/others/path_diagnostics.json)、[独立账户审计](../../../experiments/EX028_20261018/others/account_audit.json)、[预检](../../../experiments/EX028_20261018/others/precheck.json)、[研究路线及竞争解释](../../../experiments/EX028_20261018/others/research_route_review.json)。', '',
        comp['next_step'], '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 3, 'reused_accounts': 3, 'registered_candidates': 64}))


if __name__ == '__main__':
    main()
