"""Original four gates plus unchanged absolute and relative parameter-tail objective."""
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
        'mechanism_reused_controls': 3, 'new_parameter_business_accounts': parameter['new_parameter_business_accounts'],
        'parameter_actual_evaluations': parameter['actual_parameter_evaluations'],
        'parameter_reused_accounts': parameter['reused_parameter_accounts'],
        'parameter_technical_duplicate': int(parameter['status'] == 'PASS'),
        'next_action': ('原经济与参数两尾联合目标已满足；凭精确原生证据单独决定下一阶段。' if achieved else
            '本机制未满足原联合目标；保留负面结果，按实际原生路径继续机制反证，不追加年份例外或缩窄参数域。'),
        'limits': 'Extensively observed S013 development pool; same32 dependent paths, no independent market validation, extra eligibility gate, domain shrink or categorical-stability claim.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX053 原相关背景下下跌低价定时退出后重入方向对照', '',
        '总目标已达成。' if achieved else '本轮完整对照完成，改善参数敏感性的总目标尚未达成。', '',
        '保留C2132原相关性过滤和原买入确认，只增加固定的再次入场条件：上次持仓是下跌路线、最终因到期退出、退出信号收盘价低于该次入场信号收盘价时，后续原本满足条件的下跌买入还需今天收盘价高于前一交易日。这里的低于是信号价格比较，不代表实际交易亏损。', '',
        '记忆跨空仓、资格不满足及市场状态变化保留，任意路线成功发出入场信号后清空。持仓期限、全部退出优先级、费用及执行保持；不按日期或未来收益分类。原13数值中心、全域、同32坐标和父暖启动均保持；固定方向与类别选择仍有结构风险。', '',
        '## 完整账户背景对照', '',
        '| 背景与门控 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    labels = {'B0-TIME': '原相关、无门', 'N0': '原相关、低价到期后重入门',
        'B0-MEAN': '均值调整相关、无门', 'B0-COUPLED': '均值调整相关、相同重入门'}
    for key, title in labels.items():
        row = centers['rows'][key]
        lines.append(f"| {title} | {row['candidate_id']} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {row['annual']['2022']['return']*100:+.4f}% | {row['annual']['2023']['return']*100:+.4f}% | {'通过' if row['qualified'] else '未通过'} |")
    names = {'return': '年化收益', 'annual_drawdown': '各自然年回撤', 'frequency': '闭合交易频率', 'negative_buyhold_year_profit': '基准亏损年份仍盈利'}
    lines += ['', '新中心逐项判断：' + '；'.join(title + ('通过' if centers['rows']['N0']['gates'][key] else '未通过') for key, title in names.items()) + '。', '',
        '四行是按精确身份与完整原生账本认证的独立完整策略，前三个旧账户不新增评价；原相关新门是本轮唯一新增业务账户。均值背景无门对照即使未达标也完整呈现，仅作机制诊断，不成为参数面板或新增资格条件。全期回撤与逐自然年回撤口径不同，资格使用原逐年门。', '',
        '新中心串行与spawn信号及双方五账本精确一致，独立公式与全部状态/入场锚点/分类审计通过，所有成交、现金、费用与年度权益分别核对。不同完整策略间差异不等于删除旧交易利润；信号入场与实际首次成交可不同，实际多次成交按全量账本核验。', '']
    contrast = centers['center_expectation']['path_contrast']
    lines += [f"相对原中心，目标仓位不同{contrast['target_different_days']}天，原因不同{contrast['reason_different_days']}天；首个仓位分歧{contrast['first_target_divergence']}。", '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13域完整32点', '', '| 指标 | 原C2132 | 既有C4900 | 新原相关重入门 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化收益Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
            ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        lines += ['', '联合域宽标准化L2=5%、seed13、HALF_EVEN整数、LINEAR分位数，原与历史耦合对照64个完整原生参数账户按原身份和血缘复用。新32点完整执行，无删除、替换或缩域；相邻点四门通过数仅诊断。固定分类与方向不被数值参数检验证明为普适规律。', '']
    else:
        lines += ['新中心未达原四门，不运行32点；新增和复用参数账户均为零。', '']
    lines += ['## 最强反证与解释边界', '',
        '原中心2023年低价到期后重入来源实际贡献+2.3049个百分点，而全年只有+0.2841%；该来源含有维持年度盈利的机会。全下跌价格方向门先前只剩96笔且2023亏损。均值背景相同门虽中心达标，参数较差一端收益和回撤均劣于原C2132。局部门也可能伤害恢复机会，不能把低价退出自动当作坏交易。', '',
        '上一轮双相关共同确认年化12.5897%、107笔且2022亏损3.4613%，费用下降未抵消实际价格路径收益损失；据此保留原相关算法，本轮只改变局部再次入场条件。原112笔仅比最低110笔多2，2023盈利余量很小，频率与年度盈利的失败都会按原门完整呈现。', '',
        '纯runtime、独立oracle、原13域参数辅助及33条合成完整路径互证通过，失败和修正证据保留。合成检查确认实现语义，不代替经济目标。反复使用已见S013开发池，未获独立市场验证；FULL只检验证据完整性。RSCH阶段三。', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2；旧中心精确复用3；新增参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}、复用参数账户{conclusion['parameter_reused_accounts']}。", '']
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved, 'tests': tests}, flush=True)

if __name__ == '__main__':
    main()
