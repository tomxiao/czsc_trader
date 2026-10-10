"""Explain all mechanisms and the complete same-domain parameter comparison."""
from common import ROOT,SRC,RUNS,read,write,file_hash

def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']==p['status']=='PASS'
    rows=a['rows']
    previous=read(ROOT/'research/S013/assets/runs/EX014_20261011/analysis.json')['rows']['N0']
    report='''# S013：过滤平滑、确认分退出与参数敏感性结论

本轮自主机制研究及完整参数诊断已完成。原买入确认提高中心收益，但没有保护下跌路线的参数变化；删规则、价格条件退出、平滑过滤输入或等待确认分转弱退出均未形成满足原四门的改善。唯一新达标配置为C7408，到期且确认分仍达标才卖；其中心收益和回撤与C2132相同，必须依靠完整扰动结果判断是否有改进。

身份RSCH、阶段三。直接用户授权“授权你可以自主完成目标，无需评审”。沿用S013已有510500.SH资产及预热、MANDATE/6、2020-01-02至2026-09-30、1636交易日、100万元、HFQ研究单位整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。原四门保持，无新的经济否决或PTE资源选择。

## 已有证据与最强反证

C2132历史统一5%总距离32点显示年化退化9.5670、回撤恶化11.3476个百分点；这两个分位数可能来自不同配置，不能相加作为同一账户的损失。该证据支持参数脆弱性，不能证明整个参数平面的尖峰形状。

EX012完整账户对照中，原确认将中心年化从13.9456%提升到16.1572%，但三个背景中的下跌买入机会都没有被原确认直接拒绝，直接拒绝全部发生在上涨路线。门槛0.1→0.045时，开关确认两侧的回撤恶化都约10.5个百分点；期限4→3日时，两侧年化损失都约4.39个百分点。这是“买入确认已修复下跌参数脆弱性”的最强反证。不同资金继承可带来间接作用，不能把零直接拒绝说成零账户影响。

EX013五个删项新配置均失败。去掉过滤使回撤约翻倍；去掉期限减少闭合交易。放松门槛且不定时退出的年化17.6051%、2023盈利1.5725%，但只有89笔交易，不能放宽至少110笔的频率要求。两条规则有路径交互，简单删掉不足以改善。

EX014九个新价格条件及联合背景配置均失败。最好的原背景转弱条件退出年化__PRICE_CAGR__、回撤__PRICE_DD__，但2023收益__PRICE_2023__；较好的两个总指标没有满足原全部目标。相反价格方向和完整2x2背景一起保留，没有只报告最好配置。

## 本轮最小机制与全部账户

四背景B0=(自相关门槛0.1、期限4日)，B1=(0.045、4日)，B2=(0.1、3日)，B3=(0.045、3日)。TIME为原规则；SMOOTH把原20日涨跌自相关估计再用同长度20日均值平滑，下跌门槛保持，未新增可调长度；LOW_SCORE到期且原确认分低于原门槛才卖，HIGH_SCORE采用相反条件。相等只属于HIGH_SCORE。上涨原规则、区间/状态退出及优先级保持。

现有FROZEN_RULE执行接口只允许空仓/整笔持仓，未实现连续仓位或改执行合同。平滑输入仍有硬门槛，不能声称消除了所有突变。三个机制×四背景事前固定，Optuna队列管理、8进程、每进程1原生线程、请求workers=1、seed13。

|背景|机制|身份|净年化|全窗回撤|闭合交易|2022收益|2023收益|四门|
|---|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        r=rows[cell['label']]
        failed='、'.join(k for k,v in r['gates'].items() if not v)
        report+=f"|{cell['background']}|{cell['mechanism']}|{r['candidate_id']}|{r['net_cagr']:.4%}|{r['drawdown']:.4%}|{r['closed_trades']}|{r['annual']['2022']['return']:.4%}|{r['annual']['2023']['return']:.4%}|{'通过' if r['qualified'] else failed}|\n"
    report+='''
12新业务配置、13次新完整评价（含1次串行/spawn重复）；4历史控制完整序列化精确核对后复用，16个不同内容身份。只有N8通过原四门并登记为C7408，登记不等于推荐、阶段五选择或PTE批准。N8与C2132仅排除随身份生成的decision/order/fill/cycle IDs后，双方五类账本的全部其余信号与经济字段精确相同；原生身份及账本不改写。

原四门为年化至少正收益基准1.5倍、各自然年回撤严格小于基准、每60交易日平均至少4笔闭合交易、基准亏损年2022/2023策略收益严格为正。全窗回撤只作诊断。平滑配置都达不到收益门，等待确认分弱化的配置都低于交易频率要求。相反方向仍复制原背景脆弱性。

## 完整参数诊断

查看EX015结果前已发布共同域：13个活跃数值坐标，包括两路线的窗口/入场/退出/期限、下跌自相关门槛、状态窗口/门槛、确认窗口/门槛。路线源合法域、状态/确认源合法域，以及S013既有ACF搜索域[-0.60,0.50]逐项引用；结构、类别、null参数、冷却0和固定执行合同单列。

两中心各32点，域宽标准化后总欧氏距离5%，seed13、PCG64、整数HALF_EVEN、LINEAR Q10收益及Q90回撤；原中心与全部新四门达标机制完整检验。所有规定点保留，不按结果换点、不只保留达标点、不改变费用或时期、不增加10%/20%档。

原历史统一扰动计划的域字节由S007拥有，S013快照仅保存引用/哈希。本轮没有读取邻批次；前瞻声明新共同域，并同时重做原C2132，不能用历史9.5670/11.3476直接当作本轮相同量尺的基线。两套数值不同不代表历史结果被纠正或策略自动改进。

|中心|中心年化|中心回撤|32点年化Q10|32点回撤Q90|年化退化pp|回撤恶化pp|邻点四门通过|
|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for label,r in p['summaries'].items():
        report+=f"|{r['candidate_id']}|{r['center']['net_cagr']:.4%}|{r['center']['drawdown']:.4%}|{r['q10_cagr']:.4%}|{r['q90_drawdown']:.4%}|{r['return_degradation']*100:.4f}|{r['drawdown_degradation']*100:.4f}|{r['qualified_points']}/32|\n"
    d=p['differences_from_original']['N8']
    improved=d['return_degradation_difference']<0 and d['drawdown_degradation_difference']<0
    report+=f"\nC7408相对原中心：年化退化差{d['return_degradation_difference']*100:+.6f}个百分点，回撤恶化差{d['drawdown_degradation_difference']*100:+.6f}个百分点。"
    report+=('本点集两项均改善；仍需结合绝对退化和已有开发池选择偏差，不能解释成未来稳定保证。' if improved else '年化退化略有减轻，较差回撤略有增加，不能把局部变化解释成稳健性目标已经达成。两项退化用于诊断，不作为新增资格否决。')+'\n\n'
    pairs=read(RUNS/'parameter_pairs.json')
    report+=f"32个点的数值坐标逐点精确相同，其中{pairs['identical_economic_summaries']}个点的收益/回撤/交易数/各年结果/四门摘要完全相同；新机制年化更好{pairs['cagr_better_points']}点、更差{pairs['cagr_worse_points']}点。平均年化差{pairs['mean_cagr_difference']*100:+.6f}、平均回撤差{pairs['mean_drawdown_difference']*100:+.6f}个百分点。此为政策配对描述，不是独立统计检验。\n\n"
    report+='''SE公共比较明确可比，逐点分位数独立用NumPy复算一致。邻点的四门通过数是诊断，未追加经济硬门；有限32点不是置信区间或未来成功概率。没有进行全部阶段四五项自检、族排名、阶段五选择、冻结或PTE。

## 验证与留存

全部新机制12配置因果前缀/未来修改不变；合成分支检查平滑均值、到期后高低分、非法机制。源码保留上涨和区间/状态退出。代表机制及每个中心代表扰动点的串行/spawn信号、双方五类账本及结果哈希精确相同。机制16账户基准账本相同，完整数量/现金/价格/费用/年度/周期/尾仓对账通过；32点逐点账户核验保留，不掩盖已知数据问题。

'''
    report+=f"参数业务账户64个，实际参数评价{p['actual_parameter_evaluations']}次（含每中心1次技术重复）；不重放两个中心。本轮合计76个新业务配置、79次实际评价，另复用4个已有控制。所有原生账户、参数计划/映射/可行性、强类型父子绑定、SE事实及结果、完整源码、输入绑定和依赖均通过公共API保存。\n\n"
    report+='''研究源码静态检查采用明确per-file忽略：不可变mechanism_range.py保留原复制源码中的未使用Mapping导入，仅忽略该F401样式项，其余检查通过；没有修改已发布策略身份来消除样式警告。分析脚本缓存追溯及登记类型导入的调用修正仅影响留存程序，不重放机制账户、不改变指标。未做仓库全量回归。

正式交付CANDIDATES/11与FULL校验回执独立留存；旧交付和全部负面结果不改写。数据资产、候选快照和原生账户须一起保留，Git摘要不能恢复缺失数据资产。

## 结论与下一步

'''
    report+=('本轮在共同声明域内取得有限改善，推荐只作为研究候选保留；其改善幅度和绝对退化必须完整评审，尚无独立样本外验证。' if improved else '本轮没有发现保留原四门且明显减轻完整参数退化的方案。继续在同一开发池微调门槛或期限，越来越容易把偶然路径当作发现；当前证据支持结束这组简单规则改写路线，保留原候选不投入PTE的判断。')
    report+='''

下一步建议回到下跌路线的信息机制：需要能区分反弹仍有支持与反弹已经失败的信息，并在设计中同时约束持仓延长的频率代价；原确认分和单日价格方向已提供明确反证，不能未经新证据继续赋予它们保护作用。该建议是研究方向，不是已获验证的新策略；需新的可证伪信息假说及独立证据，不能放宽原目标宣布成功。
'''
    report=report.replace('__PRICE_CAGR__',f"{previous['net_cagr']:.4%}").replace('__PRICE_DD__',f"{previous['drawdown']:.4%}").replace('__PRICE_2023__',f"{previous['annual']['2023']['return']:.4%}")
    (SRC.parent/'others/report.md').write_text(report,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'This experimental delivery only',
        'objective_achieved':improved,'positive_parameter_improvement_both_metrics':improved,
        'new_qualified':1,'center_performance':'N8 same original center CAGR/drawdown/frequency',
        'parameter_difference':d,'mechanism_accounts':12,'parameter_business_accounts':64,
        'parameter_actual_evaluations':p['actual_parameter_evaluations'],'report_sha256':file_hash(SRC.parent/'others/report.md'),
        'original_economic_criteria':'unchanged','independent_holdout':'none'})
    print({'report':'COMPLETE','both_parameter_metrics_improved':improved})

if __name__=='__main__':
    main()
