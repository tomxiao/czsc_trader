"""Saved 2025 R/B/P account facts and original decision clocks; no branch wealth labels."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import socket

import pandas as pd

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()

def block(*args, **kwargs):
    raise RuntimeError('No external calls permitted')

socket.socket.connect = block
socket.create_connection = block

def publish(value):
    ref = EvidenceRef.from_dict(value)
    assert ref.experiment.strategy_id == 'S014'
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    return raw

def day(value):
    return str(value)[:10]

def dump(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

def posture(row):
    return 'PLAN_BUY' if row['entry_signal'] else 'PLAN_SELL' if row['held_at_close'] and row['exit_pending'] else 'HOLD' if row['held_at_close'] else 'FLAT'

def run(out):
    out = out.resolve()
    assert out.is_dir(), 'Create the intended materials/accounting directory first'
    warning_lock = json.loads((ROOT / 'research/S014/materials/20261019_year_driver_research/warning_lock.json').read_bytes())
    events_ref = warning_lock['events']
    events = [e for e in json.loads(publish(events_ref))['events'] if e['publication_date'].startswith('2025')]
    assert len(events) == 3
    accounts, timeline = [], []
    for experiment, candidate, label in [('EX023_20261018', 'S014-C0056', 'R'),
                                          ('EX023_20261018', 'S014-C0034', 'B'),
                                          ('EX024_20261018', 'S014-C0057', 'P')]:
        index = ROOT / 'research/S014/experiments' / experiment / 'others/comparison_accounts.json'
        record = next(x for x in json.loads(index.read_bytes())['records'] if x['candidate'] == candidate)
        account = json.loads(publish(record['evidence']))
        assert len(account['runs']) == 1 and account['result_hash'] == record['result_hash']
        pricing = account['request_identity']['pricing']
        assert pricing == {'anchor_date': '2019-12-31', 'anchor_factor': 5.892,
                           'basis': 'HFQ_RESEARCH', 'quantity_unit': 'RESEARCH_UNIT'}
        original = account['runs'][0]
        ledgers = original['ledgers']
        daily = ledgers['account_daily']['data']
        decisions = ledgers['decisions']['data']
        by_date = {day(x['date']): x for x in daily}
        cal = [day(decisions[0]['signal_date'])] + list(by_date)
        assert len(cal) == 1643 and len(set(cal)) == len(cal)
        orders = ledgers['orders']['data']
        by_decision = {x['decision_id']: x for x in orders}
        fills = ledgers['fills']['data']
        by_order = {x['order_id']: x for x in fills}
        assert len(by_decision) == len(orders) and len(by_order) == len(fills)
        for name, date_key in [('account_daily', 'date'), ('decisions', 'valid_session'),
                               ('orders', 'execution_date'), ('fills', 'fill_time')]:
            selected = [x for x in ledgers[name]['data'] if day(x[date_key]).startswith('2025')]
            path = out / (label + '_2025_' + name + '.csv')
            assert not path.exists()
            pd.DataFrame(selected).to_csv(path, index=False, lineterminator='\n')
        saved_year = [x for x in daily if day(x['date']).startswith('2025')]
        assert len(saved_year) == 243
        opening_index = next(i for i, x in enumerate(daily) if day(x['date']).startswith('2025'))
        opening = daily[opening_index-1]['equity']
        end = saved_year[-1]['equity']
        annual_return = end / opening - 1
        bh = original['buyhold']['account_daily']['data']
        assert [day(x['date']) for x in bh] == list(by_date)
        bh_return = bh[opening_index+242]['equity'] / bh[opening_index-1]['equity'] - 1
        selected_decisions = [x for x in decisions if day(x['valid_session']).startswith('2025')]
        monthly = []
        for month in range(1, 13):
            indices = [i for i, x in enumerate(daily) if day(x['date']).startswith(f'2025-{month:02}')]
            pnl = daily[indices[-1]]['equity'] - daily[indices[0]-1]['equity']
            monthly.append({'month': f'2025-{month:02}', 'existing_actual_pnl': pnl,
                            'original_annual_contribution_pp': 100 * pnl / opening})
        for decision in decisions:
            D, E = day(decision['signal_date']), day(decision['valid_session'])
            if not ('2025-05-29' <= D <= '2025-07-03'):
                continue
            at_D = by_date[D]
            known = [e for e in events if e['availability']['decision_date_15_00'] <= D]
            plan = posture(decision)
            order = by_decision.get(decision['decision_id'])
            fill = by_order.get(order['order_id']) if order else None
            if plan in ['PLAN_BUY', 'PLAN_SELL']:
                assert order and day(order['signal_date']) == D and day(order['execution_date']) == E
                assert order['side'] == ('BUY' if plan == 'PLAN_BUY' else 'SELL')
            else:
                assert order is None
            assert bool(decision['held_at_close']) == (at_D['quantity'] > 0)
            assert decision['target_position'] == float(plan in ['PLAN_BUY', 'HOLD'])
            held = bool(decision['held_at_close'])
            age = int(decision['warmup_sessions'] - decision['entry_index']) if held else None
            deadline = int(decision['deadline_index']) if held else None
            original_planned_exit_D = cal[deadline] if deadline is not None else None
            original_planned_exit_E = cal[deadline+1] if deadline is not None else None
            timeline.append({'candidate': candidate, 'variant': label, 'D_signal_date': D, 'E_valid_session': E,
                             'posture': plan, 'source_action': decision['action'],
                             'D_cash': at_D['cash'], 'D_quantity': at_D['quantity'], 'D_close': at_D['close'], 'D_equity': at_D['equity'],
                             'held_at_close': decision['held_at_close'], 'entry_signal': decision['entry_signal'],
                             'exit_pending': decision['exit_pending'], 'entry_index': decision['entry_index'],
                             'deadline_index': decision['deadline_index'], 'reservation_index': decision.get('reservation_index'),
                             'warmup_sessions': decision['warmup_sessions'], 'known_holding_age_sessions': age,
                             'original_clock_exit_decision_date': original_planned_exit_D,
                             'original_clock_exit_execution_date': original_planned_exit_E,
                             'target_position': decision['target_position'], 'support_ok': decision['support_ok'],
                             'support_break': decision['support_break'], 'failed_buy_reset': decision['failed_buy_reset'],
                             'buy_filled_today': decision['buy_filled_today'], 'sell_filled_today': decision['sell_filled_today'],
                             'known_notice_ids': [e['doc_id'] for e in known],
                             'known_notice_publication_dates': [e['publication_date'] for e in known],
                             'known_notice_conservative_D_dates': [e['availability']['decision_date_15_00'] for e in known],
                             'actual_original_order': order, 'actual_original_fill': fill})
        relevant_trades = [x for x in ledgers['trades']['data'] if '2025-05-25' <= day(x['entry_date']) <= '2025-07-03']
        accounts.append({'candidate': candidate, 'variant': label, 'account_evidence': record['evidence'],
                         'result_hash': account['result_hash'], 'pricing': pricing,
                         'source_request_hash': account['request_hash'],
                         'year_2025': {'calendar_days': 243, 'opening_equity': opening, 'closing_equity': end,
                                       'original_return': annual_return, 'original_buyhold_return': bh_return,
                                       'required_return': 1.5 * bh_return, 'return_gap_to_original_target_pp': 100 * (1.5 * bh_return - annual_return),
                                       'first_day_quantity_before': saved_year[0]['quantity_before'],
                                       'last_day_quantity': saved_year[-1]['quantity'],
                                       'D_posture_counts_by_E_year': dict(Counter(posture(x) for x in selected_decisions)),
                                       'monthly_existing_actual_pnl': monthly},
                         'selected_existing_whole_trades_may_cross_months': relevant_trades,
                         'ledger_inventory': {name: {'rows_full': len(value['data']), 'fields': list(value['data'][0]) if value['data'] else []}
                                              for name, value in ledgers.items()}})
    key_nodes = [x for x in timeline if x['D_signal_date'] in ['2025-05-30', '2025-06-03', '2025-06-13', '2025-06-16', '2025-06-17', '2025-06-18', '2025-06-19', '2025-06-20', '2025-06-25', '2025-06-26', '2025-07-02', '2025-07-03']]
    dump(out / 'original_account_source_inventory.json', {'status': 'READ_ONLY_2025_ORIGINAL_ACCOUNT_FACTS',
         'accounts': accounts, 'notice_inventory_evidence': events_ref, 'known_clock_events_2025': events,
         'limits': ['The table records original continuous-account outcomes and original decisions; no alternate branch matching, wealth estimate, or hypothetical local return label.',
                    'B and P share many actual entry dates/prices with R but quantities/cash differ; their account outcomes cannot be spliced into a local R state.',
                    'Annual/monthly money refers to calendar dates; stored whole-trade returns can cross months or years.',
                    'Known notice lists are cumulative disclosure availability facts, not a newly optimized W window.'],
         'new_fits': 0, 'new_accounts': 0, 'new_counterfactual_return_labels': 0, 'new_market_data_calls': 0})
    dump(out / 'original_D_node_facts.json', {'status': 'ORIGINAL_DECISION_ORDER_FILL_CLOCK_FACTS_ONLY',
         'account_evidence_refs': [a['account_evidence'] for a in accounts], 'notice_inventory_evidence': events_ref,
         'all_saved_D_nodes_20250529_20250703': timeline, 'key_nodes': key_nodes,
         'new_fits': 0, 'new_accounts': 0, 'new_counterfactual_return_labels': 0})
    flat = []
    for item in timeline:
        row = {key: value for key, value in item.items() if key not in ['actual_original_order', 'actual_original_fill']}
        for key, value in list(row.items()):
            if isinstance(value, list):
                row[key] = '|'.join(value)
        order, fill = item['actual_original_order'], item['actual_original_fill']
        for name, value in [('order_id', None if order is None else order['order_id']),
                            ('order_status', None if order is None else order['status']),
                            ('order_reason', None if order is None else order['reason']),
                            ('order_side', None if order is None else order['side']),
                            ('order_quantity', None if order is None else order['quantity']),
                            ('order_limit_price', None if order is None else order['limit_price']),
                            ('fill_id', None if fill is None else fill['fill_id']),
                            ('fill_price', None if fill is None else fill['price']),
                            ('fill_fees', None if fill is None else fill['fees'])]:
            row[name] = value
        flat.append(row)
    assert not (out / 'original_D_node_facts.csv').exists()
    pd.DataFrame(flat).to_csv(out / 'original_D_node_facts.csv', index=False, lineterminator='\n')
    print(json.dumps({'status': 'READ_ONLY_FACT_INVENTORY_COMPLETE', 'accounts': len(accounts), 'D_nodes': len(timeline),
                      'year_returns': {a['variant']: a['year_2025']['original_return'] for a in accounts},
                      'output': str(out.relative_to(ROOT))}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='Existing directory with no colliding result files')
    run(parser.parse_args().output_dir)
