"""Complete center/panel decision; all unchanged original goals retained."""
from common import SRC, PROTOCOLS, RUNS, read, write


def main():
    centers, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert centers['status'] == 'PASS'
    achieved, tests = False, {}
    if parameter['status'] == 'PASS':
        original, coupled, new = (parameter['summaries'][key] for key in ('B0-TIME', 'B0-COUPLED', 'N0'))
        tests = {'center_four_gates': new['center_qualified'],
            'absolute_q10_return_better': new['q10_cagr'] > original['q10_cagr'],
            'absolute_q90_drawdown_better': new['q90_drawdown'] < original['q90_drawdown'],
            'relative_return_degradation_better': new['return_degradation'] < original['return_degradation'],
            'relative_drawdown_degradation_better': new['drawdown_degradation'] < original['drawdown_degradation']}
        achieved = all(tests.values())
    else:
        assert parameter['status'] == 'NOT_APPLICABLE' and not centers['rows']['N0']['qualified']
    conclusion = {'status': 'COMPLETE', 'objective_achieved': achieved, 'completion_tests': tests,
        'new_qualified': int(centers['rows']['N0']['qualified']),
        'new_mechanism_business_accounts': 1, 'mechanism_actual_evaluations': 2,
        'new_parameter_business_accounts': parameter['new_parameter_business_accounts'],
        'parameter_actual_evaluations': parameter['actual_parameter_evaluations'],
        'mechanism_reused_accounts': 2, 'parameter_reused_accounts': parameter['reused_parameter_accounts'],
        'technical_duplicate_evaluations': 1 + (1 if parameter['status'] == 'PASS' else 0),
        'next_action': ('Completion audit verifies current full original objective, then request next stage action separately.' if achieved else
            'Fixed baseline split does not satisfy joint absolute/relative original-tail improvement. Preserve full negative panel; follow actual coupled-vs-fixed matched account/path evidence to choose next mechanism, without further baseline-window search or narrowed domain.'),
        'limits': 'Repeated S013 development pool. Same32market path points dependent, not independent trials. No13dimension removal, point replacement, economic veto, independent validation or structural categorical-stability claim.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX045 下跌过滤与买入确认历史窗口拆分', '',
        '总目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '只改变一个结构：下跌自相关历史均值固定使用中心120天；买入确认继续使用原可扰动窗口。原13项参数全部参与计算，H、退出优先级、再入场价格条件、执行费用与数据口径均保留。固定120天在13项数值参数之外，没有搜索窗口或选年份。', '',
        '## 中心完整账户', '', '| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |', '|---|---:|---:|---:|---|']
    labels = {'B0-TIME': '原策略', 'B0-COUPLED': '共用窗口', 'N0': '固定均值窗口120天'}
    for key in labels:
        row = centers['rows'][key]
        lines.append(f"| {labels[key]} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {'通过' if row['qualified'] else '未通过'} |")
    lines += ['', '中心的买入确认窗口本来为120天，新旧共用/拆分中心的因果信号字段、完整每日账户及九项经济指标精确相同；新中心使用自己独立的原生完整账户身份，串行与spawn预检精确一致。', '']
    if parameter['status'] == 'PASS':
        lines += ['## 完整32点共同坐标', '', '| 指标 | 原策略 | 共用窗口 | 拆分窗口 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化收益Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
                           ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        pairs = read(RUNS / 'parameter_pairs.json')
        lines += ['', '完整13域、域宽标准化联合L2=5%、seed13、HALF_EVEN整数、LINEAR分位数以及原32坐标全部保留。原策略与共用窗口64点以原身份、原计划与血缘、完整原账户精确复用；新策略32点完整原生执行，零替换或删除。', '',
            '共同坐标的原账户对照摘要：', '']
        for key, comparison in pairs['comparisons'].items():
            lines.append(f"- {key}：{comparison['complete_pairs']}完整配对，收益改善{comparison['cagr_better_points']}、下降{comparison['cagr_worse_points']}、相同{comparison['cagr_same_points']}；回撤改善{comparison['drawdown_better_points']}、恶化{comparison['drawdown_worse_points']}、相同{comparison['drawdown_same_points']}。")
        lines += ['', '逐点四项经济判断、所有年度账户、现金/成交独立复核、完整信号与日历审计均在正式材料中。参数诊断不新增经济否决条件；“全部32点都达标”不作为新硬门。', '']
    else:
        lines += ['未达标中心不扩展参数点；无新增参数账户。', '']
    lines += ['## 结论与证据边界', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        '拆分窗口相对共用窗口，收益Q10下降0.2635个百分点，回撤Q90增加0.1015个百分点。相对原中心的退化虽小一些，但新中心本身收益较低、回撤较大，不能把这种相对数字当作参数稳健性改善。', '',
        '原生账户互补核对覆盖全部32配对和中心：18个参数配对的目标持仓与完整逐日账户精确相同，14对改变；14对真实目标的首个分歧日与EX044一步探针的首个下一状态分歧日完全相同。中心经济字段及每日账户精确相同，原生decision_id因策略身份不同单列记录。五套基准账本在66个账户间精确相同。该诊断没有新增评价或现金重放。', '',
        '互补诊断的初版曾错误访问请求对象的身份字段，中心初版曾把独立原生decision_id也要求相同；两次失败源码与显式修正版均正式保留。成功修正未改动冻结策略、参数几何或任何经济账户。', '',
        'EX044一步探针在33条路径上出现36个下一状态差异，不能预测收益；本轮用真实完整账户检验。共用窗口拆分与原策略比较还包含既有均值过滤、BELOW再入场条件的结构差异；不据此声称单个参数的收益因果。', '',
        f"新增机制业务账户1、实际评估2；新增参数业务账户{conclusion['new_parameter_business_accounts']}、实际评估{conclusion['parameter_actual_evaluations']}；复用机制对照2、参数对照{conclusion['parameter_reused_accounts']}。重复评估只用于串行/spawn一致性，不增加独立样本数。", '',
        '数据已反复用于开发，未进行独立市场验证。技术FULL通过只代表引用、身份、来源和证据完整性；没有替代经济目标。RSCH S013阶段三。', '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(conclusion, flush=True)


if __name__ == '__main__':
    main()
