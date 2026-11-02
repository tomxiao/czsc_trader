"""Independent existing-public-V4 C holding-mechanism audit; no replay or SE."""
from hashlib import sha256
import json
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_runtime import equity_source_hash

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'research/S017/experiments/EX062_20261101'


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def facts(row):
    return {f['key']: f['text'] for f in row['explanation']['basis']}


def near(a, b, name):
    assert np.isclose(a, b, rtol=1e-11, atol=1e-9), (name, a, b)


def authenticated(record):
    ref = EvidenceRef.from_dict(record['evidence'])
    assert ref.experiment.strategy_id == 'S017' and ref.schema_version == 4
    path = ref.resolve(ROOT)
    data = path.read_bytes()
    assert sha256(data).hexdigest() == ref.sha256
    env = json.loads(data)
    closure = {key: env[key] for key in ('input_ref', 'candidate_ref', 'benchmark_ref')}
    allowed = {(v['kind'], v['sha256']) for v in closure.values()}
    dependencies = {}
    def resolve(item):
        assert set(item) == {'kind', 'sha256'} and (item['kind'], item['sha256']) in allowed
        value = (path.parent / (item['sha256'] + '.json')).read_bytes()
        assert sha256(value).hexdigest() == item['sha256']
        dependencies[item['sha256']] = item['kind']
        return value
    payload = materialize_equity(data, resolve).payload
    for key in ('evaluation_identity', 'evaluation_id', 'request_hash'):
        assert payload[key] == record[key]
    return payload, dict(evidence=record['evidence'], closure=closure, authenticated_dependencies=dependencies,
                        evaluation_identity=payload['evaluation_identity'], request_hash=payload['request_hash'])


def audit(record, policy):
    payload, proof = authenticated(record)
    request = payload['request']
    assert request['initial_cash'] == 100000 and request['fee_rate'] == .001
    assert request['window'] == {'start': '2024-01-02T14:30:00+00:00', 'end': '2025-12-31T21:00:00+00:00'}
    assert request['history_start'] == '2023-11-01' and request['drawdown_basis'] == 'BAR_CLOSE'
    assert request['frequency_window_days'] == 60 and request['window_id'] == 'TRAIN_2024_2025'
    assert json.loads(request['candidate_definition']['parameters_json']) == {'policy': policy}
    assert request['candidate_definition']['source_files'] == ['strategy.py']
    assert request['candidate_definition']['source_sha256'] == equity_source_hash(WORK / 'src', ('strategy.py',))
    assert request['input_binding']['prepared'] == read(WORK / 'others/data_preparation.json')['reference']
    assert request['candidate_definition']['execution_spec'] == request['benchmark']['execution']['execution_spec']
    raw = pd.DataFrame(payload['audit_inputs']['bars'])
    for key in ('Date', 'BarStart', 'AvailableDate'):
        raw[key] = pd.to_datetime(raw[key], utc=True)
    assert raw.Date.is_monotonic_increasing and not raw.Date.duplicated().any()
    assert raw.Date.iloc[0] >= pd.Timestamp('2023-11-01T00:00Z')
    assert raw.Date.iloc[-1] <= pd.Timestamp('2025-12-31T21:00:00Z')
    indices = {v: i for i, v in enumerate(raw.Date)}
    close, high, low = (raw[k].to_numpy(dtype=float) for k in ('Close', 'High', 'Low'))
    tr = np.r_[high[0] - low[0], np.maximum.reduce((high[1:] - low[1:], abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))]
    run = payload['runs']['candidate']
    assert not run['actions']
    rows = run['decisions']; by_id = {r['decision_id']: r for r in rows}
    orders = {r['order_id']: r for r in run['orders']}
    fills = sorted(run['fills'], key=lambda f: pd.Timestamp(f['interval_end']))
    ends = np.array([pd.Timestamp(f['interval_end']).value for f in fills], dtype=np.int64)
    quantities = np.r_[0, np.cumsum([f['quantity'] * (1 if f['side'] == 'BUY' else -1) for f in fills])]
    first = facts(rows[0])
    assert rows[0]['portfolio_revision'] == 0 and first['portfolio_quantity'] == '0'
    assert float(first['portfolio_cash']) == 100000 and first['cycle_present'] == 'False'
    setups, cycles, triggers, events = {}, {}, {}, []
    counts = Counter()
    for d in rows:
        stamp = pd.Timestamp(d['observed_through']); i = indices[stamp]; f = facts(d)
        assert raw.AvailableDate.iloc[i] <= pd.Timestamp(d['decision_at'])
        mean, atr = float(close[i-65:i].mean()), float(tr[i-13:i].mean())
        near(mean, float(f['previous_mean65']), 'lag1 MA65')
        near(atr, float(f['previous_atr13']), 'lag1 ATR13')
        for name, value in (('close',close[i]),('high',high[i]),('low',low[i]),('low2',low[i-2]),('previous_close',close[i-1]),('previous_high',high[i-1]),('previous_low',low[i-1])):
            near(float(f[name]), value, name)
        raw_c = bool(close[i-1] <= mean - 2*atr and close[i] > high[i-1])
        room = bool(close[i] < mean); signal = raw_c and room
        counts['raw_C'] += raw_c; counts['C_room'] += signal
        assert (f['raw_c']=='True') == raw_c and (f['target_room']=='True') == room
        assert (f['entry_signal']=='True') == signal and f['policy'] == policy
        known = int(np.searchsorted(ends, pd.Timestamp(d['decision_at']).value, side='right'))
        quantity = int(quantities[known])
        assert float(f['portfolio_quantity']) == quantity
        assert (f['held']=='True') == (quantity>0) and (f['cycle_present']=='True') == (quantity>0)
        if not quantity:
            assert d['target'] == int(signal)
            if signal:
                s0 = min(low[i-1],low[i]); assert s0 < close[i] < mean
                near(float(f['initial_support']), s0, 'proposal S0'); near(float(f['frozen_target']),mean,'proposal T')
                assert pd.Timestamp(f['signal_at']) == stamp
                setups[d['decision_id']] = dict(T=mean,S0=float(s0),signal_at=stamp)
            continue
        buy = fills[known-1]; assert buy['side']=='BUY'
        cycle = buy['cycle_id']; source = by_id[orders[buy['order_id']]['decision_id']]
        if cycle not in cycles:
            setup = setups[source['decision_id']]
            cycles[cycle] = dict(**setup,buy=buy,cost=buy['quantity']*buy['price']+buy['fees'],due=False,reason='NONE',support=setup['S0'],raises=0,pending=None,accepted=(0.,0.),full_indices=[],held=0,last_at=None)
        s = cycles[cycle]; s['held'] += 1
        assert s['last_at'] is None or stamp>s['last_at']; s['last_at']=stamp
        near(float(f['frozen_target']),s['T'],'frozen actual T');near(float(f['initial_support']),s['S0'],'frozen S0')
        assert pd.Timestamp(f['signal_at']) == s['signal_at']
        near(float(f['actual_cycle_cost']),s['cost'],'actual cost')
        near(float(f['target_estimated_net_space']),quantity*s['T']*.999-s['cost'],'diagnostic T net space')
        near(float(f['actual_cycle_net_mark']),quantity*close[i]*.999-s['cost'],'diagnostic net mark')
        flags = dict(pivot_confirmed=False,candidate_created=False,candidate_cancelled=False,candidate_accepted=False,support_raised=False)
        if not s['due']:
            if policy=='ACCEPTED_HIGHER_SUPPORT':
                eligible = low[i-1]<low[i-2] and low[i-1]<low[i] and low[i-1]>s['support'] and raw.BarStart.iloc[i-2]>pd.Timestamp(buy['interval_start'])
                flags['pivot_confirmed'] = bool(eligible)
                if s['pending'] is not None and low[i]<s['pending']['L']:
                    events.append(dict(cycle=cycle,decision_at=str(stamp),kind='CANCEL',**s['pending']))
                    s['pending']=None;flags['candidate_cancelled']=True
                if eligible and s['pending'] is None:
                    # Independent full raw slice through left bar, not saved strategy peak.
                    eligible_indices=[j for j in s['full_indices'] if j<=i-2]
                    assert eligible_indices
                    h=float(max(high[j] for j in eligible_indices))
                    assert h >= high[i-2] > low[i-1] > s['support']
                    s['pending']=dict(L=float(low[i-1]),H=h,at=str(stamp));flags['candidate_created']=True
                    events.append(dict(cycle=cycle,kind='CREATE',**s['pending']))
                if s['pending'] is not None and close[i]>s['pending']['H']:
                    p=s['pending'];assert p['L']>s['support']
                    assert close[i]>p['H']>p['L'];s['support']=p['L'];s['raises']+=1;s['accepted']=(p['L'],p['H'])
                    events.append(dict(cycle=cycle,kind='ACCEPT',decision_at=str(stamp),old_target=s['T'],before_old_target=bool(close[i]<s['T']),**p))
                    s['pending']=None;flags['candidate_accepted']=True;flags['support_raised']=True
            if close[i]<s['support']:
                s['due']=True;s['reason']='INITIAL_STRUCTURE_FAILED' if not s['raises'] else 'ACCEPTED_SUPPORT_FAILED'
            elif policy=='FROZEN_CENTER_REPAIR' and close[i]>=s['T']:
                s['due']=True;s['reason']='TARGET_REACHED'
            if s['due']:
                triggers[cycle]=dict(at=str(stamp),reason=s['reason'],close=float(close[i]),support=s['support'],raises=s['raises'])
            if policy=='ACCEPTED_HIGHER_SUPPORT' and raw.BarStart.iloc[i]>pd.Timestamp(buy['interval_start']):
                s['full_indices'].append(i)
            if not s['due'] and close[i]>=s['T']:
                counts['held_above_original_target_without_exit']+=1
        for key,value in flags.items():assert (f[key]=='True')==value,(key,cycle,str(stamp))
        near(float(f['support']),s['support'],'current support')
        assert int(f['support_raises'])==s['raises']
        near(float(f['accepted_low']),s['accepted'][0],'last accepted L')
        near(float(f['accepted_high']),s['accepted'][1],'last accepted H')
        assert (f['pending_support']=='True')==(s['pending'] is not None)
        if s['pending'] is not None:
            near(float(f['candidate_low']),s['pending']['L'],'frozen pending L')
            near(float(f['candidate_high']),s['pending']['H'],'frozen pending H')
            assert pd.Timestamp(f['candidate_at'])==pd.Timestamp(s['pending']['at'])
        near(float(f['peak']),max((high[j] for j in s['full_indices']),default=0.),'post-entry whole-bar global peak')
        near(float(f['peak_before_last']),max((high[j] for j in s['full_indices'][:-1]),default=0.),'peak excluding last completed full bar')
        assert (f['exit_due']=='True')==s['due'] and f['exit_trigger']==s['reason']
        assert d['target']==int(not s['due'])
    assert len(rows)==6490 and counts['raw_C']==359 and counts['C_room']==350
    failed=[];filled_buy_orders={v['order_id'] for v in fills if v['side']=='BUY'}
    for order in run['orders']:
        if order['side']=='BUY' and order['order_id'] not in filled_buy_orders:
            d=by_id[order['decision_id']];assert facts(d)['cycle_present']=='False' and d['target']==1
            failed.append(dict(order_id=order['order_id'],reason=order['reason']))
    for fill in fills:
        d=by_id[orders[fill['order_id']]['decision_id']]
        assert pd.Timestamp(fill['interval_start'])==pd.Timestamp(d['execution_start'])
        assert pd.Timestamp(fill['interval_end'])==pd.Timestamp(d['execution_end'])
        assert pd.Timestamp(d['decision_at'])<=pd.Timestamp(fill['interval_start'])
        assert pd.Timestamp(fill['interval_start'])>=pd.Timestamp('2024-01-02T14:30:00Z')
        if fill['side']=='SELL':
            assert fill['cycle_id'] in triggers and d['target']==0 and facts(d)['exit_due']=='True'
            near(fill['price'],raw.Open.iloc[indices[pd.Timestamp(fill['interval_end'])]],'real next-interval Open sell')
    assert len(cycles)==sum(v['side']=='BUY' for v in fills)
    lastbuy=next((v for v in reversed(fills) if v['side']=='BUY'),None)
    endquantity=run['account_points'][-1]['quantity']
    endcycle=lastbuy['cycle_id'] if endquantity else None
    if endcycle:assert endquantity==lastbuy['quantity'] and not cycles[endcycle]['due']
    result=dict(**proof,policy=policy,checked_decisions=len(rows),counts=dict(counts),actual_buy_cycles=len(cycles),
        executed_sell_cycles=sum(v['side']=='SELL' for v in fills),first_trigger_counts=dict(Counter(v['reason'] for v in triggers.values())),
        triggers=triggers,structure_events=events,event_counts=dict(Counter(v['kind'] for v in events)),
        acceptances_below_old_target=sum(v['kind']=='ACCEPT' and v['before_old_target'] for v in events),
        failed_buy_proposals=failed,ending_quantity=endquantity,ending_open_cycle=endcycle,
        final_exit=(dict(fill=fills[-1],trigger=triggers[fills[-1]['cycle_id']]) if fills and fills[-1]['side']=='SELL' else None),
        held_observations={key:s['held'] for key,s in cycles.items()})
    return result


def main():
    source=digest(WORK/'src/strategy.py');assert source=='74d7e22bd21b25f98ac00959ebe1900f632001a2deda77c0db21ec1793d5998a'
    check=read(WORK/'others/precheck.json');assert check['status']=='PASS' and check['strategy_sha256']==source
    assert check['precheck_sha256']==digest(WORK/'src/precheck.py')
    bindings={}
    for relative,dictionary in read(WORK/'others/pre_run.json').items():
        ref=EvidenceRef.from_dict(dictionary);assert ref.experiment.strategy_id=='S017'
        path=ref.resolve(ROOT);assert digest(path)==ref.sha256
        if relative.startswith(('src/','protocols/')):assert digest(WORK/relative)==ref.sha256
        bindings[path.relative_to(ROOT).as_posix()]=ref.sha256
    manifest=read(WORK/'others/accounts.json');analysis=read(WORK/'others/analysis.json')
    assert set(manifest)=={'C0322','C0323','C0324'} and analysis['source_accounts']==manifest and analysis['status']=='PASS'
    assert analysis['source_sha256']==digest(WORK/'src/run.py')
    control=read(WORK/'others/control_comparison.json')
    assert control['status']=='PASS' and len(control['checks'])==12 and all(control['checks'].values())
    policies={'C0322':'FROZEN_CENTER_REPAIR','C0323':'INITIAL_STRUCTURE_ONLY','C0324':'ACCEPTED_HIGHER_SUPPORT'}
    results={key:audit(manifest[key],value) for key,value in policies.items()}
    for relative,expected in bindings.items():assert digest(ROOT/relative)==expected
    result=dict(status='PASS',audit_source_sha256=digest(Path(__file__)),strategy_sha256=source,
        precheck_sha256=check['precheck_sha256'],source_bound_public_artifacts=bindings,accounts=results,
        control_twelve_economic_projections=control,
        coverage='All three public original 6490-decision paths, each actual fill source and every live candidate/accepted support transition; no new replay or certification.',
        full_money_and_frequency='Separate early_evidence independent audit; not repeated here.',
        limitations='Original complete policy paths only. Differences include occupation, re-entry and candidate eligibility; not same-trade exit causality. Static ending mark is unrealized, not closed profit. Targets/support closes trigger next-interval execution, not threshold fills or avoidable losses.',
        new_replays=0,new_SE_certifications=0,sealed_2026_access=False)
    out=ROOT/'.tmp/s017_ex062_state_audit_result.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8',newline='\n')
    print('EX062_STATE_AUDIT_PASS', {key:(v['actual_buy_cycles'],v['event_counts'],v['ending_quantity']) for key,v in results.items()},digest(out),flush=True)


if __name__=='__main__':
    main()
