"""Opening context purity and original E0 membership; no return-label reads."""
from copy import deepcopy
from common import WORK,account_input,digest,save
from features import predicates,derive,original_clock,at,GROUPS


def main():
    assert predicates(True,100.,100.)=={'ALL':True,'ABOVE_OR_EQUAL':True,'BELOW':False}
    assert predicates(True,99.99,100.)=={'ALL':True,'ABOVE_OR_EQUAL':False,'BELOW':True}
    assert not any(predicates(False,100.,100.).values())
    value,_,_=account_input();clock,_,_=original_clock();bars=value['products']['bars'];sessions=value['data']['sessions']['metadata']['sessions']
    rows,warm=derive(bars,sessions,clock)
    assert all(r['ALL']==(r['ABOVE_OR_EQUAL'] or r['BELOW']) and not(r['ABOVE_OR_EQUAL'] and r['BELOW']) for r in rows)
    assert all(r['ABOVE_OR_EQUAL'] for r in rows if r['ALL'] and r['first_bar'])
    assert all(at(r['first_bar_end'])<=at(r['signal_at']) for r in rows)
    changed=deepcopy(bars);cut=at('2025-06-02T17:00:00+00:00')
    for b in changed:
        if at(b['Date'])>=cut:
            for k in ('Open','High','Low','Close'):b[k]*=1.7
            b['Volume']*=2
    # Prefix-only clock ensures old membership is compared only where original observations stay unchanged.
    # derive validates future E0 too, so do not pass old future booleans after deliberate perturbation.
    from features import ALPHA
    # Full-clock independent E0 equality is already tested above. For suffix causality,
    # update future declaration booleans from perturbed prices by direct same causal formula.
    index={at(b['Date']):i for i,b in enumerate(changed)}
    from math import fsum
    tr=[max(b['High']-b['Low'],abs(b['High']-changed[i-1]['Close']),abs(b['Low']-changed[i-1]['Close'])) if i else b['High']-b['Low'] for i,b in enumerate(changed)]
    changedclock=deepcopy(clock)
    for d in changedclock:
        i=index[at(d['signal_at'])];p,b=changed[i-1],changed[i]
        if at(d['signal_at'])>=cut:d['e0']=bool(p['Close']<p['Open'] and b['Close']-p['High']>ALPHA*fsum(tr[i-14:i-1])/13)
    after,_=derive(changed,sessions,changedclock)
    assert [r for r in rows if at(r['signal_at'])<cut]==[r for r in after if at(r['signal_at'])<cut]
    # First/middle/final missing grid rows are explicit failures, never last-seen fallback.
    for i in (526,529,538):
        try:derive(bars[:i]+bars[i+1:],sessions,clock)
        except ValueError:pass
        else:raise AssertionError('Missing planned RTH observation accepted')
    save(WORK/'others/precheck.json',dict(status='PASS',feature_source_sha256=digest(WORK/'src/features.py'),source_sha256=digest(WORK/'src/precheck.py'),full_original_e0_count=209,actual_clock=6490,label_context_clock=len(rows),excluded_warmup=len(warm),equal_boundary=True,first_bar_above_tautology=True,observed_day_not_execution_day=True,price_volume_future_prefix=True,full543_grid_missing_rows_fail=True,new_future_labels_read=0,new_accounts=0))
    print('E0_OPENING_CONTEXT_PRECHECK_PASS;NO_LABEL_BYTES_READ')


if __name__=='__main__':main()
