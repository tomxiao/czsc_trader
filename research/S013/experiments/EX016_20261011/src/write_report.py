"""Report every prospective entry-relative exit and any complete parameter diagnostic."""
from common import SRC, RUNS, read, write, file_hash


def main():
    analysis=read(RUNS/'analysis.json')
    parameters=read(RUNS/'parameter_analysis.json')
    assert analysis['status']=='PASS'
    assert parameters['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in analysis['rows'].items() if not row['reused'] and row['qualified']]
    report='''# S013：持仓相对入场价格与参数敏感性

RSCH、阶段三；直接用户自主研究授权，保持原S013数据、MANDATE/6四项目标、执行规则与成本。已有C2132参数扰动的主要失败是净年化和基准亏损年仍盈利要求，年度回撤门不是主要失败项。此前单日价格方向、原确认分方向与平滑过滤均不足；本轮检验不同的信息：持仓价格是否仍高于入场信号日价格。

## 事前机制与完整对照

EXIT_NONPOSITIVE：下跌路线年龄达到原期限后，当前Close不高于入场信号日Close才定时退出；仍高于该价时继续持有。EXIT_NONNEGATIVE为相反方向。等号满足两边。anchor来自入场信号日、因果可得，不是成交价格或账户净盈利。费用、实际买价和订单未成交仍按完整账户计算；不把这种相对价格叫作实际盈亏。上涨期限、区间/状态退出及优先级、原买入确认全部保持。

两机制×四背景：B0=(ACF0.1,H4)、B1=(0.045,H4)、B2=(0.1,H3)、B3=(0.045,H3)。8配置在评价前完整发布；4个原TIME控制核对原生序列化后复用。没有新增可调数值坐标；零相对变化是业务比较本身。全部结果保留。Optuna固定队列、8进程、每进程原生线程1、请求workers1、seed13。

仍使用510500.SH、2020-01-02至2026-09-30、1636交易日、初始100万元、HFQ研究单位/整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。数据均来自S013已有授权资产及预热，没有其他批次或新数据。历史开发池已反复查看，非独立验证。

原四门：年化≥正收益基准1.5倍；各自然年回撤严格小于基准；每60交易日平均≥4笔闭合交易；基准亏损年2022/2023策略年度收益严格为正。全窗回撤与扰动指标均为诊断，不新增经济门。

|背景|机制|候选|净年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in analysis['cells']:
        row=analysis['rows'][cell['label']]
        failed='、'.join(name for name,value in row['gates'].items() if not value)
        report+=f"|{cell['background']}|{cell['mechanism']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failed}|\n"
    report+='\n## 参数诊断与结论\n\n'
    improvements=[]
    if parameters['status']=='PASS':
        report+='账户评价前声明与EX015相同的全部13维数值域、域宽标准化5%总L2距离、32点/中心、seed13、PCG64、INTEGER HALF_EVEN、LINEAR分位数。原中心和所有新四门达标配置均检验，失败或不达标扰动点不替换。源合法域和S013原ACF搜索域[-0.60,0.50]保持。结构、类别、null、零冷却及固定执行条件单列。不能与未保存域字节的历史S007-native扰动直接比较。\n\n'
        report+='|中心|年化Q10|回撤Q90|年化退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for label,row in parameters['summaries'].items():
            report+=f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        for label,delta in parameters['differences_from_original'].items():
            report+=f"\n{label}相对原中心：年化退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0:
                improvements.append(label)
        parameter_business=sum(row['complete_points'] for row in parameters['summaries'].values())
        parameter_actual=parameters['actual_parameter_evaluations']
        report+='\nSE公共比较可比、分位数独立复算相同。有限点集不是未来成功概率或置信区间，邻点四门结果仅作诊断。\n'
    else:
        assert not qualified
        parameter_business=parameter_actual=0
        report+='8个新机制没有原四门达标配置，未追加扰动账户。事前参数域仍保留，未为了宣布稳健性而放宽经济目标。\n'
    if improvements:
        report+='\n本轮在声明域内取得两项退化均减轻的有限研究证据；幅度、绝对退化、完整反证与开发池选择偏差仍需一并解释，不能宣称未来保证。\n'
    else:
        report+='\n本轮机制对照完成，但未证明保留原目标的参数敏感性改善；总目标尚未达成。延长持仓可能降低频率并积累亏损，相反方向完整报告，不能只挑收益最高账户。\n'
    report+='\n## 技术验证与留存\n\n'
    report+=f"8新机制配置、9次实际完整评价（1次串行/spawn技术重复），4原控制复用；参数配置{parameter_business}个、实际参数评价{parameter_actual}次。实际总评价{9+parameter_actual}，不同新业务配置{8+parameter_business}。技术重复不计新策略发现。\n\n"
    report+='全部8配置前缀及未来修改因果检查通过；合成检查包括两方向、年龄条件、等号双边、上涨原期限和非法机制；代表串行/spawn信号及策略/基准双方5账本精确相同。12中心账户的基准5账本精确相同，完整现金/数量/价格/费用/年度/周期/尾仓核验通过。研究源码Ruff检查通过；未做仓库全量回归。\n\n'
    report+='全部评价、原生账户、源码、完整数据和参数绑定通过公开研究API留存；旧证据不可变。本交付COMPLETE只表示本轮证据完整，不表示稳健目标自动达成、正式阶段四排名/交接、冻结或PTE授权。Git不是数据资产备份。\n\n'
    report+='\n## 已有账户的最强反证与下一步\n\n'
    report+='已有EX015两套各32点账户的事后描述独立留存。原32点2023实际日历年收益平均−4.0173%；下跌路线定时退出组平均贡献+2.8702个百分点、下跌状态退出+1.6173，上涨状态退出−7.6401、上涨定时退出−0.8647。这按当年每日持仓价格损益和实际费用归因，并对到账户年度净值；退出原因只是原政策的事后分组，不能解释成改变该退出即消除该损失。原32点每点均未通过基准亏损年盈利门，30点未过总收益、9点未过频率，年度回撤门均通过。\n\n'
    report+='对2023下跌定时退出按入场/退出信号日期去重，排除当日状态已切换的事件：相对入场价负组30事件，随后3日均+0.3690%；正组36事件，随后3日均−0.1261%。到10日则约−0.0308%与+0.7948%，方向改变；不能据此挑观察窗或机制。未来窗口统一使用信号价格单位；未发布初稿混用单位已在留存说明中揭示，实际年度现金/费用归因不受影响。事件重叠且非独立，不是完整新政策账户效果。\n\n'
    report+='这条反证改变下一步优先级：不能把2023损失主要归因于下跌定时退出，应先研究上涨路线入场和状态切换带来的路径损失，考虑有明确反证的状态确认或参数决策组合。仍保持原四门，不依赖反复微调旧门槛宣布成功。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(report,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':bool(improvements),'improvement_labels':improvements,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':8,'mechanism_actual_evaluations':9,
        'new_parameter_business_accounts':parameter_business,'parameter_actual_evaluations':parameter_actual,
        'original_economic_criteria':'unchanged','report_sha256':file_hash(path)})
    print({'report':'COMPLETE','new_qualified':qualified,'improvement_labels':improvements})


if __name__=='__main__':
    main()
