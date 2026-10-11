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
    lines = ['# EX051 下跌入场两端缩尾收益相关对照', '',
        '总目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '只将下跌入场过滤换为缩尾后的原相关：最近20个原日收益取第二小/第二大值作边界，将唯一外端限制到该边界，保留全部20样本及原时间顺序，再用原mean20/cov19/var20公式。中间收益幅度保留；原买入确认仍用原rawACF，市场状态、持仓期限、退出与全部原列保持。', '',
        '原13数值中心、完整原域及同32坐标保持，但缩尾后的相关与原ACF统计含义不同，同0.1不代表同过滤强度。固定每端1为事前结构；没有删成18、插值分位数、改时间顺序、abs、截断相关输出、单位映射、缩域或降级。原isclose判定下requiredT零方差明确拒绝；父warmup不变。', '',
        '## 中心完整账户', '', '| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |', '|---|---:|---:|---:|---|']
    labels = {'B0-TIME': '原C2132', 'B0-COUPLED': '既有多结构对照C4900', 'N0': '下跌缩尾相关C6980'}
    for key, name in labels.items():
        row = centers['rows'][key]
        lines.append(f"| {name} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {'通过' if row['qualified'] else '未通过'} |")
    gate_names = {'return': '年化收益', 'annual_drawdown': '各自然年回撤',
                  'frequency': '闭合交易频率', 'negative_buyhold_year_profit': '基准亏损年份仍盈利'}
    effect_reference = read(PROTOCOLS / 'effect_reference.json')
    from czsc_trader.research_tools.evidence import EvidenceRef
    from common import ROOT
    effect = read(EvidenceRef.from_dict(effect_reference).resolve(ROOT))['summary']
    contrast = centers['center_expectation']['path_contrast']
    lines += ['', '新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。', '',
        '新中心逐项判断：' + '；'.join(name + ('通过' if centers['rows']['N0']['gates'][key] else '未通过')
            for key, name in gate_names.items()) + '。', '',
        f"与原中心的1636个信号日相比，目标仓位不同{contrast['target_different_days']}天，最终信号原因不同{contrast['reason_different_days']}天；首次仓位分歧为{contrast['first_target_divergence']}。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。", '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13域完整32点', '', '| 指标 | 原C2132 | 既有C4900 | 下跌缩尾相关 |', '|---|---:|---:|---:|']
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
        f"原33完整观察路径核对：中心过滤判断不同{effect['center']['bear_filter_changes']}天，固定原既有状态的目标变化{effect['center']['conditional_target_changes']}天；32点共{effect['point_conditional_target_changes']}个目标作用点。次数不等于利润，只有新完整账户能判断经济效果。", '',
        '最强反证：EX050只看排序，年化10.6801%、2022亏损3.3704%，未过收益和基准亏损年份盈利门；EX027原ACF均值/中位数也损害频率与2023。缩尾保留中间幅度，但仍可能删除有用的孤立跳涨跌，不能先认定是降噪。19相同加1孤立或18零加两极值能缩成零方差；两端有同值时也可能完全不变。原市场状态与H敏感性仍在。', '',
        '策略、独立sorted/list-clamp原相关公式/原路径审计与原13域参数展开的聚焦合成检查通过；纯夹具失败及修正保存。父warmup不变，完整历史先计算后取信号日；无缺失填补。纯计算验证不代替经济目标。', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2；新增参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}；精确复用机制对照2、参数对照{conclusion['parameter_reused_accounts']}。重复评价仅核对串行/spawn一致性。", '',
        '反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。', '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(conclusion, flush=True)


if __name__ == '__main__':
    main()
