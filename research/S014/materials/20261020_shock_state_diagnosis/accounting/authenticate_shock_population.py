"""Original C9461 funded selected-SHOCK census only; no new action labels."""
from collections import Counter
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
CHECKS = Counter()


def deny(*args, **kwargs):
    raise RuntimeError('Population-only review forbids market/network/replay')


socket.socket.connect = deny
socket.create_connection = deny


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def day(value):
    return str(value)[:10]


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def read(path):
    return json.loads(path.read_bytes())


def published(value):
    reference = EvidenceRef.from_dict(value)
    raw = reference.resolve(ROOT).read_bytes()
    check('formal S014 exact immutable evidence', reference.experiment.strategy_id == 'S014' and sha256(raw).hexdigest() == reference.sha256)
    return json.loads(raw)


def save(name, value, is_csv=False):
    path = OUT / name
    if is_csv:
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=list(dict.fromkeys(k for r in value for k in r)))
        writer.writeheader()
        writer.writerows(value)
        content = buffer.getvalue().encode('utf-8')
    else:
        content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(content)
    return {**ref(path), **({'rows': len(value)} if is_csv else {})}


def main():
    previous_path = ROOT / 'research/S014/materials/20261020_preentry_diagnosis/accounting/pause_account_001_independent_review.json'
    check('original C9461 independent audit exact', ref(previous_path)['sha256'] == 'aa8c448637c66ee42fd3882f7bb009f74a884e0c14ad8bf3579df2a887e05ce3')
    previous = read(previous_path)
    receipt_path = ROOT / 'research/S014/experiments/EX046_20261020/others/accounts/run-001.json'
    receipt = read(receipt_path)
    account = published(receipt['evidence'])
    check('original actual C9461 authenticated', previous['status'] == 'PASS' and previous['parameters'] == receipt['parameters'] == {'pause_profile': 'AFTER_NET_LOSS_SKIP1'} and previous['account_ref'] == receipt['evidence'])
    check('original actual result hash', account['result_hash'] == previous['result_hash'] == receipt['result_hash'] == 'a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb')
    check('original exact account ref', receipt['evidence']['sha256'] == '935b74f311a04b11e494d7adea80c7c9d1badb7776706e0761a77679dc8751e0')
    binding = published(receipt['binding_ref'])
    check('pinned prepared data fingerprint bound', binding['execution_fingerprint'] == account['request_identity']['data_identity'])
    source = ROOT / 'research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py'
    check('fixed C9461 original source exact', ref(source)['sha256'] == previous['source_sha256'] == '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846')
    check('original pricing anchor and cost', account['request_identity']['pricing']['anchor_factor'] == 5.892 and account['request_identity']['costs'][0]['one_way_cost'] == .001)
    run = account['runs'][0]
    ledger = run['ledgers']
    decisions = ledger['decisions']['data']
    daily = {day(r['date']): r for r in ledger['account_daily']['data']}
    fills = {day(r['fill_time']): r for r in ledger['fills']['data']}
    orders = {day(r['signal_date']): r for r in ledger['orders']['data']}
    trade_by_cycle = {r['cycle_id']: r for r in ledger['trades']['data']}
    actual_entries = {r['entry_index']: fills[day(r['signal_date'])] for r in decisions if r['buy_filled_today']}
    selected = [r for r in decisions if r['selected_shock_exit']]
    first = {}
    population = []
    for row in selected:
        D, E = day(row['signal_date']), day(row['valid_session'])
        held = daily[D]
        buy = actual_entries[row['entry_index']]
        order, fill = orders.get(D), fills.get(E)
        cycle = buy['cycle_id']
        check('selected actual positive funded held inventory', row['held_at_close'] and held['quantity'] > 0 and held['quantity'] == buy['quantity'])
        check('original positive-P SHOCK eligible and sole variant', row['profit_exit_eligible'] and row['shock_condition'] and row['selected_profit_exit'] and row['net_profit'] > 0 and row['shock_known'] and row['z5'] > 2)
        check('D known actual age/deadline/reserve', row['holding_age'] == row['warmup_sessions'] - row['entry_index'] and row['deadline_index'] == row['entry_index'] + 9 and row['reservation_index'] == row['entry_index'] + 10)
        check('original live SELL target maps valid next session', order is not None and order['side'] == 'SELL' and day(order['execution_date']) == E and row['target_position'] == 0 and row['exit_pending'])
        check('actual SELL order fill identity and funds', fill is not None and fill['order_id'] == order['order_id'] and fill['side'] == 'SELL' and fill['cycle_id'] == cycle and fill['quantity'] == held['quantity'] and order['status'] == 'FILLED')
        trade = trade_by_cycle[cycle]
        check('original actual entry exit closed trade exact', trade['status'] == 'CLOSED' and day(trade['entry_date']) == day(buy['fill_time']) and day(trade['exit_date']) == E)
        first.setdefault(cycle, D)
        population.append({'population': 'ORIGINAL_C9461_ACTUAL_SELECTED_SHOCK', 'event_id': f'C9461-SHOCK-{D}', 'cycle_id': cycle,
                           'D': D, 'year_of_D': int(D[:4]), 'valid_E': E, 'first_selected_SHOCK_D_this_actual_cycle': first[cycle],
                           'actual_entry_order_D': day(buy['signal_date']), 'actual_entry_fill_E': day(buy['fill_time']),
                           'actual_entry_order_id': buy['order_id'], 'actual_entry_fill_id': buy['fill_id'],
                           'actual_entry_price_ledger': buy['price'], 'actual_entry_quantity': buy['quantity'], 'actual_entry_fee': buy['fees'],
                           'actual_held_quantity_D': held['quantity'], 'D_equity': held['equity'], 'D_cash': held['cash'],
                           'entry_index': row['entry_index'], 'D_market_index': row['warmup_sessions'], 'holding_age_D': row['holding_age'],
                           'deadline_index': row['deadline_index'], 'remaining_D_sessions_to_deadline': row['deadline_index'] - row['warmup_sessions'],
                           'reservation_index': row['reservation_index'], 'reservation_minus_D_index': row['reservation_index'] - row['warmup_sessions'],
                           'D_net_profit': row['net_profit'], 'D_z5': row['z5'], 'D_raw_selected_profit_exit': row['selected_profit_exit'],
                           'D_selected_cost_exit': row['selected_cost_exit'], 'D_ordinary_support_exit': row['ordinary_support_exit'],
                           'D_pending_inherited': row['pending_inherited'], 'D_deadline_exit': row['deadline_exit'],
                           'D_ma20_prior_RUNTIME_HFQ': row['ma20_prior'], 'D_ma20_prior_lag5_RUNTIME_HFQ': row['ma20_prior_lag5'],
                           'D_atr20_prior_RUNTIME_HFQ': row['atr20_prior'], 'D_shock_known': row['shock_known'],
                           'actual_exit_order_id': order['order_id'], 'actual_exit_fill_id': fill['fill_id'],
                           'actual_exit_fill_E': E, 'actual_exit_price_ledger': fill['price'], 'actual_exit_quantity': fill['quantity'], 'actual_exit_fee': fill['fees'],
                           'actual_exit_fill_trigger': fill['trigger'], 'actual_exit_order_status': order['status'],
                           'price_representation': 'HFQ_RESEARCH_ANCHORED_2019_12_31_FACTOR5_892',
                           'quantity_representation': 'RESEARCH_UNIT'})
    counts = Counter(r['year_of_D'] for r in population)
    annual = [{'year': year, 'actual_selected_SHOCK_D': counts[year], 'distinct_actual_funded_cycles': len({r['cycle_id'] for r in population if r['year_of_D'] == year}),
               'zero_population_preserved': counts[year] == 0} for year in range(2020, 2027)]
    check('complete original population not chosen case subset', len(population) == len(selected))
    check('one first SHOCK per actual cycle no repeated daily sample', len(population) == len(first))
    check('completeyear selected counts match preexisting original audit', all(counts[y] == previous['lifecycle']['annual_D_counts'][str(y)]['selected_shock_exit'] for y in range(2020, 2026)))
    outputs = [save('original_shock_population.csv', population, True), save('original_shock_population_yearly.csv', annual, True)]
    result = {'status': 'PASS_ORIGINAL_ACTUAL_POPULATION_ONLY', 'source_candidate': 'S014-C9461', 'source_account_ref': receipt['evidence'],
              'result_hash': account['result_hash'], 'source_receipt': ref(receipt_path), 'original_independent_audit': ref(previous_path), 'original_source': ref(source),
              'binding_ref': receipt['binding_ref'], 'execution_prepared': binding['execution_prepared'], 'execution_requests': binding['execution_requests'],
              'execution_identities': binding['execution_identities'], 'execution_fingerprint': binding['execution_fingerprint'],
              'original_request_pricing': account['request_identity']['pricing'], 'outputs': outputs,
              'N_selected_D': len(population), 'N_distinct_actual_cycles': len(first), 'yearly': annual,
              'holding_age_distribution': dict(Counter(r['holding_age_D'] for r in population)),
              'actual_exit_fill_trigger_counts': dict(Counter(r['actual_exit_fill_trigger'] for r in population)),
              'overlap_counts': {k: sum(bool(r[k]) for r in population) for k in ['D_selected_cost_exit', 'D_ordinary_support_exit', 'D_pending_inherited', 'D_deadline_exit']},
              'implementation': ref(Path(__file__).resolve()), 'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()),
              'resources': {'new_accounts': 0, 'new_fits': 0, 'supplier_calls': 0, 'prepared_fetches': 0, 'source_replays': 0, 'new_alternative_labels': 0},
              'limits': ['All original2020-26 actual selectedSHOCK cycles included, even years with no events; no2025/26 or matched-OFF entry filter.',
                         'Actual order/fill and firstD are facts. No alternative holding outcome, state-by-outcome selection or label computed.',
                         'Runtime state price columns are fullHFQ while actual ledger/fill prices use anchor5.892; quantity is research unit. Do not mix monetary units.',
                         'A funded single-cycle alternative is only a component counterfactual; original future entry eligibility and cash paths are not fixed under a real changed policy.']}
    print(json.dumps({'review': save('original_shock_population_review.json', result), 'N': len(population), 'yearly': annual, 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
