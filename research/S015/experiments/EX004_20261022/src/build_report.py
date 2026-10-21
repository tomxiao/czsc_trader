"""Render the research interpretation from authenticated account summaries."""
import json
from run_supplement import EROOT, WORK, save


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    rows = sum((read(WORK / f'{p}_results.json') for p in ('initial', 'followup', 'boundary')), [])
    by_id = {r['candidate_id']: r for r in rows}
    a = read(WORK / 'analysis.json')
    d = read(WORK / 'account_diagnostics.json')
    regs = read(EROOT / 'others/registrations.json')
    assert a['published_snapshot_complete'] and a['count'] == 97 and a['passed'] == 73
    pairs = read(EROOT / 'protocols/followup.json')['representatives']
    # Keep the chosen representatives and their counterexamples visible, including negatives.
    counter = []
    for p in pairs:
        ids = [p['source'], p['matched_constant']['candidate_id'], p['reverse']['candidate_id'],
               p['reverse_matched_constant']['candidate_id']]
        counter.append('| ' + ' | '.join(f"{cid}: {100*by_id[cid]['observation']['net_cagr']:.3f}% / "
                        f"{100*abs(by_id[cid]['observation']['max_drawdown']):.3f}%" for cid in ids) + ' |')
    lower_return = sum(by_id[p['source']]['observation']['net_cagr'] <
                       by_id[p['matched_constant']['candidate_id']]['observation']['net_cagr'] for p in pairs)
    lower_dd = sum(abs(by_id[p['source']]['observation']['max_drawdown']) <
                   abs(by_id[p['matched_constant']['candidate_id']]['observation']['max_drawdown']) for p in pairs)
    assert (len(pairs), lower_return, lower_dd) == (8, 8, 5)
    conclusion = ('阶段三补充完成：多档位仓位提供可执行的风险收益选择，振幅方案未超过已评估全仓规则的最高收益。'
                  'C0307相对匹配恒定仓位有有限收益和回撤改善，但另一入场锚未复现收益改善；'
                  '保留全部中心达标候选，建议进入阶段四检验，不能据开发池结果声称已稳健或可冻结。')
    save(EROOT / 'others/interpretation.json', {
        'conclusion': conclusion, 'configurations': len(rows), 'center_passed': a['passed'],
        'registered': len(regs), 'cumulative_registered': len(regs) + 40, 'cumulative_handoff': a['passed'] + 25,
        'initial_representatives': {'count': len(pairs), 'lower_return_than_matched': lower_return,
                                    'lower_drawdown_than_matched': lower_dd},
        'risk_exception': {'source': 'C0307', 'matched': 'C0401', 'other_anchor': 'C0323',
                           'other_anchor_matched': 'C0405'},
        'stopping_basis': 'Lower threshold .5 loses return gate in both anchors; upper extension converges to full weight. Local risk mechanism is now testable in stage four; no global optimum claim.',
        'not_performed': ['stage_four_32_joint_perturbations', 'fee_stress', 'formal_ranking', 'freeze', 'PTE'],
        'independent_validation': False})
    labels = {'C0200': '旧周期全仓（复现C0031）', 'C0201': '新权益全仓', 'C0203': '恒定50%',
              'C0204': '恒定75%', 'C0307': '相对振幅阈值0.75，50%/100%',
              'C0401': 'C0307匹配恒定56.4732%', 'C0400': 'C0307反向映射',
              'C0402': '反向匹配恒定93.5268%', 'C0323': '另入场锚的0.75、50%/100%',
              'C0405': '另锚匹配恒定54.3353%', 'C0403': '阈值下扩0.5，50%/100%'}
    main_table = []
    for cid, label in labels.items():
        r = by_id[cid]
        main_table.append(f"| {cid} {label} | {100*r['observation']['net_cagr']:.4f}% | "
                          f"{100*abs(r['observation']['max_drawdown']):.4f}% | {r['observation']['closed_trades']} | "
                          f"{'达标' if r['passed'] else '收益未达标'} |")
    time_rows, risk_rows = [], []
    for cid in ('C0201', 'C0204', 'C0307', 'C0401', 'C0323', 'C0405'):
        x = d[cid]
        excess = [v['excess'] for v in x['rolling252']]
        time_rows.append(f"| {cid} | {100*x['annual'][0]['strategy_return']:.3f}% | "
                         f"{100*x['annual'][1]['strategy_return']:.3f}% | "
                         f"{100*min(excess):.3f}至{100*max(excess):.3f} | "
                         f"{sum(v < 0 for v in excess)}/9；最长{x['longest_underperforming_rolling_run']} |")
        risk_rows.append(f"| {cid} | {100*x['target_mean_intent_active_days']:.4f}% | "
                         f"{100*x['mean_realized_weight']:.4f}% | {x['fees']:.2f} | "
                         f"{100*x['largest_winner_share_of_positive_closed_cashflow']:.2f}% / "
                         f"{100*x['top5_share_of_positive_closed_cashflow']:.2f}% | {x['open_tail_quantity']} |")
    report = f'''# S015 阶段三补充：振幅与多档位仓位

Status: COMPLETED — 阶段三完成，阶段四未执行。标的159326.SZ；实验EX004_20261022。

## 结论与目标

{conclusion}

本次97个配置全部得到有效完整账户，73个同时满足中心经济与双频率要求。本次已评估范围内观察到的最高净年化仍来自不使用振幅的全仓规则：C0201为48.146%，最大回撤15.123%。多档位的主要价值是提供风险收益选择；振幅分档在一个低回撤方向上出现了超出一般减仓的有限改善，但不能推广为普遍有效的收益增强。

C0307净年化26.977%、最大回撤7.845%；相同入场、退出及平均目标仓位的恒定对照C0401为25.825%、8.827%，分别改善约1.152和0.982个百分点。另一入场锚的分档方案C0323净年化23.025%，略低于其匹配对照23.099%，二者都未达到中心收益门槛。阶段三找到可检验方向，不等于完成稳健性验收。

## 范围、机制与执行口径

沿用[MANDATE/2](../../deliveries/MANDATE/2/report.md)：2025-01-02至2026-10-21共434个评价交易日，保留完整2025自然年；2024-09-09至2024-12-31共75日预热。原始投入10万元，只做多、无杠杆，次日执行，买入限价为信号收盘价上方1%，卖出市价，标准每侧费用0.1%，100份一手。期末持仓按市值计入净值，未强制平仓；未闭合尾仓不计闭合交易。

信号保持原有反转周期：收盘价相对当日成交均价的偏离低于入场阈值时开始持有意图，达到退出偏离或3个信号日结束。只研究两个已见入场锚（偏离≤0、偏离≤-0.25%），退出阈值固定+0.5%、最长3日。选择来自EX003，不是对所有进退场的全面证明。

日振幅=(最高价-最低价)/收盘价；绝对振幅使用最近5日均值，相对振幅为5日均值/20日均值。信号周期活跃时，特征超过阈值取较低仓位，否则取100%；反向对照交换两个状态的仓位。较低档初轮覆盖0%、25%、50%、75%，每个方案最多两个活跃仓位档，周期外为0%。本次未穷举任意连续仓位函数或三个以上活跃档位。

新资金合同为`target_equity_fraction/decision`，每次决策按当时权益确定目标份额；价格变化时即使目标比例不变，也可能调整股数。分档至0%不重置原信号年龄，可在同一意图周期内清仓再入场，真实闭合频率按账户实际平仓计算。旧`full_available_cash/entry_cycle`只作独立对照，避免将资金合同差异误判为振幅价值。

可执行买入持有基准净年化16.938742%、最大回撤36.289990%；中心收益门槛25.408113%，回撤须同时≤29.031992%及≤25%。滚动60日共375个窗口，中位闭合交易数≥6且至少338个窗口有≥3笔。所有达标标签严格沿用这些要求，没有新增诊断硬门。

## 设计、规模及停止依据

事前[初轮方案](protocols/supplement_search.json)包含58点：每个入场锚1个旧全仓、4个新权益常数仓位，以及相对振幅3阈值×4低档和绝对振幅3阈值×4低档。初轮39点达标。

[对照补充规则](protocols/control_addendum.json)在初轮账户之前发布。初轮完成后，按每个锚×振幅类型选最高收益及最小回撤达标代表，共8个，补做平均目标仓位匹配、反向及反向自身匹配。平均值分母为原持有意图活跃日，包含目标为0的日期；它使用整个已见开发池，是解释用的事后常数对照，不能当作事前可预测权重。

原19点后续设计尚未执行时，补齐低回撤代表的反证后形成[31点设计](protocols/followup.json)，29点达标。原24点预留是软预算，调整理由和未执行旧设计均正式保留。发现C0307后又发布[8点边界设计](protocols/boundary.json)，补齐两个入场锚的匹配、反向和更低阈值，5点达标。各组在自身账户执行前发布，后两组属于明确的结果驱动追加，不能倒称整个97点一开始就固定。

本轮58+31+8=97个配置，97成功、0失败、0取消、0未知；另有1份串并行预检查正式账户，预检查调用3次且五账本一致，不新增搜索配置。97点形成{len(a['economic_path_groups'])}个描述性经济路径指纹组（现金/持仓/权益9位小数），不等同独立假设或逐位等价认证。与EX003原84个配置分别计数，阶段三合计181个配置身份，包含旧规则复现及重复经济行为。继承阶段二1092项特征标签比较等选择历史。

24个中心未达标配置均未达到收益门槛，其中绝对振幅2%、低档0%的C0217/C0246也未通过两个频率门：60日闭合交易中位均4笔，至少3笔窗口分别249/375与238/375。其余配置频率通过，97个配置均满足两项回撤要求；不把计算成功与经济达标混为一谈。

参数提议由Optuna排队及ask/tell管理，固定seed13、不剪枝；账户经公共TDR执行，最多8进程、每进程数值线程1。配置和账户身份、提议及完整trial结果均关联正式证据。

停止依据是主要竞争解释已有对照：阈值继续向上（相对2、绝对5%）的改善趋向不使用振幅的全仓，并未超过全仓；活跃日相对振幅最大2.463920、绝对振幅最大6.753389%，阈值达到这些最大值即产生与权益全仓相同目标，这是已见样本上的信号级确定性结论，未伪报额外账户。低回撤方向向下扩至相对0.5时，两锚年化降至23.395%、21.617%，均失去中心收益资格，回撤仍约7.84%。因此停止阶段三扩网格，将有限改善及敏感性留给阶段四；不声称全局最优或排除其他仓位函数。

## 完整账户代表结果

以下为描述性对照，未进行阶段四正式排序。除C0323/C0405外，表中入场锚均为0。

| 候选与规则 | 净年化 | 最大回撤幅度 | 闭合交易 | 中心结论 |
| --- | ---: | ---: | ---: | --- |
{chr(10).join(main_table)}

C0200与EX003 C0031、C0229与EX003 C0026的434日日期/现金/持仓/权益逐值一致。C0201相对旧周期全仓仅提高年化约0.213个百分点，同时回撤增加约0.055个百分点；这是新权益再平衡合同的账户差异，未使用振幅，不能记作振幅增益。

C0307和C0401均为104笔闭合交易，60日中位15笔、375/375窗口至少3笔；差异并非多算未闭合交易。C0307年化仅比25.408113%中心收益门槛高约1.57个百分点，安全余量有限，费用压力尚未检验。

## 反证与有限例外

下表各格为“候选：年化 / 最大回撤”。8个初轮代表相对各自匹配常数全部年化下降，5个回撤下降、3个回撤反而上升；反向映射并未呈现统一劣势，8个反向代表年化都高于各自匹配常数。这里的选择方式本身来自已见结果，不据此宣称反向策略成立。

| 高振幅减仓代表 | 自身匹配常数 | 反向映射 | 反向自身匹配常数 |
| --- | --- | --- | --- |
{chr(10).join(counter)}

后续例外C0307相对C0401收益与回撤同时改善，支持“在这一已见入场锚和阈值上，调仓时点可能有增量”的有限判断。其反向C0400年化42.516%、回撤15.120%，反向匹配常数C0402为44.977%、14.320%，反向在这组对照中两个指标都更差。因此不能将初轮的反向观察推广至所有阈值。

另一入场锚C0323相对C0405，年化少约0.074个百分点、回撤少约0.657个百分点，只保留降风险效果，收益改善未复现。匹配仅控制平均目标仓位，无法让逐日实际敞口、复利资金及成交额完全一致；完整账户差异也不证明独立因果贡献。

## 时间表现、实际仓位与收益集中性

年度收益是原连续账户的切片区间收益，2026仅截至10月21日；滚动252日按21日步长得到9个重叠窗口。所有切片继承原账户现金、持仓及历史高水位，不重新投入本金。年度基准2025为32.610%、2026片段为-1.267%。

| 候选 | 2025收益 | 2026片段收益 | 滚动252日相对基准收益差范围（百分点） | 落后窗口数；最长连续落后 |
| --- | ---: | ---: | ---: | --- |
{chr(10).join(time_rows)}

C0307虽全期达标，2025收益低于基准，9个滚动窗口中有6个连续落后。相对C0401，C0307两个日历切片收益均较高，但9个滚动窗口只有4个收益更高；2025继承高水位回撤7.177%也高于C0401的6.852%。这说明完整区间改善不等于跨时段普遍改善。重叠窗口不独立，不据此计算未来胜率。

| 候选 | 活跃意图日平均目标仓位 | 全434日平均实际收盘仓位 | 累计费用（元） | 最大/前5盈利交易占正盈利 | 期末持仓（份） |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(risk_rows)}

C0307和C0401的活跃日平均目标均56.4732%；全期实际平均仓位分别28.7435%和28.7374%，相差约0.0061个百分点，累计费用分别14877.42元和14647.36元。C0307的224个活跃意图日中195日半仓、29日全仓，更直观的表述是“多数时间半仓，振幅较低时加仓”。仓位分母包含所有434日的空仓日，因此低于活跃目标。实际仓位接近但并不完全相同；有限改善不是靠更低累计费用获得。

集中性按实际闭合周期的全部买卖成交现金流扣费求和，包含分次买入和部分卖出，逐周期核对买卖份额平衡。分母仅为正盈利闭合周期之和，不包括尾仓，也不是全账户收益比例或独立交易样本。没有用原先“单次买入/卖出”算法近似多档位账本，也未冒称平台支持分阶段损益归因。

## 证据、自检与限制

合成信号检查覆盖动态档位、0目标不重置年龄、反向、全仓意图一致、前缀及未来扰动不改变过去、非法参数拒绝；串行与两路并行预检查五账本和结果哈希一致。输入连续性检查确认市场和执行数据各508行重叠OHLCVA精确一致，97账户引用与输入绑定身份、现金流和信号年龄复算通过；全部新登记候选加载及内容哈希一致。详见[策略检查](others/strategy_checks.json)、[输入连续性](others/input_continuity.json)、[收尾检查](others/final_checks.json)、[登记清单](others/registrations.json)。未进行仓库级全量回归。

当前研究继续使用用户确认的DAILY_RANGE_V3日范围成交、不考虑成交量；DFLS现有容差及账户诊断能力边界保持既定设计。EX003的日线/30分钟价差和成交量观察保留为模型解释，不新增研究硬门，不自动取消中心达标资格；本轮没有新做分钟账户或成交容量检验。

约定17:30形成决策，当前公共运行默认20:31；继承EX003 pilot在绑定历史输入下的时钟等价证据，其范围仅为该pilot。新策略的过去不受未来扰动检查不认证历史17:30真实数据发布时间或修订链，后者仍未认证，未声称已解决。

全部数据均为已见开发池，两个入场锚、代表选择和后续扩边使用已见信息；没有独立封存样本。未作统计显著性或未来成功概率判断。参数32点联合扰动、费用翻倍压力、正式排序及冻结检验均未执行，阶段三中心通过不能代替稳健性、冻结或PTE批准。实现能够表达多档位，不等于任意多档位策略均已验证。

## 候选交接及下一步

本轮登记全部73个达标配置及另外4个未达标收益回撤前沿，共77个；保留原40个不可变候选，累计交付117个身份，其中原25加新73共98个中心达标身份交接阶段四。行为相似或重复者不当作额外独立证据；正式阶段四应先核对经济路径及机制，明确去重和代表覆盖，再按已确认标准验证。其他前沿仅为有效负面证据，不能混入中心达标集合。

建议下一步进入阶段四，覆盖原周期全仓、新权益全仓、恒定减仓以及C0307一类振幅低回撤方向，在一致政策下完成32联合扰动、费用压力与比较。具体中心及类别/常数参数扰动适用方案由RSCH事前形成，不现在宣布选型。阶段四须取得用户明确批准；冻结、PTE和生产另行授权。

原[EX003阶段交付](../../deliveries/CANDIDATES/1/report.md)及所有历史原件保持不变。本实验报告、97个搜索账户、预检查账户、源码、各版设计、Optuna记录、分析、登记和关键反证显式关联正式EvidenceRef；CANDIDATES/2承接CANDIDATES/1。实际发布与FULL校验状态以平台回执及收尾交接为准。

数据、运行、EvidenceRef、候选源码快照和交付资产分别由批次assets/data、assets/runs、assets/evidence、assets/candidates、assets/deliveries保存，通常不入Git，需独立保留。仅克隆仓库不能恢复完整正式研究资产。
'''
    (EROOT / 'report.md').write_text(report, encoding='utf-8', newline='\n')
    print(json.dumps({'report_written': True, 'registered': len(regs), 'handoff': a['passed'] + 25}))


if __name__ == '__main__':
    main()
