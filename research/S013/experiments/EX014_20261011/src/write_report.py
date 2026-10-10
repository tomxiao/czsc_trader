"""Expose the complete factorial and the strongest economic counterevidence."""
from common import ROOT,SRC,RUNS,read,write,file_hash

def main():
    analysis=read(RUNS/'analysis.json')
    rows=analysis['rows']
    assert analysis['status']=='PASS'
    assert not any(rows[f'N{i}']['qualified'] for i in range(9))
    report='''# S013：价格条件退出与参数交互对照

9个新配置全部完成，均未同时通过原四项经济目标。到期后等价格转弱退出的原背景配置年化更高、全窗回撤更低，但2023仍亏损；不能把单个漂亮指标视为稳健性改善。策略参数敏感性改善的总目标尚未得到证明。

身份RSCH、阶段三。用户明确授权“授权你可以自主完成目标，无需评审”，本轮自主执行；沿用S013已有资产、MANDATE/6及原四门，不推进PTE、冻结、生产或阶段五。

## 前瞻设计与执行

四背景B0=(过滤0.1、期限4日)，B1=(0.045、4日)，B2=(0.1、3日)，B3=(0.045、3日)。TIME为原到期退出，NONE为取消定时退出，DOWN为到期且收盘不高于前一实际交易日收盘才退出，UP为到期且收盘不低于前日才退出。相等时两者均退出。上涨路线、其他退出优先级、原水平买入确认保持；没有新增数值阈值或窗口。

16个展示格对应14个内容身份，5个历史账户精确核对后复用，9个新业务配置。新完整账户评价18次：2次串行/spawn预检、首次批量8次计算，以及结果保存脚本缺失key字段后对原8请求显式重跑。首次未保存的结果不作为证据；相同交易规则未调整，重复运行不算新发现。原前瞻预算10次及实际18次同时保留。

2020-01-02至2026-09-30、1636交易日、100万元、100个HFQ研究单位整手、每侧10bp、策略和LimitBuyHold统一1%限价溢价。T决策、T+1执行。只使用S013既有数据及预热，无外部提供者调用。研究账户不是真实份额PTE账户。

## 全矩阵

|背景|机制|身份|净年化|全窗回撤|闭合交易|2022收益|2023收益|四门|
|---|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in analysis['cells']:
        r=rows[cell['label']]
        failed='、'.join(k for k,v in r['gates'].items() if not v)
        report+=f"|{cell['background']}|{cell['mechanism']}|{r['candidate_id']}|{r['net_cagr']:.4%}|{r['drawdown']:.4%}|{r['closed_trades']}|{r['annual']['2022']['return']:.4%}|{r['annual']['2023']['return']:.4%}|{'通过' if r['qualified'] else failed}|\n"
    report+='''
四门仍是年化至少正收益基准1.5倍、各自然年回撤严格小于同期基准、每60交易日平均至少4笔闭合交易（本窗至少110笔）、基准亏损年2022/2023策略收益严格为正。全窗回撤只是诊断，不新增自动否决。

## 判断与最强反证

'''
    center,n0,n7=rows['B0-TIME'],rows['N0'],rows['N7']
    report+=f"原背景DOWN年化{n0['net_cagr']:.4%}、回撤{n0['drawdown']:.4%}，优于原中心{center['net_cagr']:.4%}/{center['drawdown']:.4%}，闭合{n0['closed_trades']}笔刚好满足频率，但2023收益{n0['annual']['2023']['return']:.4%}，经济目标未同时满足。B3-DOWN年化{n7['net_cagr']:.4%}、回撤{n7['drawdown']:.4%}也未修复2023亏损。\n\n"
    report+='''全部新增方向配置2023亏损，不能仅因DOWN优于UP就把DOWN视为有效改进。B0-DOWN变为B1-DOWN的年化明显降低、回撤明显扩大；条件退出并未消除过滤门槛的交互敏感性。补齐的B3-TIME更差，证明两条敏感坐标不能仅按单独损失相加理解。

已有无定时退出周期中，到期日上涨组和下跌组延长持有后的平均周期收益都更好。这是有未来标签的描述，无法唯一支持“到期转弱卖出”的假说；本轮相反方向和完整账户是更强反证。旧周期利润不能直接相加作为新策略贡献。

删除过滤、删除定时退出、改变确认分方向、价格条件退出至此均未产生兼顾原四门的新机制。简单删参数或替换一个条件没有证明稳健改进；继续研究须解释如何同时保留过滤的风险控制、期限的周转价值，以及亏损年份的小盈利。

## 局部响应与持仓

'''
    for mechanism in ('TIME','NONE','DOWN','UP'):
        c=next(x for x in analysis['cells'] if x['background']=='B0' and x['mechanism']==mechanism)
        for bg in ('B1','B2','B3'):
            other=next(x for x in analysis['cells'] if x['background']==bg and x['mechanism']==mechanism)
            a,b=rows[c['label']],rows[other['label']]
            report+=f"- {mechanism}，B0→{bg}：年化{(b['net_cagr']-a['net_cagr'])*100:+.4f}个百分点；回撤{(b['drawdown']-a['drawdown'])*100:+.4f}个百分点；交易{b['closed_trades']-a['closed_trades']:+d}笔。\n"
    report+='\n|配置|平均完成持仓|最长完成持仓|下跌闭合|下跌时间退出|未闭合周期|\n|---|---:|---:|---:|---:|---:|\n'
    for label,r in rows.items():
        h=r['holding_diagnostic']
        report+=f"|{label}|{h['mean_closed_sessions']:.4f}|{h['max_closed_sessions']}|{h['bear_closed_cycles']}|{h['bear_time_exits']}|{len(h['open_tail_cycles'])}|\n"
    report+='''
取消期限导致失效坐标的相同账户，不能算参数稳定性提升。全部期末持仓按实际收盘计入净值，未计作闭合交易；年度价格/费用和全部变更周期保存在分析材料。局部有限差分不等于完整13坐标32点诊断。本轮没有把未达标机制追加为正式阶段四选型集合。

## 验证、保存与局限

五个复用控制与原不可变完整账户重新序列化精确相等，原哈希和身份吻合。14个账户的基准五类账本精确相等；全部账户的数量、现金、费用、逐日净值、自然年、周期、尾仓对账通过。已知分钟Low差异的潜在受影响订单为零；High不参与本买限价/卖市价撮合，不宣称重建未知轨迹。

九配置因果前缀及未来修改不变，合成检查覆盖3/4日期限、价格上涨/下跌/相等、原区间/状态退出、上涨原期限、非法方向、零冷却。代表配置串行/spawn信号、五类双方账本及结果哈希精确相等。研究源码Ruff通过，未做仓库全量回归。已发布的描述诊断脚本含一处必要路径初始化后的导入，未声明其通过通用lint。

完整账户、真实授权、前瞻方案、实际次数、完整分析、源码与依赖版本均通过公共API保存。交付CANDIDATES/10沿用MANDATE/6，FULL校验记录独立保存。历史交付及原C2132不投入PTE的决定保持。

全部设计使用已见开发池，没有独立样本外证据。未找到达标新机制不等于证明所有机制无效；继续方向应减少阈值引起的整笔交易突变或检验买入信息能否支持持仓，而不能只为好看分数降低仓位或放宽目标。
'''
    (SRC.parent/'others/report.md').write_text(report,encoding='utf-8',newline='\n')
    write(RUNS/'helper_provenance.json',{'source_experiment':'EX013_20261011',
        'exact_analysis_reference':file_hash(SRC/'analysis_reference.py'),
        'ledger_reference':file_hash(SRC/'ledger_reference.py'),'account_reference':file_hash(SRC/'account_reference.py'),
        'original_analysis_source':file_hash(ROOT/'research/S013/experiments/EX012_20261011/src/analyze.py')})
    print({'report':'COMPLETE','new_qualified':0})

if __name__=='__main__':
    main()
