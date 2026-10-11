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
            '本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。'),
        'limits': 'Repeated S013 development pool. Same32market paths are dependent, not independent trials. No coordinate removal, point replacement, extra economic veto or structural categorical-stability claim.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX048 仅确认下跌持仓转上涨的状态退出', '',
        '总目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '只对下跌路线的已有持仓，要求当前及前一完整交易日原市场状态都是上涨才按状态退出；上涨持仓遇下跌仍立即退出。区间、持仓天数、止损与追踪退出优先，入场当天不强退。空仓路线、区间、rawACF20过滤与原买入确认分完全保持。', '',
        '原13数值中心、完整原域及同32共同坐标保持，原H仍以实际信号交易日计数。两日是事前固定结构，没有搜索确认天数、增加数值门槛或年份例外。原C2132隔离退出改变；旧C4900只作多结构历史反证，不冒称单机制对照。', '',
        '## 中心完整账户', '', '| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |', '|---|---:|---:|---:|---|']
    labels = {'B0-TIME': '原C2132', 'B0-COUPLED': '既有多结构对照C4900', 'N0': '下跌持仓转上涨两日确认C5980'}
    for key, name in labels.items():
        row = centers['rows'][key]
        lines.append(f"| {name} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {'通过' if row['qualified'] else '未通过'} |")
    gate_names = {'return': '年化收益', 'annual_drawdown': '各自然年回撤',
                  'frequency': '闭合交易频率', 'negative_buyhold_year_profit': '基准亏损年份仍盈利'}
    contrast = centers['center_expectation']['path_contrast']
    lines += ['', '新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。', '',
        '新中心逐项判断：' + '；'.join(name + ('通过' if centers['rows']['N0']['gates'][key] else '未通过')
            for key, name in gate_names.items()) + '。', '',
        f"与原中心的1636个信号日相比，目标仓位不同{contrast['target_different_days']}天，最终信号原因不同{contrast['reason_different_days']}天；首次仓位分歧为{contrast['first_target_divergence']}。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。", '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13域完整32点', '', '| 指标 | 原C2132 | 既有C4900 | 下跌退出两日确认 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化收益Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
                           ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        pairs = read(RUNS / 'parameter_pairs.json')
        lines += ['', '域宽标准化联合L2=5%、seed13、HALF_EVEN整数与LINEAR分位数全部保留；原策略和历史C4900共64点按原身份、原计划与血缘及完整原账户复用。新32点完整原生执行，零删除、替换或缩域。', '']
        for key, comparison in pairs['comparisons'].items():
            lines.append(f"- {key}：{comparison['complete_pairs']}对；收益改善{comparison['cagr_better_points']}、下降{comparison['cagr_worse_points']}、相同{comparison['cagr_same_points']}；回撤改善{comparison['drawdown_better_points']}、恶化{comparison['drawdown_worse_points']}、相同{comparison['drawdown_same_points']}。")
        lines += ['', '逐点四门仅报告，不将全部32点都达标增设为新经济否决条件。', '']
    else:
        lines += ['新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。', '']
    lines += ['## 最强反证与证据边界', '',
        '事前完整33原生路径、全部13坐标的正反单步诊断显示市场窗口/阈值与持仓期限直接触发较多，确认窗口不是独立主要触发。计数不可相加为利润损失，历史持仓也是内生路径。旧三日动量中位数与EX024多数票数学等价，未重复运行。', '',
        '原路径作用点核对：中心17次最终下跌状态退出均会被两日条件推迟；32点共570个观察作用点。原规则本来不允许下跌持仓经历一天上涨后继续存活，因此这个计数首先反映原政策自身，而不是盈利优势、修订后的交易数量或独立样本。所有日期和年度分组正式留存。', '',
        '最强反证：原中心仅112笔、门槛至少110笔，延迟可能使频率不达标；可能延长亏损，也没有直接消除H或ACF门槛敏感。EX017/30旧上涨延迟和整体多数票未保住经济要求。新中心和原32点须由完整账户判断，不能从触发次数或删除旧交易预测收益。80项独立策略纯检查、54条合成oracle路径、16拒绝和52条oracle检查通过，仅证明计算机制与因果可得，不替代经济门。', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2；新增参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}；精确复用机制对照2、参数对照{conclusion['parameter_reused_accounts']}。重复评价仅核对串行/spawn一致性。", '',
        '反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。', '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(conclusion, flush=True)


if __name__ == '__main__':
    main()
