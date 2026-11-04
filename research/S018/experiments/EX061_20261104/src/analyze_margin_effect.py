"""Compare the authenticated C9101/C9142 ledgers; never evaluate accounts."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity


ROOT = Path.cwd()
EXPERIMENT = Path(__file__).resolve().parent.parent


def load(record):
    ref = d.EvidenceRef.from_dict(record['account_ref'])
    path = ref.resolve(ROOT)
    data = path.read_bytes()
    assert sha256(data).hexdigest() == ref.sha256

    def artifact(value):
        content = (path.parent / (value['sha256'] + '.json')).read_bytes()
        assert sha256(content).hexdigest() == value['sha256']
        return content

    return materialize_equity(data, artifact).payload['runs']['candidate']


def cycles(run):
    fills = defaultdict(list)
    for fill in run['fills']:
        fills[fill['cycle_id']].append({k: fill[k] for k in
            ('interval_start', 'interval_end', 'side', 'price', 'quantity', 'fees')})
    assert all(t['status'] == 'CLOSED' for t in run['trades'])
    return {t['entry_at']: dict(trade=t, fills=fills[t['cycle_id']]) for t in run['trades']}


def buy_path(cycle):
    return [(f['interval_start'], f['price']) for f in cycle['fills'] if f['side'] == 'BUY']


def main():
    records = json.loads((EXPERIMENT / 'others/results.json').read_text(encoding='utf-8'))['accounts']
    ids = ['C9101', 'C9142']
    runs = {c: load(records[c]) for c in ids}
    paired = {c: cycles(runs[c]) for c in ids}
    assert paired[ids[0]].keys() == paired[ids[1]].keys()
    changed, scaling, unchanged = [], [], 0
    for entry in paired[ids[0]]:
        a, b = [paired[c][entry] for c in ids]
        assert a['trade']['exit_at'] == b['trade']['exit_at']
        row = dict(entry_at=entry, exit_at=a['trade']['exit_at'],
            original=a, margin=b,
            net_pnl_delta=b['trade']['net_pnl']-a['trade']['net_pnl'],
            net_return_delta=b['trade']['net_return']-a['trade']['net_return'])
        if buy_path(a) != buy_path(b):
            old_buys = [f for f in a['fills'] if f['side'] == 'BUY']
            new_buys = [f for f in b['fills'] if f['side'] == 'BUY']
            # These three paths omit one completed add and keep the same exit.
            # Value that actual omitted lot at its realized exit, separately from
            # subsequent capital compounding and integer share-size differences.
            assert len(old_buys) == 2 and len(new_buys) == 1
            added, sold = old_buys[1], a['fills'][-1]
            assert sold['side'] == 'SELL'
            assert not any(v['kind'] == 'CASH_DIVIDEND'
                and added['interval_start'] <= v['time'] <= sold['interval_end']
                for v in runs[ids[0]]['actions'])
            omitted_pnl = added['quantity']*(sold['price']-added['price'])-added['fees']-sold['fees']*added['quantity']/sold['quantity']
            row['omitted_original_add_lot_net_pnl'] = omitted_pnl
            row['saving_from_omitting_lot_before_reinvestment'] = -omitted_pnl
            changed.append(row)
        elif a['fills'] != b['fills']:
            scaling.append(row)
        else:
            unchanged += 1
    a, b = [runs[c] for c in ids]
    equity_delta = b['account_daily'][-1]['equity']-a['account_daily'][-1]['equity']
    direct_pnl = sum(v['net_pnl_delta'] for v in changed)
    scale_pnl = sum(v['net_pnl_delta'] for v in scaling)
    assert abs(equity_delta-direct_pnl-scale_pnl) < 1e-6
    actions = []
    orders = {}
    for c in ids:
        orders[c] = defaultdict(list)
        for order in runs[c]['orders']:
            orders[c][order['decision_id']].append({k: order[k] for k in
                ('side', 'quantity', 'limit_price', 'status')})
    for left, right in zip(a['decisions'], b['decisions'], strict=True):
        assert left['decision_at'] == right['decision_at']
        lf, rf = [{x['key']: x['text'] for x in dec['explanation']['basis']} for dec in (left, right)]
        lo, ro = orders[ids[0]][left['decision_id']], orders[ids[1]][right['decision_id']]
        if lf['confirmation'] != rf['confirmation'] and (lo or ro):
            actions.append(dict(decision_at=left['decision_at'], observed_through=left['observed_through'],
                original_facts=lf, margin_facts=rf, original_orders=lo, margin_orders=ro))
    result = dict(status='PASS', accounts={c: dict(config=records[c]['config'],
        account_ref=records[c]['account_ref'], metrics=records[c]['candidate']) for c in ids},
        counts=dict(cycles=len(paired[ids[0]]), changed_buy_timing_or_presence=len(changed),
            unchanged_buy_timing_quantity_or_fees_changed=len(scaling), exact_unchanged_cycles=unchanged),
        final_equity_delta=equity_delta,
        net_pnl_delta_on_changed_buy_path_cycles=direct_pnl,
        net_pnl_delta_on_same_buy_path_cycles=scale_pnl,
        saving_from_omitted_lots_before_reinvestment=sum(v['saving_from_omitting_lot_before_reinvestment'] for v in changed),
        changed_buy_path_cycles=changed, same_buy_path_changed_size_cycles=scaling,
        confirmation_difference_with_orders=actions,
        interpretation='Entry and exit dates match for every cycle. Changed buy paths identify direct execution changes from the margin. Same-path size/fee differences include reinvested-capital and integer-sizing effects. The PnL grouping exactly reconciles final wealth, but is descriptive, not a fixed-capital causal decomposition.',
        account_runs=0)
    output = EXPERIMENT / 'others/analysis_margin_effect.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in
        ('accounts', 'changed_buy_path_cycles', 'same_buy_path_changed_size_cycles', 'confirmation_difference_with_orders')}, ensure_ascii=False, indent=2))
    for row in changed:
        print(row['entry_at'], 'original', buy_path(row['original']), 'margin', buy_path(row['margin']),
              'pnl_delta', row['net_pnl_delta'], 'return_delta', row['net_return_delta'])


if __name__ == '__main__':
    main()
