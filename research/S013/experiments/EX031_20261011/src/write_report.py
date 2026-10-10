"""Report two-close bull protection with every original and one-day control."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：用市场波动进度替代持仓自然日计数

RSCH阶段三，用户授权自主完成目标无需逐轮评审。COMPLETE只指本轮证据交付，保持原四经济要求、授权S013数据及执行合同。

## 证据、机制及最强反证

原C2132中心年化16.1572%、全窗回撤14.1599%、112闭合交易，原四门通过；原13维32联合扰动的收益Q10仅5.8974%、回撤Q90达30.5044%，0/32邻点通过四门。买入确认没有直接拒绝导致bear敏感性的机会，删除bear过滤或期限、价格门、平滑、条件保护和状态退出确认等对照未证明实质稳健改进。

EX028原32完整路径诊断：首次分歧27持仓退出/5空仓入场，18首次涉及TIME。此为多维联合扰动描述，不能单独识别H的因果贡献。EX030退出持续性只改bull状态强退出，两版99/107闭合交易且分别在2022/2023亏损，固定状态延迟未保住经济要求。本轮不继续调确认天数，测试自然日计数是否难以适配市场活动速度。

定义相对真实振幅v_t=max(High-Low,abs(High-prevClose),abs(Low-prevClose))/prevClose，HFQ信号且当日T收盘可得。增量v_t/严格过去20个完整v的均值，完整daily先计算再reindex，过去均值必须有限且>0，不填补/截断/裁剪。固定20是新结构职责，采用原信息组件已有20尺度，没有搜索窗口。入场日clock=0；每后续持仓日加增量，退出当天保留最终值、空仓保留最近值、新入场清零；不按实际成交重置。两个持仓路线均记录波动clock作诊断。

N0仅bear持仓以clock>=原整数H退出，bull仍真实age>=H；N1两个路线都采用波动clock。原H8/H4数值、整数类型和1..60域仍在，但被选路线的物理单位从交易日变成标准化振幅进度，不能宣称相同实际期限。被选路线没有原自然日封顶，可能实际持有超过H；未选bull期限不变。所有原rawroute/入场/ACF/确认/range及其他退出保持，loss>trailing>range>time>regime原优先级保持。原bear切bull强退出继续即时生效。warmup=max(parent,22)，最小60、原中心180不变，已有资产不足明确失败不下载。

两个新中心与原TIME一个完整中心对照，原TIME精确复用。任一新中心四门通过，两新中心各32完整新参数账户，原EX01532精确复用，未达标中心仅事前对称诊断不登记；无新达标则不执行参数账户。全部原13数值域、同中心与同32点、域宽标准化5%总L2、seed13/PCG64/整数HALF_EVEN/LINEAR分位数，不删H、不縮域、不按结果换点。参数几何一致不意味着时钟的经济含义相同。

最强反证：剧烈振幅可能提前卖掉有利反弹，安静亏损可能拖久，过去20均值为0明确拒绝；振幅不是预期收益，原ACF与route阈值脆弱仍可能存在。较弱中心导致相对退化变小不能作为成功，必须保持原四门且绝对参数尾部改善。已见EX012..30反复研究同一开发池，选择固定20/两路线结构的偏差披露，无独立验证、年份规则或特定亏损交易修补。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp、策略与可执行LimitBuyHold均1%买入溢价。无新增数据、依赖、平台/PTE/生产变更。

原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤及参数诊断不新增经济门。

## 三个完整中心账户

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
        text+='事前声明全部13个活跃数值坐标及原完整域，域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数。原C2132 H8/H4的32账户精确复用；新时钟中心选择与资格在运行前完整声明，不按结果删点、缩域或替换身份。\n\n'
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
            text+='\n本轮未得到完整波动时钟参数配对：'+pairs['reason']+'。\n'
        text+='\n原C2132与新两时钟机制均保持完全相同数值中心及32点坐标；原策略配对看波动时钟整体作用，两路线时钟与bear单路线时钟配对看bull路线时钟增量。bear单路线中心若未达标只作诊断。\n'
        for label,row in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{row['complete_pairs']}对：年化更好{row['cagr_better_points']}、更差{row['cagr_worse_points']}；回撤更小{row['drawdown_better_points']}、更大{row['drawdown_worse_points']}。平均年化差{row['mean_cagr_difference']*100:+.6f}、回撤差{row['mean_drawdown_difference']*100:+.6f}个百分点；收益Q10差{row['q10_cagr_difference']*100:+.6f}、回撤Q90差{row['q90_drawdown_difference']*100:+.6f}个百分点。\n"
    substantive=[]
    if improvement:
        substantive=[label for label in improvement if p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0]
    achieved=bool(substantive)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"2个新业务中心、3次实际评价（含一次串行/spawn技术重复）、1个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{2+business}、实际评价{3+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改、独立完整TR与严格过去均值、单位增量与原native信号等价、零/慢/尖峰进度及阈值低等高、原route/entry/score与同时退出优先级、暖机/非法拒绝及13坐标边界验证；真实新账户从绑定OHLC独立重算波动进度和全route/age/clock/入场/退出状态。完整账户现金、数量、费用、周期、尾仓、年度收益与共同基准逐项对账，代表串行/spawn信号及双方5账本精确一致，公开实际候选认证与Ruff。若参数执行另核对每点经济与现金。未做仓库全量回归，正式FULL仅核验声明证据完整性。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四排名/交接、冻结、PTE或生产。下一步依据完整账户及同坐标参数检验判断波动进度是否改善原期限敏感性，保留原经济目标与全部负面结果，不按单笔已见亏损重选比例或窗口。\n'
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
