"""Report the complete bull-state factorial and same-domain parameter diagnostics."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：上涨状态两日确认与参数敏感性

RSCH、阶段三；用户授权自主研究无需逐轮评审，保持S013已有数据、MANDATE/6、原四经济目标、执行合同、资源和依赖。目标是验证机制能否在保留经济目标的同时减轻参数退化，本交付COMPLETE只指本轮证据留存完整。

## 事前问题、竞争解释与设计

EX016中已有32个原策略扰动账户2023平均年度收益−4.0173%。上涨路线入场且原状态退出的交易平均实际年度贡献−7.6401个百分点，下跌定时退出组+2.8702；这是按实际当年持仓价格损益和费用核对净值的事后分组，不证明更改状态退出即可消除亏损。本轮因此直接区分上涨入场误判与状态过快切换两种竞争机制。

ENTRY_CONFIRM：仅对上涨路线入场，当前和前一实际交易日的原raw状态均为bull才允许买入。EXIT_CONFIRM：原上涨持仓仅在当前和前一实际交易日raw状态均为bear时按状态退出。BOTH_CONFIRM结合两者。前一交易状态由完整已绑定预热日线先算动量、再shift(1)、最后重索引实际评价sessions；首日使用真实预热上一状态，无日历天替代或缺失填充。原状态动量等于门槛仍属于bull。

这是固定两日确认结构，增加决策等待，不搜索确认长度；不是连续平滑。下跌入场和下跌状态退出保持即时原规则；上涨/下跌时间、区间、止损、追踪退出及优先级和原买入确认分保持。即使状态尚未确认，时间或区间条件仍可先触发卖出。bull持仓改变可能间接影响后续bear机会与资金，不能把bull-only说成bear账户结果不变。

三机制×四背景：B0=(ACF0.1,H4)、B1=(0.045,H4)、B2=(0.1,H3)、B3=(0.045,H3)。12个配置在评价前完整发布，4原TIME账户序列化精确核对后复用；Optuna固定队列、8进程、每进程原生线程1、请求workers1、seed13。新增状态拒绝与原分数拒绝分别核验，不改变原score含义。

最强反证：效果可能只来自少做交易、少付费用或避开已见亏损；延迟上涨状态退出也可能失去2022的保护，错过行情或降低频率。全部四背景及2022/2023、净年化、频率一并披露，不能只挑2023或最好配置。

510500.SH、2020-01-02至2026-09-30、1636交易日、初始100万元、HFQ研究单位/整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。仅S013已有授权资产及预热，无新数据、其他批次或独立封存验证。

原四门：净年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60交易日平均≥4闭合交易；基准亏损年2022/2023策略年度收益严格为正。全窗回撤及参数退化为诊断，无新增经济门。

## 全部完整账户

|背景|机制|候选|净年化|全窗回撤|闭合交易|2022收益|2023收益|状态拒绝|原四门|
|---|---|---|---:|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failed='、'.join(name for name,value in row['gates'].items() if not value)
        rejects=row['gate_counts'].get('state_rejected_opportunities',0)
        text+=f"|{cell['background']}|{cell['mechanism']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{rejects}|{'通过' if row['qualified'] else failed}|\n"
    text+='\n入场确认四个背景均通过基准亏损年盈利门，而退出确认与两者结合的全部背景均未通过该门。这支持优先检验入场方向，反对直接把上涨状态退出延迟解释成修复。四个背景共享行情，不能当独立统计样本。\n'
    if 'N2' in qualified:
        old=a['rows']['B2-TIME']
        new=a['rows']['N2']
        text+=f"\n同一H3/ACF0.1背景下，入场确认使年化从{old['net_cagr']:.4%}变为{new['net_cagr']:.4%}，2022从{old['annual']['2022']['return']:.4%}变为{new['annual']['2022']['return']:.4%}，2023从{old['annual']['2023']['return']:.4%}变为{new['annual']['2023']['return']:.4%}，交易{old['closed_trades']}→{new['closed_trades']}。2023修复伴随收益和交易代价，仍按原四门验收，不把旧交易损益相加当新政策贡献。\n"
    text+='\n## 同域完整参数诊断\n\n'
    improvement=[]
    relative_improvement=[]
    if p['status']=='PASS':
        text+='看到本轮账户结果前固定与EX015相同全部13个数值坐标和域：两路线窗口/入场/退出/期限、下跌ACF、状态窗口/门槛、确认窗口/门槛。原源合法域及S013原ACF搜索域[-0.60,0.50]保持；类别、固定两日确认、null、零冷却和固定执行条件单列。域宽标准化5%总L2、32点/中心、seed13、PCG64、INTEGER HALF_EVEN、LINEAR分位数；原中心及全部新四门达标机制均检验，规定点不按收益替换。不能将历史S007-native未保存域字节的扰动作相同量尺基线。\n\n'
        text+='|中心|年化Q10|回撤Q90|年化退化pp|回撤恶化pp|邻点原四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for row in p['summaries'].values():
            role='（H3未达标控制）' if row['candidate_id']=='C7009' else ''
            text+=f"|{row['candidate_id']}{role}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        for label,delta in p['differences_from_original'].items():
            text+=f"\n{label}相对原中心：年化退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if label in qualified and delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0:
                relative_improvement.append(label)
        parameter_total=sum(row['complete_points'] for row in p['summaries'].values())
        plans=read(PROTOCOLS/'parameter_plans_with_control.json')
        parameter_business=plans['new_parameter_business_accounts']
        parameter_reused=plans['reused_parameter_accounts']
        assert parameter_total==parameter_business+parameter_reused
        parameter_actual=p['actual_parameter_evaluations']
        text+=f"\n其中原C2132的{parameter_reused}点按EX015原身份、强类型计划/绑定、协议、相同坐标/域和账户证据完整核对复用，无新身份或重放；本轮新评价{parameter_business}点（C8002的32点与原H3未达标控制32点）。全部96点纳入诊断。H3控制在C8002代表点技术预检之后、任何批量扰动评价和参数指标查看之前补充声明；初始计划和补充计划分别不可变留存。控制不作为达标候选。\n"
        text+='\nSE公共参数比较可比，分位数独立NumPy复算一致。有限32点不是未来成功概率、置信区间或独立验证；邻点原四门通过数仅作诊断，不改变中心资格或加入硬门。\n'
        text+='\n执行说明：初始几何材料沿用“重跑原C2132”的意图文字；核验已有EX015的完整同域身份、计划和账户后，实际执行改为完整复用32点。初始材料保持不可变，以执行矩阵与本说明区分计划文字和实际次数，不把复用计作新评价。\n'
        pairs=read(RUNS/'parameter_pairs.json')
        assert pairs['status']=='PASS' and pairs['complete_same_coordinate_pairs']==32
        text+=f"\n在完全相同H3数值坐标的32对账户中，入场确认年化更好{pairs['cagr_better_points']}点、更差{pairs['cagr_worse_points']}点；回撤更小{pairs['drawdown_better_points']}点、更大{pairs['drawdown_worse_points']}点。平均年化差{pairs['mean_cagr_difference']*100:+.6f}、平均回撤差{pairs['mean_drawdown_difference']*100:+.6f}个百分点。原H3控制四门通过{pairs['original_qualified_points']}/32、新机制{pairs['new_qualified_points']}/32。这是完整政策配对描述，非独立统计检验。\n"
        delta=pairs['differences_from_h3_original']
        text+=f"\n只改变入场确认相对原H3控制：年化Q10差{delta['q10_cagr']*100:+.6f}、回撤Q90差{delta['q90_drawdown']*100:+.6f}、年化退化差{delta['return_degradation']*100:+.6f}、回撤恶化差{delta['drawdown_degradation']*100:+.6f}个百分点。这一对照用来判断主要改善是否来自期限改变；不得仅凭相对原H4的结果把全部改善归于入场确认。\n"
        text+='\n本轮实际反证：C8002的两项相对退化均比原H4小，但中心年化也由16.1572%降为11.4738%、中心全期回撤由14.1599%升为17.7302%。参数收益Q10由5.8974%降为4.6836%、回撤Q90由30.5044%升为30.6991%。因此相对退化数字的改善未转化为更好的较差参数账户表现。同H3控制收益Q10为5.2424%、回撤Q90为28.0251%；新增入场确认的尾部收益更低、尾部回撤更高，独立机制对照削弱改善主张。32对平均年化略高0.1417个百分点、平均回撤低1.6393个百分点仍是有价值的局部线索，不能代替较差一批账户反证。三个中心扰动均0/32通过原四门，此数仍仅为诊断。\n'
        text+='\n研究判断：相对中心的两项退化指标下降属实，但本轮未提供实质降低参数敏感性的充分证据。中心四门资格保持，诊断不新增候选否决条件；本轮目标不因该数字变化自动完成。\n'
    else:
        assert not qualified
        parameter_business=parameter_actual=parameter_reused=0
        text+='12个新配置均未通过原四门，未追加扰动账户；事前域与不适用原因完整保留，未用稳定但不达标的账户宣布改善。\n'
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"12新机制业务配置，13次实际评价（1次串行/spawn技术重复），4控制复用；参数新业务配置{parameter_business}、既有参数账户复用{parameter_reused}、实际评价{parameter_actual}。合计不同新业务配置{12+parameter_business}、实际评价{13+parameter_actual}；重复预检不计新策略发现。\n\n"
    text+='12配置因果前缀/未来修改不变；合成检查确认首日真实预热状态、等号bull、入场与退出方向、下跌即时原规则、非法机制。代表机制及各中心代表参数点（若适用）的串行/spawn信号及双方5类账本精确相同。16中心账户基准账本精确相同，现金/数量/费用/年度/周期/尾仓完整核验通过。研究源码Ruff通过；未做仓库全量回归。分析辅助程序新增状态拒绝单列，仅影响留存分析，不改已发布策略源码或重放账户。\n\n'
    if improvement:
        text+='本轮在事前同域有限点集内发现保留原四门且两项参数退化均减轻的机制。必须结合中心收益与回撤、改善幅度、绝对退化和反复搜索偏差解释，不能据此宣布未来稳定或进入PTE。\n\n'
    else:
        text+='本轮完整对照完成，尚未证明保留原四门的参数敏感性改善，总目标尚未达成。事后上涨/状态损失归因未自动转化为有效交易改进。\n\n'
    text+='全部原生账户、实现、数据与准备绑定、参数强类型父子关系及SE证据通过公开API留存；历史材料保持不可变。未进行正式阶段四五项自检/族排名/交接、冻结、PTE或生产操作。Git不是数据资产备份。\n\n'
    text+='下一步依完整配对路径检验状态等待的收益与频率代价；若简单状态确认不成立，则检验参数决策组合能否减少单一门槛和期限依赖，保留原四门与明确反证。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':bool(improvement),'improvement_labels':improvement,'new_qualified':len(qualified),
        'relative_degradation_improvement_labels':relative_improvement,
        'objective_judgment':'Relative degradation fell with a weaker center, while both absolute parameter tails and the matched H3 mechanism tails worsened; insufficient evidence of substantive sensitivity improvement. Center economic eligibility is unchanged.',
        'new_mechanism_business_accounts':12,'mechanism_actual_evaluations':13,
        'new_parameter_business_accounts':parameter_business,'parameter_actual_evaluations':parameter_actual,
        'reused_parameter_accounts':parameter_reused,
        'original_economic_criteria':'unchanged','report_sha256':file_hash(path)})
    print({'report':'COMPLETE','qualified':qualified,'parameter_improvements':improvement})


if __name__=='__main__':
    main()
