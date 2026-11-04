"""Audit published staged-entry accounts without evaluating or publishing accounts.

Usage: python .tmp/s018_supplement/audit.py EX058_20261104 [EX059_20261104 ...]
       --output .tmp/s018_supplement/analysis_audit.json

All OHLC, auxiliary histories, corporate actions and execution settings come from
each authenticated account's audit_inputs. No provider access or replay engine is
used. Missing new parameters are interpreted only as the documented C8612 legacy
defaults so the existing center can also be checked with this same audit.
"""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity


ROOT = Path.cwd()
FAMILY = ROOT/'research/S018'
EXTENDED_DEFAULTS = dict(beta_window=60, entry_days=2, exit_margin=0.0,
                         add_mu_margin=0.0, add_sector_margin=0.0)
BASE_PARAMETERS = {'common_share', 'common_budget', 'other_budget', 'review_after',
                   'max_hold', 'add_mode', 'initial_fraction', 'earliest_add'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def normalize_parameters(config):
    assert set(config) <= BASE_PARAMETERS | set(EXTENDED_DEFAULTS), ('unaudited parameters', set(config))
    assert BASE_PARAMETERS <= set(config), ('missing parameters', config)
    p = {**EXTENDED_DEFAULTS, **config}
    for key in ('beta_window', 'entry_days', 'review_after', 'max_hold', 'earliest_add'):
        assert type(p[key]) is int and p[key] > 0, (key, p[key])
    assert p['beta_window'] >= 2
    assert p['add_mode'] in ('repair', 'repair_both', 'scheduled', 'weakness', 'never')
    assert all(math.isfinite(p[k]) and p[k] > -1 for k in ('exit_margin', 'add_mu_margin', 'add_sector_margin'))
    assert 0 < p['initial_fraction'] <= 1
    assert all(0 <= p[k] <= 1 for k in ('common_budget', 'other_budget'))
    return p


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def approx(actual, expected, context):
    assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8), (context, actual, expected)


def load_record(experiment, candidate):
    result = read(FAMILY/'experiments'/experiment/'others/results.json')
    return result['accounts'][candidate]


def load_payload(record):
    reference = d.EvidenceRef.from_dict(record['account_ref'])
    path = reference.resolve(ROOT)
    content = path.read_bytes()
    assert sha256(content).hexdigest() == reference.sha256

    def artifact(value):
        data = (path.parent/(value['sha256']+'.json')).read_bytes()
        assert sha256(data).hexdigest() == value['sha256']
        return data

    return materialize_equity(content, artifact).payload


def economic_rows(rows):
    return [{k: v for k, v in row.items() if not k.endswith('_id')} for row in rows]


def audit_account(cid, record, payload):
    p = normalize_parameters(record['config'])
    definition = record['definition']
    assert json.loads(definition['parameters_json']) == record['config']
    assert payload['request']['candidate_definition'] == definition
    inputs = payload['audit_inputs']
    run = payload['runs']['candidate']
    spec = inputs['specification']
    assert spec == definition['execution_spec']
    assert spec['account']['cash_availability'] == 'IMMEDIATE_RESEARCH'
    assert spec['price_tick'] == .01 and spec['quantity_step'] == 1
    assert spec['buy_premium'] == .01 and spec['slippage_bp'] == 0
    assert spec['inclusive_touch'] is False
    fee = float(inputs['fee_rate'])
    assert fee == .001
    cash = float(inputs['initial_cash'])
    assert cash == 100000.
    quantity, receivable = 0, 0.
    raw_rows = inputs['bars']
    auxiliary = inputs['decision_inputs']['auxiliary']
    mu_rows, sector_rows = auxiliary['mu_hfq']['bars'], auxiliary['soxx_hfq']['bars']
    dates = [r['Date'] for r in raw_rows]
    assert dates == sorted(dates) and len(dates) == len(set(dates))
    assert dates == [r['Date'] for r in mu_rows] == [r['Date'] for r in sector_rows]
    index = {value: i for i, value in enumerate(dates)}
    raw = {r['Date'][:10]: r for r in raw_rows}
    mu = np.array([r['Close'] for r in mu_rows], dtype=float)
    sector = np.array([r['Close'] for r in sector_rows], dtype=float)
    w, n = p['beta_window'], p['entry_days']
    history_size = max(63, w+n+1, p['max_hold']+1)
    assert definition['warmup_bars'] >= history_size
    assert all(a['warmup_bars'] >= history_size for a in definition['auxiliary_inputs'])
    assert all(x['kind'] != 'SPLIT' for x in run['actions']), 'This frozen MU window has no split; do not silently audit a new action contract.'

    orders, fills = {}, {}
    for order in run['orders']:
        orders.setdefault(order['decision_id'], []).append(order)
    for fill in run['fills']:
        fills.setdefault(fill['order_id'], []).append(fill)
    assert len(run['decisions']) == len(run['account_daily'])
    prevtime = None
    entry_interval_start = anchor = sector_anchor = budget = cycle_id = None
    nbuys = 0
    cyclecost = cycleincome = 0.
    cycle_records = {}
    tally = Counter()
    betas = []
    for decision, daily in zip(run['decisions'], run['account_daily'], strict=True):
        assert decision['decision_id'] == daily['decision_id']
        observed = decision['observed_through']
        at = index[observed]
        start = at-history_size+1
        assert start >= 0 and at-w-n >= 0
        decision_at = timestamp(decision['decision_at'])
        assert timestamp(observed) < decision_at <= timestamp(decision['execution_start'])
        for table in (raw_rows, mu_rows, sector_rows):
            assert all(timestamp(r['Date']) <= timestamp(observed)
                       and timestamp(r['AvailableDate']) <= decision_at for r in table[start:at+1])
        # Derive beta from the historical price interval ending n days before the
        # observation; this deliberately avoids the strategy's trailing-array slice.
        x = np.diff(np.log(mu[at-w-n:at-n+1]))
        y = np.diff(np.log(sector[at-w-n:at-n+1]))
        assert len(x) == len(y) == w
        xc, yc = x-x.mean(), y-y.mean()
        denominator = float(np.dot(yc, yc))
        assert denominator > 0
        beta = float(np.dot(xc, yc)/denominator)
        total = float(np.diff(np.log(mu[at-n:at+1])).sum())
        common = beta*float(np.diff(np.log(sector[at-n:at+1])).sum())
        group = common < p['common_share']*total
        allocation = p['common_budget'] if group else p['other_budget']
        enter = all(mu[j] < mu[j-1] for j in range(at-n+1, at+1))
        f = {v['key']: v['text'] for v in decision['explanation']['basis']}
        assert (f['observed_signal'] == 'True') == enter
        assert (f['common_group'] == 'True') == group
        approx(float(f['entry_allocation']), allocation, (cid, observed, 'allocation'))
        approx(float(f['initial_fraction']), p['initial_fraction'], (cid, observed, 'initial_fraction'))
        for key, expected in (('beta', beta), ('common_return', common), ('total_return', total),
                              ('common2', common), ('total2', total)):
            if key in f:
                approx(float(f[key]), expected, (cid, observed, key))
                tally['numeric_feature_facts_checked'] += 1
        betas.append(beta)
        quote = raw_rows[at]
        approx(decision['reference_price'], quote['Close'], (cid, observed, 'RAW reference'))
        events = [v for v in run['actions'] if (prevtime is None or timestamp(prevtime) < timestamp(v['time']))
                  and timestamp(v['time']) <= timestamp(daily['time'])]
        pre_cash = cash+sum(v['cash_delta'] for v in events if timestamp(v['time']) <= decision_at)
        limit = (Decimal(str(quote['Close']))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')
        own = orders.get(decision['decision_id'], [])
        expected_buy = expected_sell = 0
        confirmation = False
        next_budget = None
        if quantity == 0:
            next_budget = float(Decimal(str(pre_cash))*Decimal(str(allocation)))
            approx(float(f['entry_budget']), next_budget, (cid, observed, 'flat budget'))
            approx(float(f['anchor']), float(mu[at]), (cid, observed, 'signal anchor'))
            approx(float(f['sector_anchor']), float(sector[at]), (cid, observed, 'sector signal anchor'))
            if enter:
                available = min(Decimal(str(pre_cash)), max(Decimal(0), Decimal(str(next_budget))*Decimal(str(p['initial_fraction']))))
                expected_buy = int(available/(limit*(Decimal(1)+Decimal(str(fee)))))
            assert decision['target'] == float(enter and expected_buy > 0)
        else:
            approx(float(f['entry_budget']), budget, (cid, observed, 'locked budget'))
            approx(float(f['anchor']), anchor, (cid, observed, 'locked anchor'))
            approx(float(f['sector_anchor']), sector_anchor, (cid, observed, 'locked sector anchor'))
            held = sum(timestamp(v) >= timestamp(entry_interval_start) for v in dates[start:at+1])
            done = held >= p['max_hold'] or (held >= p['review_after'] and mu[at] <= anchor*(1+p['exit_margin']))
            assert decision['target'] == float(not done), (cid, observed, held, 'exit')
            repair_mu = bool(mu[at] > anchor*(1+p['add_mu_margin']))
            repair_sector = bool(sector[at] > sector_anchor*(1+p['add_sector_margin']))
            if p['add_mode'] == 'repair':
                confirmation = repair_mu
            elif p['add_mode'] == 'repair_both':
                confirmation = repair_mu and repair_sector
            elif p['add_mode'] == 'scheduled':
                confirmation = True
            elif p['add_mode'] == 'weakness':
                confirmation = not repair_mu
            else:
                assert p['add_mode'] == 'never'
            if done:
                expected_sell = quantity
            elif nbuys == 1 and p['initial_fraction'] < 1 and held >= p['earliest_add'] and confirmation:
                available = min(Decimal(str(pre_cash)), max(Decimal(0), Decimal(str(budget))-Decimal(str(cyclecost))))
                expected_buy = int(available/(limit*(Decimal(1)+Decimal(str(fee)))))
            tally['held_decisions_checked'] += 1
        assert (f['confirmation'] == 'True') == confirmation
        buys = [v for v in own if v['side'] == 'BUY']
        sells = [v for v in own if v['side'] == 'SELL']
        assert len(buys) == int(expected_buy > 0) and len(sells) == int(expected_sell > 0), (cid, observed, expected_buy, expected_sell, own)
        day_buy = day_sell = 0
        day_net_cash = 0.
        if quantity:
            cycleincome += sum(v.get('amount', 0.) for v in events if v['kind'] == 'CASH_DIVIDEND')
        for order in own:
            assert type(order['quantity']) is int and order['quantity'] > 0
            if order['side'] == 'BUY':
                assert order['quantity'] == expected_buy and order['order_type'] == 'LIMIT'
                approx(order['limit_price'], float(limit), (cid, observed, 'limit'))
                bar = raw[daily['session']]
                assert not bar['ExecutionBlocked'] and bar['BarStatus'] == 'OBSERVED'
                crossed = bar['Open'] <= float(limit) or bar['Low'] < float(limit)
                assert (order['status'] == 'FILLED') == crossed, (cid, daily['session'], 'strict touch')
                if crossed:
                    assert len(fills[order['order_id']]) == 1
                    fill = fills[order['order_id']][0]
                    expected_price = float(bar['Open']) if bar['Open'] <= float(limit) else float(limit)
                    approx(fill['price'], expected_price, (cid, daily['session'], 'buy price'))
                    if quantity == 0:
                        anchor, sector_anchor = float(mu[at]), float(sector[at])
                        budget = next_budget
                        entry_interval_start = fill['interval_start']
                        cycle_id = fill['cycle_id']
                        nbuys = 0
                        cyclecost = cycleincome = 0.
                        tally['initial_entries'] += 1
                    else:
                        assert fill['cycle_id'] == cycle_id
                        tally['successful_adds'] += 1
                    nbuys += 1
                    assert nbuys <= 2
                    cyclecost += fill['quantity']*fill['price']+fill['fees']
                    assert cyclecost <= budget+1e-7, (cid, daily['session'], 'budget exceeded', cyclecost, budget)
                    day_buy += fill['quantity']
                else:
                    assert not fills.get(order['order_id'])
                    tally['unfilled_adds' if quantity else 'unfilled_entries'] += 1
                tally['buy_orders'] += 1
            else:
                assert order['side'] == 'SELL' and order['order_type'] == 'MARKET'
                assert order['quantity'] == expected_sell
                assert order['status'] == 'FILLED' and len(fills[order['order_id']]) == 1
                fill = fills[order['order_id']][0]
                assert fill['cycle_id'] == cycle_id
                approx(fill['price'], raw[daily['session']]['Open'], (cid, daily['session'], 'market sell'))
                day_sell += fill['quantity']
                cycleincome += fill['quantity']*fill['price']-fill['fees']
                tally['sell_orders'] += 1
            for fill in fills.get(order['order_id'], []):
                assert fill['quantity'] == order['quantity']
                assert timestamp(fill['interval_start']) >= timestamp(decision['execution_start'])
                assert timestamp(fill['interval_end']) <= timestamp(decision['execution_end'])
                value = fill['quantity']*fill['price']
                approx(fill['fees'], value*fee, (cid, daily['session'], 'fee'))
                day_net_cash += value-fill['fees'] if fill['side'] == 'SELL' else -value-fill['fees']
                tally['fees_checked'] += 1
        expected_cash = cash+sum(v['cash_delta'] for v in events)+day_net_cash
        expected_receivable = receivable+sum(v['receivable_delta'] for v in events)
        expected_quantity = quantity+day_buy-day_sell
        approx(daily['cash'], expected_cash, (cid, daily['session'], 'cash bridge'))
        approx(daily['receivable'], expected_receivable, (cid, daily['session'], 'receivable bridge'))
        assert daily['quantity'] == expected_quantity
        approx(daily['equity'], expected_cash+expected_quantity*daily['close']+expected_receivable, (cid, daily['session'], 'equity'))
        assert daily['cash'] >= -1e-8 and daily['quantity'] >= 0
        if quantity and daily['quantity'] == 0:
            cycle_records[cycle_id] = dict(cost=cyclecost, income=cycleincome,
                entry=entry_interval_start, exit=daily['time'], buys=nbuys, budget=budget)
            tally['cycles_closed'] += 1
        cash, quantity, receivable, prevtime = daily['cash'], daily['quantity'], daily['receivable'], daily['time']
        tally['causal_decisions_checked'] += 1
    for trade in run['trades']:
        if trade['status'] == 'CLOSED':
            cycle = cycle_records[trade['cycle_id']]
            approx(trade['cost'], cycle['cost'], (cid, trade['cycle_id'], 'closed cost'))
            approx(trade['income'], cycle['income'], (cid, trade['cycle_id'], 'closed income'))
            approx(trade['net_pnl'], cycle['income']-cycle['cost'], (cid, trade['cycle_id'], 'closed pnl'))
            approx(trade['net_return'], cycle['income']/cycle['cost']-1, (cid, trade['cycle_id'], 'closed return'))
            assert trade['entry_at'] == cycle['entry'] and trade['exit_at'] == cycle['exit']
    return dict(status='PASS', checks=dict(tally), parameters=p, history_size=history_size,
        beta_range=[min(betas), max(betas)],
        closed_cycle_buy_counts=dict(Counter(v['buys'] for v in cycle_records.values())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiments', nargs='+')
    parser.add_argument('--candidate', action='append', help='Optional explicit candidate subset; repeat for several candidates.')
    parser.add_argument('--baseline-experiment', default='EX056_20261104')
    parser.add_argument('--baseline-candidate', default='C8612')
    parser.add_argument('--output', default='.tmp/s018_supplement/analysis_audit.json')
    args = parser.parse_args()
    assert len(args.experiments) == len(set(args.experiments))
    base = load_record(args.baseline_experiment, args.baseline_candidate)
    base_p = normalize_parameters(base['config'])
    base_payload = None
    checks, controls = {}, {}
    selected = set(args.candidate or [])
    found = set()
    for experiment in args.experiments:
        records = read(FAMILY/'experiments'/experiment/'others/results.json')['accounts']
        for cid, record in records.items():
            if selected and cid not in selected:
                continue
            key = f'{experiment}/{cid}'
            payload = load_payload(record)
            checked = audit_account(cid, record, payload)
            checks[key] = checked
            found.add(cid)
            if checked['parameters'] == base_p:
                if base_payload is None:
                    base_payload = load_payload(base)
                current, prior = payload['runs']['candidate'], base_payload['runs']['candidate']
                assert record['definition']['execution_spec'] == base['definition']['execution_spec']
                fields = ('fills', 'account_daily', 'trades', 'actions')
                for field in fields:
                    assert economic_rows(current[field]) == economic_rows(prior[field]), (key, field, 'center mismatch')
                assert record['candidate'] == base['candidate'], (key, 'center metrics mismatch')
                controls[key] = dict(original=f'{args.baseline_experiment}/{args.baseline_candidate}',
                    fields=fields, metrics=True, status='EXACT_MATCH')
            print('AUDIT_PASS', key, checked['checks'], flush=True)
    assert checks and (not selected or selected <= found), ('missing candidates', selected-found)
    result = dict(status='PASS', accounts=len(checks), experiments=args.experiments,
        baseline=dict(experiment=args.baseline_experiment, candidate=args.baseline_candidate, account_ref=base['account_ref']),
        summary=dict(sum((Counter(v['checks']) for v in checks.values()), Counter())),
        controls=controls, checks=checks, account_runs=0,
        scope='Independent arithmetic audit of authenticated formal account inputs, decisions and ledger; no replay evaluation.',
        limitations=['This audit checks implementation, execution chronology and accounting, not predictive validity or out-of-sample robustness.',
            'Entry budget is a limit-price and fee cash ceiling; it is not a continuously rebalanced equity fraction.',
            'Repair thresholds use locked signal-day adjusted anchors, not purchase cost or proof of trend reversal.',
            'The approved fixed MU execution contract has no split in this window; a different corporate-action contract is rejected.'])
    output = (ROOT/args.output).resolve()
    assert output.is_relative_to(ROOT), 'Audit output must remain in the workspace.'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
