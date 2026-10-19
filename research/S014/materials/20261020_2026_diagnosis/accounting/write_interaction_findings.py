"""Actual Jan participation and cross-year costs; no further policy selection."""
import json
from pathlib import Path

import consolidate_interaction_audit as S


def main():
    reports = [S.A.read(S.OUT / f'interaction_account_{i:03d}_independent_review.json') for i in (0, 1)]
    accounts = [S.A.published(r['account_ref']) for r in reports]
    loss, base = reports
    jan = []
    failed = []
    for report, account in zip(reports, accounts, strict=True):
        ledger = account['runs'][0]['ledgers']
        row = next(r for r in ledger['decisions']['data'] if S.A.day(r['signal_date']) == '2026-01-23')
        order = next((r for r in ledger['orders']['data'] if S.A.day(r['signal_date']) == '2026-01-23'), None)
        fill = next((r for r in ledger['fills']['data'] if order and r['order_id'] == order['order_id']), None)
        jan.append({'pause_profile': report['parameters']['pause_profile'], 'D': '2026-01-23',
                    **{k: row[k] for k in ['completed_net_known', 'last_completed_sign', 'last_completed_net_unit', 'original_entry_candidate',
                                          'pause_armed_before_candidate', 'pause_slot_consumed', 'entry_signal', 'target_position', 'reservation_index', 'planned_slot_until']},
                    'actual_order': order, 'actual_fill': fill})
        failed.extend({'pause_profile': report['parameters']['pause_profile'], **r, 'actual_trade_outcome': None}
                      for r in ledger['orders']['data'] if r['side'] == 'BUY' and r['status'] != 'FILLED' and '2026-01-01' <= S.A.day(r['execution_date']) <= '2026-10-15')
    S.A.check('actual Jan mechanism changes as locked question', jan[0]['pause_slot_consumed'] and jan[0]['actual_order'] is None and not jan[1]['pause_slot_consumed'] and jan[1]['actual_fill']['side'] == 'BUY')
    S.A.check('BASE remembers own completed net loss truthfully', jan[1]['completed_net_known'] and jan[1]['last_completed_sign'] == -1 and not jan[1]['pause_armed_before_candidate'])
    loss_dates = {r['original_entry_E'] for r in loss['actual2026_calendar_cycle_contributions']}
    added = [r for r in base['actual2026_calendar_cycle_contributions'] if r['original_entry_E'] not in loss_dates]
    outputs = [S.csv_output('interaction_2026_new_actual_entries.csv', added)]
    actual_new_jan = next(r for r in added if r['original_entry_E'] == '2026-01-26')
    annual2026 = base['original_annual_goal_audit'][-1]
    margin = 100 * (annual2026['return'] - annual2026['required_return'])
    S.A.check('original2026 exact strict gate already passed no new buffer', annual2026['return_pass'] and margin > 0)
    summary = S.A.read(S.OUT / 'independent_interaction_audit_summary.json')
    four = S.A.read(S.OUT / 'interaction_four_cell_review.json')
    result = {'status': 'COMPLETE_FIXED_INTERACTION_DIAGNOSIS', 'implementation': S.ref(Path(__file__).resolve()),
              'sources': [S.ref(S.OUT / 'independent_interaction_audit_summary.json'), S.ref(S.OUT / 'interaction_four_cell_review.json'), S.ref(S.OUT / 'interaction_pause_actual_review.json')],
              'outputs': outputs, 'actual_Jan23_decision_and_funding': jan, 'actual_new_Jan_cycle': actual_new_jan,
              'new_actual_entry_dates_vs_LOSS': [r['original_entry_E'] for r in added], 'actual2026_failed_BUY': failed,
              'BASE_2026_original_return_pass_margin_pp': margin,
              'original_goal_counts': {r['policy_id']: {'return': r['summary']['nannual_return_pass_2020_26'], 'drawdown': r['summary']['nannual_drawdown_pass_2020_26'],
                                                       'frequency_pass': r['summary']['original_frequency_pass'], 'all_original_goals_pass': r['summary']['all_original_economic_goals_pass']} for r in reports},
              'goal_judgment': 'BASE repairs original2026 return but fails2024 return and2025 return plus drawdown. It cannot replace C9461 as an all-original-goals strategy.',
              'strong_actual_counterexamples': [{'entry_E': r['original_entry_E'], 'exit_E': r['actual_exit_E'], 'actual_trade_net_return': r['source_trade_net_return_NOT_year_contribution'],
                                                'calendar2026_contribution_pp': r['strategy_contribution_pp']} for r in added if r['source_trade_net_return_NOT_year_contribution'] < 0],
              'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'], 'independent_phase_checks': summary['independent_phase_checks'],
              'four_economic_policy_sources': four['sources'],
              'next_research_direction_without_new_accounts': 'Keep C9461 original source/parameters and prior eligibility unchanged. Existing four cells show opposing continuation/protection duties. A later proposal would need D-known evidence distinguishing sustained rise from renewed weakness across all years, not year switches, remembered dates or threshold search.',
              'limits': ['BASE first mutable-state divergence2020Apr16, targetApr22, moneyApr23; its2026 own opening324604.318 differs fromLOSS402899.81. It is not a localJan cancellation with common starting wealth.',
                         'Actual Jan26-Feb9 trade net25.9383% and calendar contribution27.0135pp differ from observed BH40.7519pp. Neither is entire policy annual gain73.4856pp.',
                         'Other added actual entries can lose; failedBUY remains null outcome. The cutoff has no assumed future source replay or wealth.',
                         'The0.2721pp2026 margin is reported, not a new buffer veto. Original annual goals and frequency alone govern the original pass count.',
                         'Descriptive four-cell return interactions reuse old funded accounts and own annual openings, not independent samples or clean causal dose effects.',
                         'Seen history, adaptive choice of this fixed supplement, zero fit/new market calls, no automatic registration or production change.']}
    path = S.OUT / 'interaction_research_findings.json'
    S.H.write(path, result)
    text = f'''# EX048 固定退出与亏损暂停交互独立结论

补充诊断已完成。取消 SHOCK 和亏损暂停后，C9481 的2026收益196.7365%，超过原门196.4644%，余量{margin:.6f}个百分点。该结果按原门通过；没有增设安全余量门。但它未达成全周期原目标，不能替代 C9461，也未正式注册。

|原口径|关闭SHOCK、保留亏损暂停 C9480|关闭SHOCK、取消亏损暂停 C9481|
|---|---:|---:|
|2024收益|15.9846%|−19.0513%|
|2025收益|−4.7050%|−1.3081%|
|2025最大回撤|28.4141%|31.4526%（原BH28.8759%）|
|2026截至10/15收益|123.2509%|196.7365%|
|原七年度收益通过|5/7|5/7|
|原七年度回撤通过|7/7|6/7|
|原频率：每60交易日闭合周期|3.215591|5.042631|
|原截止连续终值|899,477.470|963,219.365|

原 C9461 保留 SHOCK 和亏损暂停，收益6/7、回撤7/7、原频率通过。三个新旧经济政策都未全部达成原目标。不能用最高终值、平均年收益或单个2026通过替代逐年目标。

实际机制链得到验证：C9481在1/19真实完成亏损后，1/23仍如实记得该亏损，但不再暂停；1/26实际买入47,300单位、价7.14，2/9按原期限卖出、价9.01，含双边费用净赚87,687.105。完整交易收益25.9383%，按其自己年初权益贡献27.0135个百分点。C9480则消费1/23暂停名额，2/10才实际再买。原观察到的40.7519个百分点BH上涨没有被当作可赚收益。

新增实际参与也有代价：5/15、6/23、10/12买入的完整实际周期分别亏损约2.16%、6.17%、13.68%；9/30拟买、10/8实际未成交的订单保留为未成交，不能给虚构交易收益。7/28实际周期盈利约34.07%，说明暂停既可错过上涨，也会避开亏损。

C9481早在2020-04-16记忆/armed状态开始与暂停政策分叉，4/22目标、4/23资金分叉。其2026年初324,604.318、54,100单位；C9480为402,899.81、67,200单位。因此2026增加73.4856个百分点是整条固定历史政策的结果，不能归于单个1月名额。C9481全年真实财富增加638,615.047：入仓日毛损益−16,002，继续持有+587,925，卖出前收盘至实际卖价+89,892，费用23,199.953。原截止已经空仓；最后已存D10/14的退出意图在E10/15完成，不表示截止仍持有或仍有未成交卖单。

四格复用表逐SHA认证了原成本口径的SHOCK开/关与亏损暂停开/关。新source的复现账户只证明复现，不增加独立验证次数。2026两职责有明显交互，其他年份方向相反；支持先保留 C9461，并把下一研究问题限定为如何在D已知信息下区分上涨延续和再次转弱，不能按年份或事后日期切换。此处不派更多账户、不改阈值。

EX048两次真实派发全成功，0失败、0未知、0重试；完整独立账务/状态检查{summary['independent_actual_checks']:,}项，年度桥接{summary['independent_phase_checks']:,}项。EX047和EX048合计4次派发，含2次新source复现、2个新经济对照；0拟合、0新上游数据。所有七年均已见，2026部分年不年化且保留原硬门。实现、实际事实、14/2汇总和四格表见 interaction_final_accounting_delivery.json 精确清单。
'''
    md = S.OUT / 'interaction_readout.md'
    with md.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print(json.dumps({'findings': S.ref(path), 'readout': S.ref(md), 'checks': result['independent_actual_checks'], 'phase_checks': result['independent_phase_checks'], 'margin': margin}))


if __name__ == '__main__':
    main()
