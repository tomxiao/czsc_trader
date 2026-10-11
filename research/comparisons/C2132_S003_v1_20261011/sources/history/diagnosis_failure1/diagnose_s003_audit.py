"""Read-only public ReplayEvidence audit of the single authorized S003 center."""
from hashlib import sha256
from pathlib import Path
from decimal import Decimal, ROUND_FLOOR
import json

from czsc_trader.research_tools import EvidenceRef
from strategy_evaluator import ReplayEvidence, audit_replay, hash_replay_evidence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
receipts_path = ROOT / 'research/comparisons/C2132_S003_v1_20261011/account_receipts.json'
receipts_raw = receipts_path.read_bytes()
receipts = json.loads(receipts_raw)
selected = [item for item in receipts if item['family'] == 'S003']
assert len(selected) == 1
reference = EvidenceRef.from_dict(selected[0]['center'])
assert reference.experiment.strategy_id == 'S003'
source = reference.resolve(ROOT)
raw = source.read_bytes()
assert sha256(raw).hexdigest() == reference.sha256
value = json.loads(raw)
assert len(value['runs']) == 1
run = value['runs'][0]
replay = ReplayEvidence.from_dict(run['replay_evidence'])
audit = audit_replay(replay)
decisions = {row['decision_id']: row for row in replay.decisions}
daily = {str(row['date'])[:10]: row for row in replay.execution_daily}
accounts = {str(row['date'])[:10]: row for row in replay.account_daily}
bars = {str(row['time'])[:16]: row for row in replay.execution_intraday}
fills = {row['order_id']: row for row in replay.fills}
fee = replay.execution_spec['fee_rate']


def floor_tick(price):
    return float((Decimal(str(price)) / Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.001'))


limit_findings, fill_field_failures, unfilled = [], [], []
groups = {}
for order in replay.orders:
    decision = decisions[order['decision_id']]
    groups.setdefault(order['decision_id'], []).append(order)
    day = str(order['execution_date'])[:10]
    signal = daily[str(order['signal_date'])[:10]]
    opening = bars[day + 'T09:35']['open']
    reference = opening if order['checkpoint'] == 'OPEN' else bars[day + 'T11:30']['close']
    expected_limit = floor_tick(float(signal['unadjusted_close']) * 1.10) * float(signal['price_scale'])
    audit_limit = floor_tick(float(signal['close']) * 1.10)
    correct_limit = order['side'] != 'BUY' or abs(order['limit_price'] - expected_limit) <= 1e-7
    fill = fills.get(order['order_id'])
    if fill is not None:
        checks = {
            'side': fill['side'] == order['side'], 'quantity': fill['quantity'] == order['quantity'],
            'type': order['order_type'] == ('LIMIT' if order['side'] == 'BUY' else 'MARKET'),
            'checkpoint_price': abs(fill['price'] - reference) <= 1e-7,
            'fee': abs(fill['fees'] - order['quantity'] * reference * fee) <= 1e-7,
            'raw_grid_hfq_limit': correct_limit,
            'time': str(fill['fill_time'])[:16] == day + ('T09:30' if order['checkpoint'] == 'OPEN' else 'T11:30'),
            'trigger': fill['trigger'] == order['checkpoint'],
        }
        if not all(checks.values()):
            fill_field_failures.append({'order': order, 'fill': fill, 'checks': checks})
        if order['side'] == 'BUY' and abs(order['limit_price'] - audit_limit) > 1e-7:
            limit_findings.append({'order_id': order['order_id'], 'signal_date': order['signal_date'],
                'execution_date': order['execution_date'], 'actual_limit': order['limit_price'],
                'public_audit_hfq_grid_limit': audit_limit, 'raw_close': signal['unadjusted_close'],
                'signal_price_scale': signal['price_scale'], 'correct_raw_grid_then_hfq_limit': expected_limit,
                'checks_except_public_hfq_grid_all_pass': all(checks.values()), 'checks': checks})
    else:
        account = accounts[day]
        same_day_fills = [row for row in replay.fills if str(row['fill_time'])[:10] == day]
        same_day_trades = [row for row in replay.trades if str(row['entry_date'])[:10] == day]
        cash_affordable = order['quantity'] * opening * (1 + fee) <= account['cash_before'] + 1e-8
        unfilled.append({'order': order, 'decision': decision, 'opening_5m_quote': opening,
            'correct_limit': expected_limit, 'public_audit_hfq_grid_limit': audit_limit,
            'raw_close': signal['unadjusted_close'], 'signal_price_scale': signal['price_scale'],
            'price_condition': opening <= order['limit_price'], 'cash_affordable_at_quote': cash_affordable,
            'can_fill_at_open': opening <= order['limit_price'] and cash_affordable,
            'same_day_fills': same_day_fills, 'same_day_trades': same_day_trades,
            'account_row': account,
            'cash_quantity_unchanged': account['cash_before'] == account['cash'] and account['quantity_before'] == account['quantity'],
            'correct_raw_grid_hfq_limit': correct_limit})
invalid_pairs = []
for decision_id, orders in groups.items():
    if decisions[decision_id]['plan_mode'] != 'CORE_SETUP' and len(orders) != 2:
        invalid_pairs.append({'decision': decisions[decision_id], 'orders': orders,
                              'interpretation': 'Entry UNFILLED means exit dependency cannot become FILLED_ALL; HistoricalExecutor blocks and does not submit exit.'})
result = {
    'status': 'READONLY_PUBLIC_AUDIT_DIAGNOSIS',
    'reference': reference.to_dict(), 'published_bytes_sha256': reference.sha256,
    'receipts_sha256': sha256(receipts_raw).hexdigest(),
    'request_hash': value['request_hash'], 'result_hash': value['result_hash'],
    'window_id': run['window_id'], 'scenario_id': run['scenario_id'],
    'request_execution_mode': value['execution_mode'],
    'replay_execution_spec': dict(replay.execution_spec),
    'public_audit': audit.to_dict(),
    'center_findings': {
        'public_hfq_grid_limit_mismatches': limit_findings,
        'public_hfq_grid_limit_mismatch_count': len(limit_findings),
        'actual_fill_field_failures': fill_field_failures,
        'all_fill_side_quantity_type_price_fee_time_trigger_and_correct_limit_pass': not fill_field_failures,
        'unfilled_orders': unfilled,
        'single_leg_decisions_public_pair_rejected': invalid_pairs,
        'no_hidden_account_metric_trade_reason': set(audit.reason_codes) == {
            'INTRADAY_ORDER_NOT_FILLED', 'INVALID_INTRADAY_ORDER_PAIR', 'INTRADAY_FILL_MISMATCH'},
    },
    'replay_content_hash_declared': replay.content_hash,
    'replay_content_hash_computed': hash_replay_evidence(replay),
    'counts': {key: len(getattr(replay, key)) for key in
               ['evaluation_sessions', 'decisions', 'orders', 'fills', 'account_daily',
                'trades', 'execution_daily', 'execution_intraday']},
    'schema_fields': {key: sorted(getattr(replay, key)[0]) if getattr(replay, key) else []
                      for key in ['decisions', 'orders', 'fills', 'account_daily', 'trades']},
    'public_source_sha256': sha256((ROOT / 'packages/strategy_evaluator/src/strategy_evaluator/replay_audit.py').read_bytes()).hexdigest(),
    'diagnostic_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    'account_evaluations': 0, 'account_preparations': 0, 'market_reads': 0,
    'account_sources_read': 1, 'financial_source_changes': 0, 'platform_changes': 0,
}
(HERE / 's003_audit_diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'public_audit': result['public_audit'], 'mismatch_count': len(limit_findings),
                  'actual_fill_failures': fill_field_failures, 'unfilled': unfilled,
                  'single_leg_decisions': invalid_pairs, 'first_limit_mismatch': limit_findings[:1]},
                  ensure_ascii=False, indent=2))
