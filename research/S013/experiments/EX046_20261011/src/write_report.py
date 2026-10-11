"""Original objective applied to the complete native mechanism comparison."""
from common import SRC, PROTOCOLS, RUNS, read, write


def main():
    centers, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert centers['status'] == 'PASS'
    achieved = False
    tests = {'center_four_gates': centers['rows']['N0']['qualified']}
    if parameter['status'] == 'PASS':
        original, coupled, new = (parameter['summaries'][key] for key in ('B0-TIME', 'B0-COUPLED', 'N0'))
        tests.update(absolute_q10_return_better=new['q10_cagr'] > original['q10_cagr'],
            absolute_q90_drawdown_better=new['q90_drawdown'] < original['q90_drawdown'],
            relative_return_degradation_better=new['return_degradation'] < original['return_degradation'],
            relative_drawdown_degradation_better=new['drawdown_degradation'] < original['drawdown_degradation'])
        achieved = all(tests.values())
    else:
        assert parameter['status'] == 'NOT_APPLICABLE' and not tests['center_four_gates']
    conclusion = {'status': 'COMPLETE', 'objective_achieved': achieved, 'completion_tests': tests,
        'new_qualified': int(tests['center_four_gates']),
        'new_mechanism_business_accounts': 1, 'mechanism_actual_evaluations': 2,
        'new_parameter_business_accounts': parameter['new_parameter_business_accounts'],
        'parameter_actual_evaluations': parameter['actual_parameter_evaluations'],
        'mechanism_reused_accounts': 2, 'parameter_reused_accounts': parameter['reused_parameter_accounts'],
        'technical_duplicate_evaluations': 1 + int(parameter['status'] == 'PASS'),
        'next_action': ('核对全部原目标与原生证据后，单独决定下一阶段。' if achieved else
            '本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、记忆时长网格或缩窄参数域。'),
        'limits': 'Repeated S013 development pool. Same32market paths are dependent, not independent trials. No coordinate removal, point replacement, extra economic veto or structural categorical-stability claim.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX046 退出类别记忆跨市场段的最小机制对照', '',
        '总目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '仅改变退出价格类别记忆的有效期：空仓遇当日上涨状态时，在当日判断之前只清除类别；持仓最终因下跌TIME退出但当日已是上涨状态时，不再保存类别。退出原因、路由与原确认上下文保持；原确认评分、按实际L计算的下跌自相关历史均值、入场价格条件、持仓期限和所有退出优先级均保留。', '',
        '原13项参数、完整域与原数字中心保持。状态段由当日因果市场状态定义，未增加日期例外、等待期、新阈值或额外窗口；本轮不沿用EX045固定120天均值结构。', '',
        '## 中心完整账户', '', '| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |', '|---|---:|---:|---:|---|']
    labels = {'B0-TIME': '原C2132', 'B0-COUPLED': '类别长期保留', 'N0': '类别在市场段内有效'}
    for key, name in labels.items():
        row = centers['rows'][key]
        lines.append(f"| {name} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {'通过' if row['qualified'] else '未通过'} |")
    lines += ['', '新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。', '',
        '中心逐项经济判断：' + str(centers['rows']['N0']['gates']), '',
        '中心原生路径对照：' + str(centers['center_expectation']['path_contrast']), '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13域完整32点', '', '| 指标 | 原C2132 | 类别长期保留 | 类别段内有效 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化收益Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
                           ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        pairs = read(RUNS / 'parameter_pairs.json')
        lines += ['', '域宽标准化联合L2=5%、seed13、HALF_EVEN整数与LINEAR分位数全部保留；原策略和共用窗口64点按原身份、原计划与血缘及完整原账户复用。新32点完整原生执行，零删除、替换或缩域。', '']
        for key, comparison in pairs['comparisons'].items():
            lines.append(f"- {key}：{comparison['complete_pairs']}对；收益改善{comparison['cagr_better_points']}、下降{comparison['cagr_worse_points']}、相同{comparison['cagr_same_points']}；回撤改善{comparison['drawdown_better_points']}、恶化{comparison['drawdown_worse_points']}、相同{comparison['drawdown_same_points']}。")
        lines += ['', '逐点四门仅报告，不将全部32点都达标增设为新经济否决条件。', '']
    else:
        lines += ['新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。', '']
    lines += ['## 最强反证与证据边界', '',
        '事前只读诊断覆盖66条原生路径、107976个信号日；旧共用窗口与固定窗口组各26/33条路径存在跨上涨状态遗留类别的增量拒绝，累计135/137次，两个中心各3次。计数是原路径上的规则作用，不是盈利被错过的证据，也不是相互独立的样本。完整源、纯检查、覆盖检查的一次字段取值失败与显式修正均正式留存。', '',
        '最强竞争解释：遗留记忆可能是有效保护；清除记忆也会增加市场状态阈值跨线的影响。原C2132没有这类新增类别记忆仍敏感，因此这不是已证明的主要病因。中心旧路径直接影响仅2020两次与2026一次，2023/2024直接拒绝为零；后续资金和持仓传播必须以本轮完整原生账户判断，不能删除旧交易后累加收益。', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2；新增参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}；精确复用机制对照2、参数对照{conclusion['parameter_reused_accounts']}。重复评价仅核对串行/spawn一致性。", '',
        '反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。', '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(conclusion, flush=True)


if __name__ == '__main__':
    main()
