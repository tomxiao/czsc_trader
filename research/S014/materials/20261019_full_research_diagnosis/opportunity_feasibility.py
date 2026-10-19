"""Availability/variation inventory only; no outcome comparison or new rule."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX035_20261018'


def load(ref_value):
    ref = EvidenceRef.from_dict(ref_value)
    raw = ref.resolve(ROOT).read_bytes()
    if sha256(raw).hexdigest() != ref.sha256:
        raise ValueError('Source content hash differs')
    return raw, ref


def main():
    result = json.loads((EX / 'others/result.json').read_bytes())
    event_raw, event_ref = load(result['evidence']['others/events.csv'])
    if event_raw != (EX / 'others/events.csv').read_bytes():
        raise ValueError('Local event bytes differ from published source')
    # Deliberately do not load A9/O9/L9 or any future outcome column.
    events = pd.read_csv(BytesIO(event_raw), usecols=['cycle_id','entry_date','decision_date'])
    record_raw, record_ref = load(result['evidence']['others/accounts/run-000.json'])
    record = json.loads(record_raw)
    if (record['index'] != 0 or record['node'] is not None or record['status'] != 'SUCCEEDED'
            or record['audit']['status'] != 'PASS'
            or record['audit']['kind'] != 'NOOP_FULL_ACCOUNT_EQUIVALENCE'
            or record['evidence'] != result['account_evidence'][0]):
        raise ValueError('Expected audited original-policy no-intervention account')
    account_raw, account_ref = load(result['account_evidence'][0])
    account = json.loads(account_raw)
    run = account['runs'][0]
    if len(account['runs']) != 1:
        raise ValueError('Expected original no-intervention single run')
    if (account['request_identity']['strategy_reference'] != 'S014-C9000'
            or account['request_identity']['experiment_id'] != 'EX035_20261018'
            or record['result_hash'] != account['result_hash']):
        raise ValueError('No-intervention strategy/request/result identity differs')
    decisions = pd.DataFrame(run['ledgers']['decisions']['data'])
    decisions['date'] = pd.to_datetime(decisions.signal_date).dt.normalize()
    decisions = decisions.sort_values('date').reset_index(drop=True)
    if decisions.date.duplicated().any():
        raise ValueError('Duplicate original decision date')
    if decisions.intervention_done.any() or decisions.intervention_today.any():
        raise ValueError('Unexpected intervened original-policy history')
    old_result = json.loads((ROOT/'research/S014/experiments/EX032_20261018/others/result.json').read_bytes())
    calendar_raw, calendar_ref = load(old_result['evidence']['others/calendar.csv'])
    calendar = pd.read_csv(BytesIO(calendar_raw))
    pinned = pd.to_datetime(calendar.date)
    valid = pd.to_datetime(decisions.valid_session).dt.normalize()
    if (len(decisions) != len(pinned) or valid.tolist() != pinned.tolist()
            or decisions.date.iloc[1:].tolist() != pinned.iloc[:-1].tolist()):
        raise ValueError('Decision rows must match every pinned stock session exactly')
    orders = pd.DataFrame(run['ledgers']['orders']['data'])
    buys = orders.loc[orders.side.eq('BUY') & orders.status.eq('FILLED')].copy()
    buys['entry_day'] = pd.to_datetime(buys.execution_date).dt.normalize()
    if buys.entry_day.duplicated().any():
        raise ValueError('Duplicate filled entry orders')
    buys = buys.set_index('entry_day')
    for column in ['parent','high']:
        if not decisions[column].isin([0.,1.]).all():
            raise ValueError('Invalid boolean numeric observations')
    if not decisions.ready.isin([True,False]).all():
        raise ValueError('Missing readiness flag')
    eligible = decisions.ready.astype(bool) & decisions.parent.eq(1) & decisions.high.eq(1)
    positions = {d:i for i,d in enumerate(decisions.date)}
    # No alternate windows are scanned. Six sessions span two H3 holding
    # lengths, not two complete buy/sell/reentry cycles.
    rows=[]
    for event in events.itertuples():
        day, entry = pd.Timestamp(event.decision_date), pd.Timestamp(event.entry_date)
        i, e = positions.get(day), positions.get(entry)
        if i is None or e is None or i < 6 or e < 1:
            raise ValueError('Insufficient pinned causal history')
        own_trigger = e - 1
        if entry not in buys.index:
            raise ValueError('Original entry lacks a filled order')
        order = buys.loc[entry]
        trigger_day = pd.Timestamp(order.signal_date).normalize()
        if (trigger_day != decisions.date.iloc[own_trigger]
                or order.decision_id != decisions.iloc[own_trigger].decision_id
                or not decisions.iloc[own_trigger].entry_signal):
            raise ValueError('Subtracted signal must be the actual filled entry trigger')
        if not eligible.iloc[own_trigger] or own_trigger >= i:
            raise ValueError('Original entry must originate from a known eligible signal')
        count = int(eligible.iloc[i-6:i].sum())
        compulsory = int(i-6 <= own_trigger < i)
        rows.append({'cycle_id':event.cycle_id,'decision_date':event.decision_date,
            'entry_date':event.entry_date,'decision_year':day.year,
            'prior_six_potential_opportunities':count,
            'compulsory_original_trigger_in_window':compulsory,
            'additional_prior_opportunities':count-compulsory,
            'actual_entry_order_id':order.order_id,
            'verified_original_trigger_date':str(trigger_day.date()),
            'latest_feature_session':str(decisions.date.iloc[i-1].date())})
    frame=pd.DataFrame(rows)
    if len(frame)!=145 or frame.cycle_id.duplicated().any() or (frame.additional_prior_opportunities<0).any():
        raise ValueError('Expected 145 valid nonnegative causal feature inventories')
    frame.to_csv(OUT/'opportunity_feasibility_verified_rows.csv',index=False,lineterminator='\n')
    summary={'status':'FEASIBLE_INPUT_VARIATION_ONLY_NOT_EFFECTIVENESS_TEST',
        'events':len(frame),'source_references':[event_ref.to_dict(),account_ref.to_dict(),record_ref.to_dict(),calendar_ref.to_dict()],
        'calendar_and_actual_order_trigger_checks':'PASS_ALL_145',
        'original_policy_binding':'Published C9000 no-op audit equals original C0011; request/result identity and no intervention flags verified',
        'definition':'U=published original ready AND parent AND high; count strictly preceding six sessions, remove compulsory trigger of current position',
        'raw_count_distribution':{str(k):int(v) for k,v in frame.prior_six_potential_opportunities.value_counts().sort_index().items()},
        'extra_count_distribution':{str(k):int(v) for k,v in frame.additional_prior_opportunities.value_counts().sort_index().items()},
        'by_decision_year':{str(year):{'events':len(g),'no_additional':int(g.additional_prior_opportunities.eq(0).sum()),
                                    'at_least_one_additional':int(g.additional_prior_opportunities.gt(0).sum())}
                            for year,g in frame.groupby('decision_year')},
        'compulsory_trigger_present':int(frame.compulsory_original_trigger_in_window.sum()),
        'outcome_columns_loaded_or_compared':False,'new_fits':0,'new_return_labels':0,'new_accounts':0,'new_market_data_calls':0,
        'limitations':['Variation is necessary for a test, not evidence of predictive value',
                       'Original C0011 mechanism only; cannot silently transfer to C0056 reservation logic',
                       'Derived from existing prices and policy state; not a newly independent market source',
                       'Window and expression remain proposed research definitions, not validated signals']}
    with (OUT/'opportunity_feasibility_verified.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(summary,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({k:summary[k] for k in ['status','events','raw_count_distribution','extra_count_distribution','compulsory_trigger_present']}))


if __name__=='__main__':
    def blocked(*args,**kwargs):
        raise RuntimeError('Source calls prohibited')
    socket.socket.connect=blocked
    socket.create_connection=blocked
    main()
