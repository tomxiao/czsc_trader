"""Report the single entry-memory intervention and original-domain tail evidence."""
from common import SRC, RUNS, PROTOCOLS, read, write, file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=a['rows']['N0']['qualified']
    text='''# S013：下跌路线定时退出后的入场机会刷新

RSCH阶段三，用户授权自主完成目标无需逐轮评审。本轮COMPLETE仅指证据交付完成；保持原经济要求、S013既有数据及执行合同。

## 已有证据与最小对照

原C2132中心年化16.1572%、全窗回撤14.1599%、112闭合交易，四门通过；原完整13维32联合扰动收益Q10仅5.8974%、回撤Q90达30.5044%。买入确认未直接拒绝导致bear敏感性的机会；删项、平滑、条件期限/退出及波动时钟等EX012..32未证明保住经济要求的实质参数改进。

EX033精确复用33原生账户，1793状态分歧段中451段起于TIME；全部目标不同日6100，其中2778日只在单步固定规则/特征下呈现继承状态差异，2291日只呈现当日规则/特征差异，1031日混合。原中心38次bear TIME退出有27次在rawbear与原range入场机会未刷新前再次入场，22次在下一信号日。此为联合参数和既有路径描述，不是单个H的因果贡献，也不能把旧交易收益相加当作阻断后的策略收益。

本轮仅新增入场记忆：最终原reason=time、原持仓路线bear、当日rawregime=bear且bear range_position<=原entry时设置pending。空仓每个T先检查；rawregime!=bear或bear range_position>entry即解除，解除当日可按原规则买入。否则pending拒绝bear原eligible机会；等于entry仍不解除。原confirmation机会/scorepass诊断保留，pending拒绝在score拒绝之前命名。原H8/H4的信号持仓年龄、原ACF20、rawroute/range/确认、loss>trailing>range>time>regime优先级和bull全部保持。无固定等待天数、新阈值、波动时钟、日期或单笔修补；这是新增入场记忆，不宣称只改退出。

最强反证是被阻断的再次买入本来可能有利，等待会漏反弹并损害频率。原112闭合交易距110门只有两笔余量。反复使用已见S013开发池，结构选择来自EX033，存在搜索偏差；无独立验证或未来稳定保证。

一新业务中心、两次实际评价（代表串行/spawn技术重复）、一旧原中心完整账户精确复用。新中心四门通过才做32新完整参数账户，32原EX015账户精确复用；否则零新参数。全部原13数值域与原数值中心保持，5%域宽标准化总L2、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位数。原H仍为真实信号持仓交易日，未变物理单位。暖机沿父实现；不足明确失败，不下载/缩短/替换。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp，策略与LimitBuyHold统一1%买入溢价。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤与诊断不追加经济门。

## 两个完整账户

|机制|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for label in ('B0-TIME','N0'):
        r=a['rows'][label]
        failures='、'.join(k for k,passed in r['gates'].items() if not passed)
        text+=f"|{r['mechanism']}|{r['candidate_id']}|{r['net_cagr']:.4%}|{r['drawdown']:.4%}|{r['closed_trades']}|{r['annual']['2022']['return']:.4%}|{r['annual']['2023']['return']:.4%}|{'通过' if r['qualified'] else failures}|\n"
    audit=a['rows']['N0']['refresh_audit']
    text+=f"\n真实新路径设置pending {audit['armed_events']}次、解除{audit['released_events']}次，拒绝原eligible bear机会{audit['blocked_bear_opportunities']}日。机会数量不等于损失的实际交易数，完整现金/持仓路径可能改变后续机会。\n\n"
    text+='|自然年|原策略收益|新策略收益|原策略回撤|新策略回撤|基准回撤|\n|---|---:|---:|---:|---:|---:|\n'
    for y in range(2020,2027):
        b=a['rows']['B0-TIME']['annual'][str(y)]
        n=a['rows']['N0']['annual'][str(y)]
        bh=a['rows']['N0']['benchmark_annual'][str(y)]
        text+=f"|{y}|{b['return']:.4%}|{n['return']:.4%}|{b['drawdown']:.4%}|{n['drawdown']:.4%}|{bh['drawdown']:.4%}|\n"
    text+='\n## 参数结果、验证与结论\n\n'
    business=actual=reused=0
    achieved=False
    if p['status']=='PASS':
        assert qualified
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        actual=p['actual_parameter_evaluations']
        reused=manifest['reused_parameter_accounts']
        text+='原13坐标完整域、同中心同32点配对；不得用缩域、删H或较弱中心机械缩小退化宣布成功。\n\n|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for row in p['summaries'].values():
            text+=f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        delta=p['differences_from_original']['N0']
        text+=f"\n相对原策略收益Q10差{delta['q10_cagr_difference']*100:+.6f}、回撤Q90差{delta['q90_drawdown_difference']*100:+.6f}、收益退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
        pair=read(RUNS/'parameter_pairs.json')['comparisons']['N0']
        text+=f"同坐标32对：年化更好{pair['cagr_better_points']}、更差{pair['cagr_worse_points']}；回撤更小{pair['drawdown_better_points']}、更大{pair['drawdown_worse_points']}。所有配对完整保留，不外推未来稳定。\n"
        achieved=(delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0
                  and delta['q10_cagr_difference']>0 and delta['q90_drawdown_difference']<0)
        text+='\n邻点资格仅诊断，不新增经济门；32点不是未来成功概率。相对退化和绝对尾部须同时改善。\n'
    else:
        assert not qualified
        text+='新中心未通过原四门，未运行新参数账户；事前原域几何保留。不能以较少交易或局部路径改善代替原经济目标。\n'
    text+=f"\n本轮1新业务中心、2实际评价、1旧中心复用；参数新业务配置{business}、实际评价{actual}、原参数复用{reused}。纯合成因果前缀/未来修改、无触发原信号等价、原退出优先级、设置/解除/严格等号、确认/ACF门及暖机/非法/原13域边界检查。代表串行/spawn信号和策略/基准各5账本精确一致；真实绑定完整HFQ OHLC独立重算ACF20、range、rawregime、量额归一秩/原确认score及完整pending/age/entry/exit状态。现金、数量、费用、周期、尾仓、年度回报和共同基准核对。未做仓库全量回归；正式FULL仅核验声明证据完整性。\n\n"
    text+=('本轮有限点集内得到保留四门、相对退化与绝对尾部同时改善的方案，仍有搜索偏差。' if achieved else '本轮最小完整账户对照完成，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='本轮完整账户显示，强制等待原range机会刷新会过度阻断：闭合交易112降至86，2022由+12.1687%变为-2.4305%、2023由+0.2841%变为-5.1258%。全窗回撤下降不能替代频率和亏损年盈利，不能认定原重复买回应整体取消。\n\n'
    text+='下一步保留重复入场作为必要对照，检查完整原入场资格（包含ACF）重新激活是否能减少等待，先核对其与本轮范围刷新条件的差异，再选择最小完整账户对照。不按已见单笔利润挑选例外，保留负面结果及原目标。未推进正式阶段四排名/交接、冻结、PTE或生产。\n'
    path=SRC.parent/'others/report.md'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery','objective_achieved':bool(achieved),
        'new_qualified':int(qualified),'new_mechanism_business_accounts':1,'mechanism_actual_evaluations':2,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,'reused_parameter_accounts':reused,
        'report_sha256':file_hash(path),'original_economic_criteria':'UNCHANGED'})
    print({'report':'COMPLETE','new_qualified':qualified,'objective_achieved':bool(achieved)},flush=True)


if __name__=='__main__':
    main()
