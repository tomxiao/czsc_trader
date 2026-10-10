"""Report fixed virtual-neighbor voting with every center and parameter counterexample."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：仅新上涨状态入场价格方向与参数敏感性

RSCH阶段三；用户授权自主完成目标，无需逐轮评审。S013既有数据、MANDATE/6、原四项经济目标和实际执行合同保持。本轮COMPLETE只指完整证据留存，研究目标判断另列。

## 假说、完整对照与最强反证

EX017两日状态入场确认中心达标，但同H3的参数收益Q10下降0.5588个百分点、回撤Q90增加2.6740个百分点。EX018固定9/27成分多数票闭合交易95/90，均未过110次频率门且2023亏损。因此不能继续把等待或减少交易当作已经有效的保护。

EX019对所有bull入场追加价格门，H4虽然回撤约12.4%/12.6%且2023盈利，但只有97/99闭合交易，均不达标。本轮因此聚焦另一个可证伪的边界信息问题：滚动收益从C_t/C_(t-W)-1变到下一参照时，旧高价参照滚出、换为较低参照，即使当前Close持平或下跌，也可能bear转bull。这是代数上可能发生的机制，不证明它造成了已有亏损。

NEW_BULL_CLOSE_UP仅在当前raw bull、前一实际交易日raw bear，且空仓原入场机会成立时，追加当前信号Close严格大于前收，AND原买入确认分。NEW_BULL_BODY_UP用当前Close严格大于当天Open。CLOSE直接排除切换而收盘不涨，BODY只检验日内上涨，跳空低开收阳仍可能由参照滚动导致切换；两者是竞争解释。两个类别×H4/H3，共4新完整中心，ACF0.1；原H4/H3事前声明复用。

条件门只在切换日适用；切换日拒绝后，次日若仍bull，即使价格继续下跌也恢复原入场。它不是等待到价格上涨才买入。原bear持仓在切换日先按原规则退出，当天不会再同分支入场，次日稳定bull可能不受门影响。报告分别计算所有raw切换日、空仓eligible切换机会、原score通过机会和实际价格拒绝，不把所有切换当作过滤交易。

所有bear与稳定bull入场、hold与全部退出及优先级保持原TIME。价格拒绝先于原score拒绝单列，价格pass不能绕过score。真实单路由bull/bear保持。已绑定HFQ日线先计算完整动量，再shift(1)，最后重索引sessions；warmup=max(parent,W+2)，首日用真实前raw状态和前收。阈值等号归bull、价格等号拒绝，无缺失填充、执行单位混用或T+1信息。

最强反证：EX019保护可能来自稳定bull过滤，缩窄范围后消失；前后raw状态仍依赖W和threshold，可能增加不连续性。价格与raw切换可能机械相关，门可能只少做几笔交易或推迟买入。下跌日也可能是均值回归机会；年度修复、少拒绝或多交易都不能单独证明参数敏感性改善。原H4仅112闭合交易，H3为121，均需原110次门。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、100万元、HFQ研究单位、整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策/T+1执行。仅S013已有数据、无新增依赖、外部数据或独立验证。

原四门：净年化≥正收益基准1.5倍、每自然年回撤严格小于基准、每60交易日平均≥4闭合交易、基准亏损年2022/2023实际年度收益严格为正。参数诊断与全窗回撤不新增经济硬门。

## 全部中心完整账户

|机制/背景|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failures='、'.join(key for key,passed in row['gates'].items() if not passed)
        text+=f"|{cell['mechanism']}/{cell['background']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n切换机会与实际拒绝分别核对：\n'
    for label,row in a['rows'].items():
        if 'boundary_diagnostic' in row:
            b=row['boundary_diagnostic']
            text+=f"\n{label}：raw切换{b['raw_bear_to_bull_sessions']}日、空仓eligible切换机会{b['flat_eligible_boundary_opportunities']}、其中原score通过{b['original_score_passing_boundary_opportunities']}、实际价格拒绝{b['boundary_price_rejections']}；切换而Close不涨{b['boundary_nonrising_close_sessions']}日。非独立事件与机会，不是交易损益因果相加。\n"
    text+='\n## 完整参数诊断\n\n'
    improvement=[]
    business=actual=reused=0
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        reused=manifest['reused_parameter_accounts']
        actual=p['actual_parameter_evaluations']
        text+='事前声明与EX015一致的全部13个活跃中心数值坐标及完整域；固定边界过滤结构单列。域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数；所有新四门达标中心完整检验。原C2132 H4及未达标原H3控制各已有32点经身份、绑定、域、坐标、原生账户核对完整复用，不创建新身份或重放。无按结果删点、替换点或缩窄域。\n\n'
        text+='|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for row in p['summaries'].values():
            text+=f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        for label,delta in p['differences_from_original'].items():
            text+=f"\n{label}相对原策略：收益Q10差{delta['q10_cagr_difference']*100:+.6f}、回撤Q90差{delta['q90_drawdown_difference']*100:+.6f}、收益退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if label in qualified and delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0:
                improvement.append(label)
        text+='\n相对退化与绝对较差参数账户表现一起解释，不能只凭较弱中心机械缩小退化宣布目标完成。32个有限点不是未来成功概率或独立验证；邻点资格数量为诊断，不改变中心四门资格。\n'
    else:
        assert not qualified
        text+='四个中心均未通过原四门，未追加参数账户；事前完整13维几何与不适用原因留存。不能用稳定但不达标的账户宣布目标达成。\n'
    if p['status']=='PASS':
        pairs=read(RUNS/'parameter_pairs.json')
        assert pairs['status']=='PASS'
        text+='\n原H3控制C7009未通过原亏损年盈利门，只作诊断，不登记或纳入新达标候选。各新中心与其原H4/H3控制采用完全相同32组数值坐标；四门资格保持，以下配对为机制诊断。\n'
        for label,row in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{row['complete_pairs']}对：年化更好{row['cagr_better_points']}、更差{row['cagr_worse_points']}；回撤更小{row['drawdown_better_points']}、更大{row['drawdown_worse_points']}。平均年化差{row['mean_cagr_difference']*100:+.6f}、回撤差{row['mean_drawdown_difference']*100:+.6f}个百分点；收益Q10差{row['q10_cagr_difference']*100:+.6f}、回撤Q90差{row['q90_drawdown_difference']*100:+.6f}个百分点。\n"
    achieved=False
    if improvement:
        achieved=any(p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0 for label in improvement)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"4个新业务中心、5次实际评价（含一次串行/spawn技术重复）、2个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{4+business}、实际评价{5+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准和价格方向拒绝逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改因果性、前收预热/两价格方向/等号/原bear和退出规则/非法价格输入及代表串行/spawn双方5账本精确一致；研究源码Ruff通过，未做仓库全量回归。全部历史证据保持不可变，Git不是数据资产备份。FULL公共交付验证只确认关联证据完整性，不保证交易效果。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据全账户与同坐标反证判断价格方向是否提供可迁移信息；不按已见亏损修改方向门、放宽原目标或擅自新增数据。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':achieved,'improvement_labels':improvement,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':4,'mechanism_actual_evaluations':5,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,
        'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
