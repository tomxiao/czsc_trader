"""Stage-three interpretation from actual accounts and gate attribution."""
from common import SRC, RUNS, read
from diagnose import rows


def pct(value):
    return f'{100 * value:.4f}%'


def main():
    records = rows()
    selection = read(RUNS / 'selection.json')
    diagnostics = {row['candidate_id']: row for row in read(RUNS / 'diagnostics.json')['accounts']}
    paths = {row['candidate_id']: row for row in read(RUNS / 'path_attribution.json')['accounts']}
    costs = read(RUNS / 'cost_diagnostics.json')['rows']
    behavior = read(RUNS / 'behavior_groups.json')
    control = next(row for row in records if row['candidate_id'] == 'C3000')
    compound_best = next(row for row in records if row['candidate_id'] == 'C3107')
    qualified = [row for row in records if row['candidate_id'] in selection['qualified']]
    best = max(qualified, key=lambda row: row['net_cagr'])
    thickest = max(qualified, key=lambda row: row['negative_year_min_profit'])
    qualified_ids = set(selection['qualified'])
    new_groups = [group for group in behavior['groups']
                  if any(member['candidate_id'] in qualified_ids for member in group['members'])]
    repeated_control_paths = sum(group['contains_control'] for group in new_groups)
    text = [
        '# S013：互补买入确认与费用归因\n',
        '身份为RSCH，继续已批准的阶段三。沿用研究分支、S013原开发池与原四项验收条件；全部固定冷却日为零。没有进入阶段四、冻结、生产、合并或推送。S007-v1仅作为“基础机会 AND 确认分达门才买入”的表达来源，沿用上一修订已核验的定义，不读取其研究数据或结果。\n',
        f"完成{len(records)}个去重配置的TDR FULL完整账户评价，其中2个关闭新增确认的原策略对照精确复现C2308/C2132；价格幅度0档控制精确复现C3107。新增达标技术身份{len(qualified)}个；相同实际经济路径按独立材料分组，不能把身份数当独立发现次数。所有达标新身份交接，3个等价控制仅作证据，不重复登记。\n",
        f"新达标配置最高净年化为{best['candidate_id']}：{pct(best['net_cagr'])}、{best['closed_trades']}笔闭合交易、2022/2023最小净收益{pct(best['negative_year_min_profit'])}。C2308对照为{pct(control['net_cagr'])}、111笔、最小净收益{pct(control['negative_year_min_profit'])}。收益提高与盈利余量增厚必须分别判断。\n",
        f"新增达标配置中最小负基准年净收益最大的是{thickest['candidate_id']}：{pct(thickest['negative_year_min_profit'])}。相对各自原策略同时通过四门且增厚此余量的身份：{'、'.join(selection['qualified_margin_improvements_over_parent']) or '无'}。\n",
        '## 研究问题、原约定与已见信息\n',
        '原成交归因已核验6个上轮代表配置、每侧10/20/30bp共18个真实账户。C2308共111笔闭合交易中，57笔毛收益不超过40bp，45笔毛收益非正；2023年5笔bull入场且regime退出的交易平均毛收益约-0.8121%、平均持有2.2个交易日。它们提示短持仓价格收益不足，不能直接证明某个过滤条件具有因果预测力。\n',
        '开发池为510500.SH，2020-01-02至2026-09-30，共1636个交易日，使用既有预热。初始现金100万元；100个HFQ研究单位一手；2019-12-31复权因子锚0.2803；逐日price_scale映射原价0.001跳动；T日收盘已知信息、T+1限价买/市价卖，只做多、不加杠杆，每侧10bp，同口径可执行NextOpenBuyHold(100)。信号HFQ价格与锚定研究执行价格量纲不同，经济归因使用实际fill价格及数量，不用信号Close直接代替成交价。\n',
        '四门不变：净年化≥1.5×同口径买持基准；每个自然年最大回撤严格小于基准；闭合笔数×60/1636≥4（至少110笔）；2022/2023负基准年实际净收益严格为正。年度权益连续，上年末权益为当年锚，2026截至9月底。费用压力、盈利余量、集中度、邻域、样本量均为诊断，不新增资格门。\n',
        '完整开发池已在此前反复使用。初始计划在评价前发布；边界计划基于已见初始结果追加并在新评价前发布，选择偏差明确存在，没有独立封存验证。Optuna固定队列、主进程研究、4个FULL子进程、每进程原生线程1、请求workers1、种子13。没有外部获取或新增依赖。\n',
        '## 确认分职责和对照\n',
        '保留C2308的状态重入成交额门：最近一次信号退出原因为regime时，成交额分≥-0.175才允许重入。额外门只用于声明路线的买入机会，使用已有20日收益一期自相关、成交额/过去20日均值、过去20日log成交量变化均值，每项完整120日当前分位居中。等块组合为0.5×自相关分+0.25×成交额分+0.25×成交量分，价格状态与量能各占一半；acf_volume两项固定等权。分数[-0.5,0.5]不表示盈利概率。\n',
        '新增门和原门按AND联合。“普通入场”包括首次入场、上次信号退出非regime的机会；regime上下文在拒绝的空仓期间持续，到信号entry才清空。这是内部信号状态，不是实际成交退出记忆。所有入场模式也对regime重入施加新增门。弱分在持仓期间不触发退出；原退出优先级和活动路线锁定保持，只有计划明确列出的持有期对照改变max_hold。\n',
        '初始22组包含两原策略控制、6个原始自相关硬门、8个组合分应用范围/阈值对照、2个单项分以及4个持有期与评分组合。随后16组检验all分-0.45至-0.25的邻域、acf_volume宽松边界及2个独立持有期对照。根据这38组的实际归因，再追加4组价格幅度买入确认；每组实际执行前发布协议，不存在冷却天数等待条件。\n',
        '## 全部配置与原四门\n',
        '|身份|母体|净年化|闭合笔数|2022净收益|2023净收益|四门|研究配置|\n|---|---|---:|---:|---:|---:|---|---|'
    ]
    for row in records:
        outcome = '通过' if row['qualified'] else '未通过：' + '、'.join(k for k, value in row['gates'].items() if not value)
        text.append(f"|{row['candidate_id']}|{row['parent']}|{pct(row['net_cagr'])}|{row['closed_trades']}|{pct(row['annual']['2022']['return'])}|{pct(row['annual']['2023']['return'])}|{outcome}|{row['label']}|")
    chosen = list(dict.fromkeys(['C3000', 'C3001', best['candidate_id'], thickest['candidate_id'], 'C3107', 'C3006', 'C3019', 'C3021', 'C3114', 'C3115', 'C3201', 'C3202', 'C3203']))
    text += ['\n## 价格收益与真实费用\n',
        '每个成功账户逐日复算数量、现金、持仓价格变化、成交相对收盘收益和真实费用；年度价格与费用贡献均除以各自当年期初权益。尾仓按最终实际收盘标记，闭合与尾仓收益之和核对完整期末权益。交易按入场/退出年份和路线分组仅作描述，跨年周期不得替代连续自然年账户收益。\n',
        '|身份|年份|价格贡献|费用贡献|净收益|\n|---|---|---:|---:|---:|']
    for identifier in chosen:
        for year in ('2022', '2023'):
            value = diagnostics[identifier]['annual'][year]
            text.append(f"|{identifier}|{year}|{pct(value['price_contribution'])}|{pct(value['fee_contribution'])}|{pct(value['net_return'])}|")
    before, after = diagnostics['C3000']['annual']['2023'], diagnostics[best['candidate_id']]['annual']['2023']
    text.append(f"\n最高年化新配置2023年的价格贡献从{pct(before['price_contribution'])}变为{pct(after['price_contribution'])}，费用贡献从{pct(before['fee_contribution'])}变为{pct(after['fee_contribution'])}。这组差异用于解释实际账户取舍，不把被拒绝旧交易的盈利直接相加当新政策收益。\n")
    text += ['\n最高年化配置相对C2308的收益变化主要发生在其它年份：\n',
        '|年份|连续账户净收益变化（百分点）|价格贡献变化（百分点）|费用贡献变化（百分点）|\n|---|---:|---:|---:|']
    for year in map(str, range(2020, 2027)):
        old, new = diagnostics['C3000']['annual'][year], diagnostics[best['candidate_id']]['annual'][year]
        text.append(f"|{year}|{100*(new['net_return']-old['net_return']):+.5f}|{100*(new['price_contribution']-old['price_contribution']):+.5f}|{100*(new['fee_contribution']-old['fee_contribution']):+.5f}|")
    text += ['\n## 买入门实际作用与经济路径\n',
        '所有成功配置的机会、原门/附加门拒绝、信号entry、执行BUY决策、BUY订单和实际BUY成交分别计数。确认字段在持仓日也计算；拒绝统计限定confirmation_opportunity和confirmation_rejected，避免把持仓弱分算成过滤交易。\n',
        '|身份|基础机会|原门未通过|新增门未通过|两门均未通过|联合拒绝|信号入场|实际买入成交|\n|---|---:|---:|---:|---:|---:|---:|---:|']
    for identifier in chosen:
        v = paths[identifier]['decisions']['totals']
        text.append(f"|{identifier}|{v['base_opportunities']}|{v['base_gate_failed_opportunities']}|{v['extra_gate_failed_opportunities']}|{v['both_gates_failed_opportunities']}|{v['confirmation_rejected_signals']}|{v['entry_signals']}|{v['actual_buy_fills']}|")
    text.append('\n严格经济字段投影、ID关联正规化及相同路径成员见behavior_groups正式材料；完整账本与诊断列保留，分组不等于完整策略政策相同。\n')
    text.append(f"经济路径分组材料状态：{behavior['status']}，{len(records)}个配置共{behavior['economic_path_groups']}条严格投影路径；{len(qualified)}个新达标技术身份对应{len(new_groups)}条路径，其中{repeated_control_paths}条与原控制相同。源码、参数或分值不同但经济路径相同的技术身份不形成独立预测证据。\n")
    weak_groups = [group for group in paths[compound_best['candidate_id']]['decisions']['signal_year_route_exit_context_groups']
                   if group['signal_year'] == 2023 and group['regime'] == 'bull']
    applied = sum(group['extra_gate_applied_opportunities'] for group in weak_groups)
    rejected = sum(group['extra_gate_failed_opportunities'] for group in weak_groups)
    old_weak = [cycle for cycle in paths['C3000']['path']['cycles'] if cycle['status'] == 'CLOSED'
                and cycle['exit_fill_year'] == 2023 and cycle['entry_route'] == 'bull' and cycle['exit_reason'] == 'regime']
    new_weak = [cycle for cycle in paths[compound_best['candidate_id']]['path']['cycles'] if cycle['status'] == 'CLOSED'
                and cycle['exit_fill_year'] == 2023 and cycle['entry_route'] == 'bull' and cycle['exit_reason'] == 'regime']
    comparable = ('entry_fill_time', 'exit_fill_time')
    assert [[cycle[field] for field in comparable] for cycle in old_weak] == [[cycle[field] for field in comparable] for cycle in new_weak]
    for old, new in zip(old_weak, new_weak, strict=True):
        assert [[fill['fill_time'], fill['side'], fill['price']] for fill in old['fills']] == [[fill['fill_time'], fill['side'], fill['price']] for fill in new['fills']]
        assert abs(old['gross_return'] - new['gross_return']) < 1e-12
    text.append(f"互补分代表C3107的2023年bull路线只有{applied}个原机会实际应用新增门，拒绝{rejected}个；原{len(old_weak)}笔bull入场且regime退出的交易成交起止日期及价格相同，手数随继承资金变化，毛收益比例差小于1e-12。它的总年化改善主要在2024/2025年，2023问题交易没有被改变，不能解释为新增门已识别这些亏损。\n")
    text += ['\n## 价格状态幅度确认：针对归因的受限后续\n',
        '将已知的20日价格状态幅度定义为confirmation_margin=momentum20-0.005，只用于所有bull买入（含状态重入）。现有组件与状态判断使用同一20日价格变化，因此直接使用bull.momentum_min=0.005+门槛实现，保留互补门和全部退出。0、0.0025、0.005、0.01四档分别对应C3200—C3203；0档是严格等价控制。该分有价格变化的量纲，不是分位或盈利概率，也没有等待天数。\n',
        '设计依据来自已见2023交易：两个亏损入场的边界余量约0.000797和0.002371，一次盈利重入约0.011786；只是待检验线索，不能预判完整账户、其它年份或交易频率。方案保留已见信息和选择偏差说明，不新增经济验收门。\n',
        '|身份|价格余量阈值|净年化|闭合笔数|2022净收益|2023净收益|四门|\n|---|---:|---:|---:|---:|---:|---|']
    for row in records:
        if row['search'] == 'cost_confirmation_price_margin':
            failed = '通过' if row['qualified'] else '未通过：' + '、'.join(key for key, value in row['gates'].items() if not value)
            text.append(f"|{row['candidate_id']}|{row['parameters']['bull']['momentum_min']-.005:.4f}|{pct(row['net_cagr'])}|{row['closed_trades']}|{pct(row['annual']['2022']['return'])}|{pct(row['annual']['2023']['return'])}|{failed}|")
    text += ['\n## 每侧20/30bp费用压力\n',
        '压力计划在压力执行前发布，覆盖两原策略控制、新达标最大年化/余量代表、新最大余量及最小四门缺口对照；不是全体候选覆盖。每次10bp分支的五类账本精确复现原账户。20/30bp会改变实际现金、手数和可执行买持基准，以下“四门场景诊断”不改变10bp候选资格。\n',
        '|身份|每侧费用|净年化|闭合笔数|2022净收益|2023净收益|四门场景诊断|\n|---|---:|---:|---:|---:|---:|---|']
    for item in costs:
        for scenario, bp in (('baseline', 10), ('stress20', 20), ('stress30', 30)):
            row = item['scenarios'][scenario]
            text.append(f"|{item['candidate_id']}|{bp}bp|{pct(row['net_cagr'])}|{row['closed_trades']}|{pct(row['annual']['2022']['return'])}|{pct(row['annual']['2023']['return'])}|{'同时满足' if row['qualified'] else '未同时满足'}|")
    text += ['\n## 技术验证、局限与研究判断\n',
        '关闭新增门的两原策略实际账户完整等价，价格余量0档与C3107全部信号/五账本/基准严格等价；8组真实特征的因果前缀/未来变动不变检查通过；10项确定性分支检查覆盖等阈值、普通拒绝、regime豁免、原门独立拒绝、AND、弱分不退出、退出上下文、路由、权重和原退出AST一致。已发布源码和计划哈希核验通过。每个成功账户现金、数量、逐日归因及年度收益/回撤复算通过。\n',
        '已知2020-12-01分钟Low差异的潜在受影响订单为零；已有四处分钟High偏差不参与当前可信日特征及限价买/市价卖成交。原31个数据资产及28个准备记录逐行保持。不把已知问题排查解释为不存在未知误差。执行Ruff、聚焦验证及交付FULL完整性校验，不做仓库全量回归；FULL PASS只证明契约、身份和证据可核验。\n',
        '原C2308在2024-09-25至2024-10-08的一笔交易毛收益约36.66%，占所有盈利交易现金盈利约22.91%。新配置的实际大盈利集中性及短持仓分组全部保留；集中度是诊断。反复使用已见开发池和少量大盈利交易，限制未来有效性判断。\n',
        '既有组件通过合理确认表达可以提高净年化，之前成交额状态重入门已经增厚过盈利余量，不能断言“已有组件无法解决”。本轮互补门提高年化但未明显增厚较弱年份余量；原始自相关硬门大幅损失频率；缩短持有期虽可能增加频率，却牺牲价格收益。价格幅度确认产生新买入路径，但闭合笔数仅100—104，2022/2023最小净收益0.56%—1.30%，没有接近同时改善原配置的余量和四门。上述取舍不是所有组件或权重的穷尽结论。\n',
        '本轮宽松边界与邻域已有实际账户，新增门可保留频率，因此没有按条件启动价格状态幅度迟滞路线。相邻阈值若同路径只说明本开发池局部离散平台，不证明稳定性。未做新权重全面搜索、其它归一化窗口或独立样本验证；这些方向须根据机制证据决定，不能以固定次数宣称研究充分。\n',
        '本轮沿绝对确认水平、应用范围、独立持有期和价格边界幅度完成必要对照；宽松门局部已呈相同路径平台，强门和价格幅度的收益取舍均受频率约束，没有当前联合改善方向的边界线索。因此收口本轮，不以42组数量宣称研究充分。剩余更有针对性的方向是确认信息在入场前后的变化：先以原策略机会验证相对变化是否具有增量，再决定是否构建新完整策略。\n',
        '阶段三本轮交付目标完成。建议继续阶段三检验成交额与价格状态的变化信息；是否继续此方向或进入阶段四由用户决定。\n'
    ]
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(text).rstrip() + '\n', encoding='utf-8', newline='\n')
    print({'report': path.relative_to(SRC.parents[4]).as_posix()}, flush=True)


if __name__ == '__main__':
    main()
