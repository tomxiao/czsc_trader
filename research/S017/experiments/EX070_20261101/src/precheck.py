"""True run terminator, strict reclaim boundary and future-prefix checks; no labels."""
from copy import deepcopy
from math import fsum
from common import WORK,account_input,digest,save
from features import predicates,run_context,derive,original_clock,at,ALPHA


def direct():
    def row(start,end,opening,close,high,low):return dict(BarStart=start,Date=end,Open=opening,Close=close,High=high,Low=low)
    bars=[row('2024-03-08T20:00:00+00:00','2024-03-08T20:30:00+00:00',95.,95.,1000.,94.),
          row('2024-03-08T20:30:00+00:00','2024-03-08T21:00:00+00:00',104.,102.,105.,101.),
          row('2024-03-11T13:30:00+00:00','2024-03-11T14:00:00+00:00',108.,106.,109.,105.),
          row('2024-03-11T14:00:00+00:00','2024-03-11T14:30:00+00:00',107.,109.,999.,100.)]
    run=run_context(bars,3)
    assert run['run_defined'] and run['run_length']==2 and run['run_high']==109. and run['run_cross_session']
    assert run['terminator_at']==bars[0]['Date'] and run['previous_high_is_run_high'] and run['run_net_close_change']>0
    assert predicates(True,109.,run)==dict(ALL=True,SINGLE=False,MULTI_FULL=False,MULTI_PARTIAL=True,FULL=False)
    assert predicates(True,109.01,run)['MULTI_FULL']
    assert not any(predicates(False,110.,run).values())
    # Neither the giant terminator High nor current signal High enters R.
    changed=deepcopy(bars);changed[0]['High']=2000.;changed[3]['High']=3000.
    assert run_context(changed,3)['run_high']==109.
    # A genuinely absent nonnegative prefix is undefined; even one prior negative is not SINGLE.
    for subset in (bars[1:],bars[2:]):
        censored=run_context(subset,len(subset)-1)
        assert censored['left_censored'] and not censored['run_defined'] and censored['run_high'] is None
        flags=predicates(True,110.,censored);assert flags['ALL'] and not any(flags[g] for g in flags if g!='ALL')
    singlebars=[bars[0],bars[2],bars[3]];single=run_context(singlebars,2)
    assert single['run_length']==1 and predicates(True,110.,single)['SINGLE'] and predicates(True,110.,single)['FULL']
    changed=deepcopy(bars);changed[1]['High']=111.
    r=run_context(changed,3)
    assert not r['previous_high_is_run_high'] and not predicates(True,110.,r)['FULL']
    assert predicates(True,112.,r)['FULL']==(112.-changed[2]['High']>r['run_high']-changed[2]['High'])
    return dict(real_doji_boundary_excluded=True,current_signal_excluded=True,crosssession_not_reset=True,leftcensored_never_fake_single_or_full=True,run_high_equality_partial=True,previous_high_natural_full=True,negative_bodies_need_not_net_decline=True,dynamic_margin_identity=True)


def main():
    bounds=direct();value,_,_=account_input();clock,_,_=original_clock();bars=value['products']['bars'];sessions=value['data']['sessions']['metadata']['sessions']
    rows,warm=derive(bars,sessions,clock)
    actual=[r for r in rows if r['ALL']]
    assert len(actual)==209
    assert all(sum(r[g] for g in ('SINGLE','MULTI_FULL','MULTI_PARTIAL'))==int(r['run_defined']) and r['FULL']==(r['SINGLE'] or r['MULTI_FULL']) for r in actual)
    assert all(at(r['terminator_at'])<at(r['run_start_at'])<at(r['signal_at']) for r in actual if r['run_defined'])
    assert all((r['delta']>r['run_margin_above_previous_high'])==r['FULL'] for r in actual if r['run_defined'])
    changed=deepcopy(bars);cut=at('2025-06-02T17:00:00+00:00')
    for b in changed:
        if at(b['Date'])>=cut:
            for k in ('Open','High','Low','Close'):b[k]*=1.7
            b['Volume']*=2
    index={at(b['Date']):i for i,b in enumerate(changed)}
    tr=[max(b['High']-b['Low'],abs(b['High']-changed[i-1]['Close']),abs(b['Low']-changed[i-1]['Close'])) if i else b['High']-b['Low'] for i,b in enumerate(changed)]
    changedclock=deepcopy(clock)
    for d in changedclock:
        i=index[at(d['signal_at'])];p,b=changed[i-1],changed[i]
        if at(d['signal_at'])>=cut:d['e0']=bool(p['Close']<p['Open'] and b['Close']-p['High']>ALPHA*fsum(tr[i-14:i-1])/13)
    after,_=derive(changed,sessions,changedclock)
    assert [r for r in rows if at(r['signal_at'])<cut]==[r for r in after if at(r['signal_at'])<cut]
    for i in (526,529,538):
        try:derive(bars[:i]+bars[i+1:],sessions,clock)
        except ValueError:pass
        else:raise AssertionError('Missing planned RTH bar accepted')
    save(WORK/'others/precheck.json',dict(status='PASS',feature_source_sha256=digest(WORK/'src/features.py'),source_sha256=digest(WORK/'src/precheck.py'),direct=bounds,full_original_e0_count=209,actual_clock=6490,label_context_clock=len(rows),excluded_warmup=len(warm),composition_only_when_defined=True,price_volume_future_prefix=True,full543_grid_missing_rows_fail=True,new_future_labels_read=0,new_accounts=0))
    print('E0_NEGATIVE_RUN_CONTEXT_PRECHECK_PASS;NO_LABEL_BYTES_READ')


if __name__=='__main__':main()
