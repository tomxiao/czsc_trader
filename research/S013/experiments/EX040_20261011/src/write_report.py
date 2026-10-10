"""Reproduce four complete-account direction contrasts and qualified parameter tails."""
from common import SRC, RUNS, PROTOCOLS, read, write


def main():
    analysis = read(RUNS / 'analysis.json')
    parameter = read(RUNS / 'parameter_analysis.json')
    assert analysis['status'] == 'PASS' and parameter['status'] in ('PASS', 'NOT_APPLICABLE')
    labels = ('B0-TIME', 'B0-MEAN', 'N0', 'N1', 'N2', 'N3')
    assert set(analysis['rows']) == set(labels)
    text = '''# S013：下跌入场反弹方向最小完整账户对照

RSCH阶段三，用户授权自主推进，无需逐轮评审。原数据与四项经济门保持，不增加诊断否决门。

EX039精确复用35个账户的逐日诊断：原中心57次下跌买入均通过确认，但较前收上涨23次、收高于开盘22次；原33依赖账户2014次下跌买入对应765/769次。原生2023下跌10次入场两个门各保留6次，2024的10次中保留3/2次。原确认通过不等于反弹已经开始；这些计数不是新策略收益。

本轮四新配置为RAW/MEAN自相关背景×两个严格方向门。RAW原自相关ACF20与阈值保持；MEAN精确继承EX028 current ACF减严格过去L估计均值，L为原确认lookback。只对决策T空仓、原资格合格、rawregime=bear的机会，附加Close>前一实际日Close或Close>当日Open；等号和负方向拒绝，方向拒绝优先于原确认拒绝。bull和所有持仓loss/trailing/range/time/regime退出、原H8/H4、确认分与阈值保持。无额外BODY上涨背景、风险退出、等待或日期例外。

所有13原数值中心及完整域保持。方向谓词是两种新类别选择，未增加幅度阈值；类别本身不在13数值扰动中，不能宣称其稳定性。previous-regime诊断要求W+2历史，但不影响当前rawbear入场门；全部已声明32原域点已有充分原预热。MEAN的L+21基准预热保持。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号/统一执行价口径、整手100、T决策/T+1执行、单边0.1%费用、策略与可执行LimitBuyHold统一1%限买溢价。原四门：年化≥正基准1.5倍；每自然年回撤严格低于基准；每60日≥4闭合交易（至少110笔）；基准亏损年2022/2023实际连续账户收益正。全窗回撤是诊断，不替代年度门。

四新业务配置、五实际完整评价（N0串行/spawn严格一致重复），两旧完整原生背景精确复用。全部失败路径保留，独立重算完整特征、方向、机会、持仓状态及现金/数量/费用账本，六账户五基准账本一致。最强反证是限制入场可能错失恢复、减少交易并伤害薄弱年份利润；原112笔仅比110门多两笔，2023仅+0.2841%。本轮使用已见诊断选择机制，属于开发池研究，不是独立验证。

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
        text += '\n参数保持原13完整域、域宽归一总L2=.05、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位。中心满足四门且绝对尾部与相对退化同时改善才说明开发池实质改善；较弱中心造成退化缩小不算，邻点资格仅作诊断。原EX01532原生参数账户精确复用。\n'
    else:
        assert not any(analysis['rows'][label]['qualified'] for label in ('N0', 'N1', 'N2', 'N3'))
        text += '\n四新中心无一通过原四门，按事前方案不扩展新增参数账户。没有参数敏感性改善证据。\n'
    decision = read(PROTOCOLS / 'decision.json')
    text += '\n' + '\n\n'.join(decision['conclusions']) + '\n\n' + decision['next_action'] + '\n'
    text += '\n技术修正保留：原日期oracle将T+1错误地要求存在于截止T的信号行情，因末端09-29决策/09-30执行而失败。冻结原源码、方案、几何与完整账户结果保持不可变；独立v2在事前技术方法中绑定原失败和全部源码哈希，以同prepared公共日历/完整signal_dates/执行日期核对1636对会话。12组合成末端检查、34非法日期或绑定拒绝及特征/状态/统计AST一致性证明通过，实际v2全路径审计通过；零重跑账户、零数据扩展、零删日。\n'
    text += '\n全部年份、失败路径和不可变证据保留。FULL只核验证据完整性，不证明经济达标、独立验证或未来表现。未推进阶段四、冻结、PTE或生产。\n'
    write(RUNS / 'conclusion.json', {'objective_achieved': achieved, 'status': 'COMPLETE',
        'new_qualified': sum(analysis['rows'][label]['qualified'] for label in ('N0', 'N1', 'N2', 'N3')),
        'mechanism_actual_evaluations': 5, 'new_mechanism_business_accounts': 4, 'reused_center_accounts': 2,
        'new_parameter_business_accounts': parameter.get('new_parameter_business_accounts', 0),
        'parameter_actual_evaluations': parameter.get('actual_parameter_evaluations', 0),
        'reused_parameter_accounts': parameter.get('reused_parameter_accounts', 0), 'economic_targets': 'UNCHANGED'})
    target = SRC.parent / 'others/report.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved}, flush=True)


if __name__ == '__main__':
    main()
