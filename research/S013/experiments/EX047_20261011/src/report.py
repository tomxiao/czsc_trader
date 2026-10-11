"""Explain observed-state single-coordinate triggers without profit attribution."""
from collections import Counter
from common import SRC, ROOT, PROTOCOLS, RUNS, OUTPUT, read, write
from native_reference import verified_json
from diagnose import source_check


def main():
    plan = source_check()
    result = read(OUTPUT)
    assert result['status'] == 'PASS' and len(result['pairs']) == 32 and len(result['audits']) == 33
    counts = Counter()
    for pair in result['pairs'].values():
        assert pair['status'] == 'PASS' and pair['days'] == 1636
        counts.update(pair['summaries']['ALL'])
    coordinates = result['coordinates']
    coordinate_table = []
    for name in coordinates:
        row = {'coordinate': name}
        for state in ('center_state', 'point_state'):
            for statistic in ('forward_changes_base', 'forward_reproduces_changed_full',
                              'reverse_changes_full', 'reverse_restores_base', 'individual_change_cancelled_in_full'):
                row[state + '/' + statistic] = counts[f'{state}/target/{name}/{statistic}']
        coordinate_table.append(row)
    contrast = verified_json(plan['supplemental_evidence']['native-contrast'])
    summary = contrast['summary']
    conclusion = {'status': 'COMPLETE', 'objective_achieved': False, 'new_account_evaluations': 0,
        'new_account_preparations': 0, 'unique_native_accounts_full_coordinate_diagnosis': 33,
        'supplemental_actual_centers': 2, 'unique_accounts_across_materials': 35,
        'summary': result['summary'], 'counts': dict(counts), 'coordinate_target_table': coordinate_table,
        'first_actual_divergence': {key: pair['first_actual_divergence'] for key, pair in result['pairs'].items()},
        'EX046_incremental_counterevidence': summary,
        'goal_policy': plan['economic_targets'],
        'mechanism_duplicate_rejected': 'Three finite raw-momentum median >=theta iff at least2of3 raw values >=theta. Exact EX024 RegimeMajority3 in original13 domains. No new account.',
        'limits': plan['limits'],
        'next': 'Return to original numeric center. Do not smooth or delay both routes indiscriminately. Assess one bear-only rawbull regime-exit confirmation structure with original time/range priority and immediate bull downside exit; only prospectively declared full center and qualified full32 can establish economics. Native conditional trigger counts are not profit forecasts.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# 原C2132参数的当天触发与历史持仓诊断', '',
        'RSCH，S013阶段三；本轮诊断完成，改善参数敏感性的总目标尚未达成。原中心与32个完整账户精确复用，另保存2个既有中心的增量反证；零新账户、零资金重放。', '',
        '## 先看经济结果', '',
        '原中心净年化16.1572%、全窗回撤14.1599%、112笔闭合交易，四项经济目标通过；完整13维的32个共同扰动点，较差一端年化Q10仅5.8974%、回撤Q90为30.5044%。中心达标不能说明参数邻域稳定。EX043与EX045两次改法的绝对尾部更差，未实现改善。', '',
        f"EX046清除跨rawbull状态的旧类别记忆，年化从{summary['old_cagr']:.4%}降为{summary['new_cagr']:.4%}，低于本次原生买入持有基准对应门槛{summary['required_return_threshold']:.4%}。因此没有展开新32点，不能声称参数敏感性改善。", '',
        f"三次旧门拒绝在新真实路径上均变为入场，三个新增实际闭合周期均净亏。费用减少{-summary['total_fees_difference']:.2f}元，最终权益仍减少{-summary['final_equity_difference']:.2f}元。这是完整账户事实，不是把旧交易删掉再加减收益。2023/2024全部目标、信号原因和实际成交时点/价格相同，微小年度收益差来自继承现金与整手预算。完整两次诊断假设/日账联接失败和修正源码保留，正式账户未改。", '',
        '## 方法：分别只换一个参数，观察当天决定', '',
        '对每个点、每一天，在原中心的既有持仓状态和扰动点的既有持仓状态上分别计算。正向只把一个中心参数换为该点值；反向只把一个点参数恢复中心值。价格、rawACF20、原退出优先级等保持，改变窗口则重算其完整依赖：区间窗口影响对应高低价位置，确认窗口影响原完整分数，市场窗口与门槛分别用原收益率单位重算。边界等号属于上涨状态。', '',
        '全部13项、32点、1636信号日期、信号年2019—2026/执行年2020—2026、无执行日期均保留；每个新决定的下一信号状态只记录一次，不传到后一天。故这不是13套新账户，不能从次数推断收益贡献。观察到的历史持仓本身由之前联合13项参数变化形成。', '',
        f"原32点与中心实际目标仓位不同共{counts['actual/target/different']}点天。固定中心既有状态时，联合改变13项当天条件产生{counts['center_state/target/all_coordinates_change']}点天目标差异；固定各扰动既有状态时为{counts['point_state/target/all_coordinates_change']}点天。前后持仓状态不同仍会改变结果，两组计数不是可相加的损失来源。", '',
        '|只换一个参数|中心既有状态：当天目标改变|扰动既有状态：当天目标改变|反向恢复：扰动状态目标改变|',
        '|---|---:|---:|---:|']
    for row in coordinate_table:
        lines.append(f"|{row['coordinate']}|{row['center_state/forward_changes_base']}|{row['point_state/forward_changes_base']}|{row['point_state/reverse_changes_full']}|")
    lines += ['',
        f"联合条件改变目标、但没有任何单项替换能独自复现该目标的点天：中心状态{counts['center_state/target/changed_full_no_single_reproduces']}，扰动状态{counts['point_state/target/changed_full_no_single_reproduces']}。各参数可能重叠、相互掩盖或抵消；不把表中数字相加，不把触发较多解释为更大收益因果。完整目标/最终原因/下一状态及所有年分组、首次分歧分别留存。", '',
        '## 否决重复机制，下一步收敛对照', '',
        '三个有限原动量的中位数达到门槛，等价于三个原状态至少两次为上涨；这与EX024已失败的三日多数票完全相同，故没有为改名再运行账户。EX017/30延迟上涨退出降低交易频率并出现亏损年份，不能笼统把更多等待当作改进。', '',
        '下一项仅作为待检验机制：只让下跌路线持仓在连续两日原市场状态为上涨后按状态退出，上涨路线转下跌仍立即退出；原区间和持仓天数退出优先级保持。它与旧上涨退出延迟/整体多数票不同，但可能延迟亏损退出、减少交易，且可能不解决期限和过滤脆弱性。须先事前留证、完整新中心四门，再决定是否运行全部原32点；不从本轮诊断预测收益。', '',
        '## 验证与边界', '',
        '33个账户完整公共身份、序列化证据、参数计划/派生/点坐标、原特征和全信号状态、执行日历、现金/数量/费用/交易周期/尾仓及共同基准五类账本逐项核对。纯映射89项检查、52正反映射/恒等与104次固定状态调用通过；Ruff通过。未做仓库全量回归。', '',
        '只用反复研究的S013已有开发池与预热，无新增行情、独立样本或跨批次材料。完整13个原域、同32共同坐标及四项经济目标保持；不额外要求全部32点达标，也不以诊断次数新增否决条件。技术PASS仅确认声明材料完整与计算一致，不代表经济目标达成。未推进正式阶段四、冻结、PTE、生产、合并、tag或推送。', '',
        '正式数据资产与绑定仍须保留；Git源码与交付包装不是数据资产备份。']
    report = SRC.parent / 'others/report.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    assert ROOT.name == 'czsc_trader'
    print({'report': 'READY', 'objective_achieved': False, 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    main()
