"""Research interpretation from completed accounts and independent attribution."""
from common import SRC, RUNS, read
from diagnose import rows


def pct(value):
    return f'{value * 100:.4f}%'


def main():
    all_rows = rows()
    selection = read(RUNS / 'selection.json')
    diagnostic = {row['candidate_id']: row for row in read(RUNS / 'diagnostics.json')['accounts']}
    costs = read(RUNS / 'cost_diagnostics.json')['rows']
    score = read(RUNS / 'score_attribution.json')
    controls = [r for r in all_rows if not r['parameters']['confirmation']['enabled'] and r['qualified']]
    parents = {r['parent']: r for r in controls}
    new_qualified = [r for r in all_rows if r['qualified'] and r['parameters']['confirmation']['enabled']]
    best = max(new_qualified, key=lambda r: r['negative_year_min_profit'])
    original = max(controls, key=lambda r: r['negative_year_min_profit'])
    fastest = max(new_qualified, key=lambda r: r['net_cagr'])
    improvements = selection['qualified_margin_improvements_over_parent']
    text = [
        '# S013：参考 S007-v1 的信息式买入确认分\n',
        '本轮身份为RSCH，属于已授权的阶段三继续研究。用户否定固定冷却日，要求考虑确认分控制买入，并明确允许参考S007-v1的策略表达。所有旧证据、候选和阶段四反证保留；本轮不进入阶段四或冻结。\n',
        f"完成{len(all_rows)}个真实、去重参数配置的TDR FULL账户评价；{len(new_qualified)}个开启确认分的技术身份通过原四门，另有{len(controls)}个关闭确认分的达标控制。关闭控制及相同经济路径的技术继任不计独立新发现。\n",
        f"新达标配置中盈利余量最大的是{best['candidate_id']}，2022/2023两年最小净收益{pct(best['negative_year_min_profit'])}；原十个中心中最厚的控制为{original['parent']}，对应{pct(original['negative_year_min_profit'])}。新配置最高净年化为{fastest['candidate_id']}的{pct(fastest['net_cagr'])}。\n",
        f"相对自身母体提高最小盈利余量且同时保持原四门的身份：{'、'.join(improvements) if improvements else '无'}。提高总年化与改善亏损年份盈利余量分别判断，不能相互代替。\n",
        '## 借用表达和买入职责\n',
        'S007-v1只提供表达结构：基础机会满足，同时确认分达到门槛，才允许买入；持仓退出由基础规则控制，确认分转弱不强制卖出。冻结版本源码与manifest哈希已核验，授权记录保存定义及源码快照。没有读取S007数据、实验结果、种子或研究绩效，也没有移植其权重和适用性结论。\n',
        '本轮使用已有20收益的滞后一期自相关ACF（相邻涨跌是否延续）、成交额/过去20日成交额均值、过去20日log成交量变化均值。每项以当时完整的过去N个观察归一化：\n',
        '`分数 = (小于当前值的个数 + 0.5 × 等于当前值的个数) / N - 0.5`\n',
        '单项或声明的组合采用固定等权；反向分数作为反证。组合等块权重为0.5×ACF+0.25×成交额+0.25×成交量，避免两项高度相关的量能信息占2/3。S007实际使用252日/min20及其他因子，本轮120/60/40日完整窗口与新输入是S013自己的研究设计。分数范围[-0.5,0.5]，不表示盈利概率。\n',
        '全部路线的固定冷却日为零。全买入门检查每次原机会；状态重入门仅在最终信号退出原因是`regime`时激活，持续到下一次信号买入，每个交易日重新评分，达门即可买入。并发退出按loss、trailing、range、time、regime优先顺序判定，不能把它泛化成所有发生状态变化的退出。退出上下文属于信号政策，未用实际成交日冒充信号日期。\n',
        '## 评价约定和已见信息\n',
        '510500.SH原开发池2020-01-02至2026-09-30，共1636交易日；初始现金100万元，HFQ研究单位100为一手，锚点2019-12-31=0.2803；逐日price_scale映射原始0.001价格跳动，T决策、T+1执行，限价买/市价卖，只做多、不加杠杆，每侧0.1%费用，同口径可执行NextOpenBuyHold(100)基准。以上研究单位不解释为PTE实盘份额或现金。\n',
        '四门保持：净年化≥1.5×同基准；每个自然年的最大回撤严格小于基准；闭合交易数×60/1636≥4（至少110笔）；负基准年份2022及2023的实际净收益严格为正。年度权益连续、上年末权益作锚，2026截至9月底。盈利余量、20/30bp、条件标签和参数邻域是诊断，不新增门槛。\n',
        '本轮重复使用已见的完整开发池；追加设计受已见结果影响，没有独立封存样本。Optuna用于前瞻固定队列和去重，不代表全局优化或统计验证。所有调用限制为S013现有离线资产，没有新外部获取。\n',
        '## 达标配置\n',
        '|身份|母体|净年化|闭合笔数|2022收益|2023收益|比母体最小余量变化（百分点）|\n|---|---|---:|---:|---:|---:|---:|'
    ]
    for row in new_qualified:
        parent = parents[row['parent']]
        delta = 100 * (row['negative_year_min_profit'] - parent['negative_year_min_profit'])
        text.append(f"|{row['candidate_id']}|{row['parent']}|{pct(row['net_cagr'])}|{row['closed_trades']}|{pct(row['annual']['2022']['return'])}|{pct(row['annual']['2023']['return'])}|{delta:+.4f}|")
    text += [
        f"\n最大余量配置{best['candidate_id']}的精确确认参数：`{best['parameters']['confirmation']}`；上下文：`{best['parameters'].get('context', '全买入门')}`。基础规则沿用{best['parent']}、两路线冷却均为0。\n",
        f"最高净年化配置{fastest['candidate_id']}的精确确认参数：`{fastest['parameters']['confirmation']}`；上下文：`{fastest['parameters'].get('context', '全买入门')}`。它与最大盈利余量配置分别列示，不能拼成一个策略的绩效。\n",
        '\nC2100与C2018是同一经济政策的第二源码技术复现；全部共同信号、决策、订单、成交、日账户、交易和基准逐项精确一致。新增`confirmation_exit_context`诊断列单独排除，并保留原严格比较失败记录与明确比较模式，不排除任何共同经济字段。其他不同参数但同账户表现的身份仍保留，不能把身份数当独立证据次数。\n',
        '## 逐年价格与费用归因\n',
        '每个成功账户独立重建数量、现金及每日权益：持仓价格变化，加当日买卖相对收盘价的收益，再扣真实费用。全部账户年度收益与回撤复算一致，误差界限在诊断证据中。以下贡献均除以各自当年期初权益，不用全期手续费减少冒充预测力。\n',
        '|配置|年份|价格收益贡献|费用贡献|净收益|原四门|\n|---|---|---:|---:|---:|---|'
    ]
    chosen = list(dict.fromkeys([parents[best['parent']]['candidate_id'], best['candidate_id'], fastest['candidate_id'],
                               max(all_rows, key=lambda r: r['negative_year_min_profit'])['candidate_id']]))
    for identifier in chosen:
        for year in ('2022', '2023'):
            v = diagnostic[identifier]['annual'][year]
            row = next(r for r in all_rows if r['candidate_id'] == identifier)
            qualification = '通过' if row['qualified'] else '未通过：' + ','.join(k for k, passed in row['gates'].items() if not passed)
            text.append(f"|{identifier}|{year}|{pct(v['price_contribution'])}|{pct(v['fee_contribution'])}|{pct(v['net_return'])}|{qualification}|")
    text += ['\n## 信息标签、反证和量纲\n',
             f"原控制真实信号入场标签{score['original_label_rows']}行，仅{score['unique_original_signal_dates']}个不同信号日期，十个中心和1/3/5日期限大量重叠。按年份和路线分层的固定期限T+1开盘后价格收益只是描述性信息，不扣费、不等于完整交易盈利；原政策被拒绝的交易盈利不能直接相加当成新政策贡献。实际新政策机会、拒绝、入场及退出上下文另行统计。\n",
             '成交额与成交量在原机会中的相关约0.65—0.67，不能称三个独立信息源。旧bear ACF开/关、单项/组合、同日反向、路线门、等块权重均保留完整配置记录和必要完整账户。\n',
             '原始成交量来自已有原价资产；每个日期校验HFQ Volume×HFQ Close/raw Close等于raw Volume，以及成交额保持不变。原价预热只有60日，因此RAW仅采用完整40日分位配对，不以RAW40与ADJUSTED120的差异归因于复权量纲。\n',
             '|同40日配对：ADJUSTED/RAW|净年化（%）|闭合笔数|最小盈利余量（%）|\n|---|---:|---:|---:|']
    raw_rows = [r for r in all_rows if r['parameters'].get('context', {}).get('volume_basis') == 'RAW']
    for row in raw_rows:
        p = row['parameters']
        pairs = [r for r in all_rows if r['parent'] == row['parent']
                        and r['parameters']['confirmation'] == p['confirmation']
                        and r['parameters'].get('context') == {**p['context'], 'volume_basis': 'ADJUSTED'}]
        if not pairs:
            continue
        adjusted = pairs[0]
        text.append(f"|{adjusted['candidate_id']}/{row['candidate_id']}|{adjusted['net_cagr']*100:.4f}/{row['net_cagr']*100:.4f}|{adjusted['closed_trades']}/{row['closed_trades']}|{adjusted['negative_year_min_profit']*100:.4f}/{row['negative_year_min_profit']*100:.4f}|")
    text += ['\n## 费用压力（代表性覆盖）\n',
             '按实验前发布的压力计划，选择开启评分达标的最大余量及最高年化、原控制最大余量、上下文代表及非达标余量/缺口对照。仅下列账户做每侧20/30bp压力，不宣称所有新候选已做压力检验；压力不得改变10bp的资格。每次压力请求中的10bp基准完整账本精确复现原结果。\n',
             '|身份|每侧费用|净年化|闭合笔数|2022收益|2023收益|原四门|\n|---|---:|---:|---:|---:|---:|---|']
    for item in costs:
        for scenario in ('baseline', 'stress20', 'stress30'):
            row = item['scenarios'][scenario]
            text.append(f"|{item['candidate_id']}|{dict(baseline=10,stress20=20,stress30=30)[scenario]}bp|{pct(row['net_cagr'])}|{row['closed_trades']}|{pct(row['annual']['2022']['return'])}|{pct(row['annual']['2023']['return'])}|{'通过' if row['qualified'] else '未通过'}|")
    text += ['\n## 技术验证和保存范围\n',
             '合成验证覆盖分位并列值、参数异常、因果前缀/未来修改不变、关闭确认和无约束门的原历史精确等价、当日门槛相等即通过、下一日立即重评、弱确认不退出；上下文与RAW配对再做对应检查。十个原中心真实账户精确复现并验证单进程/多进程一致。\n',
             '新增原价预热引用只从已有S013资产截取到要求的截止日：首次准备因多出截止日之外一行被契约拒绝，修正为严格日期子集后准备PASS，并保留来源/目标引用及逐行等价证明。禁止外部获取的提前探针未命中已有准备键，没有发生外部取数。策略源码、计划、实际账户、归因、费用和数据引用正式发布，原31个资产及28个准备记录逐行不变。\n',
             '已知2020-12-01分钟Low差异单独检查，所有成功账户的潜在受影响订单为零；四处分钟High偏差不参与可信日特征及当前限价买/市价卖成交。此结论不等于未知数据误差不存在。\n',
             '本轮执行聚焦检查及正式交付FULL完整性验证，不做仓库全量回归。FULL PASS证明契约、身份及关联证据可核验，不证明未来收益或独立样本有效性。\n',
             '## 研究判断和下一步\n']
    best_parent = parents[best['parent']]['candidate_id']
    before = diagnostic[best_parent]['annual']['2023']
    after = diagnostic[best['candidate_id']]['annual']['2023']
    text.append(f"最佳配置2023年的价格收益贡献从{pct(before['price_contribution'])}变为{pct(after['price_contribution'])}，费用贡献从{pct(before['fee_contribution'])}变为{pct(after['fee_contribution'])}。改善包含真实账户价格路径收益增加和费用贡献下降，不仅是减少手续费；这项账本归因仍不是分数的独立预测效力证明。\n")
    pressure = next(item for item in costs if item['candidate_id'] == best['candidate_id'])
    medium = pressure['scenarios']['stress20']
    text.append(f"该最佳配置在20bp下净年化{pct(medium['net_cagr'])}，最小负基准年净收益{pct(min(medium['annual'][year]['return'] for year in medium['negative_buyhold_years']))}，原四门{'通过' if medium['qualified'] else '未同时通过'}。费用压力仍限制收益，不能把10bp改善直接解释为足以冻结。\n")
    if best['negative_year_min_profit'] <= original['negative_year_min_profit']:
        text.append('当前确认分确能改变买入路径，但尚未同时提高原中心最佳盈利余量并保持四门。严格筛选的改善常伴随交易频率不足；分数结构更合理不代表盈利问题已解决。已测试本轮声明的状态、量能、方向、归一化和应用范围，仍不能推断所有已有组件均无法解决问题。\n')
    else:
        text.append('存在同时通过四门并超过原中心最佳盈利余量的配置。已有组件通过信息式重入控制能够改善本开发池的盈利余量，因此不能推断已有组件无法解决这一问题；结论限于已见开发池，不能直接作为冻结依据。\n')
    text.append('本轮停止依据是：已定位并复核信息门的适用上下文、改善来源、邻域及费用取舍，完成必要反证；不是固定试验次数或首个达标。仍未穷举所有组件和参数，尚未验证样本外效力与长期费用稳健性。建议维持阶段三，围绕确认信息的互补性和费用敏感性继续研究；不要引入固定等待日。阶段变更、候选选择及冻结分别取得用户明确批准。\n')
    path = SRC.parent / 'others/report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(text) + '\n', encoding='utf-8', newline='\n')
    print({'report': path.relative_to(SRC.parents[4]).as_posix(), 'best_margin': best['candidate_id']}, flush=True)


if __name__ == '__main__':
    main()
