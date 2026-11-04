"""Focused read-only audit of EX051 sizing, chronology, and control accounts."""
from collections import Counter
from datetime import date
from decimal import Decimal, ROUND_FLOOR
import importlib.util
import json
import math
from pathlib import Path
from uuid import UUID

import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context
from dataflows import (ProviderConfig, EquityDataRequest, EquityQuery, EquityProduct, BarFrequency,
    InstrumentId, MarketId, AssetClass, SourceRef, PreparedDataRef)
from strategy_runtime.equity_definition import execution_spec_from_dict

ROOT = Path.cwd()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
loader = importlib.util.spec_from_file_location('exits', ROOT/'research/S018/experiments/EX047_20261104/src/analyze_exits.py')
module = importlib.util.module_from_spec(loader)
loader.loader.exec_module(module)
records = read(ROOT/'research/S018/experiments/EX051_20261104/others/results.json')['accounts']
hfq = {symbol:read(ROOT/f'research/S018/experiments/EX044_20261104/others/analysis_{symbol}_hfq.json') for symbol in ('MU','SOXX')}
assert [x['time_key'] for x in hfq['MU']] == [x['time_key'] for x in hfq['SOXX']]
dates = [x['time_key'][:10] for x in hfq['MU']]
index = {value:i for i,value in enumerate(dates)}
mu = np.array([x['close'] for x in hfq['MU']])
soxx = np.array([x['close'] for x in hfq['SOXX']])
context = create_research_context(RepositoryContext.discover(ROOT), d.ResearchBatchRef('S018'),
    providers=ProviderConfig(bindings={},equity_bindings={}),
    execution_spec=execution_spec_from_dict(next(iter(records.values()))['definition']['execution_spec']))
rawref = read(ROOT/'research/S018/experiments/EX001_20261104/others/daily_preparation.json')['reference']
prepared = PreparedDataRef(UUID(rawref['space_id']), UUID(rawref['preparation_id']), rawref['manifest_sha256'])
fetched = context.data.fetch(EquityDataRequest(InstrumentId(MarketId.US,AssetClass.STOCK,'MU'),
    SourceRef('futu','s018-mu-daily-20261104'),
    EquityQuery(EquityProduct.BARS,date(2022,1,3),date(2026,10,30),BarFrequency.DAILY)), prepared=prepared)
assert fetched.ready, fetched.error
raw = {row.Date.tz_convert('America/New_York').strftime('%Y-%m-%d'):row for row in fetched.dataframe.itertuples()}


def approx(a,b):
    assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-8),(a,b)


checks, control_checks = {}, {}
for cid, record in records.items():
    _, run, _ = module.load('EX051_20261104', cid)
    config = record['config']
    orders, fills = {}, {}
    for order in run['orders']:
        orders.setdefault(order['decision_id'], []).append(order)
    for fill in run['fills']:
        fills.setdefault(fill['order_id'], []).append(fill)
    cash, quantity, previous_time = 100000., 0, '2023-01-03T00:00:00.000000Z'
    anchor, entry_index = None, None
    tally = Counter()
    allocation_counts, unfilled = Counter(), Counter()
    for i, (decision,daily) in enumerate(zip(run['decisions'],run['account_daily'],strict=True)):
        assert decision['decision_id'] == daily['decision_id']
        observation = decision['observed_through'][:10]
        end = index[observation]+1
        prices, sectors = mu[end-63:end], soxx[end-63:end]
        assert len(prices) == len(sectors) == 63
        assert dates[end-1] < decision['execution_start'][:10]
        assert decision['observed_through'] < decision['execution_start']
        assert decision['observed_through'] <= decision['decision_at']
        m,s = np.diff(np.log(prices)),np.diff(np.log(sectors))
        beta = float(np.cov(m[:-2],s[:-2],ddof=1)[0,1]/np.var(s[:-2],ddof=1))
        total,common = float(m[-2:].sum()),beta*float(s[-2:].sum())
        facts = {x['key']:x['text'] for x in decision['explanation']['basis']}
        approx(float(facts['beta']),beta)
        approx(float(facts['common2']),common)
        approx(float(facts['total2']),total)
        common_group = config['common_share'] is None or common < config['common_share']*total
        allocation = config['common_budget'] if common_group else config['other_budget']
        enter = prices[-1] < prices[-2] < prices[-3] and allocation > 0
        assert (facts['observed_signal']=='True') == enter
        assert (facts['common_group']=='True') == common_group
        approx(float(facts['entry_allocation']),allocation)
        approx(decision['reference_price'],raw[observation].Close)
        own_orders = orders.get(decision['decision_id'],[])
        pre_cash = cash + sum(x['cash_delta'] for x in run['actions']
            if previous_time < x['time'] <= decision['decision_at'])
        if quantity == 0:
            approx(float(facts['anchor']),float(prices[-1]))
            assert decision['target'] == float(enter)
        else:
            approx(float(facts['anchor']),anchor)
            held = i-entry_index
            done = held >= config['max_hold'] or (held >= config['review_after'] and prices[-1] <= anchor)
            assert decision['target'] == float(not done)
            assert not any(x['side']=='BUY' for x in own_orders), (cid,'unrequested top up')
            tally['held_decisions_no_topup'] += 1
        for order in own_orders:
            assert order['quantity'] == int(order['quantity']) and order['quantity'] > 0
            if order['side']=='BUY':
                assert quantity == 0 and enter
                assert order['order_type']=='LIMIT'
                limit = (Decimal(str(float(raw[observation].Close)))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')
                approx(order['limit_price'],float(limit))
                budget = Decimal(str(pre_cash))*Decimal(str(allocation))
                expected_quantity = int(budget/(limit*Decimal('1.001')))
                assert order['quantity']==expected_quantity, (cid, daily['session'],order['quantity'],expected_quantity,pre_cash)
                assert Decimal(str(order['quantity']))*limit*Decimal('1.001') <= budget
                assert (Decimal(str(order['quantity']))+1)*limit*Decimal('1.001') > budget
                bar = raw[daily['session']]
                crossed = bar.Open <= float(limit) or bar.Low < float(limit)
                assert (order['status']=='FILLED') == crossed
                if crossed:
                    assert len(fills[order['order_id']])==1
                    fill = fills[order['order_id']][0]
                    expected_price = float(bar.Open) if bar.Open <= float(limit) else float(limit)
                    approx(fill['price'],expected_price)
                    anchor,entry_index = float(prices[-1]),i
                    allocation_counts[str(allocation)] += 1
                else:
                    assert not fills.get(order['order_id'])
                    unfilled[order['reason']] += 1
                tally['buy_orders'] += 1
            else:
                assert order['side']=='SELL' and order['order_type']=='MARKET'
                assert order['quantity']==quantity
                tally['sell_orders'] += 1
            for fill in fills.get(order['order_id'],[]):
                assert fill['quantity']==order['quantity']
                approx(fill['fees'],fill['price']*fill['quantity']*.001)
                tally['fill_fees_checked'] += 1
        expected_cash = cash + sum(x['cash_delta'] for x in run['actions'] if previous_time < x['time'] <= daily['time'])
        for order in own_orders:
            for fill in fills.get(order['order_id'],[]):
                value = fill['price']*fill['quantity']
                expected_cash += value-fill['fees'] if fill['side']=='SELL' else -value-fill['fees']
        approx(daily['cash'],expected_cash)
        assert daily['cash'] >= -1e-8 and daily['quantity'] >= 0
        cash,quantity,previous_time = daily['cash'],daily['quantity'],daily['time']
        tally['causal_decisions_checked'] += 1
    checks[cid] = dict(status='PASS', checks=dict(tally),filled_entry_allocations=dict(allocation_counts),unfilled=dict(unfilled))
    if cid in ('C8139','C8140'):
        prior_id = 'C7502' if cid=='C8139' else 'C7501'
        oldrecord,prior,_=module.load('EX045_20261104',prior_id)
        fields = ('fills','account_daily','trades','actions')
        for field in fields:
            economic = lambda rows:[{k:v for k,v in x.items() if not k.endswith('_id')} for x in rows]
            assert economic(run[field]) == economic(prior[field]),(cid,field)
        assert record['candidate']==oldrecord['candidate']
        control_checks[cid]=dict(original=prior_id,status='EXACT_MATCH',fields=fields,metrics=True)
output = dict(status='PASS',accounts=len(checks),controls=control_checks,checks=checks,
    summary=dict(sum((Counter(x['checks']) for x in checks.values()),Counter())),
    scope='Read-only published-account checks; no rerun, no new experiments.',
    sources=['Formal EX051/EX045 account evidence verified by SHA256.',
        'Immutable RAW preparation EX001; EX044 HFQ matched exactly by the formal preparation harness.'],
    observations=['Budget fraction caps entry cash using limit price plus fee; actual fill-price spending can be smaller.',
        'The emitted target=1 does not mean full exposure for explicit partial-budget orders; orders carry the actual share quantity.',
        'entry_allocation facts on held days describe current signal classification, not an instruction to resize existing holdings.',
        'An initially fixed quantity is retained until exit even when common/other group changes.',
        'The source preserves the EX035 explicit-order sizing mechanics and uses RAW close rather than HFQ close for the limit.',
        'All stateful exits checked against actual prior fills; all feature calculations use only the 63-bar prefix ending observed_through.'])
(Path(__file__).resolve().parents[1]/'others/analysis_account_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in output.items() if k!='checks'},ensure_ascii=False,indent=2))
