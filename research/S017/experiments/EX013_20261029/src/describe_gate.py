"""Describe actual market-gate decisions; do not infer an alternative account."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import json

from analyze import EXPERIMENT, WORK, load_accounts, save


def describe(payload, reference):
    run = payload['runs']['candidate']
    decisions = {row['decision_id']: row for row in run['decisions']}
    orders = {row['order_id']: row for row in run['orders']}
    if len(decisions) != len(run['decisions']) or len(orders) != len(run['orders']):
        raise ValueError('duplicate decision or order identity')
    reasons, intentions, suppressed = {}, Counter(), 0
    for identity, row in decisions.items():
        if row['signal_status'] != 'EVALUATED':
            suppressed += 1
            continue
        facts = {item['key']: item['text'] for item in row['explanation']['basis']}
        for field in ('held', 'base_target', 'market_allowed'):
            if facts[field] not in ('True', 'False'):
                raise ValueError('nonboolean decision fact: ' + field)
        if facts['held'] == 'True' and row['target'] == 0:
            stock = facts['base_target'] == 'False'
            market = facts['market_allowed'] == 'False'
            if not (stock or market):
                raise ValueError('unexplained exit request')
            reason = 'BOTH' if stock and market else 'STOCK_ONLY' if stock else 'MARKET_ONLY'
            reasons[identity] = reason
            intentions[reason] += 1
    fills, counts, years = [], Counter(), {}
    for fill in run['fills']:
        if fill['side'] != 'SELL':
            continue
        identity = orders[fill['order_id']]['decision_id']
        reason = reasons[identity]
        year = fill['interval_start'][:4]
        counts[reason] += 1
        years.setdefault(year, Counter())[reason] += 1
        fills.append({'reason': reason, 'decision_id': identity, 'fill': fill})
    if len(fills) != run['metrics']['closed_cycles']:
        raise ValueError('whole-cycle exit count differs from authenticated metrics')
    output = {
        'status': 'PASS', 'schema': 's017-market-gate-usage/v1',
        'source_account': reference.to_dict(),
        'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'exit_intentions': dict(intentions), 'actual_sell_fills': dict(counts),
        'actual_sell_fills_by_year': {year: dict(value) for year, value in years.items()},
        'suppressed_decisions': suppressed, 'fills': fills,
        'semantics': 'MARKET_ONLY means an actual held position was sold when LITE base_target remained true and market_allowed was false. Counts are linked through exact order/decision identities.',
        'limitations': [
            'Describes the already published C0040 account, not hypothetical profit after removing exits.',
            'Signal intentions can repeat before execution; actual sell fills are counted separately.',
            'No claim that these exits caused the net performance difference; public paired diagnosis remains required.',
        ],
    }
    return output


def main():
    payloads, references = load_accounts(WORK, EXPERIMENT, ('C0040',))
    output = describe(payloads['C0040'], references['C0040'])
    save(WORK / 'others/market_gate_usage.json', output)
    print(json.dumps({key: output[key] for key in ('status', 'exit_intentions', 'actual_sell_fills', 'actual_sell_fills_by_year')}))


if __name__ == '__main__':
    main()
