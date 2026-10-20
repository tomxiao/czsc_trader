"""Actual event/exit and March loss-pause facts from three audited ledgers only."""
import json
from pathlib import Path

import anchor_account_common as C
from consolidate_anchor_audit import csv_output, ref

OUT, A, H = C.OUT, C.A, C.H


def main():
    summary = A.read(OUT / 'independent_anchor_audit_summary.json')
    reports = [A.read(C.ROOT / value['path']) for value in summary['account_reports']]
    highlights, cycles, pause_rows = [], [], []
    for report in reports:
        profile = report['parameters']['anchor_profile']
        yearly = {row['year']: row for row in report['original_annual_goal_audit']}
        selected = [e for e in report['lifecycle']['actual_anchor_events'] if e['selected_anchor_exit']]
        highlights.append({'anchor_profile': profile, 'diagID': report['diagID'],
                           'annual_return_pass': report['summary']['nannual_return_pass_2020_26'],
                           'annual_drawdown_pass': report['summary']['nannual_drawdown_pass_2020_26'],
                           'frequency': report['summary']['frequency_full_contract'], 'frequency_pass': report['summary']['original_frequency_pass'],
                           'all_original_goals_pass': report['summary']['all_original_economic_goals_pass'],
                           'year2025_return': yearly[2025]['return'], 'year2025_shortfall_pp': 100 * (yearly[2025]['required_return'] - yearly[2025]['return']),
                           'year2026_return': yearly[2026]['return'], 'year2026_shortfall_pp': 100 * (yearly[2026]['required_return'] - yearly[2026]['return']),
                           'terminal_equity': report['boundary2026_actuals']['ending_equity'], 'own2026_boundary': report['boundary2026_actuals'],
                           'created_anchor_distinct_cycles': len({e['cycle_id'] for e in report['lifecycle']['actual_anchor_events'] if e['created_today']}),
                           'selected_anchor_D': len(selected), 'selected_anchor_distinct_cycles': len({e['cycle_id'] for e in selected}),
                           'new_exit_added_D': sum(e['new_exit_added'] for e in selected), 'cost_overlap_D': sum(e['cost_overlap'] for e in selected),
                           'support_overlap_D': sum(e['support_overlap'] for e in selected), 'prefix': report['prefix']})
        account = A.published(report['account_ref'])
        ledger = account['runs'][0]['ledgers']
        pairs = {}
        for fill in ledger['fills']['data']:
            pairs.setdefault(fill['cycle_id'], {})[fill['side']] = fill
        decisions = {A.day(row['signal_date']): row for row in ledger['decisions']['data']}
        trades = {r['cycle_id']: r for r in ledger['trades']['data']}
        wanted = {event['cycle_id'] for event in selected}
        if profile == 'ORIGINAL_C9502_CONTROL':
            wanted.update(event['cycle_id'] for event in report['lifecycle']['first_own_SHOCK_events'] if event['D'] >= '2025-01-01')
        for cycle in sorted(wanted):
            buy, sale = pairs[cycle]['BUY'], pairs[cycle].get('SELL')
            exitD = A.day(sale['signal_date']) if sale else None
            exit_row = decisions.get(exitD)
            trade = trades[cycle]
            cycles.append({'anchor_profile': profile, 'diagID': report['diagID'], 'cycle_id': cycle,
                           'account_ref_sha256': report['account_ref']['sha256'], 'entry_D': A.day(buy['signal_date']), 'entry_E': A.day(buy['fill_time']),
                           'entry_price': buy['price'], 'entry_quantity': buy['quantity'], 'entry_fee': buy['fees'], 'entry_fill_id': buy['fill_id'],
                           'exit_D': exitD, 'exit_E': A.day(sale['fill_time']) if sale else None, 'exit_price': sale['price'] if sale else None,
                           'exit_fee': sale['fees'] if sale else None, 'exit_fill_id': sale['fill_id'] if sale else None,
                           'actual_status': trade['status'], 'actual_full_cycle_net_return': trade['net_return'],
                           'actual_full_cycle_net_cash_not_calendar_contribution': sale['price'] * sale['quantity'] - sale['fees'] - buy['price'] * buy['quantity'] - buy['fees'] if sale else None,
                           **{'exit_' + key: exit_row[key] if exit_row else None for key in ['selected_anchor_exit', 'selected_combined_risk_exit', 'selected_cost_exit', 'ordinary_support_exit', 'deadline_exit', 'pending_inherited']}})
        for day in ['2025-03-27', '2025-03-28', '2025-03-31', '2025-04-01', '2025-04-09', '2025-04-10']:
            row = decisions[day]
            pause_rows.append({'anchor_profile': profile, 'diagID': report['diagID'], 'D': day,
                               **{key: row[key] for key in ['valid_session', 'held_at_close', 'first_shock_today', 'anchor_created_today', 'anchor_raw_condition', 'selected_anchor_exit', 'selected_cost_exit', 'ordinary_support_exit', 'target_position', 'net_profit', 'completed_net_unit', 'last_completed_sign', 'pause_armed', 'pause_slot_consumed', 'reservation_index']}})
    outputs = [csv_output('anchor_actual_exit_cycles.csv', cycles), csv_output('anchor_march_pause_chain.csv', pause_rows)]
    findings = {'status': 'COMPLETE_INDEPENDENT_THREE_FUNDED_ACCOUNT_INTERPRETATION', 'experiment': 'EX051_20261020',
                'inputs': [ref(OUT / name) for name in ['independent_anchor_audit_summary.json', 'anchor_policy_yearly_summary.csv', 'anchor_policy_summary.csv', 'anchor_actual_events.csv']],
                'highlights': highlights, 'actual_detail_outputs': outputs,
                'judgment': [
                    'Neither fixed event-anchor rule repairs all original annual goals. ZERO/1ATR return5/7 versusC9502control6/7; all DD7/7 and original frequency pass. No new rejection gate was added.',
                    'Both detect March weakening on2025Mar28 while originalnetP still+0.5055% and cost/S5false. Actual T+1 sale Mar31 at5.58 after entryMar21 at5.66 yields-1.6104037% net, not the positive decision-close mark. Control sellsApr1 at5.18 for-8.6634214%.',
                    'Both still realize a loss, arm original pause onMar31 and consumeApr9 candidate into reservation1286. Apr10 staysflat; earlier instruction did not restore that participation. Quantities/capital differ across three actual paths.',
                    '2025 annual returns improve to26.980678/26.988208%, still below40.187864% required.2026 falls from203.939341% to8.629282/28.189966%, below196.464402% required. Frozen1ATR does not solve the normal-pullback versus deterioration distinction.',
                    'ZERO has9 selected new-exit cycles,1ATR5 in own histories; all are incremental versus same-own-D originalcost/S5, not exclusive performance causes. Same-cycle threshold inclusion never implies nested full-policy populations, funds or outcomes.',
                    'Keep C9502 as this experiment diagnostic control. Do not scan wider ATR buffers, periods, fee margins or year switches from these results. A deferred firstSHOCK-context proposal needs a separate explicit method succession and lock; no next account executed by this report.'
                ],
                'technical_incident': 'Original000 engineSUCCEEDED, internal raw-projection KeyError retained. Same000 supplemented plus independent source-reconstructed flags/financial exactPASS. v1 source/account never overwritten, active1/2 actually bindv2. No funded retry/enginefailure.',
                'raw_anchor_observation_semantics': 'Reconstructed from authenticated sourceHFQ/event index and preserved originalATR feature; not directly observed raw decision columns.',
                'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
                'independent_phase_checks': summary['independent_phase_checks'], 'implementation': ref(Path(__file__).resolve()),
                'limits': ['Shared-seen adaptive development, no untouched validation.', 'Actual full-cycle netcash is not calendar-year contribution for carry cycles. No local counterfactual labels or new hypothetical reentry.', 'No registration, phaseadvance or original eligibility edit.']}
    path = OUT / 'anchor_research_findings.json'
    H.write(path, findings)
    text = '''# 延持后的冻结锚退出：三账户结论

完整独立审计995749项通过。三笔实际账户引擎均成功，零失败、未知或重派；原控制一次内部审计投影KeyError及同账户补核单独留存，未改源码、原账本或旧回执。

|政策|2025收益|2026收益|原收益门|原回撤门|原频率|
|---|---:|---:|---:|---:|---:|
|C9502精确控制|17.96%|203.94%|6/7|7/7|3.325，通过|
|持续跌破SHOCK收盘锚|26.98%|8.63%|5/7|7/7|3.289，通过|
|持续回落达到冻结1ATR|26.99%|28.19%|5/7|7/7|3.289，通过|

两新规则都在2025-03-28识别转弱并发出卖出意图，当时账面净收益仍+0.5055%、原成本/S5退出尚未触发。实际下一交易日3月31日卖价5.58，相对3月21日买价5.66，含费用仍亏1.6104%；原控制4月1日5.18卖出、整笔亏8.6634%。提前退出减轻损伤，但不能把决策收盘价当成交价或声称保住正收益。

亏损记忆仍在3月31日启动，4月9日仍消费一次暂停机会，预约改到1286，4月10日继续空仓。两新账户2025仍未达到40.1879%收益门；2026则失去原C9502的196.4644%门。一个固定波幅缓冲没有解决正常回落与有效转弱的区别。

ZERO共9个新增退出周期，1ATR共5个，所有触发都保留完整自有资金/入场/成交/退出/暂停链。某同周期阈值有包含关系，不等于完整政策的人口和资金收益有包含关系。各自年初分母与2026跨年仓详见原年度表及边界表，不能按年份拼接政策。

本实验三臂到此收口，全部原七年度收益/严格回撤与频率门保持。后续若研究首次SHOCK当时的趋势许可，须独立说明对旧负面结论的后继方法选择，不能称已获得新独立信息或直接混合已见状态。

来源：`anchor_policy_yearly_summary.csv`、`anchor_policy_summary.csv`、`anchor_actual_events.csv`、`anchor_actual_exit_cycles.csv`、`anchor_march_pause_chain.csv`、`independent_anchor_audit_summary.json`、`anchor_research_findings.json`。未投影原始锚列的价格值来自认证原资产重建，正式标记/索引/动作已逐D核实，不冒称原始锚列直接观测。
'''
    target = OUT / 'anchor_readout.md'
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print(json.dumps({'findings': ref(path), 'readout': ref(target), 'actual_outputs': outputs, 'highlights': highlights}))


if __name__ == '__main__':
    main()
