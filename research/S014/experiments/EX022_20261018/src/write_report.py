"""Render every fixed timing pair after evidence, audit and interpretation exist."""
import json
from pathlib import Path
from statistics import median

EX = Path(__file__).resolve().parents[1]
BASES = ('repeated_H10', 'support_entry_H10')


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    matches = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(matches) == 1, where
    return matches[0]


def dist(values):
    return f'{min(values):.2%}／{median(values):.2%}／{max(values):.2%}'


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    trials = read('others/optuna_trials.json')['trials']
    assert paths['status'] == audit['status'] == pre['status'] == 'PASS'
    assert comp['account_count'] == 22 and comp['new_accounts'] == 20 and comp['reused_accounts'] == 2
    assert len(trials) == 20 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 44
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret the audited evidence before rendering.'
    full = sorted((r for r in paths['paired_controls'] if r['window'] == 'ALL'), key=lambda r: r['delay'])
    early = sorted((r for r in paths['paired_controls'] if r['window'] == 'WITHOUT2026'), key=lambda r: r['delay'])
    assert [r['delay'] for r in full] == [r['delay'] for r in early] == list(range(11))
    by_variant = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第3轮：支撑入场的首次决策时点敏感性', '',
        comp['conclusion'], '',
        '## 固定范围与原目标', '',
        '本轮新增20个账户，精确复用EX021中A/B的delay0两个账户，共22个对照；继承前25个候选后累计45个唯一账户候选，交付拟为CANDIDATES/6承接CANDIDATES/5。本轮为10轮预算中的第3轮，第4轮已另行锁定，尚未分配6轮；新增上游调用0，公告追溯继续暂缓。', '',
        'A在空仓时按原规则重复计划买入；B仅当当日后复权收盘不低于此前5个评价交易日最低收盘时计划买入，支撑线不含当前日。两者均在实际买入日E后固定10日退出：E+9收盘决策、E+10计划卖出。卖出失败保持退出意图，失败买入按原规则清除并等后续完成日再判断；没有新增主动止损。', '',
        '只改变首次可决策日：完成60+delay个评价交易日后启动，delay固定为0至10；后续不重复加入等待，也不按日历强迫成交。11个偏移对应无失败订单时“持有10日加下一日重新入场”的理想周转长度；真实失败和支撑等待会改变节奏，所以并未覆盖所有可能相位。A/B同偏移配对比较，不能选择最高收益偏移充当策略，也不能把11对视为11份独立样本。', '',
        '首次日期不同会把买卖日期向后移动；之后一次买入失败、一次支撑不满足或一次卖出延期，又可能把两条路径重新拉开或拉到相同交易日。即使后续成交日期相同，早期盈亏留下的资金及整数手差异仍然存在，不代表净值完全相同。', '',
        '沿用600722.SH的2020-01-01至2026-10-15研究期，实际1642交易日、初始10万元、单边0.1%费用、后复权研究口径、100股整数手及原全仓限价买入／开盘卖出规则。跌停开盘加一价位卖出仍须区间触及；无排队、部分成交或额外滑点。无年度重置、无期末强平，所有固定BuyHold证据一致且首次买入2020-01-02。', '',
        '每年收益在BuyHold正收益时至少达到其1.5倍，否则严格正收益；每年最大回撤严格低于BuyHold。2026截至10月15日直接纳入、不年化。年度回撤包含年初衔接净值，平均频率为60×闭合交易数÷1642≥3。时间敏感性只是诊断，没有新增通过数量、最差偏移或显著性硬门。', '',
        'Optuna将20个新增配置事前全部enqueue，逐一核对身份后用真实账户结果tell；delay0只复用原正式证据，不重复执行。没有自由搜索、剪枝、追加偏移或按结果选优。全部数据已经用于研究，以下均为已见样本诊断。', '',
        '## 全部配对及原目标情况', '',
        f"22个账户满足全部原目标的数量为{comp['all_targets_pass_count']}。下表列出每个偏移，不挑选最佳项。每格“A／B”保持同一顺序；收益、回撤列为全期值。", '',
        '| 首次偏移 | A收益 | B收益 | B−A收益差（百分点） | A／B最大回撤 | A／B年度收益通过 | A／B年度回撤通过 | A／B每60日闭合数 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in full:
        d = r['delay']
        a, b = [by_variant[f'{base}_delay{d}'] for base in BASES]
        lines.append(f"| {d} | {r['A_return']:.2%} | {r['B_return']:.2%} | {r['return_difference']*100:+.2f} | {a['full_max_drawdown']:.2%}／{b['full_max_drawdown']:.2%} | {a['annual_return_pass_count']}／{b['annual_return_pass_count']} | {a['annual_drawdown_pass_count']}／{b['annual_drawdown_pass_count']} | {a['frequency_per_60']:.2f}／{b['frequency_per_60']:.2f} |")
    lines += ['', f"固定BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。年度通过数分母均为7。",
        '', '## 配对分布与去2026核对', '',
        '| 窗口 | A收益：最小／中位／最大 | B收益：最小／中位／最大 | B−A：最小／中位／最大 | B收益高于A的配对数 |',
        '|---|---:|---:|---:|---:|']
    for name, records in [('全期', full), ('截至2025年末', early)]:
        lines.append(f"| {name} | {dist([r['A_return'] for r in records])} | {dist([r['B_return'] for r in records])} | {dist([r['return_difference'] for r in records])} | {sum(r['return_difference'] > 0 for r in records)}/11 |")
    lines += ['', '收益差分布按同偏移逐对计算，再取分位；不是两组中位收益直接相减。这里的收益差百分数表示百分点。去2026使用2025年末真实净值，未平仓按当时市值计价，没有虚构提前卖出或卖出费。', '',
        '| 偏移 | 截至2025年末A收益 | B收益 | B−A收益差（百分点） |',
        '|---|---:|---:|---:|']
    for r in early:
        lines.append(f"| {r['delay']} | {r['A_return']:.2%} | {r['B_return']:.2%} | {r['return_difference']*100:+.2f} |")
    lines += ['', '## 年度分布与门槛', '',
        '| 年份 | B−A收益差：最小／中位／最大 | B收益高于A | A／B收益达标数 | A／B回撤达标数 | 收益门槛 | BuyHold回撤 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        records = [r for r in paths['annual_paired'] if r['year'] == year]
        assert len(records) == 11
        a = select(comp['annual'], variant='repeated_H10_delay0', year=year)
        threshold = f"≥{a['required_return']:.2%}" if a['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {dist([r['return_difference'] for r in records])} | {sum(r['return_difference']>0 for r in records)}/11 | {sum(r['A_return_pass'] for r in records)}／{sum(r['B_return_pass'] for r in records)} | {sum(r['A_drawdown_pass'] for r in records)}／{sum(r['B_drawdown_pass'] for r in records)} | {threshold} | {a['buyhold_drawdown']:.2%} |")
    lines += ['', '2022年B所有偏移的收益及回撤均达标；2024年B所有偏移都亏损，收益及回撤均未达标，且收益全部低于同偏移A。2023、2025、2026的B年度收益也全部未过门槛。因后续成交日期收敛，这种一致性主要来自共同执行路径，不能解释为11次独立复验。', '',
        '年度达标数分母为每组11个偏移，并非独立成功次数。原验收仍逐个完整账户检查全部7年和频率，不能将不同偏移的好年份拼接为达标策略。', '',
        '## 实际成交路径与相位', '',
        '| 偏移 | A／B首次实际买入 | A／B相对delay0不同成交事件数 | A／B最后不同成交日 | A/B共同入场数（全期） |',
        '|---|---|---:|---|---:|']
    for d in range(11):
        aa, bb = [select(paths['execution_dates'], base=base, delay=d) for base in BASES]
        dates = [r['last_different_execution_date'] or '无差异' for r in (aa, bb)]
        lines.append(f"| {d} | {aa['first_actual_buy']}／{bb['first_actual_buy']} | {aa['different_execution_date_side_events']}／{bb['different_execution_date_side_events']} | {'／'.join(dates)} | {full[d]['matched_entry_count']} |")
    lines += ['', 'B各非零偏移最晚在2021-04-14之后，观察到的成交日期与delay0一致；早期资金差仍延续。B的delay8、delay9首次实际买入均为2020-04-17，全部经济结果一致。这些是支撑等待把不同起点拉回同一参与节奏的具体证据，也限制了11组配对能提供的独立信息量。', '',
        '不同成交事件按日期与买卖方向比较，忽略股数；最后不同日只说明其后观察到的成交事件一致，不保证未来永不分离。同偏移A/B共同入场很少时，收益差主要需理解为完整参与路径变化，而不是对固定交易清单逐笔删选。', '',
        '## 审计、证据与下一步', '',
        f"因果及公共输入预检{pre['check_count']}项PASS；独立账户审计{audit['check_count']}项PASS。22个账户全期和去2026共44项资金周期复利核对，最大绝对收益误差{max_error:.3g}。独立审计覆盖真实成交计时、支撑线、启动偏移、失败订单、费用资金、无订单日、末日及固定BuyHold；复用账户核对原证据，不新增回放。真实停牌日为0，停牌相关边界由合成预检覆盖，不能称已有真实停牌验证。", '',
        '以下链接以正式交付报告为基准：[锁定设计](../../../experiments/EX022_20261018/protocols/comparison_lock.json)、[全部账户与年度目标](../../../experiments/EX022_20261018/others/comparison.json)、[配对和路径诊断](../../../experiments/EX022_20261018/others/path_diagnostics.json)、[账户审计及完整审计指纹](../../../experiments/EX022_20261018/others/account_audit.json)、[预检与源码输入指纹](../../../experiments/EX022_20261018/others/precheck.json)。全部原始证据引用和CSV在上述文件中保留。', '',
        comp['next_step'], '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 20, 'reused_accounts': 2, 'registered_candidates': 45, 'report': 'protocols/account_report.md'}))


if __name__ == '__main__':
    main()
