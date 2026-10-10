"""Report two-close bull protection with every original and one-day control."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：只改变上涨持仓的状态强制退出

RSCH阶段三，用户授权自主研究无需逐轮评审。COMPLETE只指本轮完整证据交付。原四经济要求、既有数据和执行合同保持。

## 证据、机制与最强反证

原C2132中心达标：净年化16.1572%、全窗回撤14.1599%、112闭合交易。原13维32个联合扰动账户收益Q10仅5.8974%、回撤Q90达30.5044%，全部邻点未过四门。买入确认未直接拒绝bear机会，不能解释bear阈值和期限脆弱性；删除这些规则也失败。后续均值、价格门与组合未通过全部原四门，阴性结果完整保留。

EX028对原32完整路径的描述核查：首次分歧27持仓退出/5空仓入场，18首次涉及time。联合多维扰动不能证明某参数的单独因果贡献。EX024固定3票多数同时改入场路由和强退出，年化9.6230%、2023亏损，不能隔离退出。EX017 EXIT_CONFIRM已精确测试bull持仓连续2rawbear退出，因此旧2日只复用，不重复冒充新实验。

本轮两个新结构N0/N1只改bull持仓的regime强退出：N0完整daily最近3个raw状态全bear；N1最近3个至少2bear。rawmomentum=Close_t/Close_(t-W)-1，等号>=阈值为bull，3项必须全有限，在会话reindex前计算，包含入场前市场状态。N1可能在当前rawbull但前2日bear时退出，这个代价明确保留。入场当天不强退、不加等待锁，空仓仍当前rawroute、原range/ACF/score入场。bear持仓切rawbull仍立即退出；关闭exit_on_regime_change则两新条件失效。优先级loss>trailing>range>time>regime完全保持，所以原H8/H4封顶，没有无限延期。固定3是结构选择，不增加或删除原13数值坐标。

原TIME、旧2日EXIT_CONFIRM、旧全路由3票多数共3完整中心原样复用；仅2新中心。任一新中心通过四门，两个新中心各32完整新参数账户（其中未达标者仅事前诊断），原TIME32原样复用；旧2日/全路由多数不追加参数。全部同13原域、同数值中心、同32坐标、5%总L2与seed13，不替换点、不缩域、不追加经济硬门。

最强反证：原期限与range优先级可能使确认无效；延迟退出可能放大亏损，多数可在已回升rawbull退出，改变后续入场/费用和2023薄弱盈利。持续性更高、较弱中心的相对退化更小均不能证明经济改善。选择固定3基于已见EX017/24/28/29，是反复研究的开发池，没有独立验证，不修某笔2024交易或使用年份特例。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp、策略及可执行LimitBuyHold均1%买入溢价。只用授权S013已有资产，无新增数据、依赖、平台变更。热身max(parent,W+3)，原中心180、最小60、W60最小63。

原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤和参数尾部是诊断，不新增经济门。

## 五个完整中心账户

|机制/背景|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failures='、'.join(key for key,passed in row['gates'].items() if not passed)
        text+=f"|{cell['mechanism']}/{cell['background']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n## 完整参数诊断\n\n'
    improvement=[]
    business=actual=reused=0
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        reused=manifest['reused_parameter_accounts']
        actual=p['actual_parameter_evaluations']
        text+='事前声明全部13个活跃数值坐标及原完整域，域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数。原C2132 H8/H4的32账户精确复用；新退出中心选择与资格在运行前完整声明，不按结果删点、缩域或替换身份。\n\n'
        for key,row in p['summaries'].items():
            text+=f"{key}：{row.get('role','')}，中心原四门资格{row.get('center_qualified','见中心表')}。\n\n"
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
        text+='两个新中心均未通过原四门，未追加参数账户；事前完整13维几何与不适用原因留存。不能用稳定但不达标的账户宣布目标达成。\n'
    if p['status']=='PASS':
        pairs=read(RUNS/'parameter_pairs.json')
        assert pairs['status'] in ('PASS','NOT_APPLICABLE')
        if pairs['status']=='NOT_APPLICABLE':
            text+='\n本轮未得到完整退出机制参数配对：'+pairs['reason']+'。\n'
        text+='\n原C2132与新两退出机制均保持完全相同数值中心及32点坐标；原策略配对看退出确认整体作用，多数3与连续3配对看多数与连续条件差异。连续3中心若未达标只作诊断。\n'
        for label,row in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{row['complete_pairs']}对：年化更好{row['cagr_better_points']}、更差{row['cagr_worse_points']}；回撤更小{row['drawdown_better_points']}、更大{row['drawdown_worse_points']}。平均年化差{row['mean_cagr_difference']*100:+.6f}、回撤差{row['mean_drawdown_difference']*100:+.6f}个百分点；收益Q10差{row['q10_cagr_difference']*100:+.6f}、回撤Q90差{row['q90_drawdown_difference']*100:+.6f}个百分点。\n"
    substantive=[]
    if improvement:
        substantive=[label for label in improvement if p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0]
    achieved=bool(substantive)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"2个新业务中心、3次实际评价（含一次串行/spawn技术重复）、3个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{2+business}、实际评价{3+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改、完整3票及等号/非法输入/持仓优先级、原raw路由与入场/score保持验证；真实新账户从绑定Close独立重算ACF20、rawregime、range和3票，全入场/持仓/期限/强退出逐日核对；所有完整账户现金、数量、费用、闭合周期、尾仓、自然年收益与共同可执行基准对账。代表串行/spawn信号及双方5账本精确一致，实际候选公开认证与Ruff。若参数执行另核对每点经济与现金账本。未做全仓库回归；FULL仅核验声明证据完整性。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。若本轮未达标，独立退出延迟没有保住经济要求，不继续搜索确认天数；下一步优先验证固定持仓期限能否用市场波动进度替代自然日计数，保留原13坐标及全部经济要求，先固定机制及完整验证再看新账户。此方向尚未执行，不把期限首次分歧描述当成因果证明，不按已见亏损修某笔交易或缩窄参数域。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':achieved,'improvement_labels':substantive,
        'relative_degradation_improvement_labels':improvement,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':2,'mechanism_actual_evaluations':3,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,
        'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
