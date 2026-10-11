"""Original four gates and unchanged absolute plus center-relative tail objective."""
from common import SRC, PROTOCOLS, RUNS, read, write


def main():
    centers, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert centers['status'] == 'PASS'
    tests = {'center_four_gates': centers['rows']['N0']['qualified']}
    if parameter['status'] == 'PASS':
        original, coupled, new = (parameter['summaries'][key] for key in ('B0-TIME', 'B0-COUPLED', 'N0'))
        tests.update(absolute_q10_return_better=new['q10_cagr'] > original['q10_cagr'],
            absolute_q90_drawdown_better=new['q90_drawdown'] < original['q90_drawdown'],
            relative_return_degradation_better=new['return_degradation'] < original['return_degradation'],
            relative_drawdown_degradation_better=new['drawdown_degradation'] < original['drawdown_degradation'])
    achieved = all(tests.values()) and parameter['status'] == 'PASS'
    conclusion = {'status': 'COMPLETE', 'objective_achieved': achieved, 'tests': tests,
        'new_mechanism_business_accounts': 1, 'mechanism_actual_evaluations': 2,
        'mechanism_reused_controls': 4, 'new_parameter_business_accounts': parameter['new_parameter_business_accounts'],
        'parameter_actual_evaluations': parameter['actual_parameter_evaluations'],
        'parameter_reused_accounts': parameter['reused_parameter_accounts'],
        'parameter_technical_duplicate': int(parameter['status'] == 'PASS'),
        'next_action': ('原经济与参数两尾联合目标已满足；下一阶段另行决定。' if achieved else
            '联合机制未满足原目标，依据完整路径反证继续研究，保持原目标与原参数域。'),
        'limits': 'Repeatedly exposed S013 development pool; finite dependent original13/same32 tests, no independent market validation.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX058 上涨切换价格门与下跌局部资格恢复的联合对照', '',
        '原经济与参数改善目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '在原C2132数值中心组合两个已有业务规则：空仓遇到原下跌路线刚切换至上涨路线，原入场资格成立时要求收盘严格高于当天开盘，之后仍须原买入确认；下跌到期退出信号价低于本轮入场信号价后，空仓且当前仍属下跌路线并收阳线时，允许原相关性失格机会恢复资格，仍须原区间、动量及买入确认。没有新增零分确认门。', '',
        '价格门只作用于切换当天，之后稳定上涨日沿用原规则。任意成功入场信号清空旧退出记忆，空仓价格或分数拒绝则保留；持仓日不适用资格例外。到期、区间、路线切换和风险退出及优先级、年龄、信号锚点全部沿用原规则。退出价格分类不是实际成交盈亏。', '',
        '原策略、单独上涨边界BODY门、单独下跌局部BODY恢复、联合规则构成四格。四个实际完整政策分别传播持仓和资金，旧收益、交易数量及利润不能相加预测组合结果。历史均值相关+CLOSE账户额外复用，只作历史反证。', '',
        '选择依据来自已见开发池：原32点2023下跌到期退出来源平均贡献为正，上涨路线切换退出来源为负；单独边界门改善年度收益与回撤，却少1笔闭合交易达标，单独恢复资格增加交易却2023亏损。它们只支持互补机制的可证伪假说，不证明组合一定改善。选择偏差完整披露，没有独立市场验证。', '',
        '## 完整中心账户', '',
        '| 对照 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 原四门 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    titles = {'B0-TIME': '原策略', 'B0-BULL-BOUNDARY': '单独上涨边界BODY门',
        'B0-RAW-RECOVERY': '单独下跌局部BODY恢复', 'N0': '联合机制', 'B0-COUPLED': '历史均值相关+CLOSE门'}
    for key, title in titles.items():
        row = centers['rows'][key]
        lines.append(f"| {title} | {row['candidate_id']} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {row['annual']['2022']['return']*100:+.4f}% | {row['annual']['2023']['return']*100:+.4f}% | {'通过' if row['qualified'] else '未通过'} |")
    names = {'return': '年化收益', 'annual_drawdown': '各自然年回撤', 'frequency': '闭合交易频率', 'negative_buyhold_year_profit': '基准亏损年份仍盈利'}
    lines += ['', '联合中心：' + '；'.join(title + ('通过' if centers['rows']['N0']['gates'][key] else '未通过') for key, title in names.items()) + '。', '',
        '四个旧账户按原身份、请求、载荷、数据、依赖和原生序列化认证复用。C9102与C7980均未达原四门，不升级为参数面板或新否决条件。一个新业务中心串行与spawn技术重复两次，信号及策略、基准双方五账本精确一致；现金、数量、价格、费用、年度、周期与尾仓核验通过，新策略完整逐日独立公式和状态机核验通过。技术PASS不代表经济达标。', '']
    contrast = centers['center_expectation']['path_contrast']
    lines += [f"联合与原中心目标仓位不同{contrast['target_different_days']}天，原因不同{contrast['reason_different_days']}天；首个仓位分歧{contrast['first_target_divergence']}。", '',
        '原确认分数及阈值计算不变。固定相同决策前状态时，稳定上涨日保留原资格，下跌资格包含原机会并可能恢复例外，上涨切换当天新增方向门；这些逻辑关系不代表整个完整政策的交易集合包含关系。局部OR例外会条件性屏蔽下跌相关门，原数值坐标仍在其他路径保持作用；不能把屏蔽本身当作稳健性证明。', '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13完整域与同32坐标', '',
            '| 指标 | 原C2132 | 历史C4900 | 联合C8880 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
                           ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        lines += ['', '原13数值中心、全域、类型和单位保持，同域宽标准化联合L2=5%、32点、seed13、HALF_EVEN整数、LINEAR分位数。旧两组64原生账户认证复用，新32完整执行，不删维、不缩域、不替换坐标。邻居四门通过数量仅诊断，不新增否决条件。', '']
    else:
        lines += ['联合中心未通过原四项经济目标，原32点检验不适用；新增与复用参数账户均为零。', '']
    lines += ['## 最强反证及适用边界', '',
        '单独边界BODY门C9102只有109笔，低于最低110笔；单独恢复C7980虽118笔、年化16.8663%，2023仍亏损0.0252%。历史均值相关叠加边界BODY的EX029仍未过年度回撤门。互补描述不能保证组合保住频率、收益或回撤，更不能代替参数两尾检验。', '',
        'EX057将局部恢复分数限制为中性以上，中心2023反而亏损1.1162%；完整归因显示其保留退出记忆后触发不同的后来入场，原全年净利润约+4088.72元变成−16547.08元，实际价差利润下降16465.00元且费用增加4170.80元。不能删除旧负分交易来推算新收益，也不能把确认分数更高当作盈利保证。', '',
        '原C2132虽然中心达标，原32点年化Q10仅5.8974%、全期回撤Q90为30.5044%；历史C4900中心达标但两项绝对尾部均更差。联合中心达标与少量局部改善不构成目标完成，必须同时改善绝对尾部与相对中心的两项退化。', '',
        'previous raw路线来自完整因果日线动量先shift再重索引。暖启动为max(原父需求,路线窗口+2)，原中心及同32实际父需求已覆盖+2，实际准备区间不变；完整域路线窗口60、其他窗口小且确认40时需求62较原61多一条因果历史，明确披露，不缩域或补缺失值。所有原13数值仍可检验；固定类别、价格方向及两规则的组合不是数值检验已证明的普适规律。', '',
        '仅S013既有数据和原交易合同，已见开发池反复研究，没有独立市场验证。RSCH阶段三，未推进其他阶段、冻结、PTE或生产；FULL只校验关联证据完整性，Git不是完整数据资产备份。', '',
        '目标判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2、旧中心复用4；新参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}、旧参数复用{conclusion['parameter_reused_accounts']}。", '']
    (SRC.parent / 'others').mkdir(exist_ok=True)
    (SRC.parent / 'others/report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved, 'tests': tests}, flush=True)


if __name__ == '__main__':
    main()
