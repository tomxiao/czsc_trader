"""Render the fixed EX007 support prototypes from EX021 audited evidence."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
A, B, C = 'repeated_H10', 'support_entry_H10', 'support_exit_H10'
LABELS = {'baseline_H3': '原H3（上下文）', 'baseline_H6': '原H6（上下文）',
          'renewal_parent_H3_cap0': 'C0028续持（上下文）',
          A: 'A：固定10日重复入场', B: 'B：支撑入场／固定10日', C: 'C：支撑入场／破坏退出'}


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    result = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(result) == 1, where
    return result[0]


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    trials = read('others/optuna_trials.json')['trials']
    assert paths['status'] == audit['status'] == pre['status'] == 'PASS'
    assert comp['account_count'] == 6 and comp['all_targets_pass_count'] == 0
    assert len(trials) == 3 and all(t['state'] == 'COMPLETE' for t in trials)
    assert comp['new_accounts'] == 3 and comp['reused_accounts'] == 3
    rows = {r['variant']: r for r in comp['summaries']}
    assert rows[B]['annual_return_pass_count'] == 3 and rows[C]['annual_return_pass_count'] == 2
    early = {r['variant']: r for r in paths['exposure'] if r['window'] == 'WITHOUT2026'}
    ba = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=A, changed=B)
    cb = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=B, changed=C)
    cb22 = select(paths['decompositions'], window='ALL', entry_cohort='2022', baseline=B, changed=C)
    assert len(paths['reconciliations']) == 12
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    comp['conclusion'] = (
        f"第2轮固定A/B/C账户中，B支撑入场固定10日全期净收益{rows[B]['total_return']:.2%}，"
        f"去2026仍为{early[B]['return']:.2%}，改善2021、2022收益，但年度收益仅3/7、回撤5/7通过。"
        "B与A仅9个共同入场，优势主要体现为交易时点及后续参与顺序改变，不能认定为稳定单笔过滤能力。"
        "C支撑破坏退出增加换手并降低B全期收益，损伤2022；6个对照全部原目标通过0个，尚不具备阶段四准备度。"
    )
    comp['next_step'] = (
        "继续已公开锁定的[第3轮EX022](../../../experiments/EX022_20261018/protocols/comparison_lock.json)："
        "A/B各取首次决策延后0至10日，0精确复用，新增20账户；只改首次可决策日，不改变后续等待和固定10日持有。"
        "核对同偏移B−A的全部11组，不选择最佳偏移；11覆盖无失败时H10的理想周转长度，但真实失败订单打破周期性，"
        "不能称覆盖所有可能相位或11个独立样本。借此检验B优势的起始时点敏感性，再考虑与C0028续持路径的互补，"
        "只允许当时可知状态驱动，不按事后年度切换。暂不扩支撑窗口、阈值或主动止损参数，不自动推进阶段四。"
    )
    (EX / 'others/comparison.json').write_text(json.dumps(comp, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    lines = ['# S014 阶段三自主第2轮：前5日收盘低点支撑的连续账户对照', '',
        f"**发现值得继续验证的账户路径改善，但尚未达标。** B支撑入场／固定10日的全期净收益为{rows[B]['total_return']:.2%}，"
        f"截至2025年末仍盈利{early[B]['return']:.2%}；2021、2022收益改善明确。但B年度收益仅3/7、回撤5/7通过，"
        'C主动退出也未补足缺口。6个对照全部原目标通过0个，不能进入阶段四。', '',
        '## 固定设计与公平比较范围', '',
        '本轮是10轮自主阶段三预算的第2轮，实际新增C0033至C0035三个账户，精确复用C0011、C0016、C0028三个上下文账户。继承前22个候选后共25个唯一账户候选；交付拟为CANDIDATES/5承接CANDIDATES/4。第3轮EX022已另行锁定，剩余8轮包含正在推进的第3轮与尚未分配的7轮。没有新增上游调用，公告追溯继续暂缓。', '',
        '三种新构造来自EX007已提出的A/B/C机械对照，不把早期支撑诊断直接视作已验证收益机制。支撑线为当前日前5个评价交易日后复权收盘价的最低值，不含当日。先完成评价区间内60交易日启动：首次可决策日2020-04-02，首次可能买入日2020-04-03。三者均取消原低开收阳和高环境入场要求；因此A/B/C互为本轮机制对照，原H3、H6与C0028因入场和启动机制不同，仅作历史上下文，不能作单一支撑因素的因果对照。', '',
        '- A：启动后空仓时计划买入，真实买入日E起固定持有10日，E+9收盘发出卖出，计划E+10成交。',
        '- B：与A相同，但空仓时要求当日收盘不低于支撑线才计划买入；买入后仍固定10日退出。',
        '- C：B的入场条件不变；持仓时若收盘低于支撑线，则提前发出卖出，最晚仍按固定10日计划退出。买入当日收盘可以触发下一日卖出，无同日卖出。',
        '- 一次买入未成交后清除旧计划，不在同一收盘重发；后续完成日才重新判断。真实卖出后的收盘可计划下一交易日买入。卖出受阻则保持退出意图，即便支撑恢复也不撤回。', '',
        '仍使用600722.SH已有数据，名义2020-01-01至2026-10-15、实际1642交易日；初始10万元、单边费用0.1%、100股整数手、全额可用资金、后复权研究口径和原限价买入及开盘卖出规则全部保留。跌停开盘卖出使用开盘价加一价位，区间触及才可成交；不引入排队、部分成交或滑点。跨年连续，无年度重置，无期末强平。固定BuyHold从2020-01-02开始且所有账户一致。', '',
        'Optuna仅记录3个事前锁定构造，预先enqueue、按固定身份核对后回放并tell真实目标分数；没有自由参数搜索、扩格或剪枝。所有样本已用于研究，全期和去2026结果均属于已见样本诊断，不是独立样本外验证。', '',
        '逐年收益：BuyHold当年正收益时要求策略收益≥其1.5倍，否则严格>0；各自然年最大回撤严格小于BuyHold。2026截至10月15日直接纳入、不年化。年度回撤包含前一年底衔接净值。频率为60×闭合交易数÷1642≥3，未平仓不计闭合。', '',
        '## 连续账户结果', '',
        '| 构造 | 候选 | 全期净收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in comp['summaries']:
        lines.append(f"| {LABELS[row['variant']]} | {row['candidate']} | {row['total_return']:.2%} | {row['full_max_drawdown']:.2%} | {row['annual_return_pass_count']}/7 | {row['annual_drawdown_pass_count']}/7 | {row['frequency_per_60']:.2f} |")
    lines += ['', f"固定BuyHold全期净收益{comp['buyhold']['total_return']:.2%}、全期最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。三个新构造均达到频率要求，不能用较高全期收益替代逐年验收。", '',
        '## A/B/C逐年收益和B的回撤缺口', '',
        '| 年份 | A收益 | B收益 | C收益 | BuyHold收益 | 收益门槛 | B回撤 | BuyHold回撤 | B收益／回撤通过 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for year in range(2020, 2027):
        aa, bb, cc = [select(comp['annual'], variant=v, year=year) for v in (A, B, C)]
        threshold = f"≥{bb['required_return']:.2%}" if bb['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {aa['return']:.2%} | {bb['return']:.2%} | {cc['return']:.2%} | {bb['buyhold_return']:.2%} | {threshold} | {bb['max_drawdown']:.2%} | {bb['buyhold_drawdown']:.2%} | {'是' if bb['return_pass'] else '否'}／{'是' if bb['drawdown_pass'] else '否'} |")
    lines += ['', 'B的2021收益73.95%超过71.90%门槛，2022收益3.80%恢复正值；但2023、2024亏损，2025、2026虽盈利仍低于门槛，2021和2024回撤也未通过。C把2024修复为盈利，却将2022从B的3.80%变成−26.65%，且2021重新低于收益门槛；不能将主动支撑退出认作普遍改进。', '',
        '## 参与顺序变化比单笔过滤更能解释结果', '',
        '以下按相同实际买入日期匹配资金周期，用周期log收益差精确加总到净值log差；log贡献没有百分比点单位。遗漏项取原路径收益的相反数。它是路径核对，不是相互独立的因果贡献。', '',
        '| 对照／窗口 | 共同入场数／贡献 | 原路径独有数／贡献 | 新路径独有数／贡献 | 合计log差 |',
        '|---|---:|---:|---:|---:|']
    for window in ('ALL', 'WITHOUT2026'):
        for left, right, name in ((A, B, 'B−A'), (B, C, 'C−B'), (A, C, 'C−A')):
            p = select(paths['decompositions'], window=window, entry_cohort='ALL', baseline=left, changed=right)
            cells = [f"{p['counts'][k]}／{p['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
            lines.append(f"| {name}／{'全期' if window == 'ALL' else '截至2025年末'} | {' | '.join(cells)} | {p['total_cycle_log_difference']:+.6f} |")
    lines += ['', f"B与A仅{ba['counts']['matched']}个共同入场，共同贡献接近零；全期改进来自{ba['counts']['right_only']}个不同日期的B入场，"
        '同时遗漏A交易。因此B并非仅从A固定交易清单中删除几笔亏损。A/B/C首次实际买入均为2020-04-03；支撑条件在后续某次等待后改变参与日期，固定10日持有再把日期差沿账户路径传递。支撑信息与时钟相位目前尚未分离。', '',
        f"去掉2026后，A累计{early[A]['return']:.2%}、B {early[B]['return']:.2%}、C {early[C]['return']:.2%}。B相对A的改善在早期仍然存在；但这不能证明邻近持有期限、不同起始相位或未见未来样本同样有效。", '',
        f"C相对B共同{cb['counts']['matched']}个入场贡献{cb['cycle_log_contributions']['matched']:+.6f}，"
        f"遗漏B的{cb['counts']['left_only']}笔贡献{cb['cycle_log_contributions']['left_only']:+.6f}，"
        f"新增C的{cb['counts']['right_only']}笔贡献{cb['cycle_log_contributions']['right_only']:+.6f}。"
        '提前退出既直接改变共同交易收益，也释放资金导致后续不同日期重新参与，不能只评估被止损那一笔。', '',
        f"2022入场队列中，C−B共同{cb22['counts']['matched']}笔贡献{cb22['cycle_log_contributions']['matched']:+.6f}，"
        f"遗漏{cb22['counts']['left_only']}笔贡献{cb22['cycle_log_contributions']['left_only']:+.6f}，"
        f"新增{cb22['counts']['right_only']}笔贡献{cb22['cycle_log_contributions']['right_only']:+.6f}。"
        '新增参与路径损伤大于共同交易提前退出损伤，支持优先检查退出后参与顺序，不能据此追加支撑阈值搜索。入场年份队列可能跨年，它与年度净值验收不是同一口径。', '',
        '| 新构造 | 收盘持仓日数 | 闭合／未平仓 | 实付费用（元） |',
        '|---|---:|---:|---:|']
    for v in (A, B, C):
        r = rows[v]
        lines.append(f"| {LABELS[v]} | {r['exposure_close_sessions']} | {r['closed_trades']}／{r['open_trades']} | {r['fees']:.2f} |")
    lines += ['', 'B比A仅少54个收盘持仓日，但入场日期大幅错开；C比B少198个持仓日、闭合交易增加96笔。费用均按同一0.1%费率实际计算，绝对金额也受复利后资金规模影响，不能把费用金额差单独当作收益差的原因。', '',
        '## 验证与边界', '',
        f"因果及公共输入预检{pre['check_count']}项PASS；独立账户审计{audit['check_count']}项PASS。"
        '核对前5日支撑、60日启动、真实成交日计时、失败买入重置、卖出锁存、每日持仓及现金、整数手、费用、成交价格、无订单日、最后一天和固定BuyHold；复用账户核对原证据，不重复执行。', '',
        f"资金周期复利与账户净值共{len(paths['reconciliations'])}项核对，最大绝对收益误差{max_error:.3g}。"
        f"C真实出现{select(audit['accounts'], variant=C)['support_triggered_exits_before_time_cap']}次时间上限前支撑退出。"
        '本窗真实停牌样本为0；停牌失败和恢复等边界由合成预检覆盖，不能将合成通过称为真实停牌经验。仅保存末日决策，不虚构窗外成交或终点卖出费。', '',
        '以下链接以正式交付报告为基准。正式账户引用见[新增账户](../../../experiments/EX021_20261018/others/account_results.json)、[全部对照](../../../experiments/EX021_20261018/others/comparison_accounts.json)；比较表及年度表见[账户比较](../../../experiments/EX021_20261018/others/comparison.json)；路径分解见[路径诊断](../../../experiments/EX021_20261018/others/path_diagnostics.json)及其列出的CSV。完整审计路径与SHA见[账户审计](../../../experiments/EX021_20261018/others/account_audit.json)，策略和输入指纹见[预检](../../../experiments/EX021_20261018/others/precheck.json)，事前约束见[对照锁定](../../../experiments/EX021_20261018/protocols/comparison_lock.json)。', '',
        '## 下一问题', '', comp['next_step'], '',
        '本轮结论是保留B作为待验证的完整账户构造，暂不接受C为风险改进组件。下一轮应先检验支撑改善能否跨已知时间控制持续，而不是选取收益最高的年度、追加支撑阈值或宣布已找到稳定最优策略。', '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'report': 'protocols/account_report.md', 'new_accounts': 3, 'reused_context_accounts': 3, 'total_unique_candidates': 25}, ensure_ascii=False))


if __name__ == '__main__':
    main()
