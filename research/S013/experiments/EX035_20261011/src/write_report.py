"""Dynamic three-center report; eligibility release only and unchanged gates."""
from common import SRC, RUNS, PROTOCOLS, read, write, file_hash


def main():
    a = read(RUNS / 'analysis.json')
    p = read(RUNS / 'parameter_analysis.json')
    assert a['status'] == 'PASS' and p['status'] in ('PASS', 'NOT_APPLICABLE')
    labels = ('B0-TIME', 'C0-RANGE_REFRESH', 'N0')
    assert set(a['rows']) == set(labels)
    assert a['rows']['B0-TIME']['candidate_id'] == 'C2132'
    assert a['rows']['C0-RANGE_REFRESH']['candidate_id'] == 'C6100'
    assert not a['rows']['C0-RANGE_REFRESH']['qualified']
    assert a['rows']['N0']['candidate_id'] == 'C6000'
    qualified = a['rows']['N0']['qualified']
    text = '''# S013：下跌路线定时退出后的完整入场资格刷新

RSCH阶段三，用户授权自主完成目标无需逐轮评审。本轮COMPLETE只表示证据交付完成，保持原经济要求、S013既有数据及执行合同。

## 证据与最小对照

原C2132中心四门通过，但原完整13维32联合扰动收益Q10仅5.8974%、回撤Q90达30.5044%。删项、平滑、条件退出、状态确认及波动时钟等已有对照未证明保住原经济目标的实质参数改善。EX033状态分歧与重新入场诊断给出退出后状态连锁的线索，属于联合参数及既有完整路径的描述，不能解释成某个H的独立因果作用。

EX034仅等待rawbear/range机会刷新，旧C6100未通过原四门。本轮先精确核验原C2132和旧C6100原生账户，再对固定旧C6100路径做事前声明的pending诊断：18个pending段中10段存在原ACF/动量资格已失效而原range条件仍成立的更早解除机会。相对旧解除日或观察窗末的间隔中位15个信号日，该时点后合计25个旧blocked机会。这些数值不传播新的持仓状态，不预测新交易数、利润或回撤，也不能把旧交易收益加总为机制增益。完整方法和原生账户证据保留。

本轮只有1个新结构BEAR_TIME_ELIGIBILITY_REFRESH。设置pending精确保持EX034：原持仓路线bear、最终原reason=time、当日rawregime=bear且bear range_position<=原bear.entry；设置时不追加ACF、动量或买入确认score条件。空仓每个T先检查解除：沿用rawregime!=bear或bear range_position>entry；仅新增非null原bear.acf_min下acf1<acf_min，或非null原bear.momentum_min下momentum20<momentum_min。ACF/动量等于阈值不解除，score不参与解除；本轮原momentum_min保持null。解除当日按原规则判断入场，bear资格刚失效时不会买入，资格重新满足后无需另等一天。pending拒绝原eligible bear机会，并优先命名entry_refresh_rejected；原confirmation_opportunity与confirmation_pass完整保留。

原H8/H4信号持仓年龄、原ACF20、raw路由/range/确认、loss>trailing>range>time>regime优先级和bull全部保持，无新增阈值、等待天数、保护或时钟。原13数值中心与完整域不变，暖机沿父实现；不足明确失败，不下载、缩短或替换。

最强反证是较及时解除可能只恢复交易次数，同时损害回撤或亏损年收益。更早解除不保证下一次买入有利；所有实际收益必须由新完整现金/持仓路径计算。结构受EX034失败及上述旧路径诊断启发，反复使用已见S013开发池，存在搜索偏差，无独立验证或未来稳定保证。

本轮3个完整中心：B0-TIME原C2132、C0-RANGE_REFRESH旧C6100、N0新C6000。只有1新业务配置、2实际评价（串行/spawn技术重复），2旧中心完整账户精确复用。旧C6100只作失败控制证据，不登记或推广为新达标候选。N0原四门通过才运行32新完整参数账户，并精确复用32原EX015 TIME账户；否则零新参数。旧C6100不追加参数账户。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp，策略与LimitBuyHold统一1%买入溢价。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤、邻点资格与其他诊断不新增经济门。

## 三个完整中心结果

|角色|机制|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---:|---|
'''
    for label in labels:
        row = a['rows'][label]
        failures = '、'.join(key for key, passed in row['gates'].items() if not passed)
        text += (f"|{label}|{row['mechanism']}|{row['candidate_id']}|{row['net_cagr']:.4%}|"
                 f"{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|"
                 f"{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n")
    audit = a['rows']['N0']['refresh_audit']
    text += (f"\n新完整路径设置pending {audit['armed_events']}次、解除{audit['released_events']}次，"
             f"拒绝原eligible bear机会{audit['blocked_bear_opportunities']}日。机会数不等于损失或恢复的实际交易数；"
             "新路径改变后续现金、持仓和机会。\n\n")
    text += ('|自然年|原TIME收益|旧range刷新收益|新资格刷新收益|原TIME回撤|旧range刷新回撤|新资格刷新回撤|基准回撤|\n'
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|\n')
    for year in range(2020, 2027):
        b, c, n = (a['rows'][label]['annual'][str(year)] for label in labels)
        bh = a['rows']['N0']['benchmark_annual'][str(year)]
        text += (f"|{year}|{b['return']:.4%}|{c['return']:.4%}|{n['return']:.4%}|"
                 f"{b['drawdown']:.4%}|{c['drawdown']:.4%}|{n['drawdown']:.4%}|{bh['drawdown']:.4%}|\n")
    text += '\n## 参数结果、验证与目标判断\n\n'
    business = actual = reused = 0
    joint_tail_improvement = False
    if p['status'] == 'PASS':
        assert qualified and set(p['summaries']) == {'B0-TIME', 'N0'}
        manifest = read(PROTOCOLS / 'parameter_plans.json')
        business = manifest['new_parameter_business_accounts']
        actual = p['actual_parameter_evaluations']
        reused = manifest['reused_parameter_accounts']
        assert business == reused == 32 and actual == 33
        text += ('原13坐标完整域、同数值中心同32点配对：5%域宽标准化总L2、seed13/PCG64、整数HALF_EVEN、LINEAR分位数。'
                 '原H仍为信号持仓交易日，物理单位未变。不得缩域、删H、挑点或用较弱中心机械缩小退化宣布成功。\n\n'
                 '|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n')
        for row in p['summaries'].values():
            text += (f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|"
                     f"{row['return_degradation'] * 100:.4f}|{row['drawdown_degradation'] * 100:.4f}|{row['qualified_points']}/32|\n")
        delta = p['differences_from_original']['N0']
        text += (f"\n相对原TIME收益Q10差{delta['q10_cagr_difference'] * 100:+.6f}、"
                 f"回撤Q90差{delta['q90_drawdown_difference'] * 100:+.6f}、"
                 f"收益退化差{delta['return_degradation_difference'] * 100:+.6f}、"
                 f"回撤恶化差{delta['drawdown_degradation_difference'] * 100:+.6f}个百分点。\n")
        pair = read(RUNS / 'parameter_pairs.json')['comparisons']['N0']
        text += (f"同坐标32对：年化更好{pair['cagr_better_points']}、更差{pair['cagr_worse_points']}；"
                 f"回撤更小{pair['drawdown_better_points']}、更大{pair['drawdown_worse_points']}。全部配对保留。\n")
        joint_tail_improvement = (delta['return_degradation_difference'] < 0 and
                                  delta['drawdown_degradation_difference'] < 0 and
                                  delta['q10_cagr_difference'] > 0 and delta['q90_drawdown_difference'] < 0)
        text += ('相对退化与绝对尾部同时改善的方向诊断：' + ('通过' if joint_tail_improvement else '未通过') +
                 '。方向诊断不新增经济门，也不自动等于目标达成；微小变化、配对分布与搜索偏差须一并判断。邻点资格仅诊断，32点不是未来成功概率。\n')
    else:
        assert not qualified
        text += 'N0未通过原四门，未运行新参数账户；事前原域几何保留。不能以交易次数恢复、全窗回撤或局部路径改善替代原经济目标。\n'
        b, c, n = (a['rows'][label] for label in labels)
        text += (f"\n完整账户给出的实际结论：扩大解除后闭合交易从旧range刷新方案的{c['closed_trades']}次变为"
                 f"{n['closed_trades']}次，仍低于原策略的{b['closed_trades']}次。年化从原策略{b['net_cagr']:.4%}"
                 f"降至{n['net_cagr']:.4%}；新2022收益{n['annual']['2022']['return']:.4%}、"
                 f"2023收益{n['annual']['2023']['return']:.4%}。回撤降低没有补回交易频率与亏损年盈利的要求。"
                 'range刷新与完整资格刷新两个重复入场等待方案均未保留原四门，停止沿这一结构继续微调。\n')
    text += (f"\n本轮1新业务中心、2实际评价、2旧中心复用；参数新业务配置{business}、实际评价{actual}、原TIME参数复用{reused}。"
             f"新业务总数{1 + business}、实际评价总数{2 + actual}；旧完整账户复用不计新评价。"
             '纯合成因果前缀/未来修改、未触发新增解除时与EX034全部原列及pending诊断精确等价、原退出优先级、'
             '设置/解除/ACF及动量严格等号、score不参与解除、原13域边界及暖机/非法拒绝检查。'
             '代表串行/spawn信号和策略/基准各5账本精确一致；真实绑定完整HFQ OHLC独立重算ACF20、range、rawregime、'
             '量额归一秩/原确认score及完整pending/age/entry/exit状态。现金、数量、费用、周期、尾仓、年度回报和共同基准核对。'
             '未做仓库全量回归；正式FULL只核验声明证据完整性，不证明收益或稳健性。\n\n')
    text += '本轮最小完整账户对照交付与总研究目标分别判断；尚未证明保留原四门的实质参数敏感性改善，总目标仍未达成。\n\n'
    text += ('下一步转向原买入确认score阈值边界、量额分量与bull路线敏感性的共同变化，先做完整路径统计，'
             '不按已见年份、日期、少一笔交易或单笔利润挑选例外；该诊断方向不等于已声明或启动下一新机制。'
             '保留原目标及负面结果，未推进正式阶段四排名/交接、冻结、PTE或生产。\n')
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    write(RUNS / 'conclusion.json', {'status': 'COMPLETE', 'completion_scope': 'this experimental delivery',
        'objective_achieved': False, 'joint_tail_improvement': bool(joint_tail_improvement),
        'new_qualified': int(qualified), 'new_mechanism_business_accounts': 1, 'mechanism_actual_evaluations': 2,
        'reused_center_accounts': 2, 'new_parameter_business_accounts': business,
        'parameter_actual_evaluations': actual, 'reused_parameter_accounts': reused,
        'report_sha256': file_hash(path), 'original_economic_criteria': 'UNCHANGED'})
    print({'report': 'COMPLETE', 'new_qualified': qualified, 'objective_achieved': False}, flush=True)


if __name__ == '__main__':
    main()
