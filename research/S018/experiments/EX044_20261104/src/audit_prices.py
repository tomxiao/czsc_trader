from pathlib import Path
import json
import numpy as np
import pandas as pd

W=Path(__file__).resolve().parents[1]
O=W/'others'


def reconstruct(raw,events,dates):
    a,b=1.,0.;idx=0;out=[];factors=[]
    events=sorted(events,key=lambda x:x['ex_div_date'])
    for i,day in enumerate(dates):
        while idx<len(events) and events[idx]['ex_div_date']<=day:
            e=events[idx]
            b+=a*e['backward_adj_factorB']
            a*=e['backward_adj_factorA']
            idx+=1
        out.append(raw[i]*a+b);factors.append([a,b])
    return np.asarray(out),factors


def main():
    output={};data={}
    for symbol in ['MU','SOXX']:
        hfq=pd.read_json(O/f'analysis_{symbol}_hfq.json');dates=hfq.time_key.str[:10].tolist()
        raw=pd.read_json(O/'analysis_MU_frozen_raw.json') if symbol=='MU' else pd.read_json(O/'analysis_SOXX_none.json')
        raw_dates=pd.to_datetime(raw.Date).dt.strftime('%Y-%m-%d').tolist() if symbol=='MU' else raw.time_key.str[:10].tolist()
        assert raw_dates==dates
        cols=['Open','High','Low','Close'] if symbol=='MU' else ['open','high','low','close']
        events=json.loads((O/f'analysis_{symbol}_rehab.json').read_text(encoding='utf-8'))
        rebuilt,factors=reconstruct(raw[cols].to_numpy(),events,dates)
        actual=hfq[['open','high','low','close']].to_numpy()
        error=float(np.max(np.abs(rebuilt-actual)))
        assert error<1e-5,(symbol,error)
        assert len(dates)==1212 and len(set(dates))==1212
        assert (hfq.volume>0).all()
        assert np.isfinite(actual).all() and (actual>0).all()
        assert (hfq.low<=hfq[['open','close']].min(axis=1)).all()
        assert (hfq.high>=hfq[['open','close']].max(axis=1)).all()
        for t in range(0,len(dates),37):
            prefix=[e for e in events if e['ex_div_date']<=dates[t]]
            p,_=reconstruct(raw[cols].to_numpy()[:t+1],prefix,dates[:t+1])
            np.testing.assert_allclose(p,rebuilt[:t+1],atol=1e-10,rtol=0)
        current=[e for e in events if '2022-01-03'<=e['ex_div_date']<='2026-10-30']
        checks=[]
        for e in current:
            j=dates.index(e['ex_div_date']);a,b=factors[j];old_a,old_b=factors[j-1]
            # In the no-market-move counterfactual, this event's A/B restores continuity.
            pre=float(raw.iloc[j-1][cols[-1]])
            ex=(pre-e['backward_adj_factorB'])/e['backward_adj_factorA']
            assert abs(ex*a+b-(pre*old_a+old_b))<1e-8
            checks.append({'ex_date':e['ex_div_date'],'cash':e['per_cash_div'],'split':e['split_ratio'],
                'raw_close_return':float(raw.iloc[j][cols[-1]]/pre-1),
                'hfq_close_return':float(actual[j,-1]/actual[j-1,-1]-1)})
        output[symbol]={'bars':len(dates),'development_bars':sum(d>='2023-01-03' for d in dates),
            'max_ohlc_reconstruction_error':error,'warmup_start_cumulative_factor':factors[0],
            'last_cumulative_factor':factors[-1],'events_in_window':len(current),'event_checks':checks,
            'physical_prefix_checks':len(range(0,len(dates),37))}
        data[symbol]=pd.DataFrame({'date':dates,'close':actual[:,-1]})
    assert data['MU'].date.tolist()==data['SOXX'].date.tolist()
    output['method']='P_hfq=A*P_raw+B; start A=1,B=0; event a,b: B<-B+A*b then A<-A*a, only effective dates<=bar date. This is additive cash adjustment, not dividend reinvestment total return.'
    output['availability_limit']='Vendor snapshot and effective dates support causal mathematical reconstruction. Announcement-vintage archives are unavailable; availability at effective session is a research assumption, not independently proved historical publication timing.'
    output['mu_execution_preservation']='All 1212 HFQ OHLC bars reconstruct from frozen original MU raw data, so no detected OHLC revision at 1e-5 tolerance. Original prepared execution data untouched.'
    (O/'analysis_price_audit.json').write_bytes((json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    print({s:{k:v for k,v in output[s].items() if k!='event_checks'} for s in ['MU','SOXX']})


if __name__=='__main__':main()
