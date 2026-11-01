"""Locked zero-account accounting and actual-path coverage; no horizon labels."""
from collections import Counter,defaultdict
from datetime import datetime,timedelta
import math,sys
from pathlib import Path
from common import ROOT,WORK,read,save,digest,checked,auth,projection

def at(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
def same(a,b,label):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6),(label,a,b)

def locked():
    lock=read(WORK/'others/pre_run.json');assert lock['status']=='LOCKED_PRE_DIAGNOSTIC'
    for relative,ref in lock['materials'].items():
        path,rr=checked(ref);assert rr.experiment.experiment_id==WORK.name
        assert digest(WORK/relative)==rr.sha256
    assert lock['new_accounts_before_lock']==lock['new_group_returns_before_lock']==0
    return lock

def grid(inputs,c):
    bars=inputs['products']['bars'];sessions=inputs['data']['sessions']['metadata']['sessions']
    assert len(bars)==c['expected_bars_with_warmup'] and len(sessions)==c['expected_sessions_with_warmup']
    stamps=[at(b['Date']) for b in bars];assert stamps==sorted(set(stamps))
    assert min(stamps).date().isoformat()>=c['warmup_min'] and max(stamps).date().isoformat()<=c['train'][1]
    positions={t:i for i,t in enumerate(stamps)};days=[];allindices=[]
    assert [s['session_date'] for s in sessions]==sorted(set(s['session_date'] for s in sessions))
    for s in sessions:
        assert s['timezone']=='America/New_York';indices=[]
        for segment in s['segments']:
            t,end=at(segment['start']),at(segment['end'])
            while t<end:
                finish=t+timedelta(minutes=30);assert finish<=end and finish in positions
                i=positions[finish];b=bars[i];assert at(b['BarStart'])==t and at(b['AvailableDate'])<=finish
                assert all(math.isfinite(b[k]) and b[k]>0 for k in ('Open','High','Low','Close'))
                assert b['Low']<=min(b['Open'],b['Close'])<=max(b['Open'],b['Close'])<=b['High']
                indices.append(i);t=finish
        assert indices;allindices+=indices;days.append({'session':s['session_date'],'indices':indices,'calendar':s})
    assert allindices==list(range(len(bars)))
    training=[d for d in days if c['train'][0]<=d['session']<=c['train'][1]]
    assert len(training)==502 and sum(len(d['indices']) for d in training)==6490
    for d in training:
        j=days.index(d);assert j>0 and days[j-1]['indices'][-1]+1==d['indices'][0]
    return bars,days,training

def summary(values,dates,topk):
    positive=sorted([(v,d) for v,d in zip(values,dates) if v>0],reverse=True)
    negative=sorted([(v,d) for v,d in zip(values,dates) if v<0])
    ps=math.fsum(v for v,d in positive);ns=math.fsum(v for v,d in negative)
    return {'count':len(values),'sum':math.fsum(values),'positive_sum':ps,'negative_sum':ns,
        'positive_count':len(positive),'negative_count':len(negative),'zero_count':sum(v==0 for v in values),
        'positive_top':{str(k):{'sum':math.fsum(v for v,d in positive[:k]),'share_of_positive':math.fsum(v for v,d in positive[:k])/ps if ps else None,'members':[{'date':d,'value':v} for v,d in positive[:k]]} for k in topk},
        'negative_top':{str(k):{'sum':math.fsum(v for v,d in negative[:k]),'share_of_abs_negative':math.fsum(v for v,d in negative[:k])/ns if ns else None,'members':[{'date':d,'value':v} for v,d in negative[:k]]} for k in topk}}

PRICE_FIELDS=('market_overnight_price','market_intraday_price','market_overnight_log','market_intraday_log','market_total_log',
    'flat_overnight_price_excluding_initial','flat_intraday_price','flat_overnight_log_excluding_initial','flat_intraday_log','flat_total_log_excluding_initial')
ACCOUNT_FIELDS=('account_overnight_pnl','account_intraday_execution_gross_pnl','actual_fees','account_net_change','account_overnight_log','account_intraday_net_log','account_total_log')

def aggregate(rows,c):
    out={}
    keys=['ALL','2024','2025']+[str(y)+'Q'+str(q) for y in (2024,2025) for q in (1,2,3,4)]
    for key in keys:
        chosen=[r for r in rows if key=='ALL' or r['session'].startswith(key) or (len(key)==6 and r['session'][:4]==key[:4] and (int(r['session'][5:7])-1)//3+1==int(key[-1]))]
        assert chosen,key
        dates=[r['session'] for r in chosen]
        sums={f:math.fsum(r[f] for r in chosen) for f in PRICE_FIELDS+ACCOUNT_FIELDS}
        same(sums['market_overnight_log']+sums['market_intraday_log'],sums['market_total_log'],'period market log')
        same(sums['account_overnight_log']+sums['account_intraday_net_log'],sums['account_total_log'],'period account log')
        out[key]={'days':len(chosen),'sums':sums,'market_price_factor':math.exp(sums['market_total_log']),
            'market_overnight_price_factor':math.exp(sums['market_overnight_log']),'market_intraday_price_factor':math.exp(sums['market_intraday_log']),
            'actual_account_net_factor':math.exp(sums['account_total_log']),'actual_account_overnight_factor':math.exp(sums['account_overnight_log']),
            'actual_account_intraday_net_factor':math.exp(sums['account_intraday_net_log']),
            'concentration':{f:summary([r[f] for r in chosen],dates,c['concentration_top_k']) for f in PRICE_FIELDS+ACCOUNT_FIELDS}}
    return out

def reconstruct(run,bars,days,training):
    by_time={at(b['Date']):i for i,b in enumerate(bars)}
    train_by_index={i:d for d in training for i in d['indices']}
    points=run['account_points'];daily=run['account_daily'];fills=sorted(run['fills'],key=lambda f:at(f['interval_end']))
    assert len(points)==6490 and len(daily)==502 and len(run['decisions'])==6490 and not run['actions']
    assert len({p['time'] for p in points})==6490
    cursor=0;cash=100000.;qty=0;eq=100000.;rows=[];daily_parts=defaultdict(list)
    for n,p in enumerate(points):
        i=by_time[at(p['time'])];b=bars[i];d=train_by_index[i];first=i==d['indices'][0];P=bars[i-1]['Close'];O=b['Open'];C=b['Close']
        assert p['session']==d['session'] and C==p['close'] and not p['valuation_stale'] and p['receivable']==0
        previous_qty,previous_eq=qty,eq;applied=[]
        while cursor<len(fills) and at(fills[cursor]['interval_end'])<=at(p['time']):
            f=fills[cursor];assert at(f['interval_end'])==at(p['time']) and at(f['interval_start'])==at(b['BarStart'])
            assert f['quantity']>0 and f['quantity']==int(f['quantity']);same(f['fees'],f['quantity']*f['price']*.001,'actual fee')
            if f['side']=='BUY':assert qty==0;cash-=f['quantity']*f['price']+f['fees'];qty+=f['quantity']
            else:assert f['side']=='SELL' and qty==f['quantity'];cash+=f['quantity']*f['price']-f['fees'];qty-=f['quantity']
            applied.append(f);cursor+=1
        assert len(applied)<=1
        state=('BUY_TRANSITION' if applied[0]['side']=='BUY' else 'SELL_TRANSITION') if applied else ('WHOLE_HELD' if previous_qty else 'WHOLE_FLAT')
        fillbridge=math.fsum((1 if f['side']=='BUY' else -1)*f['quantity']*(C-f['price']) for f in applied)
        fee=math.fsum(f['fees'] for f in applied);gross=previous_qty*(C-P)+fillbridge
        overnight=previous_qty*(O-P) if first else 0.
        intraday=gross-overnight;eq=cash+qty*C;delta=eq-previous_eq
        same(gross-fee,delta,'every-bar exact gross/cost bridge');same(cash,p['cash'],'every-bar cash');same(eq,p['equity'],'every-bar equity');assert qty==p['quantity'] and cash>=-1e-6
        initial=first and n==0
        overnightlog=math.log(O/P) if first else 0.
        intra_price=(C-O)+(0. if first else O-P);intra_log=math.log(C/O)+(0. if first else math.log(O/P))
        flatgap=first and previous_qty==0 and not initial
        row={'time':p['time'],'session':p['session'],'bar_index':i,'first_rth_bar':first,'initial_unavailable_overnight_boundary':initial,
            'state':state,'prior_quantity':previous_qty,'end_quantity':qty,'prior_close':P,'open':O,'close':C,'equity_before':previous_eq,'equity_after':eq,
            'account_overnight_pnl':overnight,'account_intraday_execution_gross_pnl':intraday,'account_net_change':delta,'actual_fees':fee,
            'held_body_gross_pnl':previous_qty*(C-O),'held_within_rth_open_bridge_pnl':0. if first else previous_qty*(O-P),'actual_fill_to_close_bridge_pnl':fillbridge,
            'market_overnight_price':O-P if first else 0.,'market_intraday_price':intra_price,
            'market_overnight_log':overnightlog,'market_intraday_log':intra_log,'market_total_log':math.log(C/P),
            'flat_overnight_price_excluding_initial':O-P if flatgap else 0.,'flat_overnight_log_excluding_initial':overnightlog if flatgap else 0.,
            'flat_intraday_price':intra_price if state=='WHOLE_FLAT' else 0.,'flat_intraday_log':intra_log if state=='WHOLE_FLAT' else 0.,
            'fill_count':len(applied),'fill_side':None if not applied else applied[0]['side']}
        row['flat_total_log_excluding_initial']=row['flat_overnight_log_excluding_initial']+row['flat_intraday_log']
        same(overnight+row['held_body_gross_pnl']+row['held_within_rth_open_bridge_pnl']+fillbridge-fee,delta,'body/open/fill exact bridge')
        rows.append(row);daily_parts[p['session']].append(row)
    assert cursor==len(fills)
    daily_rows=[];previous_day_eq=100000.
    for d,marked in zip(training,daily):
        session=d['session'];part=daily_parts[session];first,last=part[0],part[-1];assert session==marked['session'] and len(part)==len(d['indices'])
        same(last['equity_after'],marked['equity'],'daily original mark');assert marked['quantity']==last['end_quantity']
        sums={f:math.fsum(r[f] for r in part) for f in PRICE_FIELDS if f in first}
        sums.update({f:math.fsum(r[f] for r in part) for f in ACCOUNT_FIELDS[:4]})
        virtual_gap_eq=previous_day_eq+sums['account_overnight_pnl'];assert virtual_gap_eq>0
        overnightlog=math.log(virtual_gap_eq/previous_day_eq);intradaylog=math.log(last['equity_after']/virtual_gap_eq)
        total_log=math.log(last['equity_after']/previous_day_eq)
        same(overnightlog+intradaylog,total_log,'actual account multiplicative daily bridge')
        same(sums['account_net_change'],last['equity_after']-previous_day_eq,'daily dollar bridge')
        previous=bars[d['indices'][0]-1]['Close'];O=first['open'];C=last['close']
        same(sums['market_intraday_price'],C-O,'daily intraday full price bridge')
        same(sums['market_intraday_log'],math.log(C/O),'daily intraday full log bridge')
        same(sums['market_total_log'],math.log(C/previous),'daily close-to-close log bridge')
        daily_rows.append({'session':session,'prior_close':previous,'open':O,'close':C,'prior_account_equity':previous_day_eq,'virtual_post_gap_account_equity':virtual_gap_eq,
            'end_account_equity':last['equity_after'],'prior_quantity':first['prior_quantity'],'end_quantity':last['end_quantity'],
            'overnight_exposure':'INITIAL_BOUNDARY_NOT_AVAILABLE' if len(daily_rows)==0 else ('HELD' if first['prior_quantity'] else 'FLAT'),
            'state_counts':dict(Counter(r['state'] for r in part)),**sums,'account_overnight_log':overnightlog,'account_intraday_net_log':intradaylog,'account_total_log':total_log})
        previous_day_eq=last['equity_after']
    same(math.fsum(r['account_net_change'] for r in rows),eq-100000.,'whole actual equity change')
    same(math.exp(math.fsum(r['account_total_log'] for r in daily_rows)),eq/100000.,'whole actual account factor')
    return rows,daily_rows

def exposures(rows):
    out={}
    for period in ('ALL','2024','2025'):
        part=[r for r in rows if period=='ALL' or r['session'].startswith(period)]
        states={}
        for state in ('WHOLE_FLAT','BUY_TRANSITION','SELL_TRANSITION','WHOLE_HELD'):
            chosen=[r for r in part if r['state']==state]
            states[state]={'bars':len(chosen),'sessions':len({r['session'] for r in chosen}),
                'intraday_one_share_price':summary([r['market_intraday_price'] for r in chosen],[r['time'] for r in chosen],(1,5,10)),
                'intraday_log':summary([r['market_intraday_log'] for r in chosen],[r['time'] for r in chosen],(1,5,10))}
        gaps={}
        for state in ('INITIAL_BOUNDARY_NOT_AVAILABLE','HELD','FLAT'):
            chosen=[r for r in part if r['first_rth_bar'] and (('INITIAL_BOUNDARY_NOT_AVAILABLE' if r['initial_unavailable_overnight_boundary'] else ('HELD' if r['prior_quantity'] else 'FLAT'))==state)]
            gaps[state]={'nights':len(chosen),'one_share_price':summary([r['market_overnight_price'] for r in chosen],[r['session'] for r in chosen],(1,5,10)),
                         'log':summary([r['market_overnight_log'] for r in chosen],[r['session'] for r in chosen],(1,5,10))}
        same(math.fsum(x['intraday_log']['sum'] for x in states.values()),math.fsum(r['market_intraday_log'] for r in part),'all intraday states exhaustive')
        out[period]={'intraday_states':states,'overnight_states':gaps}
    return out

def flat_episodes(rows):
    groups=[];current=[]
    for r in rows:
        if r['state']=='WHOLE_FLAT':current.append(r)
        elif current:groups.append(current);current=[]
    if current:groups.append(current)
    result=[]
    for n,part in enumerate(groups):
        result.append({'episode':n+1,'start':part[0]['time'],'end':part[-1]['time'],'bars':len(part),'sessions':len({r['session'] for r in part}),
            'left_train_censored':part[0] is rows[0],'right_train_censored':part[-1] is rows[-1],
            'overnight_log_excluding_initial':math.fsum(r['flat_overnight_log_excluding_initial'] for r in part),
            'intraday_log':math.fsum(r['flat_intraday_log'] for r in part),
            'one_share_price_change_excluding_initial':math.fsum(r['flat_overnight_price_excluding_initial']+r['flat_intraday_price'] for r in part),
            'positive_bar_log_sum':math.fsum(r['flat_total_log_excluding_initial'] for r in part if r['flat_total_log_excluding_initial']>0),
            'negative_bar_log_sum':math.fsum(r['flat_total_log_excluding_initial'] for r in part if r['flat_total_log_excluding_initial']<0),
            'member_times':[r['time'] for r in part]})
    # Flat overnight before a BUY transition belongs to overnight exposure, not a whole-flat candle episode.
    return {'definition':'maximal consecutive WHOLE_FLAT marked intervals; separate FLAT overnight may end in BUY_TRANSITION and is not forced into these episodes',
            'all_episodes':result,'count':len(result),'longest_by_bars':sorted(result,key=lambda r:(-r['bars'],r['start']))[:10]}

def executable_bh(run):
    assert not run['actions'];end=run['account_points'][-1];fees=math.fsum(f['fees'] for f in run['fills'])
    factor=end['equity']/100000.;return {'ending_equity':end['equity'],'ending_quantity':end['quantity'],'actual_fees':fees,
        'net_factor':factor,'net_annualized_252_over_502':factor**(252/502)-1.,'actual_fills':run['fills'],
        'not_equal_to_market_price_chain':'fresh cash,actual entry timing,integer quantities,fees,and retained terminal inventory'}

def main():
    lock=locked();c=read(WORK/'protocols/contract.json')
    records={key:read(ROOT/'research/S017/experiments'/exp/'others/accounts.json')[key] for key,exp in c['source_accounts'].items()}
    old,inputs,proof=auth(records['C0222']);control,cinp,cproof=auth(records['C0329'])
    assert old['input_ref']==control['input_ref']=={'kind':'equity_input','sha256':c['input_sha256']} and inputs==cinp
    assert old['request']['data_manifest']==control['request']['data_manifest']==c['prepared_manifest_sha256']
    assert old['request']['initial_cash']==control['request']['initial_cash']==100000. and old['request']['fee_rate']==.001
    checks={}
    for kind in ('candidate','buy_hold'):
        a,b=projection(old['runs'][kind]),projection(control['runs'][kind])
        for name in a:checks[kind+'/'+name]=a[name]==b[name]
    assert len(checks)==12 and all(checks.values())
    bars,days,training=grid(inputs,c)
    rows,daily=reconstruct(old['runs']['candidate'],bars,days,training)
    ag=aggregate(daily,c);exposure=exposures(rows)
    analysis=read(ROOT/'research/S017/experiments/EX056_20261031/others/analysis.json')['summaries']['C0222']['candidate']
    dd=analysis['max_drawdown_path'];peak,trough=dd['peak'],dd['trough']
    segment=[r for r in rows if (peak is None or at(r['time'])>at(peak)) and at(r['time'])<=at(trough)]
    prev=100000. if peak is None else next(r['equity_after'] for r in rows if at(r['time'])==at(peak))
    end=next(r['equity_after'] for r in rows if at(r['time'])==at(trough))
    ddsums={f:math.fsum(r[f] for r in segment) for f in ACCOUNT_FIELDS[:4]};same(ddsums['account_net_change'],end-prev,'original DD segment bridge')
    same(1.-end/prev,analysis['bar_max_drawdown'],'original public DD identity')
    first=daily[0];total=ag['ALL']['sums']
    info={'status':'PASS_ZERO_NEW_ACCOUNT_DIAGNOSTIC','source_sha256':digest(Path(__file__)),'pre_run_lock_sha256':digest(WORK/'others/pre_run.json'),
        'public_lock':lock,'provenance':proof,'identical_control_provenance':cproof,'complete_12_economic_projections':checks,
        'calendar':{'complete_session_count':543,'complete_bar_count':7017,'train_session_count':502,'train_bar_count':6490,
            'content_sha256':inputs['data']['sessions']['content_sha256'],'metadata':inputs['data']['sessions']['metadata'],
            'prior_session_first_last_link_verified':True},
        'inherited_corporate_action_evidence':{'input_data_actions':inputs['data']['actions'],'input_products_actions':inputs['products']['actions'],
            'candidate_run_actions':old['runs']['candidate']['actions'],'warning':'Original declared NONE/no-event research assumptions,not independent historical corporate-action verification; unadjusted price chain is not verified total shareholder return.'},
        'market_initial_boundary':{'first_train_session':first['session'],'prior_2023_close':first['prior_close'],'first_open':first['open'],
            'first_overnight_log':first['market_overnight_log'],'not_available_to_fresh_account':True,
            'open_anchored_whole_price_factor':math.exp(total['market_total_log']-first['market_overnight_log'])},
        'periods':ag,'actual_path_exposure':exposure,'whole_flat_episodes':flat_episodes(rows),'daily_rows':daily,'bar_rows':rows,
        'original_max_DD':{'public_path':dd,'peak_equity':prev,'trough_equity':end,'bar_count':len(segment),'accounting_sums':ddsums},
        'executable_original_BH':executable_bh(old['runs']['buy_hold']),
        'limitations':['Descriptive account-specific exposure attribution,not a tradable flat-period or overnight strategy and not causal incremental profit.',
            'Do not combine positive-only periods or delete losing fills to claim an account. All positive/negative states and transition candles retained.',
            '6490 candles,502 sessions and correlated flat episodes are not independent samples; reused training,not phase4 or independent validation.',
            'No intrabar trade ordering/event/earnings cause is inferred; original time precision and data verification limitations retained.'],
        'new_accounts':0,'new_SE':0,'new_horizon_labels':0,'new_downloads':0,'sealed_2026_access':False}
    save(WORK/'others/diagnostic.json',info)
    print('EX067_DIAGNOSTIC_PASS',digest(WORK/'others/diagnostic.json'),flush=True)
    print(json_brief(info),flush=True)

def json_brief(info):
    import json
    return json.dumps({'period_sums':{k:v['sums'] for k,v in info['periods'].items() if k in ('ALL','2024','2025')},
        'market_factors':{k:{f:v[f] for f in ('market_price_factor','market_overnight_price_factor','market_intraday_price_factor','actual_account_net_factor','actual_account_overnight_factor','actual_account_intraday_net_factor')} for k,v in info['periods'].items() if k in ('ALL','2024','2025')},
        'exposure_counts':{k:{'overnight':{s:z['nights'] for s,z in v['overnight_states'].items()},'intraday':{s:z['bars'] for s,z in v['intraday_states'].items()}} for k,v in info['actual_path_exposure'].items()},
        'flat_episodes':info['whole_flat_episodes']['count'],'DD':info['original_max_DD']},ensure_ascii=False)

if __name__=='__main__':main()
