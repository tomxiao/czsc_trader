"""RSCH-authored conclusions and tables from completed real account evidence."""
from common import RUNS, SRC, read
from diagnose import rows

LABELS = {'return': '整体年化', 'annual_drawdown': '逐年回撤', 'frequency': '交易频率',
          'negative_buyhold_year_profit': '基准亏损年份正收益'}
DESCRIPTIONS = {'C1000': '原模型复现控制', 'C1013': '仅上涨转下跌退出',
                'C1124': '上涨路线持有上限9信号日', 'C1016': '双向退出后冷却2信号日',
                'C1201': '双向退出后冷却5信号日', 'C1203': '上涨转下跌退出后冷却2信号日'}


def pct(value):
    return f'{100 * value:.4f}%'


def main():
    for path in RUNS.glob('state_*.json'):
        if 'rows' in read(path):
            assert read(path)['status'] == 'COMPLETE'
    data = rows()
    indexed = {row['candidate_id']: row for row in data}
    selection = read(RUNS / 'selection.json')
    diagnostics = read(RUNS / 'diagnostics.json')
    costs = read(RUNS / 'cost_diagnostics.json')
    assert len(diagnostics['accounts']) == len(data)
    assert costs['status'] == 'COMPLETE'
    cost_ids = {item['candidate_id'] for item in costs['rows']}
    assert set(selection['qualified']) <= cost_ids
    base = indexed['C1000']
    new = [indexed[x] for x in selection['qualified'] if x != 'C1000']
    improvement = [r for r in new if r['negative_year_min_profit'] > base['negative_year_min_profit']]
    if improvement:
        conclusion = ('观察到新增达标配置提高了基准亏损年份的最小盈利余量；'
                      '是否形成可推荐的改善仍须结合费用、邻域和共同样本选择偏差判断。')
    else:
        conclusion = ('本轮没有找到同时满足原四项目标、又提高基准亏损年份最小盈利余量的新配置。'
                      '新增达标配置保留资格，但未解决原阶段四揭示的盈利薄弱问题。')
    text = f'''# S013阶段三修订四：状态周转、年度盈利余量与频率的机制对照

{conclusion} 完成{len(data)}个不同源码/参数配置的真实完整账户评价，全部SUCCEEDED，无FAILED或UNKNOWN。
其中{len(selection['qualified'])}个通过原四门，包含C1000原模型复现控制；其余{len(new)}个为新增达标配置。
原阶段三10个中心以C9001–C9030技术迁移后的对应身份继续保留，本轮未改变其历史资格、账本或阶段四结论。

## 授权、目标和价格边界

2026-10-09用户批准回阶段三研究年度盈利余量与成本敏感性。仅使用S013、510500.SH和原开发池；所有供应商入口显式禁止新取数，实际评价全部复用本批次正式资产。
实际2020-01-02至2026-09-30共1636交易日，初始100万元、100个后复权研究单位整手、每侧10bp（0.1%）、T日已知信息在T+1执行、只做多、不加杠杆。
HFQ_RESEARCH沿用2019-12-31锚点及0.2803因子，原始0.001价格网格经实际price_scale转换；BuyHold使用同标的下一交易日开盘、同费用和资本。
结果属于研究单位账户，不能直接视为PTE真实ETF份额收益。

四项同时要求：整体净年化≥同窗BuyHold的1.5倍；每自然年回撤幅度严格更小；平均每60交易日闭合交易数≥4（本窗至少110笔）；BuyHold实际年度收益<0时，策略同年收益严格>0。
闭合交易为完成入场和退出的周期。年度现金与持仓连续，以初始现金或上一年末权益作为锚；2026仅截至9月30日，使用未舍入数值作资格判断。
年度盈利余量指基准亏损年份策略正收益超过0的幅度；费用压力、参数扰动及集中性继续只作诊断，未增加经济否决门。

## 机制、控制和研究判断

原C0494的技术继任C9023，2023价格收益约6.50万元，费用约6.06万元，净利约4340元。原阶段三归因表明，状态变化退出保护了2022，却增加了2023费用；不能简单取消全部状态退出。

新StableRange实现分别控制动量阈值死区、连续状态确认、连续退出确认、退出方向和仅状态退出后的冷却；入场锁定路线、持有期、止损、限价及T+1执行沿用原语义。
上涨路线bull、下跌路线bear按过去20个交易日动量相对0选择。设置中的hold-a-b表示两条路线分别最多持有a/b个信号日；both表示双向状态退出，bull_to_bear表示仅上涨转下跌退出，cooldown表示退出后等待的信号日数。
死区表示动量在阈值附近保留原状态；确认表示连续若干个信号日才认可变化。冷却按信号目标状态计数，不按实际成交日重置；实际限价未成交与信号持有锚的差异仍是已知限制。

C1000关闭全部新增机制，所有原信号及完整经济账本与C9023精确一致，跨账本关联ID仅作保持关系的归一化。单进程和spawn批量结果亦精确一致。
小死区或延迟确认多数减少交易，但同时损失价格收益和2022风险控制；仅保留下跌转上涨退出失去2022盈利，是取消上涨转下跌风险出口的明确反证。
仅保留上涨转下跌退出、或把bull持有期从8改9日，仍出现新达标配置，但盈利余量未改善。

状态冷却2日及后续扩边确实提高了部分年度盈利。较短持有期的同参数配对对照，用于核验是否能恢复频率而保留改善；新增参数搜索没有按2022/2023标签或日期硬编码路由。
以下结果是同一已见开发池内完整策略路径的对照，不能把某一退出交易的完整周期利润直接解释为该退出动作的因果贡献，也不能把跨年周期总利润代替年度收益。

## 标准配置与前沿

|配置|机制|净年化|闭合交易|2022净收益|2023净收益|原四门|
|---|---|---:|---:|---:|---:|---|
'''
    displayed = list(dict.fromkeys(['C1000'] + selection['qualified'] + selection['frontier']))
    for identifier in displayed:
        r = indexed[identifier]
        failed = '、'.join(LABELS[k] for k, v in r['gates'].items() if not v)
        text += (f"|{identifier}|{DESCRIPTIONS.get(identifier, r['label'])}|{pct(r['net_cagr'])}|{r['closed_trades']}|"
                 f"{pct(r['annual']['2022']['return'])}|{pct(r['annual']['2023']['return'])}|"
                 f"{'通过' if r['qualified'] else '未通过：' + failed}|\n")
    text += '''
阶段三前沿只展示收益、负基准年份盈利余量和达到4次上限后的频率取舍；达到原频率要求的值同等满足目标。不是阶段四正式排序，不按新的加权分或费用硬门重新判资格。

## 年度价格与费用归因

按实际每日持仓、成交价格和费用重建价格损益：昨日持仓的收盘变动，加当日成交至收盘的估值变化，再扣实际费用；与每日权益增量对账。各年度贡献分别按该配置当年期初权益归一化，因此期初资本可能不同。

|配置|2023价格贡献|2023费用贡献|2023净收益|2023净利（元）|
|---|---:|---:|---:|---:|
'''
    proofs = {p['candidate_id']: p for p in diagnostics['accounts']}
    for identifier in displayed:
        year = proofs[identifier]['annual']['2023']
        text += (f"|{identifier}|{pct(year['price_contribution'])}|{pct(year['fee_contribution'])}|"
                 f"{pct(year['net_return'])}|{year['net_pnl']:.2f}|\n")
    text += '''
C1016相对原控制的2023收益改善，并非纯节费：价格贡献增加约0.4458个百分点，费用贡献减少约0.6019个百分点，共改善约1.0477个百分点；但全窗少了12笔闭合交易。
C1013按年初资本的费用贡献虽下降，价格贡献也下降且幅度更大，净盈利余量变薄。C1124在2023的净利仅约297元，降低绝对费用没有解决正收益接近零的问题。

## 同持有期的配对反证与扩边

|配置|设置|净年化|闭合交易|2022净收益|2023净收益|
|---|---|---:|---:|---:|---:|
'''
    for identifier in ['C1103', 'C1105', 'C1109', 'C1111', 'C1016', 'C1200', 'C1201', 'C1202', 'C1203']:
        r = indexed[identifier]
        text += (f"|{identifier}|{r['label']}|{pct(r['net_cagr'])}|{r['closed_trades']}|"
                 f"{pct(r['annual']['2022']['return'])}|{pct(r['annual']['2023']['return'])}|\n")
    for identifier in ('C1314', 'C1315', 'C1316', 'C1317', 'C1318'):
        r = indexed[identifier]
        text += (f"|{identifier}|{r['label']}|{pct(r['net_cagr'])}|{r['closed_trades']}|"
                 f"{pct(r['annual']['2022']['return'])}|{pct(r['annual']['2023']['return'])}|\n")
    text += '''
冷却5日的外沿6/8日同时降低年化、交易频率并使2022转负，没有继续单向扩冷却的改善依据。将bull最长持有改4日确实恢复到116笔，但2022转为亏损、整体年化10.2496%仍低于原门槛；改6/7日也未同时满足四门。
这组配对与扩边说明当前盈利提高依赖避开特定持仓路径，不能仅靠增加短周期交易来补足频率；不是已证明所有持有期和冷却组合都无效。所有新达标配置及盈利余量前沿均保留；失败对照没有被自动重试或改写为成功。
'''
    text += '\n## 费用压力\n\n全部新标准达标配置及选定前沿在相同输入下重算单侧20/30bp，并各自核验10bp基线重复账本精确一致。费用压力不改变标准场景资格。\n\n'
    text += '|配置|10bp年化|20bp年化|30bp年化|20bp的2022收益|20bp的2023收益|30bp的2023收益|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for item in costs['rows']:
        b, s20, s30 = (item['scenarios'][key] for key in ('baseline', 'stress20', 'stress30'))
        text += (f"|{item['candidate_id']}|{pct(b['net_cagr'])}|{pct(s20['net_cagr'])}|{pct(s30['net_cagr'])}|"
                 f"{pct(s20['annual']['2022']['return'])}|{pct(s20['annual']['2023']['return'])}|"
                 f"{pct(s30['annual']['2023']['return'])}|\n")
    text += '\n## 逐自然年目标核验\n\n收益按各自实际连续权益计算；下表优先并列BuyHold与标准达标配置。\n\n|年份|BuyHold净收益|' + '|'.join(selection['qualified']) + '|\n'
    text += '|---|' + '---:|' * (1 + len(selection['qualified'])) + '\n'
    for year in base['annual']:
        text += '|' + year + '|' + pct(base['buyhold_annual'][year]['return']) + '|' + '|'.join(
            pct(indexed[x]['annual'][year]['return']) for x in selection['qualified']) + '|\n'
    text += '\n逐年回撤优势为BuyHold回撤幅度减策略回撤幅度，正数满足严格更小；单位百分点。\n\n|年份|' + '|'.join(selection['qualified']) + '|\n'
    text += '|---|' + '---:|' * len(selection['qualified']) + '\n'
    for year in base['annual']:
        text += '|' + year + '|' + '|'.join(f"{100 * indexed[x]['annual_dd_margins'][year]:.4f}"
                                          for x in selection['qualified']) + '|\n'
    text += f'''
## 搜索、证据和限制

本轮{len(data)}个不同配置，由Optuna固定队列在主进程管理、按参数哈希去重；4个Windows spawn评价进程，每个原生线程1、每请求workers=1、种子13。另有1次控制复算，及{len(costs['rows'])}个三费用场景请求，其中10bp基线为重复一致性检查。
各轮在运行前显式发布方案，后续设计依据已观察结果并披露选择历史；不是随机未见样本检验。原阶段三494个成功配置、16次UNKNOWN及阶段四80个扰动的历史原件保持，本轮没有用新增计数冒充完整搜索分布校正。
整个开发池反复用于路线和参数选择，没有独立保留样本。原阶段四统计诊断不自动适用于新候选；本轮未计算新的完整研究族PBO/DSR，不把排名或置信区间解释为未来成功概率。

所有{len(data)}个标准账户独立核验年度权益、逐日现金及持仓、价格/费用损益，金额重建误差均小于0.000001元。已声明2020-12-01分钟Low偏差可能改变实际订单的数量为{diagnostics['known_low_error_potential_orders']}；四个分钟High偏差不进入可信日线特征或当前撮合。仅覆盖已声明异常，未知分钟路径及供应商因子历史可得性限制保持。
原31份研究资产、28份历史准备及原候选/交付原件保持；计算消费技术迁移后契约版本1的正式资产及新准备引用。正式账户、源码、依赖和准备引用须随交付保留；Git和.tmp缓存不能替代正式资产。
新增策略未进入阶段四标准自检、阶段五技术检验或冻结；本轮未修改平台、依赖、生产或PTE账户，也未执行全仓回归。

## 收口与下一步

{conclusion} 停止判断应依据真实改善、配对反证和剩余方向，而非固定评价次数；本轮不宣称已穷举所有策略或不存在更优配置。
建议先审阅本轮正式交付，保留旧候选和全部新达标配置，暂缓冻结。若本轮周转机制的盈利与频率取舍不能共存，应优先重新研究能增加价格收益的可用信息，而非继续只围绕亏损年份的少量交易微调。
进入阶段四、回阶段二、选择候选、冻结及生产动作分别等待用户明确决定。
'''
    (SRC.parent / 'others/report.md').write_text(text, encoding='utf-8', newline='\n')
    print({'report_written': True, 'configurations': len(data), 'new_qualified': len(new)})


if __name__ == '__main__':
    main()
