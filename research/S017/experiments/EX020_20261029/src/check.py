"""Focused synthetic checks before any EX020 historical result is observed."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import numpy as np
import pandas as pd
from study import (WORK,legacy,digest,save,context,scan_task,label_task,match,bootstrap,block_weights)
from check_signals import run_checks


def fixture():
    end=pd.date_range('2020-01-01',periods=380,freq='30min',tz='UTC')
    close=100+np.sin(np.arange(380)/3)*2+np.arange(380)*.02
    bars=pd.DataFrame({'Date':end,'BarStart':end-pd.Timedelta(minutes=30),'AvailableDate':end,
        'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':10000.,
        'BarStatus':'OBSERVED','ExecutionBlocked':False})
    base=[(10,8,9),(12,9,11),(11,7,8),(10,5,6),(12,7,11),(15,10,14),(12,9,10),(11,7,8),(13,8,12)]
    bars.loc[260:268,['High','Low','Close']]=np.array(base,dtype=float)*10
    bars.loc[260:268,'Open']=bars.loc[260:268,'Close']
    bars.loc[269,['Open','High','Low','Close']]=[120.,130.,110.,120.]
    constraints=pd.DataFrame({'Date':bars.BarStart,'AvailableDate':bars.BarStart,
        'Tradable':True,'QuantityStep':1.,'PriceTick':.01})
    return bars,constraints


def main():
    context()
    checks=run_checks()
    bars,constraints=fixture()
    scan=(bars,list(range(260,280)))
    expected=scan_task(scan)
    assert any(flag for _,flag,_ in expected)
    labels=[(bars,constraints,[100,268,375],n) for n in (3,130)]
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(scan_task,[scan,scan]))==[expected,expected]
        assert list(pool.map(label_task,labels))==[label_task(x) for x in labels]
    checks.append('positive_PAT_and_short_long_labels_serial_spawn_equal')
    row=legacy.label(bars,constraints,100,130)
    assert row['status']=='COMPLETE'
    assert row['entry_price']==float(bars.iloc[101].Open)
    assert row['exit_price']==float(bars.iloc[231].Open)
    assert abs(row['price_net_return']-(row['exit_price']*.999/(row['entry_price']*1.001)-1))<1e-14
    assert legacy.label(bars,constraints,375,130)['status']=='RIGHT_CENSORED_EXIT'
    blocked=bars.copy(deep=True)
    blocked.loc[231,'ExecutionBlocked']=True
    assert legacy.label(blocked,constraints,100,130)['status']=='NO_EXIT'
    blocked.loc[101,'ExecutionBlocked']=True
    assert legacy.label(blocked,constraints,100,130)['status']=='NO_ENTRY'
    checks.append('130_bar_timing_two_fees_censor_and_blocked_execution')
    weights,identity=block_weights(45,replicates=10)
    again,same=block_weights(45,replicates=10)
    assert identity==same and np.array_equal(weights,again) and np.all(weights.sum(axis=1)==45)
    checks.append('shared_20_session_blocks_are_reproducible_and_keep_sample_length')
    rows=[{'i':i,'date':f'2020-01-0{1+i//2}','month':'2020-01','stratum':'same',
           'price_net_return':v} for i,v in enumerate([.1,-.2,.3,.4,-.1,.2])]
    selected=[rows[0],rows[2],rows[4]]
    w=np.array([[2,0,1],[0,1,2],[0,0,0]])
    intervals,draws=bootstrap(rows,selected,rows,sorted({r['date'] for r in rows}),w)
    for j in range(2):
        own=sum(w[j,i]*selected[i]['price_net_return'] for i in range(3))/sum(w[j])
        base=sum(w[j,i//2]*r['price_net_return'] for i,r in enumerate(rows))/(2*sum(w[j]))
        assert abs(draws['matched_difference'][j]-(own-base))<1e-14
    assert draws['matched_difference'][2] is None and intervals['matched_difference']['empty_replicates']==1
    assert match([rows[0]],[rows[0]])['control_support']['singleton_target_events']==1
    assert match([rows[0]],[rows[0]])['difference']['mean']==0
    empty,_=bootstrap(rows,[],rows,sorted({r['date'] for r in rows}),w)
    assert empty['price_mean']['valid_replicates']==0
    checks.append('bootstrap_reestimates_controls_empty_replicates_and_singleton_support')
    sources={p.name:digest(p) for p in (WORK/'src').glob('*.py') if p.stem not in ('render','lifecycle')}
    save(WORK/'others/checks.json',{'status':'PASS','checks':checks,'sources':sources,
        'scope':'Synthetic and metadata only; no historical result labels or portfolio execution.'})
    print('FOCUSED_CHECKS PASS',len(checks),flush=True)


if __name__=='__main__':
    main()
