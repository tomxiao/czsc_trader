"""Render the explicit research judgment with verified numeric account facts."""
from run import WORK, read, digest

LABELS = {'C0048': 'S017-M009 固定65柱', 'C0049': 'S017-M010 结构失效', 'C0050': 'S017-M011 移动止损'}

def pct(value):
    return '无定义' if value is None else f'{value*100:.2f}%'

def main():
    analysis = read(WORK/'others/analysis.json')
    judgment = read(WORK/'others/judgment.json')
    verified = read(WORK/'others/result_validation.json')
    if (verified['status'] != 'PASS' or verified['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or judgment['analysis_sha256'] != verified['analysis_sha256']):
        raise ValueError('Only verified source-bound results may be rendered')
    summaries = analysis['summaries']
    lines = ['# EX027：固定入场下的三种完整账户退出竞争', '', 'Status: COMPLETED', '',
        '## 结论与下一步', '', judgment['conclusion'], '']
    lines += [f'- {item}' for item in judgment['findings']]
    lines += ['', '**下一步：** '+judgment['next_step'], '',
        '本轮将工程接线、执行一致性核验、固定65柱基线和三种完整账户比较合并为一个研究实验。工程核验不单独占额度；本轮后20轮已发起19轮（完成18、失败1），剩1轮。条件拆解支线仍关闭。技术核验通过不代表策略达标，也不代表进入阶段三。', '',
        '## 固定机制及交易合同', '',
        '三组均使用不变的 **S017-M005**：前柱为阴线，当前完成柱收盘收复前柱高点；前柱成交量至少为其过去20个不同交易日同美东起始时刻成交量中位数的1.5倍，前柱真实波幅不高于更早13柱的平均真实波幅。无新增背景过滤，持仓期间新信号不加仓、不重置时钟。', '',
        '|退出编号|候选身份|规则|', '|---|---|---|',
        '|S017-M009|C0048|真实买入后持有65根完整30分钟柱，再于下一可执行区间卖出。|',
        '|S017-M010|C0049|收盘严格跌破入场信号及前柱的两柱最低价则提前退出，否则65柱退出。|',
        '|S017-M011|C0050|收盘严格跌破持仓最高完成收盘价减3倍入场信号ATR13则提前退出，否则65柱退出。峰值从信号收盘开始，只升不降；ATR冻结。|', '',
        'ATR13是13根K线真实波幅的简单平均；本轮3倍是事前固定的代表性容忍度，未经参数优化。三组最迟在完成第65柱时触发退出；实际清仓可因执行约束延迟，本轮S017-M009及S017-M010最长实际持有66柱。这不属于主动延长持有窗口，本轮没有检验更长的计划持有期。止损仅在收盘确认、下一段市价成交；触发后锁存至实际清仓，不假设在止损线成交。', '',
        '开发期为2019-01-02至2025-12-31，2018-11至12月预热；首个可交易决策可使用2018年末已完成信号。初始10万美元，只做多、不加杠杆、全可用资金整股；固定1%限价买入溢价、每侧0.1%费用、零滑点，买单只在下一30分钟区间有效，市价卖出，卖出资金即时可用是研究假设。期末不强平。买持基准采用相同合同。详见[事前设计](protocols/design.md)和[授权](protocols/authorization.md)。', '',
        '## 完整账户结果', '',
        '|退出机制|累计净收益|净年化|30分钟最大回撤|日终最大回撤|闭合交易|持仓柱占比|费用USD|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for key, label in LABELS.items():
        v = summaries[key]['candidate']
        lines.append(f"|{label}|{pct(v['total_return'])}|{pct(v['annualized_return'])}|{pct(v['bar_max_drawdown'])}|{pct(v['daily_max_drawdown'])}|{v['closed_cycles']}|{pct(v['holding_bar_fraction'])}|{v['fees']:.2f}|")
    benchmark = summaries['C0048']['benchmark']
    v = benchmark
    lines.append(f"|同合同买入持有|{pct(v['total_return'])}|{pct(v['annualized_return'])}|{pct(v['bar_max_drawdown'])}|{pct(v['daily_max_drawdown'])}|{v['closed_cycles']}|{pct(v['holding_bar_fraction'])}|{v['fees']:.2f}|")
    return_goal = f"净年化至少{pct(1.5*v['annualized_return'])}（正基准的1.5倍）" if v['annualized_return'] > 0 else '策略净年化严格大于0（基准非正）'
    lines += ['', f"确认目标：{return_goal}；30分钟回撤同时不超过基准0.8倍（{pct(.8*v['bar_max_drawdown'])}）和25%；60交易日闭合交易中位数至少6，至少90%窗口不少于3笔。不得以某项改善抵扣另一项未达标。", '',
        '|退出机制|60日闭合中位数|不少于3笔窗口占比|完整窗口数|年化达标|相对回撤达标|绝对回撤达标|频率中位达标|频率覆盖达标|五项达标|',
        '|---|---:|---:|---:|---|---|---|---|---|---|']
    for key, label in LABELS.items():
        item = summaries[key]
        c, g = item['candidate'], item['goals']
        flags = ['是' if g[name] else '否' for name in ('annualized_return', 'relative_drawdown', 'absolute_drawdown', 'frequency_median', 'frequency_coverage')]
        lines.append(f"|{label}|{c['rolling_60_closed_cycle_median']}|{pct(c['frequency_60_sessions']['coverage_at_least_three'])}|{c['frequency_60_sessions']['complete_windows']}|"+'|'.join(flags)+f"|{'是' if item['all_goals_met'] else '否'}|")
    lines += ['', '## 从信号到实际交易', '',
        '|退出机制|原始信号|空仓信号|已持仓时忽略|实际买入|买单未成交|闭合持有柱数中位数|净盈利交易占比|平均单笔净收益|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key, label in LABELS.items():
        c, m = summaries[key]['candidate'], summaries[key]['mechanism']
        n = m['counts']
        lines.append(f"|{label}|{n['entry_signals']}|{n['flat_signals']}|{n['held_signals_ignored']}|{n['actual_buy_fills']}|{n['unfilled_buy_orders']}|{m['closed_holding_bars']['median']}|{pct(c['trade_pnl']['win_rate'])}|{pct(c['trade_pnl']['mean_cycle_net_return'])}|")
    lines += ['', '忽略信号表示当时已有仓位，包含继续持有和发出卖出决策时的新入场信号；它们不是独立可交易机会，也不能直接换算成错失利润。改变退出后，腾出的资金改变后续入场序列，因此全账户差额不是同一组交易的纯止损效果。', '',
        '|退出机制|按固定65柱退出|按结构失效退出|按移动止损退出|期末持股|平均已投资资金占比|', '|---|---:|---:|---:|---:|---:|']
    for key, label in LABELS.items():
        c, exits = summaries[key]['candidate'], summaries[key]['mechanism']['closed_exits_by_trigger']
        lines.append(f"|{label}|{exits.get('S017-M009', 0)}|{exits.get('S017-M010', 0)}|{exits.get('S017-M011', 0)}|{c['ending_quantity']}|{pct(c['mean_invested_equity_fraction'])}|")
    lines += ['', '## 连续账户逐年收益', '', '|年份|S017-M009|S017-M010|S017-M011|买入持有|', '|---|---:|---:|---:|---:|']
    for index, row in enumerate(benchmark['year_returns']):
        values = [summaries[k]['candidate']['year_returns'][index]['net_return'] for k in LABELS]
        lines.append(f"|{row['year']}|"+'|'.join(pct(x) for x in [*values, row['net_return']])+'|')
    lines += ['', '上述为同一账户逐年末净值变化，年初不重置资金，不等于按交易平仓年份汇总的损益。持仓柱占比是完成柱观察中持有股份的比例，不是自然时间占比。', '',
        '## 验证、证据和限制', '',
        '- 入场逐点复现22790个原普查决策点，S017-M005共324次、零差异；三组正式账户的市场信号也与已发布EX024事实全部一致。',
        '- 七组合成机制检查，以及三候选公共SRT/TXE七表串行/多进程一致与未来数据扰动检查通过。此处不声称全仓回归。',
        '- 三项正式账户及各自同合同买持通过公共评价与证据发布；两项公共账户诊断覆盖三账户，来源身份一致且损益对账通过。',
        '- 三组主行情/会话/公司行动/交易约束、费用、执行合同一致，嵌入买持完整经济路径一致；分析和结果验证均绑定真实已发布证据。',
        '- 原分析器把同一UTC时间的两种文本格式直接比较而停止；修订版仅统一时间键格式，原冻结源码和失败事实保留，策略、参数及账户结果未改，也没有重跑账户或追加额度。见[分析器修订](others/analysis_revision.json)。',
        '- 数据仅开发池，已经反复查看且据历史研究选择机制，不能称独立验证或证明未来有效；2026封存样本未使用。已知中断数据不构成全部历史停牌的独立完备证明；RAW及NONE公司行动记录不等于独立认证含分红总回报。', '',
        '本轮不包含参数邻域、费用压力及其他后续稳健性验收；即使五项目标同时达标，也不能直接认定全部阶段通过或授权冻结。', '',
        '证据：[账户清单](others/accounts.json)、[账户分析与公共诊断引用](others/analysis.json)、[结果一致性核验](others/result_validation.json)、[入场逐点复现](others/entry_reproduction.json)、[公共执行预检](others/precheck.json)、[冻结来源](others/pre_run_evidence.json)。', '']
    (WORK/'report.md').write_bytes('\n'.join(lines).encode('utf-8'))
    print('REPORT_RENDERED', flush=True)

if __name__ == '__main__':
    main()
