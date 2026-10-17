"""Render the final fixed reservation contrast and audited ten-round synthesis."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
BASES = ('support_exit_H10', 'support_exit_reserve_H10')
NEW = ('support_exit_profit_reserve_H10', 'support_exit_nonprofit_reserve_H10')
NAMES = dict(zip(BASES + NEW, ('C即时再入场', 'R全部保留预约', '仅正浮盈保留预约', '仅非正浮盈保留预约'), strict=True))


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
    budget = read('others/budget_summary.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == pre['status'] == budget['status'] == 'PASS'
    assert read('others/budget_summary_review.json')['status'] == 'PASS'
    assert read('others/research_route_review.json')['status'] == 'PASS'
    assert comp['new_accounts'] == 2 and comp['reused_accounts'] == 2 and comp['account_count'] == 4
    assert len(trials) == 2 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 8
    assert comp.get('conclusion') and comp.get('next_step') and comp.get('budget_conclusion')
    assert budget['unique_candidate_ids'] == 66 and budget['autonomous_new_accounts'] == 52
    assert budget['prior_accounts'] == 14 and budget['completed_account_rounds'] == 10
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第10轮及10轮总结', '', comp['budget_conclusion'], '',
        '## 最后一轮：条件预约对照', '', comp['conclusion'], '',
        '本轮新增C0075/C0076两个账户，复用C0035即时再入场与C0056全部预约两个端点，共4格；新增上游调用0。全部支撑破坏仍照常触发提前卖出，只改变卖出后是否继续等待原E+10预约。首次严格早于E+9收盘的破坏时，冻结含实际买费浮盈P=收盘价/(实际买价×1.001)−1；一组只在P>0保留预约，另一组只在P≤0保留，零属于非正组。', '',
        '未保留预约也必须等实际卖出后才可计划次日买入，不作同日卖出再买入的假设。保留预约最早E+10收盘计划再入场；卖出受阻始终锁存，晚于预约结束才卖出则从实际卖出收盘起可重新计划。到期退出仍按原时钟，P不重判、不依未来卖价改变。与此前按P决定是否卖出的实验不同，本轮固定早退本身，只检验资金等待方式。', '',
        '两互补方向均事前锁定，没有已有证据支持哪组获利。46个完整共同等待窗口只有6个正浮盈例，56个原早退缺少共同路径，35窗结束仍持仓；这些限制不因运行新账户而消失。Optuna仅记录2个固定配置，无自由采样、剪枝、阈值扫描或年度开关。', '',
        '费用、执行和目标均保持：600722.SH、实际2020-01-02至2026-10-15共1642交易日、10万元、单边0.1%、后复权研究、整数手全仓、原限价买入／开盘或跌停开盘加一价位卖出；跨年连续，无期末强平，同一BuyHold。每年收益须达到正BuyHold的1.5倍，否则严格正收益；每年最大回撤严格低于BuyHold；60×闭合交易数÷1642≥3。2026按截至10月15日直接验收。', '',
        '| 构造 | 候选 | 全期收益 | 最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in BASES + NEW:
        q = rows[v]
        lines.append(f"| {NAMES[v]} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"本轮全部原目标通过{comp['all_targets_pass_count']}/4。", '',
        '| 年份 | C即时再入场 | R全部预约 | 仅正浮盈预约 | 仅非正浮盈预约 | 收益门槛 |',
        '|---|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        values = [select(comp['annual'], variant=v, year=year) for v in BASES + NEW]
        q = values[0]
        threshold = f"≥{q['required_return']:.2%}" if q['buyhold_return'] > 0 else '>0%'
        returns = ' | '.join(format(v['return'], '.2%') for v in values)
        lines.append(f'| {year} | {returns} | {threshold} |')
    for v in NEW:
        ret = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{NAMES[v]}收益未过：{'、'.join(ret) or '无'}；回撤未过：{'、'.join(dd) or '无'}。"]
    lines += ['', '正浮盈预约只通过2020收益目标；非正浮盈预约通过2020、2023。两者2021收益虽接近门槛，71.25%与71.61%仍低于71.90%，按原约定均未通过；2022、2024、2025仍有明显缺口。正浮盈方案2025虽盈利36.62%，仍低于40.19%门槛；非正方案该年亏10.24%，且回撤失败。2026均未达到196.46%收益门槛，不能以全期盈利替代逐年验收。']
    lines += ['', '## 参与路径及费用', '',
        '| 构造 | 截至2025年末收益 | 全期持仓收盘日数 | 闭合／未平仓 | 实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in BASES + NEW:
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {NAMES[v]} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '| 新规则减端点 | 共同入场数／log贡献 | 端点独有数／log贡献 | 新独有数／log贡献 | 全期log差 |',
        '|---|---:|---:|---:|---:|']
    for v in NEW:
        for base in BASES:
            q = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=base, changed=v)
            cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
            lines.append(f"| {NAMES[v]}减{NAMES[base]} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', '匹配按真实买入日，log分解核对复利，不是百分点。变化的预约会改变后续真实入场、资金和整数手，不能把不同路径总差直接归因为单次早退状态。去2026用真实年末净值，费用已计入收益、未平仓按市值计价。', '',
        '正浮盈预约相对即时再入场C只有24次新入场、32次旧入场不再出现，201次共同入场贡献仅+0.000280 log；新增与遗漏几乎抵消，合计−0.000763，年度收益通过还从2/7降至1/7。非正预约相对全预约R只保留75次共同入场，63次R独有机会的差分−0.835925，68次新机会仅+0.083191，合计−0.754654。结果没有证实既有浮盈零边界能稳定选择何时等待。', '',
        '## 十轮累计结论与完整候选缺口', '',
        '本次授权10轮已全部使用，新增52个正式账户；与前序14个登记候选合计66个唯一身份。复用基线不重复计新增，参数身份、经济路径和独立证据是不同概念：66个登记身份不是66条独立有效策略。累计文件按候选ID去重并核对复用指标一致，全部原目标仍是唯一验收标准。', '']
    lines += [f"累计全部原目标通过{budget['all_targets_pass_count']}/66；复用指标及年度结果一致性核对{budget['reuse_consistency_checks']}项PASS。", '',
        '| 授权轮次 | 实验 | 新增账户 | 新账户全部目标通过 |', '|---:|---|---:|---:|']
    for r in budget['rounds']:
        lines.append(f"| {r['round']} | {r['experiment']} | {r['new_accounts']} | {r['all_targets_pass_count']} |")
    lines += ['', f"用同一年收益和回撤同时通过数作描述，最高为{budget['max_annual_both_pass_count']}/7；这只是展示剩余缺口的诊断，不替代原目标，不是新的排名或淘汰门槛。下列候选均使用自身连续完整账户，未按年份拼接其他赢家。", '']
    for q in budget['max_annual_both_candidates']:
        lines += [f"{q['candidate']}（{q['variant']}）：全期收益{q['total_return']:.2%}、最大回撤{q['full_max_drawdown']:.2%}，年度收益{q['annual_return_pass_count']}/7、回撤{q['annual_drawdown_pass_count']}/7，每60日闭合{q['frequency_per_60']:.2f}。", '',
            '| 年份 | 候选收益 | 收益目标 | 候选回撤 | BuyHold回撤（须严格小于） | 同时通过 |',
            '|---|---:|---:|---:|---:|---|']
        for a in q['annual']:
            threshold = f"≥{a['required_return']:.2%}" if a['buyhold_return'] > 0 else '>0%'
            lines.append(f"| {a['year']} | {a['return']:.2%} | {threshold} | {a['max_drawdown']:.2%} | {a['buyhold_drawdown']:.2%} | {'是' if a['both_pass'] else '否'} |")
        lines += ['', f"收益未过：{'、'.join(map(str, q['failed_return_years'])) or '无'}；回撤未过：{'、'.join(map(str, q['failed_drawdown_years'])) or '无'}。"]
    lines += ['', 'C0056的高全期收益也有执行与集中性边界：截至2025年末为+144.54%，低于固定H10-B的+163.69%；其全期相对B的优势主要来自2026年入场错位。7月下旬B连续跌停未能卖出，而R按既定日频限价规则买入，后续机会出现差异；这不是对真实排队成交的验证。原[路径异常复核](../../../experiments/EX023_20261018/others/path_exception_review.json)保留订单与行情证据。', '',
        '十轮没有把持仓续接、支撑等待／提前退出、首次破坏浮盈退出、阳线确认、统一短长周期或本轮条件预约组合成满足全部年度目标的策略。完整起始偏移对照也未解决该缺口；H18则被原频率容量上界直接排除。部分构造提供局部收益或风险差异，但这些具体试验不支持把退出时钟调整当成已经解决的收益机制。', '',
        '仍未知的是：哪些入场环境具有可重复、跨行情状态的净收益来源，怎样在不事后挑年份的情况下保留上涨机会并控制下行损失。现有试验没有证明全部数值机制或现有数据已被穷尽，也没有给出购买公告数据的必要性。后续应以该问题和可反驳的收益机制为依据，而不是继续增加组件数量。', '']
    lines += ['', '## 验证及后续边界', '',
        f"本轮预检{pre['check_count']}项PASS、独立账户审计{audit['check_count']}项PASS；8项全期／去2026复利核对最大绝对误差{max_error:.3g}。累计汇总复核PASS，重复引用账户未重新执行。", '',
        '正浮盈预约实际225次买卖，174次首次提前破坏中24正、150非正，保留预约24次、实际卖出后释放150次，另51次按到期退出；非正浮盈预约143次买卖，107次首次破坏中12正、95非正，保留95次、释放12次，另36次到期。两者预约等待68／634日、阻止合条件信号41／452日；这些是日数，不是可成交交易笔数。真实P=0、卖出失败和停牌均未出现，相关边界只由合成预检覆盖。', '',
        '所有研究数据已见且实验为逐步调整，收益曲线和截窗诊断不是独立样本外验证。日频触及即全量成交保持原约定，未证明真实排队成交。此轮结束本次实验额度，新增账户需要新的预算授权；阶段四也不自动启动。', '',
        '以下链接以正式交付报告为基准：[固定设计](../../../experiments/EX029_20261018/protocols/comparison_lock.json)、[本轮账户及年度目标](../../../experiments/EX029_20261018/others/comparison.json)、[实际路径](../../../experiments/EX029_20261018/others/path_diagnostics.json)、[独立审计](../../../experiments/EX029_20261018/others/account_audit.json)、[预检](../../../experiments/EX029_20261018/others/precheck.json)、[10轮去重累计及完整年度缺口](../../../experiments/EX029_20261018/others/budget_summary.json)、[累计独立复核](../../../experiments/EX029_20261018/others/budget_summary_review.json)、[研究诊断建议与反例](../../../experiments/EX029_20261018/others/research_route_review.json)。', '',
        comp['next_step'], '',
        '建议的首个阶段二问题具体为：滚动5日最低收盘下移时产生的“表面恢复”，与价格真正收复上次破位时冻结的支撑位，是否对应不同后续收益。应覆盖全体可观察机会，明确当时可知的状态，并保留旧破位位以下重入69笔仍有正贡献的既有反例；不能由一个直觉直接添加过滤器。本轮不执行这项新诊断，需要另行批准研究阶段与预算。', '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 2, 'reused_accounts': 2, 'registered_candidates': 66}))


if __name__ == '__main__':
    main()
