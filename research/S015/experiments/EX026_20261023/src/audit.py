"""Independent arithmetic, causal boundaries and synthetic execution checks."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from trading_execution_engine import MarketExecutionRules, SessionPriceLimits
from study import ROOT, HERE, HORIZONS, TIMES, read, save, sources, inputs, features, events


def synthetic(raw, bars):
    r = raw.iloc[:80].copy()
    r.loc[:, ['Open','High','Low','Close']] = 10.
    r['Amount'], r['Volume'] = 1000., 100.
    b = bars.iloc[:8].copy()
    b.loc[:, ['Open','High','Low','Close']] = 10.
    base = features(r.iloc[:76], b)
    assert not bool(base.A.iloc[0]) and not bool(base.B.iloc[0]) and not bool(base.C.iloc[0])
    r.loc[75, 'Close'] = 11.
    r.loc[:74, 'High'], r.loc[:74, 'Low'] = 11., 9.
    f = features(r.iloc[:76], b)
    assert bool(f.A.iloc[0]) and not bool(f.B.iloc[0])
    r.loc[70:74, 'High'], r.loc[70:74, 'Low'] = 10.1, 9.9
    assert bool(features(r.iloc[:76], b).B.iloc[0])
    b.loc[4, 'Close'], b.loc[7, 'Close'] = 11., 12.
    assert bool(features(r.iloc[:76], b).C.iloc[0])
    b.loc[7, 'Close'] = 11.
    assert not bool(features(r.iloc[:76], b).C.iloc[0])
    b.loc[4, 'Close'], b.loc[7, 'Close'] = 10., 12.
    assert not bool(features(r.iloc[:76], b).C.iloc[0])
    try:
        features(r.iloc[:76], b.iloc[:-1])
    except AssertionError:
        pass
    else:
        raise AssertionError('Missing minute bar did not fail closed')
    r.loc[:, ['Open','High','Low','Close']] = 10.
    rules = MarketExecutionRules('159326.SZ',tuple(SessionPriceLimits(pd.Timestamp(d).date(),9.,12.) for d in r.Date)).to_dict()
    def ev(frame, pos=75):
        return events((frame,frame,rules,1,[pos]))[0]
    assert ev(r)['status'] == 'CLOSED'
    assert ev(r)['actual_exit_date'] > ev(r)['entry_date']
    blocked = r.copy()
    blocked.loc[76,['Open','High','Low','Close']] = [11.,11.,10.5,11.]
    assert ev(blocked)['status'] == 'BUY_UNFILLED'
    delayed = r.copy()
    delayed.loc[77,['Open','High','Low','Close']] = 9.
    rr = ev(delayed)
    assert rr['status'] == 'CLOSED' and rr['exit_delay'] == 1
    assert json.loads(rr['exit_attempts'])[0]['reason'] == 'DAILY_RANGE_NOT_REACHED'
    delayed.loc[78:79,['Open','High','Low','Close']] = 9.
    assert ev(delayed)['status'] == 'SELL_UNFILLED_AT_END'
    assert ev(r,78)['status'] == 'EXIT_RIGHT_CENSORED' and ev(r,78)['entry_gross'] is not None
    assert ev(r,79)['status'] == 'NO_NEXT_SESSION'
    return {'strict_A_B_C_boundaries':'PASS','missing_minute':'FAIL_CLOSED','buy_unfilled':'PASS',
        'delayed_and_unfilled_exit':'PASS','end_boundaries':'PASS','synthetic_event_calls':9}


def main():
    refs = sources()
    adj, raw, bars, rules, identities = inputs(refs)
    # Keep authenticated evidence separately; repeated pandas slices otherwise
    # deepcopy the provenance payload in attrs, unrelated to numeric causality.
    for frame in (adj, raw, bars):
        frame.attrs = {}
    x = pd.read_csv(HERE/'others/features.csv', float_precision='round_trip')
    e = pd.read_csv(HERE/'others/events.csv', float_precision='round_trip')
    results = read(HERE/'others/results.json')
    # Separate direct scalar definitions, including all actual prior windows.
    for p in range(434):
        i = p+75
        historical = raw.iloc[i-20:i]
        a = float(raw.Close.iloc[i]) > max(historical.Close)
        widths = [(float(row.High)-float(row.Low))/float(row.Close) for row in historical.itertuples()]
        b = a and sum(widths[-5:])/5 < sum(widths)/20
        daybars = bars[p*8:(p+1)*8]
        assert tuple(pd.to_datetime(daybars.Date).dt.strftime('%H:%M')) == TIMES
        c = daybars.Close.iloc[4] > daybars.Open.iloc[0] and daybars.Close.iloc[7] > daybars.Close.iloc[4]
        assert [a,b,c] == list(x.loc[p,['A','B','C']])
    # Exact local dependency is at most20 prior daily rows and the current8 bars.
    # Evaluate75 prior rows plus current for every point, then perturb the next
    # day. This removes repeated parsing of unrelated historical minute groups.
    original = features(raw,bars)
    for p in range(434):
        i = p+75
        local = raw.iloc[i-75:i+1].reset_index(drop=True)
        prefix = features(local,bars.iloc[p*8:(p+1)*8])
        expected = original.iloc[p:p+1].reset_index(drop=True).copy()
        expected['position'] = 0
        pd.testing.assert_frame_equal(prefix,expected)
        if p<433:
            changed = raw.iloc[i-75:i+2].reset_index(drop=True).copy()
            shifted = bars.iloc[p*8:(p+2)*8].reset_index(drop=True).copy()
            changed.loc[76:,['Open','High','Low','Close']] *= 1.17
            shifted.loc[8:,['Open','High','Low','Close']] *= .83
            perturbed = features(changed,shifted)
            pd.testing.assert_frame_equal(perturbed.iloc[:1],expected)
        if p % 100 == 0:
            print(f'causal_cutoffs_verified={p+1}',flush=True)
    for p in (0,99,183,267,351):
        i=p+75
        prefix=features(raw.iloc[:i+1],bars.iloc[:(p+1)*8])
        pd.testing.assert_frame_equal(prefix,original.iloc[:p+1])
        changed,shifted=raw.copy(),bars.copy()
        changed.loc[i+1:,['Open','High','Low','Close']] *= 1.17
        shifted.loc[(p+1)*8:,['Open','High','Low','Close']] *= .83
        pd.testing.assert_frame_equal(features(changed,shifted).iloc[:p+1],original.iloc[:p+1])
    oldentry = pd.read_csv(refs['entry_labels'].resolve(ROOT),float_precision='round_trip').set_index('date')
    oldevents = pd.read_csv(refs['old_event_labels'].resolve(ROOT),float_precision='round_trip')
    overlap = {}
    for h in HORIZONS:
        g = e[e.horizon.eq(h)].set_index('date')
        assert list(g.index) == list(oldentry.index)
        for key in ('quantity','buy_limit','buy_price'):
            np.testing.assert_allclose(g[key],oldentry[key],rtol=0,atol=1e-12,equal_nan=True)
        assert g.loc[oldentry.status.eq('BUY_UNFILLED'),'status'].eq('BUY_UNFILLED').all()
        filled = oldentry.status.eq('FILLED')
        np.testing.assert_allclose(g.loc[filled,'entry_gross']/100000,oldentry.loc[filled,'gross'],rtol=0,atol=1e-14)
        if h in (1,3):
            old = oldevents[oldevents.horizon.eq(h)&oldevents.status.eq('FILLED')].set_index('signal_date')
            matched = g.loc[old.index]
            assert matched.status.eq('CLOSED').all()
            for key in ('buy_price','sell_price','quantity'):
                np.testing.assert_allclose(matched[key],old[key],rtol=0,atol=1e-12)
            np.testing.assert_allclose(matched.net/100000,old.label,rtol=0,atol=1e-14)
            overlap[str(h)] = len(matched)
        closed = g[g.status.eq('CLOSED')]
        np.testing.assert_allclose(closed.net,closed.quantity*(closed.sell_price-closed.buy_price)-closed.quantity*(closed.sell_price+closed.buy_price)*.001,atol=1e-8,rtol=0)
        np.testing.assert_allclose(closed.net,closed.entry_gross+closed.subsequent_gross-closed.buy_fee-closed.sell_fee,atol=1e-8,rtol=0)
        assert (closed.actual_exit_date > closed.entry_date).all()
        assert g.loc[~g.status.eq('CLOSED'),'net'].isna().all()
        for name in ('A','B','C'):
            s = results['horizons'][str(h)]['comparisons'][name]
            y = closed.loc[closed[name],'net']
            out = closed.loc[~closed[name],'net']
            assert s['in']['n'] == len(y) and len(y)+len(out) == len(closed)
            assert abs(s['in']['net_mean_return']-float(y.mean()/100000)) < 1e-14
            assert abs(s['in']['positive_yuan']-float(y[y>0].sum())) < 1e-7
            assert abs(s['in']['negative_yuan']+float(y[y<0].sum())) < 1e-7
            assert abs(s['in']['missed_positive_yuan']-float(out[out>0].sum())) < 1e-7
    registration = ROOT/'research/registrations/S015/candidates'
    hashes = {p.name:sha256(p.read_bytes()).hexdigest() for p in registration.glob('*.json')}
    previous = read(ROOT/'research/S015/experiments/EX014_20261023/others/verification.json')['candidate_registration_hashes']
    assert hashes == previous
    check = {'status':'PASS','feature_scalar_replication':434,'local75_prefix_cutoffs':434,'local_next_day_perturbation_cutoffs':433,
        'complete_prefix_and_all_future_perturbation_cutoffs':[0,99,183,267,351],
        'existing_entry_labels_each_horizon':434,'old_closed_horizon_matches':overlap,
        'net_and_decomposition_equations':'PASS','all9_opportunity_amounts':'PASS',
        'candidate_registration_hashes_unchanged':len(hashes),'data_identities':identities,'synthetic':synthetic(raw,bars),
        'limits':'No independent holdout or full account acceptance; no warehouse-wide regression.'}
    save(HERE/'others/audit.json',check)
    print(json.dumps(check),flush=True)


if __name__ == '__main__':
    main()
