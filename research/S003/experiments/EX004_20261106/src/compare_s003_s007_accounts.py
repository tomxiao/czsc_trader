from pathlib import Path
import json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007_accounts'
DATA=ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007_data'
report={}
for family in ('S003','S007'):
    native=json.loads((OUT/(family+'-native.json')).read_text())['facts']
    oldfills=pd.read_csv(OUT/(family+'-legacy-fills.csv')); newfills=pd.DataFrame(native['fills'])
    assert len(oldfills)==len(newfills)
    oldtime=pd.to_datetime(oldfills.fill_time).dt.tz_localize('Asia/Shanghai').dt.tz_convert('UTC')
    newtime=pd.to_datetime(newfills.executed_at)
    assert list(oldtime)==list(newtime)
    for field in ('side','quantity'):assert oldfills[field].tolist()==newfills[field].tolist()
    differences={}
    for field in ('price','fees'):
        difference=float(np.max(np.abs(oldfills[field].to_numpy()-newfills[field].to_numpy())))
        assert difference<1e-8
        differences['fill_'+field]=difference
    oldorders=pd.read_csv(OUT/(family+'-legacy-orders.csv')); neworders=pd.DataFrame(native['orders'])
    assert oldorders.execution_date.tolist()==pd.to_datetime(neworders.valid_start).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d').tolist()
    for field in ('side','quantity','order_type','status'):
        assert oldorders[field].tolist()==neworders[field].tolist()
    buy=oldorders.order_type.eq('LIMIT')
    assert oldorders.loc[buy,'limit_price'].tolist()==neworders.loc[buy,'limit_price'].tolist()
    olddaily=pd.read_csv(OUT/(family+'-legacy-account_daily.csv')); newdaily=pd.DataFrame(native['account_daily'])
    assert olddaily.date.tolist()==newdaily.session.tolist()
    assert olddaily.quantity.tolist()==newdaily.quantity.tolist()
    for field in ('cash','close','equity'):
        difference=float(np.max(np.abs(olddaily[field].to_numpy()-newdaily[field].to_numpy())))
        assert difference<1e-8
        differences['daily_'+field]=difference
    report[family]={'status':'PASS_WITH_DECLARED_SCOPE','start':olddaily.date.iloc[0],'end':olddaily.date.iloc[-1],
        'days':len(olddaily),'orders':len(oldorders),'fills':len(oldfills),'max_abs_differences':differences,
        'final_cash':float(newdaily.cash.iloc[-1]),'final_quantity':int(newdaily.quantity.iloc[-1]),'final_equity':float(newdaily.equity.iloc[-1]),
        'order_mapping':'IDs are new content identities; MARKET legacy reference limit_price maps to native None; fill timestamps normalize Shanghai to UTC.',
        'scope':'Actual source Aug1-Nov5 with no actions independently verified; declared post-seed account only; no production operation or full-history V4 claim.'}
quotes={}
for frequency in ('m5','m30'):
    frame=pd.read_csv(DATA/('s003_raw_'+frequency+'.csv'));dt=pd.to_datetime(frame.Date)
    frame['session']=dt.dt.strftime('%Y-%m-%d');frame['clock']=dt.dt.strftime('%H:%M')
    opening=frame.loc[frame.clock.eq('09:35' if frequency=='m5' else '10:00')].set_index('session').Open
    closing=frame.loc[frame.clock.eq('11:30')].set_index('session').Close
    quotes[frequency]=(opening,closing)
for a,b in zip(quotes['m5'],quotes['m30'],strict=True):pd.testing.assert_series_equal(a,b,check_exact=True)
report['S003']['checkpoint_quote_sessions_exact']=len(quotes['m5'][0])
(OUT/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
