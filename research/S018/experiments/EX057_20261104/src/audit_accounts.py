"""Read-only audit of prior-closed-cycle memory, age, locked entry fraction and staged orders."""
from collections import Counter
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math
from pathlib import Path
from uuid import UUID
import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import (ProviderConfig, EquityDataRequest, EquityQuery, EquityProduct, BarFrequency,
    InstrumentId, MarketId, AssetClass, SourceRef, PreparedDataRef)
from strategy_runtime.equity_definition import execution_spec_from_dict

ROOT=Path.cwd()
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
records=read(ROOT/'research/S018/experiments/EX057_20261104/others/results.json')['accounts']
def load(eid,cid):
    record=read(ROOT/f'research/S018/experiments/{eid}/others/results.json')['accounts'][cid]
    ref=d.EvidenceRef.from_dict(record['account_ref']); path=ref.resolve(ROOT)
    raw=path.read_bytes(); assert sha256(raw).hexdigest()==ref.sha256
    def artifact(v):
        data=(path.parent/(v['sha256']+'.json')).read_bytes()
        assert sha256(data).hexdigest()==v['sha256']
        return data
    return record,materialize_equity(raw,artifact).payload['runs']['candidate']

hfq={symbol:read(ROOT/f'research/S018/experiments/EX044_20261104/others/analysis_{symbol}_hfq.json') for symbol in ('MU','SOXX')}
assert [x['time_key'] for x in hfq['MU']]==[x['time_key'] for x in hfq['SOXX']]
dates=[x['time_key'][:10] for x in hfq['MU']]; index={x:i for i,x in enumerate(dates)}
mu=np.array([x['close'] for x in hfq['MU']]); soxx=np.array([x['close'] for x in hfq['SOXX']])
ctx=create_research_context(RepositoryContext.discover(ROOT),d.ResearchBatchRef('S018'),
    providers=ProviderConfig(bindings={},equity_bindings={}),
    execution_spec=execution_spec_from_dict(next(iter(records.values()))['definition']['execution_spec']))
r=read(ROOT/'research/S018/experiments/EX001_20261104/others/daily_preparation.json')['reference']
ref=PreparedDataRef(UUID(r['space_id']),UUID(r['preparation_id']),r['manifest_sha256'])
got=ctx.data.fetch(EquityDataRequest(InstrumentId(MarketId.US,AssetClass.STOCK,'MU'),SourceRef('futu','s018-mu-daily-20261104'),
    EquityQuery(EquityProduct.BARS,date(2022,1,3),date(2026,10,30),BarFrequency.DAILY)),prepared=ref)
assert got.ready,got.error
raw={row.Date.tz_convert('America/New_York').strftime('%Y-%m-%d'):row for row in got.dataframe.itertuples()}
def approx(a,b):
    assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-8),(a,b)

checks,controls={},{}
for cid,record in records.items():
    _,run=load('EX057_20261104',cid); p=record['config']
    orders,fills={},{}
    for x in run['orders']: orders.setdefault(x['decision_id'],[]).append(x)
    for x in run['fills']: fills.setdefault(x['order_id'],[]).append(x)
    cash,quantity,prevtime=100000.,0,'2023-01-03T00:00:00.000000Z'
    entry_index=anchor=sector_anchor=budget=cycle_id=None
    nbuys=0; cyclecost=0.; cycle_entry=None
    cycle_records={}; tally=Counter(); never_add_reason=Counter()
    locked_fraction=None; locked_memory=None
    closed_history=[x for x in run['trades'] if x['status']=='CLOSED']
    assert [x['exit_at'] for x in closed_history]==sorted(x['exit_at'] for x in closed_history)
    for i,(decision,daily) in enumerate(zip(run['decisions'],run['account_daily'],strict=True)):
        assert decision['decision_id']==daily['decision_id']
        observation=decision['observed_through'][:10]; end=index[observation]+1
        prices,sectors=mu[end-63:end],soxx[end-63:end]
        assert len(prices)==len(sectors)==63
        assert decision['observed_through']<decision['execution_start']
        assert decision['observed_through']<=decision['decision_at']
        m,s=np.diff(np.log(prices)),np.diff(np.log(sectors))
        beta=float(np.cov(m[:-2],s[:-2],ddof=1)[0,1]/np.var(s[:-2],ddof=1))
        common=beta*float(s[-2:].sum()); total=float(m[-2:].sum())
        group=common<p['common_share']*total
        allocation=p['common_budget'] if group else p['other_budget']
        enter=bool(prices[-1]<prices[-2]<prices[-3])
        f={x['key']:x['text'] for x in decision['explanation']['basis']}
        assert (f['observed_signal']=='True')==enter
        assert (f['common_group']=='True')==group
        approx(float(f['entry_allocation']),allocation)
        available_closed=[x for x in closed_history if x['exit_at']<=decision['decision_at']]
        previous=available_closed[-1] if available_closed else None
        history=previous is not None
        prior_return=previous['income']/previous['cost']-1 if history else 0.
        # Close dates are from the actual immutable bar rows, not future trade labels.
        age=sum(raw[day].Date.to_pydatetime() >= __import__('datetime').datetime.fromisoformat(previous['exit_at'].replace('Z','+00:00'))
            for day in dates[end-63:end]) if history else 0
        approx(float(f['prior_cycle_return']),prior_return)
        assert int(float(f['prior_cycle_age']))==age,(cid,observation,age,f['prior_cycle_age'])
        assert (f['history_available']=='True')==history
        if p['memory_mode']=='after_loss':
            memory=history and 1<=age<=p['memory_age'] and prior_return < -p['loss_threshold']
        elif p['memory_mode']=='after_win':
            memory=history and 1<=age<=p['memory_age'] and prior_return > p['loss_threshold']
        else:
            assert p['memory_mode'] in ('none','uniform')
            memory=p['memory_mode']=='uniform'
        fraction=p['initial_fraction']*(p['memory_scale'] if memory else 1.)
        if quantity:
            fraction,memory=locked_fraction,locked_memory
            tally['locked_memory_held_decisions']+=1
        approx(float(f['initial_fraction']),fraction)
        assert (f['memory_active']=='True')==memory
        if not quantity:
            tally['flat_memory_active_decisions' if memory else 'flat_memory_inactive_decisions']+=1
        tally['prior_cycle_and_age_checked']+=1
        approx(decision['reference_price'],float(raw[observation].Close))
        pre_cash=cash+sum(x['cash_delta'] for x in run['actions'] if prevtime<x['time']<=decision['decision_at'])
        limit=(Decimal(str(float(raw[observation].Close)))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')
        own=orders.get(decision['decision_id'],[])
        expected_buy=0; expected_sell=0; confirmation=False; next_budget=None
        if quantity==0:
            next_budget=float(Decimal(str(pre_cash))*Decimal(str(allocation)))
            approx(float(f['entry_budget']),next_budget)
            approx(float(f['anchor']),float(prices[-1])); approx(float(f['sector_anchor']),float(sectors[-1]))
            if enter:
                available=min(Decimal(str(pre_cash)),Decimal(str(next_budget))*Decimal(str(fraction)))
                expected_buy=int(available/(limit*Decimal('1.001')))
            assert decision['target']==float(enter and expected_buy>0)
        else:
            approx(float(f['entry_budget']),budget)
            approx(float(f['anchor']),anchor); approx(float(f['sector_anchor']),sector_anchor)
            held=i-entry_index
            done=held>=p['max_hold'] or (held>=p['review_after'] and prices[-1]<=anchor)
            assert decision['target']==float(not done),(cid,daily['session'],held)
            if p['add_mode']=='repair': confirmation=bool(prices[-1]>anchor)
            elif p['add_mode']=='repair_both': confirmation=bool(prices[-1]>anchor and sectors[-1]>sector_anchor)
            elif p['add_mode']=='scheduled': confirmation=True
            elif p['add_mode']=='weakness': confirmation=bool(prices[-1]<=anchor)
            else: assert p['add_mode']=='never'
            if done: expected_sell=quantity
            elif nbuys==1 and fraction<1 and held>=p['earliest_add'] and confirmation:
                available=min(Decimal(str(pre_cash)),max(Decimal(0),Decimal(str(budget))-Decimal(str(cyclecost))))
                expected_buy=int(available/(limit*Decimal('1.001')))
            tally['held_decisions_checked']+=1
        assert (f['confirmation']=='True')==confirmation
        buys=[x for x in own if x['side']=='BUY']; sells=[x for x in own if x['side']=='SELL']
        assert len(buys)==int(expected_buy>0) and len(sells)==int(expected_sell>0),(cid,daily['session'],expected_buy,expected_sell,own)
        for order in own:
            assert order['quantity']==int(order['quantity']) and order['quantity']>0
            if order['side']=='BUY':
                assert order['quantity']==expected_buy,(cid,daily['session'],order['quantity'],expected_buy)
                assert order['order_type']=='LIMIT'; approx(order['limit_price'],float(limit))
                bar=raw[daily['session']]
                crossed=bar.Open<=float(limit) or bar.Low<float(limit)
                assert (order['status']=='FILLED')==crossed
                if crossed:
                    assert len(fills[order['order_id']])==1
                    fill=fills[order['order_id']][0]
                    approx(fill['price'],float(bar.Open) if bar.Open<=float(limit) else float(limit))
                    if quantity==0:
                        anchor,sector_anchor=float(prices[-1]),float(sectors[-1])
                        budget=next_budget; entry_index=i; nbuys=0; cyclecost=0.
                        locked_fraction,locked_memory=fraction,memory
                        tally['memory_active_entries' if memory else 'memory_inactive_entries']+=1
                        cycle_id=fill['cycle_id']; cycle_entry=fill['interval_start']
                    else:
                        assert fill['cycle_id']==cycle_id
                        tally['successful_adds']+=1
                    nbuys+=1; assert nbuys<=2
                    cyclecost+=fill['quantity']*fill['price']+fill['fees']
                    assert cyclecost<=budget+1e-7,(cid,daily['session'],cyclecost,budget)
                else:
                    assert not fills.get(order['order_id'])
                    tally['unfilled_adds' if quantity else 'unfilled_entries']+=1
                tally['buy_orders']+=1
            else:
                assert order['quantity']==expected_sell and order['order_type']=='MARKET'
                assert all(x['cycle_id']==cycle_id for x in fills.get(order['order_id'],[]))
                tally['sell_orders']+=1
            for fill in fills.get(order['order_id'],[]):
                assert fill['quantity']==order['quantity']
                approx(fill['fees'],fill['quantity']*fill['price']*.001)
                tally['fees_checked']+=1
        expected_cash=cash+sum(x['cash_delta'] for x in run['actions'] if prevtime<x['time']<=daily['time'])
        for order in own:
            for fill in fills.get(order['order_id'],[]):
                value=fill['price']*fill['quantity']
                expected_cash+=value-fill['fees'] if fill['side']=='SELL' else -value-fill['fees']
        approx(daily['cash'],expected_cash)
        assert daily['cash']>=-1e-8 and daily['quantity']>=0
        if quantity and daily['quantity']==0:
            cycle_records[cycle_id]=dict(cost=cyclecost,entry=cycle_entry,buys=nbuys,budget=budget)
            tally['cycles_closed']+=1
        cash,quantity,prevtime=daily['cash'],daily['quantity'],daily['time']
        tally['causal_decisions_checked']+=1
    for trade in run['trades']:
        if trade['status']=='CLOSED':
            cycle=cycle_records[trade['cycle_id']]
            approx(trade['cost'],cycle['cost']); assert trade['entry_at']==cycle['entry']
    checks[cid]=dict(status='PASS',checks=dict(tally),closed_cycle_buy_counts=dict(Counter(x['buys'] for x in cycle_records.values())))
    mapping={'C8732':('EX055_20261104','C8511'),'C8733':('EX056_20261104','C8612')}
    if cid in mapping:
        old_record,old=load(*mapping[cid]); fields=('fills','account_daily','trades','actions')
        for field in fields:
            econ=lambda rows:[{k:v for k,v in row.items() if not k.endswith('_id')} for row in rows]
            assert econ(run[field])==econ(old[field]),(cid,field)
        assert record['candidate']==old_record['candidate'],(cid,'metrics')
        controls[cid]=dict(original=mapping[cid][1],status='EXACT_MATCH',fields=fields,metrics=True)
    print('AUDIT_PASS',cid,dict(tally),flush=True)

result=dict(status='PASS',accounts=len(checks),summary=dict(sum((Counter(x['checks']) for x in checks.values()),Counter())),
    controls=controls,checks=checks,scope='Read-only published accounts, no account recomputation.',
    source='Frozen RAW EX001 and verified HFQ EX044; every decision recomputed from its past-only price prefix.',
    limitations=['Cash budget is a limit-price including-fee upper bound, not a continuously rebalanced equity fraction.',
        'Confirmation means a close above signal-day anchor, not necessarily a profitable position or a trend reversal.',
        'Prior closed cycle is selected only when exit_at <= decision_at; memory age uses the current 63 completed daily rows.',
        'Age counts the exit-session close as one. Older records can saturate at 63, above all tested memory windows.',
        'Entry fraction and memory status lock after actual initial fill, while the full cash budget stays unchanged.'])
(Path(__file__).resolve().parents[1]/'others/analysis_audit57.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
