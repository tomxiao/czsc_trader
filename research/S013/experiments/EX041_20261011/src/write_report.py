"""Reproduce two targeted reentry accounts and full-domain parameter conclusion."""
from common import SRC, RUNS, PROTOCOLS, read, write


def main():
    analysis, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert analysis['status'] == 'PASS' and parameter['status'] in ('PASS', 'NOT_APPLICABLE')
    labels = ('B0-TIME', 'B0-MEAN', 'N0', 'N1')
    assert set(analysis['rows']) == set(labels)
    text = '''# S013：下跌定时退出后再次入场的价格方向最小对照

RSCH阶段三，用户授权自主研究，无需逐轮评审。原S013数据、四项经济门和13维完整域保持。

EX033原33完整账户诊断显示下跌TIME退出后常在原范围/路由条件刷新前重新入场。EX034/35刷新等待已损害交易次数和基准亏损年盈利。EX040四个所有下跌买入方向门也失败：闭合交易95–106笔不足110，2023收益全部为负。此次只把价格门放在原定时退出后的再次入场上下文，检验减少不当重复买回是否有净改善；这些已见信息和失败结果在选择前已披露。

两新配置均保留EX028均值居中自相关背景：当前ACF20减严格过去L估计均值，L为原confirmation.lookback；其原C8701背景123笔，仅2024年度回撤不满足原门。只在T空仓、原资格合格、rawregime=bear，并且上次信号退出路线bear/原因time、其后没有任何新信号入场时，分别加严格Close>前一实际日Close或Close>当日Open。等号拒绝，方向拒绝优先原确认拒绝。每次持仓信号退出保存退出前路线与原因，每次任意路线成功信号入场清除二者；方向拒绝、资格失败、空仓时路由变化不清除。这是策略信号状态，与实际成交/闭合交易不同。

首次/非TIME/上次bull-TIME下跌机会及全部bull机会保留原入场；所有持仓loss/trailing/range/time/regime退出、原H8/H4信号持仓日、原确认分与阈值不变。没有新增等待刷新条件、止损、风险宽度、幅度阈值或年份例外。新增两类别与上下文范围不在原13数值坐标中，未证明类别或范围选择稳定。全部13数值仍有效，MEAN既有L+21预热和W+2纯前路由诊断依赖披露。

510500.SH、2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、统一可执行价口径、整手100、T决策/T+1执行、单边0.1%费用、策略与LimitBuyHold统一1%限买溢价。原四门：年化≥正基准1.5倍；每自然年回撤严格低于基准；每60日≥4闭合交易（至少110笔）；基准亏损年2022/2023实际连续账户收益为正。全窗回撤是诊断，不替代年度门。

两新业务配置、三实际完整评价（N0串行/spawn完全一致重复），两旧完整原生背景精确复用。原生全部信号与现金/数量/费用账本独立核对，四账户五基准账本一致。日期按已绑定公共交易日历、完整signal_dates和执行日期验证全部1636对T→下一会话；信号行情截至末T，无未来价格或删除末端信号。所有失败账户和年份保留。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for label in labels:
        row = analysis['rows'][label]
        failures = '、'.join(k for k, v in row['gates'].items() if not v)
        text += f"|{label}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:+.4%}|{row['annual']['2023']['return']:+.4%}|{'通过' if row['qualified'] else failures}|\n"
    text += '\n|账户|自然年|收益|回撤|基准回撤|年度回撤门|\n|---|---:|---:|---:|---:|---|\n'
    for label in labels:
        row = analysis['rows'][label]
        for year, value in row['annual'].items():
            benchmark = row['benchmark_annual'][year]['drawdown']
            text += f"|{label}|{year}|{value['return']:+.4%}|{value['drawdown']:.4%}|{benchmark:.4%}|{'通过' if value['drawdown'] < benchmark else '未通过'}|\n"
    achieved = False
    if parameter['status'] == 'PASS':
        original = parameter['summaries']['B0-TIME']
        text += '\n|中心|收益Q10|回撤Q90|收益退化|回撤退化|邻点四门通过数|\n|---|---:|---:|---:|---:|---:|\n'
        for label, row in parameter['summaries'].items():
            text += f"|{label}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']:.4%}|{row['drawdown_degradation']:.4%}|{row['qualified_points']}/32|\n"
            if label != 'B0-TIME':
                achieved |= bool(analysis['rows'][label]['qualified'] and row['q10_cagr'] > original['q10_cagr'] and
                    row['q90_drawdown'] < original['q90_drawdown'] and row['return_degradation'] < original['return_degradation'] and
                    row['drawdown_degradation'] < original['drawdown_degradation'])
        text += '\n参数保持原13完整域、域宽归一总L2=.05、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位。中心满足四门且绝对尾部与相对退化同时改善才说明开发池实质改善；较弱中心造成退化缩小不算。邻点资格是诊断。原EX01532完整原生身份/计划/绑定/账户精确复用。\n'
    else:
        assert not any(analysis['rows'][label]['qualified'] for label in ('N0', 'N1'))
        text += '\n两新中心均未通过原四门，按事前方案零新增参数账户。本轮无参数敏感性改善证据。\n'
    decision = read(PROTOCOLS / 'decision.json')
    text += '\n' + '\n\n'.join(decision['conclusions']) + '\n\n' + decision['next_action'] + '\n'
    text += '\n已见开发池反复选择存在偏差，不是独立验证或未来保证。全路径差异是完整账户对照，不能用删掉旧交易的盈亏相加替代新利润。FULL只核验证据完整性。未推进正式阶段四、冻结、PTE或生产。\n'
    correction = read(PROTOCOLS / 'technical_correction.json')
    assert correction['new_account_evaluations'] == 0 and correction['runtime_changed'] is False
    text += '\n原独立审计在last_exit_reason初始无退出记录的493行发现原生NaN与重建None表示差异。冻结原源码与失败完整保留；显式v2仅核对last_exit_reason/last_exit_route两类别字段的相同缺失位置，所有非空类别和经济字段仍严格相等，拒绝17项非法状态/表示篡改。特征、全状态重建及日历函数AST完全相同，原生账户未重跑，参数、规则和四门未变。\n'
    write(RUNS / 'conclusion.json', {'objective_achieved': achieved, 'status': 'COMPLETE',
        'new_qualified': sum(analysis['rows'][label]['qualified'] for label in ('N0', 'N1')),
        'mechanism_actual_evaluations': 3, 'new_mechanism_business_accounts': 2, 'reused_center_accounts': 2,
        'new_parameter_business_accounts': parameter.get('new_parameter_business_accounts', 0),
        'parameter_actual_evaluations': parameter.get('actual_parameter_evaluations', 0),
        'reused_parameter_accounts': parameter.get('reused_parameter_accounts', 0), 'economic_targets': 'UNCHANGED'})
    target = SRC.parent / 'others/report.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved}, flush=True)


if __name__ == '__main__':
    main()
