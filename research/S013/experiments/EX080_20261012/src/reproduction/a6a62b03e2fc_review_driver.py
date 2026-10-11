"""Root scientific review and nonoverlap proxy attribution; no new account."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.research_tools import build_assessment_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution_v3 as d


def run():
    exp, path, plan = d.stage()
    ctx = d.common().context(1)
    refs = d.read(path / 'protocols/audit_references.json')
    audit = d.read(d.public(refs['verification.json']))
    if audit['status'] != 'PASS' or audit['new_accounts'] != 1 or audit['technical_financial_repeats'] != 0:
        raise ValueError('One authenticated actual account required')
    centre, base = audit['economics'], audit['baseline_economics']
    c = d.common()
    bound, result = c.cache_read(d.OUT / 'account.pkl.gz')
    if d.digest(d.OUT / 'account.pkl.gz') != d.read(d.OUT / 'execution.json')['cache_sha256']:
        raise ValueError('Native cache differs')
    preprefs = d.read(path / 'protocols/prepare_references_v2.json')
    policy = d.frame(preprefs['policy.csv'])
    prices = pd.DataFrame(bound.execution_data.execution_daily, copy=False).set_index('dt')
    prices.index = pd.to_datetime(prices.index).as_unit('ns')
    decisions = result.runs[0].execution.decisions
    orders, fills = result.runs[0].execution.orders, result.runs[0].execution.fills
    (baseline_bound, baseline_result), _ = d.native(c)
    first_execution = pd.Timestamp(decisions.loc[pd.to_numeric(decisions.net_forecast).notna(), 'valid_session'].iloc[0])

    def comparable_slice(pair):
        account = pair[1].runs[0].execution.account_daily
        ix = np.flatnonzero(pd.to_datetime(account.date).ge(first_execution).to_numpy())
        opening = float(account.equity.iloc[ix[0] - 1])
        wealth = np.r_[opening, account.equity.iloc[ix].to_numpy(float)]
        fact = build_assessment_evidence(*pair)[0]
        count = sum(x.exit_session >= first_execution.date().isoformat() for x in fact.closed_cycles)
        bh_open = fact.benchmark_equity[ix[0] - 1]
        benchmark = np.r_[bh_open, np.asarray(fact.benchmark_equity)[ix]]
        return {'start': first_execution.date().isoformat(), 'end': '2026-09-30', 'sessions': len(ix),
                'opening_equity': opening, 'opening_quantity': int(account.quantity.iloc[ix[0] - 1]),
                'net_cagr': float((wealth[-1] / opening) ** (252 / len(ix)) - 1),
                'drawdown': float(np.max(1 - wealth / np.maximum.accumulate(wealth))),
                'closed_trades': count, 'frequency60': 60 * count / len(ix),
                'benchmark_cagr': float((benchmark[-1] / bh_open) ** (252 / len(ix)) - 1),
                'benchmark_drawdown': float(np.max(1 - benchmark / np.maximum.accumulate(benchmark))),
                'scope': 'Description only; original ledger with opening holdings/wealth retained, no new account or replacement of full1636 gates'}

    common_period = {'EX080': comparable_slice((bound, result)), 'C8880': comparable_slice((baseline_bound, baseline_result))}
    episodes = []
    for i_value in np.flatnonzero(policy.signal_reason.eq('entry').to_numpy()):
        i = int(i_value)
        last = min(i + 4, len(policy) - 1)
        ids = set(decisions.iloc[i:last + 1].decision_id)
        oo = orders.loc[orders.decision_id.isin(ids)]
        ff = fills.loc[fills.decision_id.isin(ids)]
        buys = ff.loc[ff.side.eq('BUY')]
        mature = i + 5 < len(prices)
        episodes.append({
            'entry_signal': policy.index[i].isoformat(), 'entry_position': int(i),
            'forecast': float(policy.net_forecast.iloc[i]),
            'intended_entry_execution': prices.index[i + 1].isoformat(),
            'intended_exit_execution': prices.index[i + 5].isoformat() if mature else None,
            'proxy_mature': mature,
            'net_open_proxy': float(prices.open.iloc[i + 5] / prices.open.iloc[i + 1] * (.999 / 1.001) - 1) if mature else None,
            'order_count': len(oo), 'buy_fill_count': len(buys), 'sell_fill_count': int(ff.side.eq('SELL').sum()),
            'unfilled_buy_orders': int((oo.side.eq('BUY') & oo.status.eq('UNFILLED')).sum()),
            'first_buy_fill': pd.Timestamp(buys.fill_time.iloc[0]).isoformat() if len(buys) else None,
            'actual_cycle_ids': sorted(set(ff.cycle_id)),
            'actual_fees': float(ff.fees.sum()),
        })
    d.write(d.OUT / 'episode_attribution.json', {'episodes': episodes, 'scope': 'Policy episode order/fill linkage and nonoverlap fractional OPEN proxy, not a second account or additive causal profit decomposition'})
    accepted = np.array([x['net_open_proxy'] for x in episodes if x['proxy_mature']])
    by_year = {}
    for year in range(2020, 2027):
        group = [x for x in episodes if x['entry_signal'].startswith(str(year))]
        mature = [x['net_open_proxy'] for x in group if x['proxy_mature']]
        by_year[str(year)] = {'episodes': len(group), 'mature': len(mature), 'mean_net_open_proxy': float(np.mean(mature)) if mature else None}
    rejected_positive = int(policy.positive_forecast.sum()) - len(episodes)
    judgment = ('固定四日确认净预测不能独立支撑原四项经济要求。保留确认信息的有限条件性线索，放弃当前年度单分数预测>0加四日时钟这一策略表达；不调邻近阈值、期限或正则系数补救。'
                if not centre['qualified'] else '中心满足原四门，仍须完成事前规定标准32扰动和独立双费验证，抗扰动目标尚未证明。')
    percent = lambda x: f'{100 * x:.4f}%'
    report = f'''# EX080：确认净机会落实为真实账户

{judgment}

这一轮把 EX079 的原确认分数年度净收益预测原样落实为一次完整账户：预测大于0且政策空仓时入场，持有四个交易日，到期退出，退出信号当天不能重新入场。采用原510500.SH、完整2020-01-02至2026-09-30开发池、100万元、后复权固定锚、每侧0.1%费用、整手及原1%限价执行合同；2020训练期空仓也计入完整区间。

## 原四项经济硬门

|项目|EX080 C9080|原对照 C8880|原要求|EX080判断|
|---|---:|---:|---|---|
|净年化收益|{percent(centre['net_cagr'])}|{percent(base['net_cagr'])}|至少{percent(1.5 * centre['benchmark_cagr'])}|{'达标' if centre['gates']['return'] else '未达标'}|
|完整区间最大回撤|{percent(centre['full_drawdown'])}|{percent(base['full_drawdown'])}|验收按逐自然年严格小于相同buyhold，不用全区间回撤替代年度门|见年度表|
|闭合交易|{centre['closed_trades']}|{base['closed_trades']}|完整1636交易日平均每60日至少4次，即至少110次|{'达标' if centre['gates']['frequency'] else '未达标'}|
|平均每60日闭合交易|{centre['frequency60']:.4f}|{base['frequency60']:.4f}|至少4|同上|
|逐年回撤门|{'达标' if centre['gates']['annual_drawdown'] else '未达标'}|{'达标' if base['gates']['annual_drawdown'] else '未达标'}|每年回撤严格小于同年buyhold|保持原定义|
|buyhold亏损年份盈利门|{'达标' if centre['gates']['negative_buyhold_year_profit'] else '未达标'}|{'达标' if base['gates']['negative_buyhold_year_profit'] else '未达标'}|按实际buyhold负收益年份触发，策略净收益严格大于0|保持原定义|

## 年度结果

|年份|EX080净收益|C8880净收益|buyhold净收益|EX080回撤|buyhold回撤|EX080费用|
|---|---:|---:|---:|---:|---:|---:|
'''
    for year, row in centre['annual'].items():
        bh = centre['benchmark_annual'][year]
        report += f"|{year}|{percent(row['return'])}|{percent(base['annual'][year]['return'])}|{percent(bh['return'])}|{percent(row['drawdown'])}|{percent(bh['drawdown'])}|{audit['cash_account']['annual'][year]['fees']:.2f}|\n"
    slice_new, slice_old = common_period['EX080'], common_period['C8880']
    report += f"\n共同可预测执行区间{slice_new['start']}至2026-09-30仅作描述：EX080净年化{percent(slice_new['net_cagr'])}、回撤{percent(slice_new['drawdown'])}；C8880净年化{percent(slice_old['net_cagr'])}、回撤{percent(slice_old['drawdown'])}；相同buyhold净年化{percent(slice_new['benchmark_cagr'])}、回撤{percent(slice_new['benchmark_drawdown'])}。两者保持原账本期初持仓和权益，没有新账户；完整1636日原四门仍是验收口径。\n"
    report += f'''
## 信号机会为什么不等于账户盈利

EX079 有694个预测为正的信号，其中691个四日标签成熟；每个信号允许资金重叠的均值约+0.1212%，这只是扣两侧费用后的OPEN价格代理。其均值置信区间跨零，2022和2026分组仍亏损，不能视为稳定盈利证明。

本轮政策接受{len(episodes)}次入场意图，拒绝在已有持仓或到期退出信号上重复入场的正预测{rejected_positive}次。接受意图中{len(accepted)}个代理标签成熟，其非重叠四日OPEN代理均值为{percent(float(accepted.mean()))}，复合代理收益为{percent(float(np.prod(1 + accepted) - 1))}。这依然不是第二个可执行账户：不能代替真实限价成交、整手、晚成交、未成交、补买、现金占用及末期持仓。真实闭合交易只按原生账本计数，二者差异不作可加总的因果利润解释。

逐个接受意图的计划日期、实际买卖成交、未成交与费用已经留证。最终未结束持仓保留，未强平或缩短持有期，不计入闭合交易。

## 自检与结论边界

仅复用这一个中心账本计算126日/21日步长滚动超额收益Q10、最大正盈利交易前10%贡献、2000次/平均20日块/种子13的配对超额年化区间；结果见核验JSON。{'中心原四门失败，按事前停项规则不运行' if not centre['qualified'] else '尚未运行'}新标准32点或双费账户。参数收益Q10、回撤Q90及32点逐项/联合达标率均不可得，不能填0或写成通过；PBO/DSR因完整研究族证据不足不可得。本轮没有完成完整五项自检，也没有达成整体抗扰动研究目标。

## 技术核验及修正

准备阶段的候选标识格式已独立修正留证。首个C9079评价调用在SRT输入准备阶段因重复日线成交价输入而拒绝，未进入交易账户计算、未生成完整原生结果。原方案与源码保留，技术修订C9080删除冗余输入，复用原成交价表重建相同特征；参数、预测表达、持仓政策和经济要求未改。另分离非数值DataFrame元数据以避免重复复制，保留输入身份认证。

修订后1635个历史预测及正负判定与EX079相符，独立复算22904个特征值、六次成熟年度训练和全部政策字段通过；完整原生序列化、现金数量费用、年度边界、订单成交链接及首触核验通过。技术通过与经济达标、信息有效和未来稳健是不同结论。实际新增完整账户1个，账户重跑0；早于账户的失败评价调用1次完整披露。

## 下一步与额度

{'停止这一固定策略表达，回到信息组件：优先检验确认信息与价格状态的作用关系，先取得增量证据，才允许进入新完整账户。原对照的较高收益仍不能抵消其标准扰动脆弱性。' if not centre['qualified'] else '按事前完整有效域完成32点与独立双费，再讨论可保留性。'} 同一已见开发池上的适应性研究不能冒充独立封存验证，不扩大数据范围，不新增经济硬门。

新增10轮额度已完成2/10（EX079、EX080），剩余8轮，最后允许EX088；额度用完暂停，不启动EX089。正式报告完整副本存入本实验others/report.md并逐字节/SHA256校验。
'''
    diagrow = audit['three_ledger_checks']['rows'][0]
    diagnostics = {x['metric']: x for x in diagrow['diagnostics']}
    interval = diagrow['uncertainty']
    extra = f"""\n复用中心账本的三项实际诊断：

|诊断|实际结果|解释|
|---|---:|---|
|126日滚动超额收益Q10|{100 * diagnostics['ROLLING_EXCESS_Q10']['value']:.4f}个百分点|较差的一批半年窗口明显落后buyhold|
|前10%正盈利交易贡献|{percent(diagnostics['PROFIT_CONCENTRATION']['value'])}|只对严格正盈利闭合交易计算，不新增集中度硬门|
|配对超额年化95%区间|[{100 * interval['lower_95']:.4f}, {100 * interval['upper_95']:.4f}]个百分点|跨零；是固定账本重抽样区间，不是未来成功概率|

全区间实际费用合计{sum(x['fees'] for x in audit['cash_account']['annual'].values()):.2f}元，最终净增值{centre['annual']['2026']['closing_equity'] - 1_000_000:.2f}元。实际订单{audit['orders_first_touch']['order_n']}份、买入成交{audit['orders_first_touch']['buy_fill_n']}笔、卖出成交{audit['orders_first_touch']['sell_fill_n']}笔，未成交订单{audit['orders_first_touch']['unfilled_n']}份。交易频率够了，但每次机会留下的净盈利及下跌年份保护不够，不能靠多交易弥补。
"""
    report = report.replace('## 技术核验及修正', extra + '\n## 技术核验及修正')
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'objective_achieved': False, 'original_four_hard_gates_changed': False,
              'experiment': exp.to_dict(), 'candidate': 'C9080', 'judgment': judgment, 'economics': centre,
              'baseline_economics': base, 'common_predictable_period_description': common_period, 'accepted_episode_summary_by_year': by_year,
              'positive_forecasts': int(policy.positive_forecast.sum()), 'policy_episodes': len(episodes),
              'mature_nonoverlap_proxy': {'n': len(accepted), 'mean': float(accepted.mean()), 'compound_proxy': float(np.prod(1 + accepted) - 1)},
              'financial_roles': {'centre_new': 1, 'baseline_reused': 1, 'standard32_new': 0, 'fee_new': 0, 'financial_repeats': 0},
              'evidence_references': {'plan.json': d.read(path / 'protocols/method_references_v2.json')['plan.json'], 'native.json': audit['centre_reference'], 'verification.json': refs['verification.json']},
              'report_markdown': report}
    d.write(d.OUT / 'root_review.json', review)
    outrefs = {name: d.put(ctx, exp, p) for name, p in {'root_review.json': d.OUT / 'root_review.json', 'episode_attribution.json': d.OUT / 'episode_attribution.json', 'review_driver.py': Path(__file__)}.items()}
    d.write(path / 'protocols/review_references.json', outrefs)
    print({'status': review['status'], 'judgment': judgment, 'quota_completed': 2}, flush=True)


if __name__ == '__main__':
    run()
