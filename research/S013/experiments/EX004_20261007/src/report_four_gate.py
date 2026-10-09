"""RSCH-authored interpretation and tables for the third candidate revision."""
LABELS = {'return': '整体收益', 'annual_drawdown': '逐年回撤',
          'frequency': '平均频率', 'negative_buyhold_year_profit': '负基准年份盈利'}


def build_report(analysis, rows, refs, account_refs, stopping, quality):
    by_id = {r['candidate_id']: r for r in rows if r['status'] == 'SUCCEEDED'}
    qualified = [by_id[c] for c in analysis['qualified_ids']]
    center = by_id['C0440']
    bh = center['buyhold_annual']
    lines = ['# S013阶段三修订三：动量状态分工与亏损年份盈利', '',
             f"本次继续阶段三后，累计{analysis['successful_configurations']}个不同配置完成完整账户评价，其中本次新增{analysis['new_successful_configurations']}个。全部四项目标同时达标{len(qualified)}个；全部保留并交接。",
             '', '## 目标与评价口径', '',
             '沿用MANDATE/4：开发池整体净年化≥10.8342%（1.5×同窗BuyHold的7.2228%）；逐自然年最大回撤幅度严格更小；平均每60交易日闭合交易数≥4（1636日至少110笔）；BuyHold年度实际净收益<0时，策略同年实际净收益严格>0。未新增经济否决项。', '',
             '自然年收益从初始资金或上一年末权益计算，扣费后现金和持仓跨年连续，2026年只到9月30日；全年展示实际收益，整体年化仍用252/1636折算。基准亏损年份为2022、2023，判断使用未舍入数值。', '',
             '510500.SH，2020-01-01至2026-09-30，首个交易日2020-01-02；100万元、100个研究单位整手、每侧10bp、只做多、不加杠杆。HFQ_RESEARCH在2019-12-31以0.2803因子固定归一化，策略和基准共用价格、资金、费用与日历。收益不直接代表真实ETF份额账户收益；PTE/SRT执行仍输出未复权价格。', '',
             '## 机制与竞争解释', '',
             '旧高收益C0385在2022年价格损失和费用均为负面贡献；2023年微弱价格收益被费用吞没。原相关性过滤路线C0315两年盈利，但只有56笔闭合交易。第一组34个单路线过滤/持有期对照未同时达标，说明单纯强化过滤付出了整体收益或频率代价。', '',
             '新策略使用T日已知的过去20日动量选择入场路线：动量≥阈值走较宽松的180日区间路线，否则走120日区间且要求20日收益一阶相关性≥门槛的路线。入场时锁定路线；区间到达退出线、持有期限或启用的损失控制触发退出。可选在动量状态改变时退出。没有读取未来年度BuyHold盈利标签或按年份硬编码路由。', '',
             '三组相同路线FULL控制通过：原非ID字段、逐日账户、订单、成交与交易精确一致，新增状态诊断单列；独立候选和结果哈希均保留。此项验证组合实现，不宣称两个不同特征集合在SE全证据中等价。', '',
             'C0440与C0439只有“状态改变时退出”不同：2022收益从-13.8044%变为+7.9616%，2024从+42.6235%变为+58.7042%；2023却从+0.8199%降至+0.3029%，2021也下降。状态退出在观察到的账户中改变入场/退出和后续仓位路径，不能分离成一个独立市场因子的收益；改善并非逐年一致。详细每日价格与费用归因见关联材料。', '',
             '两次准备的整体身份不同，剔除策略身份后的输入计划相同；已通过公共DFLS fetch验证calendar/daily/execution逐值相等，daily含180条2019年预热记录。执行输入的四项身份也一致。归因支持同一已见开发池内完整退出政策的影响，不推断未见环境中的因果效应。', '',
             'C0440在2023年净利润仅4253.89元：1月盈利60542.65元，其余月份合计亏损56288.76元；算术剔除最大盈利周期后年度收益会变为-2.1874%。2024最大盈利周期占该年净利润62.8270%，前三周期占88.7875%。这些是收益依赖诊断，未重跑“跳过该交易”的反事实账户，也未新增经济淘汰门。', '',
             '## 全部达标配置', '',
             '| 候选 | 净年化 | 闭合交易 | 每60日 | 2022收益 | 2023收益 | 最小逐年回撤优势 | 完整账户 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in sorted(qualified, key=lambda r: r['candidate_id']):
        c = row['candidate_id']
        lines.append(f"| {c} | {row['net_cagr']:.4%} | {row['closed_trades']} | {row['frequency60']:.4f} | {row['annual']['2022']['return']:.4%} | {row['annual']['2023']['return']:.4%} | {row['min_dd_margin']*100:.4f}个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/{account_refs[c].path}) |")
    lines += ['', '下面列出完整参数相对C0440的变化，所有正式身份包含源码和依赖；没有以相同表现合并不同配置。', '',
              'C0440：bull窗口180、入场0.675、退出0.95、最长信号持有8日、无相关性/动量/止损过滤；bear窗口120、入场0.85、退出0.99、最长4日、ACF门槛0.1；动量窗口20、阈值0、状态改变退出；共同限价溢价1%、冷却0。', '',
              '| 候选 | 相对C0440参数变化 |', '| --- | --- |']
    for r in sorted(qualified, key=lambda r: r['candidate_id']):
        changes = []
        for key, value in r['parameters'].items():
            if isinstance(value, dict):
                changes += [f'{key}.{k}={v}' for k, v in value.items() if v != center['parameters'][key][k]]
            elif value != center['parameters'][key]:
                changes.append(f'{key}={value}')
        lines.append(f"| {r['candidate_id']} | {'；'.join(changes) or '中心配置'} |")
    lines += ['', '## 自然年策略与基准比较', '',
              'C0440作为机制对照中心展示；这不是阶段四正式排序或选型。', '',
              '| 年份 | BuyHold净收益 | C0440净收益 | BuyHold回撤 | C0440回撤 |',
              '| --- | ---: | ---: | ---: | ---: |']
    for y in center['annual']:
        own, base = center['annual'][y], bh[y]
        lines.append(f"| {y}{'（至9月30日）' if y == '2026' else ''} | {base['return']:.4%} | {own['return']:.4%} | {base['max_drawdown_magnitude']:.4%} | {own['max_drawdown_magnitude']:.4%} |")
    lines += ['', '## 前沿与必要反证', '',
              analysis['frontier_definition'], '',
              '| 配置 | 净年化 | 闭合交易 | 2022收益 | 2023收益 | 未通过要求 |',
              '| --- | ---: | ---: | ---: | ---: | --- |']
    for c in analysis['retained_ids']:
        r = by_id[c]
        failed = '、'.join(LABELS[k] for k, v in r['gates'].items() if not v) or '无'
        lines.append(f"| {c} | {r['net_cagr']:.4%} | {r['closed_trades']} | {r['annual']['2022']['return']:.4%} | {r['annual']['2023']['return']:.4%} | {failed} |")
    lines += ['', '## 搜索与选择历史', '',
              '| 搜索组 | 实际评价尝试 | 成功不同配置 | 四门达标 |', '| --- | ---: | ---: | ---: |']
    for name, group in analysis['groups'].items():
        lines.append(f"| {name} | {group['attempts']} | {group['successful_configurations']} | {group['qualified']} |")
    lines += ['', '旧378个成功配置重新套用四项字面条件，16次UNKNOWN原状态保持。固定对照和扩边在执行前发布，以Optuna固定队列及参数哈希去重；种子13，最多4个spawn进程、每个原生线程1、单请求workers=1、每个父进程只评价一批。重复点复用同内容同口径结果。不同源码的相同路线账户仍独立评价。', '',
              '本次根据已见亏损归因选择动量分工，根据初次达标点设计相邻对照、持有期扩边和交互。全部开发池持续用于方法和参数选择，没有独立封存验证样本。年度约束检查不等于样本外检验；达标数量不能解释为独立发现数量或未来成功概率。', '',
              '## 数据、执行及未解决问题', '',
              f"沿用本批次数据与准备引用。已声明的五处残余偏差位于30分钟聚合相对可信独立日线的High/Low，日线组件来源为ETF_OHLCV daily；四处分钟High未进入日线区间特征或LIMIT买入/MARKET卖出撮合。对当前{quality['successful_configurations']}个成功配置逐单复核2020-12-01分钟Low偏差，发现可能改变已发生订单成交金额的订单{quality['potential_economic_change_count']}项；仅覆盖已声明偏差及真实订单，没有重建未知分钟修复路径或供应商历史版本。", '',
              '供应商复权因子历史发布时间、修订和真实馈送延迟未重建。最长持有期、止损及冷却仍按信号目标序列，不按限价实际成交日期重置。部分配置在基准上涨年份跑输；C0440在2026前九个月为-4.7535%，而基准为+0.9951%。这些观察保留在报告中，不擅自增加硬门。', '',
              '本次未修改平台或新增数据/依赖。未执行仓库全量回归；阶段四五项标准自检、正式排序、技术冻结和真实ETF份额PTE评价尚未开展。', '',
              '## 收口依据与下一步', '', stopping.strip(), '', '## 关联证据', '']
    for name, ref in refs.items():
        lines.append(f'- [{name}](../../../assets/deliveries/CANDIDATES/3/{ref.path})')
    return '\n'.join(lines) + '\n'
