"""Report bounded early exit mechanisms with every center and parameter counterexample."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：上涨持仓减半与边界价格过滤的完整对照

RSCH阶段三；用户授权自主完成目标，无需逐轮评审。S013既有数据、MANDATE/6、四项经济目标和执行合同保持。COMPLETE仅指本轮证据交付，目标判断另列。

## 机制与最强反证

原C2132参数变化后收益和回撤大幅变动。EX012直接机会审计表明原买入确认在三个背景未直接拒绝bear机会；即使取消确认，bear ACF和H脆弱性仍存在。EX013删除过滤或定时退出均未达标，EX014..022方向、分数、价格条件、集合表决和平滑等实验也未证明实质改善。EX017唯一新达标中心的参数绝对尾部反而更差，不能因相对退化缩小就宣称成功。

本轮固定将上涨路线bull最长持有期由8天减半为4天，原下跌bear ACF0.1/H4及其他规则全部保持。两个新中心分别使用原TIME和EX020 NEW_BULL_BODY_UP。后者仅在空仓、原入场机会成立且raw bear转bull当日要求Close>Open AND原确认分；稳定bull和bear不加门，拒绝后不等待涨价再进入。原H8 TIME和BODY两个完整账户精确复用，形成期限×价格过滤的四格对照。原源码与EX020源码不变，只有bull参数H8→4。

选择历史完整披露：BODY H8年化16.6697%、回撤13.3493%、2023盈利，但109笔闭合交易未达到110笔门槛。EX022提前bear退出将频次恢复111–117笔却使2023亏损。本轮检验缩短已进入的bull持仓，是否减少弱上涨阶段的损失并保留bear反弹期限。4天是事前固定的减半幅度，不能事后为补一笔交易挑选期限。

最强反证是改善完全来自缩短持仓、释放资金或增加交易，而非价格门信息；同H4原TIME账户隔离这项解释。短持仓也可能截断收益、增加费用，仍受bear ACF、H、regime窗口和阈值影响。中心达标、更多交易或相对退化下降都不能单独宣布改善。

若有新中心达标，全部达标中心完整检验；若仅BODY4达标，TIME4也完整检验32点，作为未达标诊断控制，不登记或推广。新TIME4/BODY4数值中心与全部32点完全相同，原H8点采用相同域和方法但坐标不同，不能伪称同点配对。所有13个数值坐标保留原完整范围，bull H仍是活跃1..60参数。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、100万元、HFQ信号、整手100、每侧10bp、策略与LimitBuyHold均1%买入溢价、T决策/T+1执行、二元仓位。只用反复研究的S013已有开发池，无新增数据、依赖或独立验证。

原四门：净年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易；基准亏损年2022/2023实际年度收益严格为正。全窗回撤和参数诊断不新增经济硬门。

## 四格完整账户

|机制/背景|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
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
        text+='事前声明全部13个活跃数值坐标及原完整域，域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数。原C2132 H8的32账户精确复用；新TIME4/BODY4选择与资格在运行前完整声明，不按结果删点、缩域或替换身份。\n\n'
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
            text+='\n本轮未得到完整TIME4/BODY4参数配对：'+pairs['reason']+'。\n'
        text+='\n原H8与新H4是同域整体政策比较，不是同数值点配对；只有新TIME4/BODY4之间可作严格同点机制比较。未达标TIME4若追加，仅作为诊断，不登记或推广。\n'
        for label,row in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{row['complete_pairs']}对：年化更好{row['cagr_better_points']}、更差{row['cagr_worse_points']}；回撤更小{row['drawdown_better_points']}、更大{row['drawdown_worse_points']}。平均年化差{row['mean_cagr_difference']*100:+.6f}、回撤差{row['mean_drawdown_difference']*100:+.6f}个百分点；收益Q10差{row['q10_cagr_difference']*100:+.6f}、回撤Q90差{row['q90_drawdown_difference']*100:+.6f}个百分点。\n"
    substantive=[]
    if improvement:
        substantive=[label for label in improvement if p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0]
    achieved=bool(substantive)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"2个新业务中心、3次实际评价（含一次串行/spawn技术重复）、2个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{2+business}、实际评价{3+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成四格因果性/未来修改、bull H1/4/8/60期限边界、bear H4保持、稳定bull同期限TIME/BODY原列精确一致；代表账户串行/spawn双方5账本精确一致。全部账户完整现金/费用/数量/周期/尾仓/年度收益与基准核对，原买入确认独立核对；源码Ruff通过，未做仓库全量回归。正式FULL验证只确认关联证据完整性。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据同期限参数对照，区分持有期限改变与边界价格信息；保持原经济目标，不按已见亏损重选条件或缩窄参数域。\n'
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
