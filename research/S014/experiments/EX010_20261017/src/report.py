"""Generate the bounded industry research report from verified economic evidence."""
import json
from inputs import ROOT,EXPERIMENT


def main():
    def read(name):return json.loads((EXPERIMENT/f'others/{name}.json').read_text(encoding='utf-8'))
    ready=read('upstream_verification_resolved');r=read('computation_result');f=read('followup_result');s=read('stock_lag_result');cash=read('attribution_result')
    audits=[read(n) for n in ('audit','followup_audit','stock_lag_audit')]
    assert ready['status']=='PASS' and all(a['status']=='PASS' for a in audits)
    def p(x):return f'{100*x:+.3f}'
    def ci(xs):return '['+','.join(p(x) for x in xs)+']'
    def link(path,name):return f'[{name}](../../../experiments/EX010_20261017/{path})'
    mainrows=[]
    for h,algo,mode,left in [(3,'ridge','frozen','plain'),(3,'ridge','rolling','both'),(3,'tree','frozen','both'),(3,'tree','rolling','both'),
        (1,'ridge','frozen','lagged'),(1,'ridge','rolling','lagged'),(1,'tree','frozen','lagged')]:
        x=next(x for x in r['comparisons'] if x['kind']=='model' and (x['horizon'],x['algo'],x['mode'],x['left'],x['right'])==(h,algo,mode,left,'market'))
        mainrows.append(f'| {h}日/{algo}/{mode}/{left} | {p(x["difference"])} | {ci(x["interval95"])} | {p(x["without2026"])} | {p(x["drop3_per_year"])} |')
    erows=[]
    names={'sector-rebound':'行业独立修复','sector-laggard-repair':'行业上涨中的落后股收阳','sector-confirms-stock-repair':'行业盘中修复确认个股修复',
        'sector-trend-with-stock-repair':'行业近期强弱区分个股修复','relative-leader-in-sector-pressure':'行业受压时个股抗跌','common-sector-selloff':'共同化工卖压后的修复'}
    for n,label in names.items():
        x=next(x for x in r['comparisons'] if x['kind']=='event' and x['horizon']==3 and x['name']==n and x['mode']=='raw')
        z=next(x for x in r['comparisons'] if x['kind']=='event' and x['horizon']==3 and x['name']==n and x['mode']=='residual')
        erows.append(f'| {label} | {p(x["difference"])} | {p(z["difference"])} | {ci(z["interval95"])} |')
    follows=[]
    for algo,mode,left,right in [('ridge','frozen','lagsector','base'),('ridge','rolling','lagsector','base'),('ridge','frozen','lagboth','lagmarket'),
        ('ridge','rolling','lagboth','lagmarket'),('ridge','zero','lagboth','lagmarket'),('ridge','frozen','laginnovation','base'),('tree','frozen','lagboth','lagmarket')]:
        x=next(x for x in f['comparisons'] if (x['algo'],x['mode'],x['left'],x['right'])==(algo,mode,left,right))
        follows.append(f'| {algo}/{mode}/{left}−{right} | {p(x["difference"])} | {ci(x["interval95"])} | {p(x["without2026"])} | {p(x["drop3_per_year"])} |')
    stockrows=[]
    for mode,left,right in [('frozen','withsector','stocklag'),('rolling','withsector','stocklag'),('zero','withsector','stocklag'),
        ('frozen','withinnovation','stocklag'),('frozen','sectoralternative','stocklag'),('rolling','sectoralternative','stocklag')]:
        x=next(x for x in s['comparisons'] if (x['mode'],x['left'],x['right'])==(mode,left,right))
        stockrows.append(f'| {mode}/{left}−{right} | {p(x["difference"])} | {ci(x["interval95"])} | {p(x["without2026"])} | {p(x["drop3_per_year"])} |')
    cashrows=[]
    for x in cash['annual']:
        if x['horizon']==1 and x['mode']=='all-filled':
            cashrows.append(f'| {x["year"]} | {x["n"]} | {p(x["later_cash"])}% | {p(x["market_later"])}% | {p(x["both_later"])}% | {p(x["both_later_residual"])}% | {p(x["market_later_residual_rmse"])}% → {p(x["both_later_residual_rmse"])}% |')
    report=f'''# S014 阶段二：化工行业代理核验、解释检验与收益线索反证

**已完成获准的同周期化工指数权限/覆盖核验及其阶段二研究。当前市场加行业模型没有充分解释2025低开修复后的隔夜损失；行业滞后信息有局部线性排序增量，但更强股票滞后对照削弱了它，尚不确认新的收益入场组件。阶段二整体保持PARTIAL，当前不建议进入阶段三。**

明确得到的结果是：本次固定化工价格代理没有解决原反例，先前应优先考虑行业共同拖累的假设须下调优先级。不能据此断定公司事件是损失原因，也不能说所有行业信息无效。下一步更有辨别力的方向是公司披露信息的真实可得性核验；本轮没有读取任何公司公告目录或事件原文，不自动扩大范围。

## 一、同一指数的代码核对与真实上游结果

用户批准同周期`000813.SH`日线，使用剩余5次调用，先验上游再继续阶段二。事前{link('protocols/design.json','研究设计')}固定后，公开DFLS全窗口请求返回`EMPTY_DATA`，原请求和失败{link('others/upstream_verification.json','记录')}保留，没有把空数据解释为权限不足。

随后核对[Tushare官方说明](https://tushare.pro/document/2?doc_id=95)：中证指数公司的供应商后缀为CSI，应以`index_basic`代码为准。同一账号目录查询`symbol=000813,market=CSI`唯一返回`000813.CSI/细分化工/中证细分化工产业主题指数`，发布方中证指数有限公司，发布日期20120411。{link('others/vendor_identity.json','目录证据')}确认这与用户批准的指数相同。此前建议`.SH`后缀不准确，本轮显式纠正供应商标识；没有替换指数、引入平台别名或回写旧证据。

| 实际调用顺序 | 内容 | 结果 |
| --- | --- | --- |
| 1 | index_daily，000813.SH，完整原窗口 | EMPTY_DATA |
| 2 | index_basic，仅000813的CSI目录 | 唯一确认同名指数000813.CSI |
| 3 | S014公开DFLS index.domestic_daily，000813.CSI | READY，1642个交易日 |

本轮累计3次，原恢复及上证指数45次后累计48/50，剩余2次。目录查询仅为同账号身份诊断，不作历史收益输入；正式行业行情来自S014原生`prepare(REFRESH)/fetch`。

正确代码实际覆盖2020-01-02至2026-10-15，与股票、上证指数和原交易日历的1642个交易日完全一致，无重复/缺日/越界日。价格有限且为正、活动量非负、OHLC边界、前收连续、涨跌额/幅恒等式等{len(ready['checks'])}项检查通过。原生数据哈希`{ready['identity']['content_sha256']}`；请求、准备引用、来源版本和累计调用见{link('others/upstream_verification_resolved.json','完整核验')}。

采用完成T日收盘后可用约定，历史发布时间与修订仍未证实。不用指数成交额/成交量作股票均价边界测试。000813只是固定化工行业价格代理，不代表金牛化工历史成员身份、甲醇利润或完全匹配的公司业务；没有用当前成员重建历史。

## 二、研究比较与交易语义

经济目标承接MANDATE/2不变：10万元、单侧0.1%、HFQ_RESEARCH实际SRT股数、固定前收+1%限价买入及TXE开盘卖出/下限一价位规则。全部H1/3净现金标签继承EX008；未成交0，右截断不强平。H1最早T+2卖出，不能在买入当天兑现首日收盘修复。

全部数据为已见开发池，行业序列也不是独立未见验证样本。2023..2026按年外推，训练标签实际到期严格早于测试年度首个信号。H1测试912次、H3为910次；它们是重叠独立尝试，不是连续账户、年度收益或真实闭合交易频率。原逐年收益、严格年度回撤及全期频率要求均未更改且尚未验收。

基线为前轮已验证的股票19项加市场7项及相对响应4项。新增行业日内/隔夜、1/5/20日、波幅等信息；两因素回归用**截至T-1的过去60日**股票、市场和行业对数收益，含截距、市场与行业系数。实际1581个可拟合日均满秩，中心化两因素矩阵最大条件数约{r['max_condition']:.3f}，没有以不完整拟合填补数据。截距不叫共同市场收益，也不进入共同因素现金代理。

主试验固定岭10及深度3/叶40树，包含股票、股票加市场、股票加行业、市场加行业原值、双因素相对表达、行业滞后1日、行业滞后20日。选择分别采用历史训练分数75%分位和仅过去126日分数75%分位；树分数并列，实际覆盖不强制25%。没有未来年度排名或参数扫描。具体实现澄清及预先发布引用见{link('protocols/implementation.json','实现口径')}和{link('protocols/implementation_published.json','发布记录')}。

## 三、解释2025损失：加入行业后没有改善

下表对原低开收阳A的已成交H1尝试，后段为首持有日收盘至实际退出的现金变化/10万元；代理是信号时已知系数乘随后实际指数变化，**仅事后解释**，未进入决策。残差由实际变化减代理定义，不是因果识别或可兑现对冲利润。

| 信号年 | 成交数 | 实际后段现金 | 市场单因素代理 | 市场加行业代理 | 双因素残差 | 单因素→双因素残差RMSE |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(cashrows)}

2025的76次成交：首段+0.2911%、后段-0.4548%、费用0.1958%，净-0.3595%。市场加行业后段代理为**+0.0195%**，残差约**-0.4743%**，比市场单因素残差-0.4432%更负，RMSE也未改善。

为处理盘中限价触及时点不同，单列股票买卖均在开盘成交的75次：实际后段-0.4609%，双因素代理+0.0195%，残差-0.4804%，结论相近。非开盘成交只能使用指数开盘代理，已逐条标记；没有把不精确同步路径当实际成交。

2026残差RMSE确有改善，不能概括成“行业任何时候都没有解释力”；它仍未解释当前最关键的2025亏损。行业指数篮子与公司业务不完全匹配、系数时变或非线性等仍是竞争解释，不能把未解释部分全部归因于公司事件。全部H1/3及开盘子集见{link('others/attribution_result.json','现金归因结果')}。

## 四、已知行业信息的净收益增量

下表均相对强股票加市场基线，单位为**每个可评价信号日的净现金分配差，百分点**，非账户年收益。frozen为训练阈值，rolling为过去126日分数阈值；plain为加行业原值，both为加原值与双因素相对响应，lagged为行业原值滞后1日。

| 期限/模型/阈值/行业表达 | 增量 | 普通95%区间 | 去2026 | 每年删最好3个差值贡献 |
| --- | --- | --- | --- | --- |
{chr(10).join(mainrows)}

3日期限当前行业原值/相对组合在岭和树、两种阈值下多数增量为负；1日滞后行业岭模型出现正向线索，应追查而不是因首次检验完成收口。其frozen选中200次，198次成交，尝试平均净收益+0.566%；但总体MAE由市场基线2.186%升至2.208%，rolling增量明显较小，树表达不支持相同效果。

## 五、直接机制与附加信息的竞争解释

主设计预先定义6个机制，检验行业独立修复、落后股追赶、行业确认个股修复、行业趋势、行业受压时个股抗跌及共同卖压。边界为固定0或仅过去到期训练分位，没有按结果选择阈值。

| 3日机制 | 原始条件净收益差 | 扣除同一强股票加市场预测后的差 | 残差普通95%区间 |
| --- | --- | --- | --- |
{chr(10).join(erows)}

落后股收阳的3日原始优势约+1.098个百分点，调整已知股票/市场预测后约+0.144，不能认定行业独立信息。行业盘中修复确认个股修复的H1/3原始和残差方向均未支持预期。共同行业卖压缺组年份明确不填0，稀少本身不是否定依据。所有期限、年份、数量及去事件重叠见{link('others/computation_result.json','主结果')}、{link('others/annual.csv','年度表')}。

## 六、追踪滞后行业线索：有有限支持，也有未解决反证

先发布{link('protocols/followup_design.json','滞后对照设计')}，再比较遗漏的前一日大盘信息、去市场共同变化后的行业信息，以及行业波幅/方向。新行业变化的滞后系数需要多一天预热，所有补充变体统一从信号62开始；基线在相同队列重新拟合。测试年队列数量不变，不能把补充值与信号61训练的主值当完全相同模型。

下表base为原强股票+市场，lagmarket加前一日大盘，lagboth同时加前一日大盘与行业，laginnovation为去市场部分后的行业变化。zero为成本后预测值>0，经济盈亏边界，没有调优。

| 1日对照 | 增量 | 普通95%区间 | 去2026 | 每年删最好3个差值贡献 |
| --- | --- | --- | --- | --- |
{chr(10).join(follows)}

不能把这些正向结果省略：岭模型中lagboth相对lagmarket，frozen和rolling的普通区间都在0以上，剔除2026后仍正。这支持有限的线性排序线索。但换为zero边界、树表达或删除少数最有利贡献后优势不清，仍不足以确认稳定可用的入场用途。普通区间及历史调整都只是诊断，不新增组件所有年份盈利或置信门。

还需排除前一日股票自身信息遗漏。于是先发布{link('protocols/stock_lag_design.json','股票滞后直接对照')}，在相同前一日大盘基线上补入前一日股票7项形态，再加入行业原值或行业独立变化。

| 1日线性直接对照 | 增量 | 普通95%区间 | 去2026 | 每年删最好3个差值贡献 |
| --- | --- | --- | --- | --- |
{chr(10).join(stockrows)}

直接加行业原值的增量收缩到约+0.0355/+0.0167个百分点（frozen/rolling），普通区间跨0，删最好3次后为负。行业替换股票滞后块在部分表达仍有正向证据，不能宣称完全被股票信息解释；但独立附加收益用途目前仍不充分。没有继续调整邻近滞后、参数或筛选一个阈值作为新发现。

## 七、阶段判断与下一步

本次获准范围的核验及研究已完成，阶段二整体**PARTIAL**。保留原2项风险/执行辅助；本轮行业条件排序和滞后行业条件排序均为证据不足，不新增SUPPORTED收益入场组件。这里缺的是收益用途的充分证据，**不是000813行情缺日或取数失败**。逐年经济目标仍留给获批后的完整策略评价。

当前判断由原假设更新为：单一化工价格代理未缩小2025隔夜损失，价格信息的条件排序线索仍受更强竞争控制和贡献集中影响。当前已不能提出比上述对照更有辨别力的同范围新问题，暂不追加同类指数或同义价格扫描；不是因为调用额度耗尽、实验数量或某个统计门而收口。

下一步建议先核验`600722.SH`同窗口公司公告目录、原文URL和真实披露时间，研究问题是“决策前可知的公司信息能否区分持续负面重定价与短暂修复”。[Tushare公告文档](https://tushare.pro/document/2?doc_id=176)声明`anns_d`需单独权限、单次最多2000条并有可选`rec_time`。这些不是账号权限或时点准确性的实测证明。

具体{link('protocols/next_scope_proposal.json','下一步方案')}只申请**上游可行性核验**，使用最多剩余2次Tushare调用，并核对原交易所/巨潮披露时点和公告锚点。事件缺行不等于当天无公告，不能用交易日历宣称公告100%覆盖，也不能将ann_date或供应商收录时间冒充决策前真实披露时间。平台当前没有公告数据集契约，核验后再决定是否申请DEV实现；不先开发，不自行接入公告作正式研究输入。

这项新增范围尚未获批，未查询公告目录、标题或下载事件原文。阶段三未获批准，本轮也不建议直接进入。原周期、费用、交易语义与验收目标不变。

## 八、证据与验证范围

主{link('others/audit.json','审核')}通过{len(audits[0]['checks'])}项，含1581个历史暴露、112模型、80比较和427现金分解；补充{link('others/followup_audit.json','审核')}通过{len(audits[1]['checks'])}项，含56模型和42比较；股票滞后{link('others/stock_lag_audit.json','审核')}通过{len(audits[2]['checks'])}项，含16模型及12比较。全部模型阈值、仅过去126分数、标签身份、成熟时序、数量、费用、事件条件及聚合已复核。

本轮共184次固定拟合，其中36次既有复现；134个主比较，名义历史574项仍含重复对照及未枚举的适应性暴露，不等于独立发现。无参数搜索、完整账户、候选或生产操作。部分宽表构造出现pandas性能提示，不影响结果，未改写已发布实现。

原生数据及内容寻址证据、完整运行表在S014 assets目录，必须与Git材料共同保存。FULL/PASS只确认已声明身份、证据及计算完整性，不等于Alpha或策略经济目标达标。报告及复制件必须字节一致，历史交付不回写。
'''
    (EXPERIMENT/'protocols/report.md').write_text(report,encoding='utf-8',newline='\n');print('REPORT_RENDERED',len(report))


if __name__=='__main__':
    main()
