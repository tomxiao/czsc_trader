"""Report fixed virtual-neighbor voting with every center and parameter counterexample."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：固定邻参数投票与参数敏感性

RSCH阶段三，用户授权自主完成目标，无需逐轮评审。保留S013已有数据、MANDATE/6、原四项经济目标及实际执行合同。本轮COMPLETE仅表示证据留存完整，目标判断另列。

## 问题、机制与最强反证

EX017的上涨入场确认中心达四门，但相对原H4的参数收益Q10降低1.2138个百分点、回撤Q90增加0.1947个百分点；同H3控制的对应差为−0.5588/+2.6740个百分点。相对中心退化缩小伴随中心收益降低，不能宣称实质改善。因此本轮回到原C2132 TIME，检验不依赖单一过滤门槛或期限的固定邻域决策。

VOTE9：下跌ACF中心及±0.033、期限中心及±1的笛卡尔积9个成分，至少5票持仓。VOTE27：上述9成分再与状态门槛中心及±0.012交叉，共27个成分、至少14票持仓。ACF与状态间隔为既定域宽3%，期限为1个交易日；间隔、票数、权重、阈值均事前固定，不搜索。两个完整中心均评价，不按表现改变成分。

每个成分独立维护原TIME信号持仓与买入确认门；初始信号状态空仓，预热只提供已知历史特征。成分不持有真实资金，其目标多数票产生唯一实际目标0/1。实际交易不会重置成分的年龄或入场锚，组合收益不能用成分收益平均代替。每个成分的原确认门保持，但组合实际买入不一定满足单一中心当天的机会与分数门；这是明确改变的组合决策机制。未追加中心门，也未加入EX017两日入场确认。

内部派生期限预定义截断至[1,60]、状态门槛至[-0.2,0.2]，重复成分保留全部票数；ACF内部偏移只满足原源码有限值要求。没有失败成分替换或隐式重试。外层扰动后重新派生成分；内部固定邻域与外层5%总L2扰动是不同概念，不能混为同一检验。

实际路由统一标识ensemble，中心原bull/bear状态另存center_regime。实际退出原因vote只表示多数由持仓转为空仓，不能冒充某个成员的time/regime退出。中心score、ACF与range仅是诊断特征，不作为实际唯一路由归因。

最强反证：多数票可能仅复制中间参数；买入延后、卖出延后、少做交易可能降低年化、扩大回撤或破坏亏损年盈利。原C2132仅112次闭合交易，频率门需至少110，余量很小。9对原规则检验ACF/期限组合，27对9检验加入状态邻域是否有增益；不能把联合效果分别宣称三个轴均有效。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、初始100万元、HFQ研究单位、整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T已知信息决策/T+1实际执行。仅已有S013输入，无新外部数据、依赖或独立验证。原四门仍为净年化≥正收益基准1.5倍、每自然年回撤严格小于基准、每60交易日平均≥4闭合交易、基准亏损年2022/2023实际年度收益为正。全期回撤与参数诊断不新增经济门。

## 全部完整中心账户

|机制|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failures='、'.join(key for key,passed in row['gates'].items() if not passed)
        text+=f"|{cell['mechanism']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n## 完整参数诊断\n\n'
    improvement=[]
    business=actual=reused=0
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        reused=manifest['reused_parameter_accounts']
        actual=p['actual_parameter_evaluations']
        text+='事前声明与EX015一致的全部13个活跃中心数值坐标及完整域；固定投票结构单列。域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数；所有新四门达标中心完整检验。原C2132已有32点经身份、绑定、域、坐标、原生账户核对完整复用，不创建新身份或重放。无按结果删点、替换点或缩窄域。\n\n'
        text+='|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for row in p['summaries'].values():
            text+=f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        for label,delta in p['differences_from_original'].items():
            text+=f"\n{label}相对原策略：收益Q10差{delta['q10_cagr_difference']*100:+.6f}、回撤Q90差{delta['q90_drawdown_difference']*100:+.6f}、收益退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0:
                improvement.append(label)
        text+='\n相对退化与绝对较差参数账户表现一起解释，不能只凭较弱中心机械缩小退化宣布目标完成。32个有限点不是未来成功概率或独立验证；邻点资格数量为诊断，不改变中心四门资格。\n'
    else:
        assert not qualified
        text+='两个中心均未通过原四门，未追加参数账户；事前完整13维几何与不适用原因留存。不能用稳定但不达标的账户宣布目标达成。\n'
    achieved=False
    if improvement:
        achieved=all(p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0 for label in improvement)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"2个新业务中心、3次实际评价（含一次串行/spawn技术重复）、1个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{2+business}、实际评价{3+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准和多数目标逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改因果性、固定成员/票数/边界/非法输入及代表串行/spawn双方5账本精确一致；研究源码Ruff通过，未做仓库全量回归。全部历史证据保持不可变，Git不是数据资产备份。FULL公共交付验证只确认关联证据完整性，不保证交易效果。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据完整反证判断多数票是否只延迟切换，再考虑改变实际决策信息；不继续按已见亏损微调投票间隔、放宽经济目标或新增数据。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':achieved,'improvement_labels':improvement,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':2,'mechanism_actual_evaluations':3,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,
        'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
