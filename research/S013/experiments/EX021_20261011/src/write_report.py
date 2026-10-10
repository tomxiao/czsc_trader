"""Report fixed smoothed reference mechanisms with every center and parameter counterexample."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：平滑滞后参考价与参数敏感性

RSCH阶段三；用户授权自主完成目标，无需逐轮评审。S013既有数据、MANDATE/6、原四项经济目标与实际执行合同保持。COMPLETE只指本轮证据交付完成，目标判断另列。

## 假说、完整对照与最强反证

EX017两日状态入场确认中心达标，但同H3的参数收益Q10下降0.5588个百分点、回撤Q90增加2.6740个百分点；EX018多数票机制失去交易频率，EX019所有bull价格门也失去交易频率。EX020仅切换日价格门的H4中心改善收益/回撤，却只有108/109闭合交易，低于110；H3恢复交易频率，却仍不满足2023盈利。因此本轮不按差一笔的结果继续调整过滤阈值，而直接检验状态分类中的滞后参考价。

原状态收益R=Close_t/Close_(t-W)-1。窗口改变时，一个旧单日参考价携带全部分母权重；参考价滚出可能造成状态切换，即使当前价格方向并未改善。这是代数上的可能，尚未证明它造成已有亏损。

LAG3_MEAN把分母改为滞后W-1、W、W+1的Close均值；LAG5_MEAN用W-2至W+2的5日均值。当前Close不平滑，原阈值单位和等号bull语义保持。固定3/5日核分别与原H4/H3组合，ACF0.1，共4新中心、2原控制复用。平均核只是事前固定结构类别，不新增可搜索数值参数；W仍是完整5..60原参数，不假固定。所有13个原活跃数值坐标完整保留。

仅状态参考变化；新的状态同时用于选择bull/bear入场路径和原强制状态退出。原买入确认分、bull/bear入场范围/ACF条件、计时/范围/止损/跟踪止损及退出优先级保持。无额外价格门、等待、多数票或账户分仓。每个滞后参考价均来自当时已知的HFQ信号日线，W>=5保证最近参考至少3个交易日前。完整daily上计算均值后重索引sessions，warmup=max(parent,W+k+1)，缺失不填充。

最强反证：平滑分母的单日权重，不等于平滑二元交易决策；跨阈值仍可能跳变，参考均值也会改变趋势时机与强制退出。可能减少有价值交易、滞后响应，或把原灵敏度转移到阈值与ACF/H参数。3/5日都是新的结构选择，在已反复研究的S013池中比较，非独立证据。中心变好、状态切换变少、相对退化变小，均不能单独宣布目标达成；必须同时解释原四门资格和绝对较差参数账户结果。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、100万元、HFQ研究单位、整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策/T+1执行。仅S013已有数据、无新增依赖、外部数据或独立验证。

原四门：净年化≥正收益基准1.5倍、每自然年回撤严格小于基准、每60交易日平均≥4闭合交易、基准亏损年2022/2023实际年度收益严格为正。参数诊断和全窗回撤不新增经济硬门。

## 全部中心完整账户

|机制/背景|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failures='、'.join(key for key,passed in row['gates'].items() if not passed)
        text+=f"|{cell['mechanism']}/{cell['background']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n参考结构与状态计数分别核对：\n'
    for label,row in a['rows'].items():
        if 'reference_diagnostic' in row:
            b=row['reference_diagnostic']
            text+=f"\n{label}：{b['reference_count']}项参考均值、核半宽{b['kernel_halfwidth']}，bull状态{b['bull_sessions']}日，评价区间内部状态切换{b['regime_switch_sessions']}次。状态计数为描述，不能换算成交易损益贡献。\n"
    text+='\n## 完整参数诊断\n\n'
    improvement=[]
    business=actual=reused=0
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        reused=manifest['reused_parameter_accounts']
        actual=p['actual_parameter_evaluations']
        text+='事前声明与EX015一致的全部13个活跃中心数值坐标及完整域；固定3/5日参考均值结构单列。域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数；所有新四门达标中心完整检验。原C2132 H4及未达标原H3控制各已有32点经身份、绑定、域、坐标、原生账户核对完整复用，不创建新身份或重放。无按结果删点、替换点或缩窄域。\n\n'
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
    substantive=[]
    if improvement:
        substantive=[label for label in improvement if p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0]
    achieved=bool(substantive)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"4个新业务中心、5次实际评价（含一次串行/spawn技术重复）、2个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{4+business}、实际评价{5+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改因果性、3/5项均值代数/窗口与预热边界/阈值等号/原买入确认和退出优先级/非法价格输入及代表串行/spawn双方5账本精确一致；研究源码Ruff通过，未做仓库全量回归。全部历史证据保持不可变，Git不是数据资产备份。FULL公共交付验证只确认关联证据完整性，不保证交易效果。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据全账户与同坐标反证判断参考价平滑是否改善交易规则敏感性；不按已见亏损重选平均核、放宽原目标或擅自新增数据。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':achieved,'improvement_labels':substantive,
        'relative_degradation_improvement_labels':improvement,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':4,'mechanism_actual_evaluations':5,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,
        'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
