"""Explain the approved deletion test without equating deleted parameters with stability."""
from common import ROOT,SRC,RUNS,read,write,file_hash

def main():
    analysis=read(RUNS/'analysis.json')
    assert analysis['status']=='PASS'
    rows=analysis['rows']
    assert not any(rows[f'N{i}']['qualified'] for i in range(5)), 'Report must be revised for qualified findings'
    original,weak,short=rows['B0-M1'],rows['B1-M1'],rows['B2-M1']
    nofilter,notimer,both,weaktimer,shortfilter=[rows[f'N{i}'] for i in range(5)]
    interaction={
        'acf_change_original':{k:weak[k]-original[k] for k in ('net_cagr','drawdown','closed_trades')},
        'acf_change_without_timer':{k:weaktimer[k]-notimer[k] for k in ('net_cagr','drawdown','closed_trades')},
        'hold_change_original':{k:short[k]-original[k] for k in ('net_cagr','drawdown','closed_trades')},
        'hold_change_without_acf':{k:shortfilter[k]-nofilter[k] for k in ('net_cagr','drawdown','closed_trades')},
        'definition':'Finite paired policy contrasts on actual accounts; not additive trade contribution, statistical interaction significance or 32-point robustness.'}
    write(RUNS/'interaction.json',interaction)
    names={'ORIGINAL':'原机制','NO_BEAR_ACF':'取消下跌过滤','NO_BEAR_TIMER':'取消下跌定时退出','NEITHER':'同时取消'}
    report='''# S013：下跌过滤与定时退出删项实验

本轮获批实验已完成，总目标尚未达成。5个新配置均未同时满足原四项经济目标；不能靠删除两条敏感规则得到合格且已验证稳健的新策略。新的定位证据是：过滤与定时退出明显存在路径交互，改变其中一条会改变另一条参数的反应。

身份RSCH，阶段三；原水平买入确认保持。原C2132不投入PTE的决定及历史阶段四结果不变。本轮没有进入阶段四，没有独立样本外验证，没有新增候选登记。

## 执行及比较边界

按用户明确回答“批准按此方案执行”实施原机制、只取消下跌自相关过滤、只取消下跌定时退出、同时取消两者。三个背景是原参数、自相关0.045和下跌持仓3日。12格展示对应8个内容身份，3个原对照核对后复用，5个新配置完成；6次新账户评价包含1次串行/并行技术重复，不是6个独立策略发现。

只使用S013既有510500.SH资产及预热，2020-01-02至2026-09-30、1636日、100万元、100个HFQ研究单位整手、每侧10bp、策略与LimitBuyHold基准统一1%买入溢价。T决策T+1执行，原网格及价格角色保持。新账户跨年连续；基准实际亏损年份为2022/2023。研究单位账户不等同PTE真实份额账户。

取消过滤用原实现的bear.acf_min=None；取消定时退出用独立研究源码允许bear.max_hold=None并明确跳过age条件，不用大数字冒充关闭。上涨8日限制、原确认门、区间退出、状态变化退出与优先级保持，冷却为0。关闭参数在身份生成前归一，重复展示格共享账户。

## 全部结果

回撤列为全窗最大回撤，用于诊断；四门中的回撤要求按每个自然年分别核验。不能因全窗回撤较大自动新增资格否决。

|背景|机制|身份|净年化|全窗回撤|闭合交易|2022净收益|2023净收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in analysis['cells']:
        row=rows[cell['label']]
        failed=','.join(k for k,v in row['gates'].items() if not v)
        report+=f"|{cell['background']}|{names[cell['mechanism']]}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else '未通过：'+failed}|\n"
    report+='''
四门沿用整体净年化至少基准1.5倍、每年回撤严格更小、每60交易日平均至少4笔闭合交易，以及基准亏损年份策略净收益严格为正。此窗至少110笔闭合交易。新配置全部通过收益和逐年回撤门，但存在负基准年盈利和/或频率缺口；只有原B0对照通过全部四门。

## 通俗结论与最强反证

取消过滤不是去掉一个多余限制。原背景年化16.1572%变为13.7570%，回撤14.1599%变为29.5711%；交易112变为217，2022/2023分别亏损3.2809%/9.1143%。更多交易没有补回风险代价。取消过滤的3日配置回撤30.0101%，2023亏损11.8841%；该过滤仍有必要价值。

取消定时退出也不能直接成为改进。原门槛下年化小升至16.5258%，但回撤扩大至22.9693%，交易仅84笔，最长完成持仓35日，2023亏损1.4742%。原规则的退出时点虽敏感，但它确实提供了更短持仓和更多闭合交易，不能只为消灭参数而删除。

最有价值的竞争解释是两条规则互相影响：门槛降至0.045且不定时退出时，年化17.6051%、回撤21.7643%、2023盈利1.5725%，相对同门槛原4日退出的15.8174%、24.6200%、2023亏损1.9705%出现改善。它仍只有89笔交易，低于110笔要求，不能放宽目标宣布成功。

同时取消两条规则仍有29.6108%回撤，2022/2023分别亏损7.4460%/4.4233%。没有“删得越多越稳”的证据。

## 参数反应与真实交互

'''
    for title,key in [('原定时退出下，门槛0.1→0.045','acf_change_original'),
                      ('取消定时退出后，门槛0.1→0.045','acf_change_without_timer'),
                      ('原过滤下，持仓4→3日','hold_change_original'),
                      ('取消过滤后，持仓4→3日','hold_change_without_acf')]:
        item=interaction[key]
        report+=f"- {title}：年化变化{item['net_cagr']*100:+.4f}个百分点，回撤变化{item['drawdown']*100:+.4f}个百分点，闭合交易变化{item['closed_trades']:+d}笔。\n"
    report+='''
门槛的回撤反应从恶化转为改善，说明原门槛敏感性不能脱离固定退出解释；取消过滤后，3/4日差异也减小，但整个风险水平更差。较小的局部参数反应必须连同收益、回撤、频率和负基准年结果一起看，不能单独宣布稳健。上述有限差分不是统计显著性，也不能相加解释联合扰动损失。

## 归因、持仓及尾仓

'''
    report+='|配置|平均完成持仓日数|最长完成持仓日数|下跌闭合交易|下跌定时退出|期末未闭合周期|\n|---|---:|---:|---:|---:|---:|\n'
    for label,row in rows.items():
        h=row['holding_diagnostic']
        report+=f"|{label}|{h['mean_closed_sessions']:.4f}|{h['max_closed_sessions']}|{h['bear_closed_cycles']}|{h['bear_time_exits']}|{len(h['open_tail_cycles'])}|\n"
    report+='''
所有策略期末均保留一笔真实未闭合周期；按收盘标记计入净值，未计为闭合交易。无定时退出的最长持仓35/36/48日及尾仓均保留，不能仅按完成交易评价风险。

逐日价格与费用重建、逐年账户收益、交易周期和尾仓对账保存在完整分析中。各背景删项与原机制的年度价格/费用差分和路径变动全部保留。不同策略继承资金及机会集合不同，旧交易收益之和不是改变规则的反事实贡献。

## 验证与留证

三份复用对照与已发布完整账户重新序列化精确相等，原字节哈希及内容身份吻合；未重算原策略。8个账户的基准五类账本精确相等。5个新配置及3个复用控制的成交→现金/数量、逐日价格/费用、年度收益/回撤、周期/尾仓全部对账通过。已知2020-12-01分钟Low差异的潜在受影响订单为零；已知分钟High偏差不参与本限价买入/市价卖出撮合，不声称重建未知历史轨迹。

合成测试覆盖原整数期限的三配置精确等价、五个新配置前缀因果性/未来修改不变、关闭期限超60日仍不触发时间退出、整数4日期限、区间/状态退出保留、非法期限及上涨关闭拒绝、零冷却。同配置串行/并行信号及双方五类账本、结果哈希精确相等。源码检查通过；没有做仓库级全量回归。

公共API发布五份新完整账户、前瞻方案、真实批准、复用核对、完整分析、交互、技术验证及重现源码；原CANDIDATES/7及历史账户不改写。正式交付为CANDIDATES/8，沿用MANDATE/6；完整校验回执另存protocols/delivery_reference.json与assets/runs/EX013_20261011/delivery_validation.json。

## 局限、停止依据及下一步

本轮固定删项对照回答了规则必要性和两条局部参数的交互：两条规则有价值但现有组合敏感，简单取消未形成达标新候选。没有按已见结果追加阈值、期限或新规则，不是因为预算用完而宣称总目标完成。

开发池反复使用，设计来自已见脆弱性，没有独立样本外证据。取消参数后，原3/4日或0.045/0.1坐标自然失效；重复格不变不构成整体稳定性改善。没有改变参数域或用更少维数制造更好的扰动结果，也未执行正式5%/32点自检。

建议保留过滤提供的风险控制价值，下一轮优先评审下跌反弹的条件退出：研究如何在反弹未结束时避免机械到期卖出，同时在反弹失败时及时释放资金。它必须面对本轮“更长持仓可能改善部分收益，却降低频率并增加回撤”的反证；现阶段只是一条研究假设，具体条件与对照需先评审。阶段四、选型、冻结、PTE及生产仍各需授权。
'''
    (SRC.parent/'others/report.md').write_text(report,encoding='utf-8',newline='\n')
    write(RUNS/'helper_provenance.json',{'reference_functions_origin':'research/S013/experiments/EX012_20261011/src/analyze.py',
        'original_sha256':file_hash(ROOT/'research/S013/experiments/EX012_20261011/src/analyze.py'),
        'exact_function_extract':file_hash(SRC/'analysis_reference.py'),
        'ledger_reference_copy':file_hash(SRC/'ledger_reference.py'),'account_reference_copy':file_hash(SRC/'account_reference.py')})
    print({'report_written':True,'new_qualified':0,'interaction':interaction})

if __name__=='__main__':
    main()
