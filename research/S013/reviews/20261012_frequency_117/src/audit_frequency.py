"""Independent recorded-event audit; no signals, account or strategy calculation."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT/'.tmp/s013-frequency-117'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(value, expected):
    if isinstance(expected, dict):
        for key, item in expected.items():
            assert key in value, key
            check(value[key], item)
    elif isinstance(expected, float):
        assert math.isfinite(value) and abs(value-expected)<=1e-10, (value,expected)
    else:
        assert value==expected, (value,expected)


def drawdown(values):
    peak, greatest = values[0], 0.0
    for value in values:
        peak=max(peak,value)
        greatest=max(greatest,1-value/peak)
    return greatest


def path_key(replay):
    # Tuple comparison partitions actual paths independently of SHA grouping.
    account=tuple(tuple(row[k] for k in ('date','cash','quantity','equity','close'))
                  for row in replay['account_daily'])
    fills=tuple(tuple(row[k] for k in ('fill_time','side','price','quantity','fees'))
                for row in replay['fills'])
    targets=tuple((row['signal_date'],int(row['target_position'])) for row in replay['decisions'])
    return account,fills,targets


def known_limit(day,spec):
    """Independent raw Decimal grid, scaled only by the known signal T factor."""
    raw=Decimal(str(day['unadjusted_close']))
    premium=Decimal(str(spec['entry_limit_parameter']))
    tick=Decimal(str(spec['instrument']['price_tick']))
    scale=Decimal(str(day['price_scale']))
    return float((raw*(1+premium)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick*scale)


def label_category(decision, account, prior, params):
    rp=params[decision['regime']]
    position=decision[decision['regime']+'_range_position']
    acf=decision['entry_acf_value'] if 'entry_acf_value' in decision else decision['acf1']
    in_range=position<=rp['entry']
    acf_ok=rp['acf_min'] is None or acf>=rp['acf_min']
    reason=decision['signal_reason']
    eligibility=bool(decision['entry_eligible']) if 'entry_eligible' in decision else in_range and acf_ok
    if account['quantity_before']>0:
        category='ACTUAL_POSITION_OCCUPIED'
    elif prior:
        category='SIGNAL_HOLD_WITH_EMPTY_ACCOUNT'
    elif reason=='entry':
        category='ACCEPTED_ENTRY'
    elif reason in ('confirmation_rejected','entry_direction_rejected'):
        category={'confirmation_rejected':'CONFIRMATION_REJECTED',
                  'entry_direction_rejected':'DIRECTION_REJECTED'}[reason]
    elif reason in ('time','range','regime','loss','trailing'):
        category='EXIT_SAME_T_NO_REENTRY'
    elif reason=='flat':
        category=('RANGE_AND_RAW_ACF_REJECTED' if not in_range and not acf_ok
                  else 'RANGE_REJECTED' if not in_range
                  else 'RAW_ACF_REJECTED' if not acf_ok
                  else 'FLAT_OTHER_RECORDED_RULE' if eligibility
                  else 'OTHER_RECORDED_STATE')
    else:
        category='OTHER_RECORDED_STATE'
    return category,position,in_range,acf,acf_ok,eligibility


def deep_check(replay, detail, params, positive):
    daily=replay['execution_daily']
    indices={row['date'][:10]:i for i,row in enumerate(daily)}
    accounts={row['date'][:10]:row for row in replay['account_daily']}
    fills={row['fill_time'][:10] for row in replay['fills']}
    reported={row['signal_date']:row for row in detail['events']}
    assert len(reported)==len(replay['decisions'])==1636
    counts, distributions=Counter(),defaultdict(list)
    rebuilt=[]
    prior=False
    for decision in replay['decisions']:
        t=decision['signal_date'][:10]
        entry=decision['valid_session'][:10]
        assert indices[entry]==indices[t]+1
        category,position,in_range,acf,acf_ok,eligible=label_category(decision,accounts[entry],prior,params)
        h=params[decision['regime']]['max_hold']
        begin=indices[entry]
        end=begin+h
        positive_entry=int(entry[:4]) in positive
        item={'candidate_id':detail['candidate_id'],'signal_date':t,'entry_session':entry,
              'signal_reason':decision['signal_reason'],'category':category,'regime':decision['regime'],
              'range_value':position,'range_pass':in_range,'raw_acf_value':acf,'raw_acf_pass':acf_ok,
              'recorded_entry_eligible':bool(eligible),'actual_position_before':accounts[entry]['quantity_before'],
              'prior_signal_holding':prior,'positive_entry_year':positive_entry,'H':h,
              'proxy_exit_session':None,'proxy_net_open_return':None,'proxy_exit_positive_year':False,
              'open_within_known_limit':None,'whole_interval_actual_flat':False,'greedy_hindsight_selected':False}
        if positive_entry:
            counts[category]+=1
        if end<len(daily):
            exit_date=daily[end]['date'][:10]
            net=daily[end]['open']/daily[begin]['open']*(1-.001)/(1+.001)-1
            interval=[daily[i]['date'][:10] for i in range(begin,end+1)]
            no_activity=all(accounts[date]['quantity_before']==accounts[date]['quantity']==0
                            and date not in fills for date in interval)
            feasible=daily[begin]['open']<=known_limit(daily[indices[t]],replay['execution_spec'])+1e-12
            item.update(proxy_exit_session=exit_date,proxy_net_open_return=net,
                        proxy_exit_positive_year=int(exit_date[:4]) in positive,
                        open_within_known_limit=feasible,whole_interval_actual_flat=no_activity)
            if positive_entry:
                distributions[category].append(net)
        check(reported[t],{k:v for k,v in item.items() if k!='greedy_hindsight_selected'})
        rebuilt.append(item)
        prior=decision['target_position']!=0
    candidates=[row for row in rebuilt if row['category'].endswith('REJECTED')
                and row['proxy_exit_positive_year'] and row['whole_interval_actual_flat']
                and row['open_within_known_limit'] and row['proxy_net_open_return']>0]
    selected=set()
    end_of_previous=None
    for row in sorted(candidates,key=lambda value:(value['proxy_exit_session'],value['entry_session'])):
        if end_of_previous is None or row['entry_session']>end_of_previous:
            selected.add(row['signal_date'])
            end_of_previous=row['proxy_exit_session']
    for row in rebuilt:
        assert reported[row['signal_date']]['greedy_hindsight_selected']==(row['signal_date'] in selected)
    check(detail['positive_entry_year_category_counts'],dict(counts))
    assert sum(counts.values())==1152
    assert len(candidates)==detail['rejected_profitable_actual_cash_gap_windows']
    assert len(selected)==detail['nonoverlapping_hindsight_gap_windows']
    summaries={key:{'n':len(values),'positive':sum(value>0 for value in values),
                    'mean_net_open_return':math.fsum(values)/len(values)}
               for key,values in distributions.items()}
    check(detail['hindsight_price_distributions'],summaries)
    assert detail['actual_buy_order_count']==sum(order['side']=='BUY' for order in replay['orders'])
    check(detail['actual_order_statuses'],dict(Counter(order['status'] for order in replay['orders'])))
    assert detail['positive_quantity_before_days']==sum(row['quantity_before']>0
            for row in replay['account_daily'] if int(row['date'][:4]) in positive)
    return {'recorded_events':len(rebuilt),'category_counts':dict(counts),
            'hindsight_cash_gap_fragments':len(candidates),'hindsight_nonoverlap_fragments':len(selected),
            'known_raw_decimal_grid_flags':'EXACT'}


def verify():
    review=read(WORK/'review.json')
    source=ROOT/review['source']
    assert sha(source)==review['input_sha256']
    results=read(source)
    all_rows={row['candidate_id']:row for row in results['rows']}
    candidates=[row for row in all_rows.values() if all(value for key,value in
            row['gates_v2']['gates'].items() if key!='positive_buyhold_year_frequency')]
    candidates.sort(key=lambda row:(-row['gates_v2']['positive_closed_cycles'],
                                    -row['economics']['net_cagr'],row['candidate_id']))
    assert len(candidates)==review['candidate_count']==117
    assert [row['candidate_id'] for row in candidates]==[row['candidate_id'] for row in review['ranking']]
    positive=set(review['positive_years'])
    assert positive=={2020,2021,2024,2025,2026}
    details={row['candidate_id']:row for row in review['detailed_recorded_event_review']}
    assert len(details)==9
    groups=defaultdict(list)
    actual_grid_n,actual_grid_error,changed_scale_n=0,0.,0
    deep_proofs={}
    for source_row,rank in zip(candidates,review['ranking'],strict=True):
        cid=source_row['candidate_id']
        path=ROOT/source_row['source']
        assert sha(path)==source_row['source_sha256']==rank['source_sha256']
        data=read(path)
        evidence=data['assessment_evidence'][0]
        replay=data['runs'][0]['replay_evidence']
        equities=[row['equity'] for row in evidence['account']]
        dates=[row['session'] for row in evidence['account']]
        closed=[row['exit_session'] for row in evidence['closed_cycles']]
        count=sum(int(date[:4]) in positive for date in closed)
        cagr=(equities[-1]/1e6)**(252/len(equities))-1
        year_before=1e6
        annual={}
        for year in sorted({date[:4] for date in dates}):
            yvalues=[value for date,value in zip(dates,equities,strict=True) if date.startswith(year)]
            annual[year]={'opening_equity':year_before,'closing_equity':yvalues[-1],
                          'return':yvalues[-1]/year_before-1,'drawdown':drawdown([year_before,*yvalues]),
                          'sessions':len(yvalues),'closed_cycles':sum(date.startswith(year) for date in closed)}
            year_before=yvalues[-1]
        check(rank,{'positive_closed_trades':count,'frequency60':60*count/1152,
                    'missing_closed_trades':77-count,'net_cagr':cagr,
                    'full_drawdown':drawdown([1e6,*equities]),'annual':annual,
                    'return_gate_margin_pp':100*(cagr-1.5*results['benchmark']['benchmark_cagr']),
                    'minimum_negative_year_return':min(annual[str(year)]['return']
                        for year in (2022,2023))})
        reasons=Counter(row['signal_reason'] for row in replay['decisions']
                        if int(row['valid_session'][:4]) in positive)
        check(rank['reason_counts_positive_entry_years'],dict(reasons))
        groups[path_key(replay)].append(cid)
        prices={row['date'][:10]:row for row in replay['execution_daily']}
        for order in replay['orders']:
            if order['side']!='BUY':
                continue
            t,e=order['signal_date'][:10],order['execution_date'][:10]
            grid=known_limit(prices[t],replay['execution_spec'])
            error=abs(grid-order['limit_price'])
            assert error<=1e-9,(cid,t,grid,order['limit_price'])
            actual_grid_error=max(actual_grid_error,error)
            actual_grid_n+=1
            changed_scale_n+=prices[t]['price_scale']!=prices[e]['price_scale']
        if cid in details:
            record=read(ROOT/f'research/registrations/S013/candidates/{cid}.json')['record']
            pp=ROOT/'research/S013'/record['payload']['path']
            assert sha(pp)==record['payload']['sha256']
            payload=read(pp)
            assert payload['parameters']==details[cid]['parameters']
            deep_proofs[cid]=deep_check(replay,details[cid],payload['parameters'],positive)
    actual_groups={frozenset(ids) for ids in groups.values()}
    claimed_groups={frozenset(ids) for ids in review['economic_path_groups'].values()}
    assert actual_groups==claimed_groups and len(groups)==review['distinct_economic_paths']==58
    assert review['nearest_ids']==[row['candidate_id'] for row in candidates
            if row['gates_v2']['positive_closed_cycles']==72]
    return {'status':'PASS','ranking_candidates':117,'distinct_actual_paths':58,
            'deep_recorded_event_reviews':deep_proofs,'all_actual_buy_orders_grid_verified':actual_grid_n,
            'actual_orders_with_changed_T_to_E_scale':changed_scale_n,
            'maximum_grid_error':actual_grid_error,'review_sha256':sha(WORK/'review.json'),
            'audit_source_sha256':sha(Path(__file__)),'new_strategy_runs':0,'new_accounts':0,
            'scope':'Independent actual-ledger ranking and tuple grouping, saved-field categories, T/E/H and fixed-cost OPEN descriptions, known-T raw Decimal grids, observed cash-gap flags and earliest-end strict interval packing.',
            'limits':['Future-positive selection is hindsight, not identifiable opportunities or actual additional trades.',
                      'No range/regime exits, sizing, cash compounding, order submission or policy counterfactual simulated.',
                      'Passing this audit proves descriptive arithmetic, not Alpha, causal opportunity loss or four-gate feasibility.']}


if __name__=='__main__':
    proof=verify()
    with (WORK/'audit_frequency.json').open('x',encoding='utf-8') as stream:
        json.dump(proof,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps(proof,ensure_ascii=False))
