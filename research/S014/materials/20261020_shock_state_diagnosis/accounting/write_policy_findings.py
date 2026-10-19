"""Summarize audited three actual paths only; no new replay or counterfactual."""
import json
from pathlib import Path

import policy_account_common as C
from consolidate_policy_audit import csv_output, ref

OUT, A, H = C.OUT, C.A, C.H


def main():
    summary = A.read(OUT / 'independent_policy_audit_summary.json')
    reports = [A.read(C.ROOT / item['path']) for item in summary['account_reports']]
    highlights, cycle_rows = [], []
    for report in reports:
        annual = {row['year']: row for row in report['original_annual_goal_audit']}
        profile = report['parameters']['policy_profile']
        highlights.append({'policy_profile': profile, 'diagID': report['diagID'], 'original_return_pass': report['summary']['nannual_return_pass_2020_26'],
                           'original_drawdown_pass': report['summary']['nannual_drawdown_pass_2020_26'],
                           'frequency': report['summary']['frequency_full_contract'], 'frequency_pass': report['summary']['original_frequency_pass'],
                           'all_original_goals_pass': report['summary']['all_original_economic_goals_pass'],
                           'year2025_return': annual[2025]['return'], 'year2025_required': annual[2025]['required_return'],
                           'year2025_shortfall_pp': 100 * (annual[2025]['required_return'] - annual[2025]['return']),
                           'year2026_return': annual[2026]['return'], 'year2026_required': annual[2026]['required_return'],
                           'year2026_margin_pp': 100 * (annual[2026]['return'] - annual[2026]['required_return']),
                           'terminal_equity': report['boundary2026_actuals']['ending_equity'], 'prefix': report['prefix'],
                           'boundary2026': report['boundary2026_actuals'],
                           'own_first_SHOCK_n': len(report['lifecycle']['first_own_SHOCK_events']),
                           'own_first_SHOCK_hold_n': sum(e['hold_decision'] for e in report['lifecycle']['first_own_SHOCK_events'])})
        account = A.published(report['account_ref'])
        ledger = account['runs'][0]['ledgers']
        fills = {}
        for fill in ledger['fills']['data']:
            fills.setdefault(fill['cycle_id'], {})[fill['side']] = fill
        decisions = {A.day(row['signal_date']): row for row in ledger['decisions']['data']}
        for event in report['lifecycle']['first_own_SHOCK_events']:
            if profile != 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD' and event['D'] < '2025-01-01':
                continue
            pair = fills[event['cycle_id']]
            buy, sale = pair['BUY'], pair.get('SELL')
            exit_D = A.day(sale['signal_date']) if sale else None
            exit_state = decisions[exit_D] if sale else None
            cycle_rows.append({'policy_profile': profile, 'diagID': report['diagID'], **event,
                               'account_evidence_sha256': report['account_ref']['sha256'],
                               'actual_entry_D': A.day(buy['signal_date']), 'actual_entry_price': buy['price'], 'actual_entry_fee': buy['fees'],
                               'actual_exit_D': exit_D, 'actual_exit_E': A.day(sale['fill_time']) if sale else None,
                               'actual_exit_price': sale['price'] if sale else None, 'actual_exit_fee': sale['fees'] if sale else None,
                               'actual_entry_order_id': buy['order_id'], 'actual_entry_fill_id': buy['fill_id'],
                               'actual_exit_order_id': sale['order_id'] if sale else None, 'actual_exit_fill_id': sale['fill_id'] if sale else None,
                               'full_cycle_net_cash_not_calendar_year_contribution': sale['quantity'] * sale['price'] - sale['fees'] - buy['quantity'] * buy['price'] - buy['fees'] if sale else None,
                               **{('actual_exit_' + key): exit_state[key] if exit_state else None for key in ['pending_inherited', 'deadline_exit', 'selected_shock_exit', 'selected_cost_exit', 'ordinary_support_exit']}})
    table = csv_output('policy_key_actual_cycles.csv', cycle_rows)
    finding = {'status': 'COMPLETE_AUDITED_THREE_ACTUAL_FIXED_PROFILES', 'experiment': 'EX050_20261020',
               'inputs': [ref(OUT / 'independent_policy_audit_summary.json'), ref(OUT / 'full_policy_yearly_summary.csv'), ref(OUT / 'full_policy_summary.csv'), ref(OUT / 'full_policy_first_SHOCK_actual_cycles.csv')],
               'highlights': highlights, 'key_cycle_detail': table,
               'judgment': [
                   'No profile meets all original goals. Keep C9461 as existing diagnostic baseline; freshC9500 is exact economic replication, not independent strategy validation.',
                   'S2 sacrifices original2025 passage and still fails2026. The local component0.4203pp gain cannot support an annual-return claim.',
                   'Age policy passes2026 by7.47493866pp and raises terminal wealth to1638378.751, but2025 misses its original return target by22.22756526pp. Its full-contract6/7 return count equals original, with a different failed year.',
                   'All three drawdown goals7/7 and original frequency pass. Do not add nonharm or statistical gates, nor waive the2025 shortfall or partial2026 hard goal.',
                   'Age policy keeps entryday2025Jun19 and2026Jan9 original SHOCK exits, while2025Mar27 aged4 remains latched into a losing exit. It does not distinguish every previously held rise from weakening.',
                   'Age2026 Jan6 aged8 continuation exitsJan8 at6.30, less than originalJan7 at6.46. Jan9 age0 still realizesJan12 at6.80, and Jan29/Feb11/Mar6/Sep1 actual extensions supply positive participation. Do not claim every age>=1 suppression helps.',
                   'All policies diverge since2020, carry different2026 opening equities/quantities and own strict completion/pause chains. Terminal/annual differences are full-history policy outcomes, not local cancellation profits or sums of component labels.',
                   'Stop at the three fixed accounts. A next research question may seek D-known differences between March2025 weakening and later2026 continuation within held cycles, without year switches or posthoc threshold tuning.'
               ],
               'selection_disclosure': 'All years seen; S2 unresolved clock composition, age direction selected after local labels. No heldout validation or automatic registration/eligibility/phase promotion.',
               'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
               'independent_phase_checks': summary['independent_phase_checks'], 'implementation': ref(Path(__file__).resolve())}
    path = OUT / 'policy_research_findings.json'
    H.write(path, finding)
    readout = '''# 首次自有SHOCK三档完整政策

三笔真实账户全部成功，独立实际核验860475项通过，零失败、未知、重试、拟合或新供应商调用。新控制C9500精确复现原C9461；它只证明新源码等价，不是新增独立策略样本。

|政策|2025收益|2026收益|原收益门|原回撤门|原频率|
|---|---:|---:|---:|---:|---:|
|原C9461控制|47.03%|79.20%|6/7|7/7|3.362，通过|
|首次S2为真则周期延持|−4.71%|128.87%|5/7|7/7|3.216，通过|
|首次SHOCK年龄≥1则周期延持|17.96%|203.94%|6/7|7/7|3.325，通过|

年龄规则2026超过196.4644%原收益门7.47494个百分点，最终权益1638378.751；但2025低于40.1879%门22.22757个百分点。它将失败年份从2026换到2025，原目标仍未达成。各政策使用自身年初权益，不能按年份拼接或用共同资金分母取代完整账户。

年龄规则保留2025-06-19、2026-01-09买入当日SHOCK的原退出。2025-03-27已持仓4天则继续持有，实际4月1日退出、整笔净收益−8.66%；原政策3月28日退出为+5.27%。它尚不能识别所有已持仓上涨中的转弱。2026-01-06年龄8的延持也少赚；后续1月29日、2月11日、3月6日、9月1日则发生了真实延续参与。所有首次节点及实际退出见完整CSV，不只保留有利案例。

S2完整账户没有修复原目标。年龄规则是更有辨别力的动作问题，但其方向是在已见局部标签后选择，不能称样本外验证。两档在2020就分叉，2026入场资金、跨年持仓和亏损后暂停链均属于各自真实历史。局部延持差额不能相加为年度收益。

本轮到三固定账户结束，保留C9461作既有诊断对照。下一问题可聚焦已持仓条件下，交易当时什么信息能区分2025年3月的转弱和2026的上涨延续；当前不按年份开关规则、不修改阈值、不再派账户。原七年度收益、回撤及频率硬门全部保留，未正式注册候选或修改资格。

来源：`full_policy_yearly_summary.csv`、`full_policy_summary.csv`、`full_policy_first_SHOCK_actual_cycles.csv`、`policy_key_actual_cycles.csv`、`independent_policy_audit_summary.json`、`policy_research_findings.json`。关键表中的整笔周期净额跨年时不等于自然年贡献。
'''
    target = OUT / 'policy_readout.md'
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(readout)
    print(json.dumps({'findings': ref(path), 'readout': ref(target), 'cycle_detail': table}))


if __name__ == '__main__':
    main()
