"""Reproduce a full five-account report and unchanged parameter-improvement test."""
from common import SRC,RUNS,read,write


def main():
    analysis=read(RUNS/'analysis.json')
    parameter=read(RUNS/'parameter_analysis.json')
    assert analysis['status']=='PASS' and parameter['status'] in ('PASS','NOT_APPLICABLE')
    labels=('B0-TIME','B0-MEAN','B0-BODY','N0','N1')
    assert set(analysis['rows'])==set(labels)
    text='''# S013：下跌持仓逆向波幅退出最小机制对照

RSCH阶段三，用户授权自主完成目标，无需逐轮评审。沿用原S013数据与四项经济要求，本轮完成只表示已交付证据。

EX036完整既有账户诊断：原中心下跌路线57次买入机会全部通过确认；33账户2021次下跌机会仅7次被拒绝。共同满足原资格的配对日，确认判断不同21次。机会依已有持仓状态，不是删除确认后的收益。均值居中自相关C8701仅差2024年度回撤要求，其峰谷损失全部位于实际下跌持仓。该路径归因是描述，不是新增风险规则的利润预测。

本轮两新机制分别在EX028均值居中自相关及EX029同类BODY背景上增加同一风险退出：已持仓下跌路线，从HFQ信号入场Close锚点到当前Close的逆向位移达到严格过去20日真实波幅均值的一个单位时，T发出退出，T+1按原规则执行。TR=max(High-Low,abs(High-previousClose),abs(Low-previousClose))；参考均值shift(1)，当日冲击不进入单位。单位随T的过去历史变化，不冻结在入场日；包含等号、不在入场当日退出。优先级loss>trailing>bear_risk>range>time>regime。退出后按原资格可以再次入场，无新增等待。bull路线和原确认保持。

固定一个单位及20日是新机制选择，未对它们做参数稳定性检验。信号锚点不同于实际成交价和费用，日频退出不保证成交止损价。原H8/H4信号持仓日、全部13数值中心及完整域保持，不按年份/盈利交易例外。最强反证是提前退出可恢复反弹、增加重复买卖费用并损害2022/2023收益。

510500.SH、2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、整手100、T决策/T+1执行、单边0.1%费用，策略及LimitBuyHold统一1%限买溢价。四项要求：年化达到正基准1.5倍；每自然年最大回撤严格小于基准；每60日平均至少4闭合交易（至少110笔）；基准亏损年2022/2023实际连续账户年度收益为正。全窗回撤与邻点诊断不新增经济门。

两新业务配置、三实际完整评价（N0串行/spawn重复一致；N1一次），三旧原生完整账户精确复用。完整信号及现金/数量/费用账本独立核对，原生绑定HFQ重算ACF、因果量额秩/确认分、范围位置、路由、TR单位及全持仓状态。仅各自通过原四门的新中心接受32完整13维扰动点；原EX01532精确复用，不扩展未达标中心。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for label in labels:
        row=analysis['rows'][label]
        failures='、'.join(k for k,v in row['gates'].items() if not v)
        text+=f"|{label}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:+.4%}|{row['annual']['2023']['return']:+.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n|账户|自然年|收益|回撤|基准回撤|年度回撤门|\n|---|---:|---:|---:|---:|---|\n'
    for label in labels:
        row=analysis['rows'][label]
        for year,value in row['annual'].items():
            benchmark=row['benchmark_annual'][year]['drawdown']
            text+=f"|{label}|{year}|{value['return']:+.4%}|{value['drawdown']:.4%}|{benchmark:.4%}|{'通过' if value['drawdown']<benchmark else '未通过'}|\n"
    for label in ('N0','N1'):
        audit=analysis['rows'][label]['acf_audit']
        text+=f"\n{label}独立全路径风险退出{audit['bear_risk_exits']}次；该计数不是增加的盈利交易数。完整路径变化及所有闭合/未闭合交易保留。\n"
    achieved=False
    if parameter['status']=='PASS':
        text+='\n|中心|收益Q10|回撤Q90|收益退化|回撤退化|邻点四门通过数|\n|---|---:|---:|---:|---:|---:|\n'
        original=parameter['summaries']['B0-TIME']
        for label,row in parameter['summaries'].items():
            text+=f"|{label}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']:.4%}|{row['drawdown_degradation']:.4%}|{row['qualified_points']}/32|\n"
            if label!='B0-TIME':
                achieved |= bool(analysis['rows'][label]['qualified'] and row['q10_cagr']>original['q10_cagr'] and row['q90_drawdown']<original['q90_drawdown'] and row['return_degradation']<original['return_degradation'] and row['drawdown_degradation']<original['drawdown_degradation'])
        text+='\n参数方法保持原13完整域、域宽归一总L2=.05、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位。中心原四门通过且绝对Q10/Q90尾部与相对退化同时改善，才可说明本开发池上的实质改善；单纯较弱中心导致退化缩小不算。邻点资格仅诊断，不要求32点全部过门。\n'
    else:
        assert not any(analysis['rows'][label]['qualified'] for label in ('N0','N1'))
        text+='\n两个新中心均未通过原四门，因此按事前计划不运行新增参数账户。这不是参数稳定性改善证明。\n'
    text+='\n全部已见年份和完整失败账户保留。反复使用开发池产生选择偏差，无独立验证、未来保证或对新常量稳定性的证明。FULL只核验声明证据完整性。未推进正式阶段四、冻结、PTE或生产。\n'
    text+=f"\n本轮目标判断：{'开发池上原定义的实质参数改善已出现，仍需明确新常量与独立样本边界。' if achieved else '总改善目标仍未达成；本轮机制的接受或否定依据为完整账户与原经济要求。'}\n"
    conclusion={'objective_achieved':achieved,'status':'COMPLETE','new_qualified':sum(analysis['rows'][label]['qualified'] for label in ('N0','N1')),
        'mechanism_actual_evaluations':3,'new_mechanism_business_accounts':2,'reused_center_accounts':3,
        'new_parameter_business_accounts':parameter.get('new_parameter_business_accounts',0),
        'parameter_actual_evaluations':parameter.get('actual_parameter_evaluations',0),'reused_parameter_accounts':parameter.get('reused_parameter_accounts',0),
        'economic_targets':'UNCHANGED','qualification_only_original_four_gates':True}
    write(RUNS/'conclusion.json',conclusion)
    path=SRC.parent/'others/report.md'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding='utf-8',newline='\n')
    print({'report':'COMPLETE','objective_achieved':achieved},flush=True)


if __name__=='__main__':
    main()
