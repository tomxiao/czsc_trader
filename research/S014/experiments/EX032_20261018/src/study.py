"""Fixed offline interaction study; twelve slots, no refits or new labels."""
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json
import socket
import sys

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / 'others'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def write(p, obj):
    with p.open('x', encoding='utf-8', newline='\n') as h:
        h.write(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def block(*args, **kwargs):
    raise RuntimeError('EX032: network forbidden')


def offline():
    socket.socket.connect = block
    socket.create_connection = block


def source(ex, key):
    v = read(ROOT/f'research/S014/experiments/{ex}/others/result.json')['evidence'][key]
    ref = EvidenceRef.from_dict(v)
    p = ref.resolve(ROOT)
    assert digest(p) == ref.sha256
    return p, v


def check_locks(name):
    for rel, v in read(EX/f'protocols/{name}.json').items():
        assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes() == (ROOT/rel).read_bytes(), rel


def state(tclose, qclose):
    valid = tclose.notna() & qclose.notna() & tclose.gt(0) & qclose.gt(0)
    change = (tclose / qclose - 1).where(valid)
    return change, change.le(0).astype(float).where(valid)


def precheck():
    p = read(EX/'protocols/design.json')
    assert p['execution_authorized'] and p['proposed_fits_cap'] == 12
    assert len(set(p['baseline_columns'])) == 65
    change, s = state(pd.Series([100., 101., 99., 100., 100.]), pd.Series([100.,100.,100.,np.nan,0.]))
    np.testing.assert_equal(s.to_numpy(), [1.,0.,1.,np.nan,np.nan])
    assert (pd.Series([1.,1.,0.])*s.iloc[:3]).tolist() == [1.,0.,0.]
    assert np.array([2,3,4])[np.array([2,3,4]) < 3].tolist() == [2]
    assert (np.array([1.,2.,3.]) >= 2).tolist() == [False,True,True]
    assert abs(1000*(11-10-.001*(11+10))/100000-.00979) < 1e-15
    bars=pd.DataFrame({'Date':[date(2020,1,2),date(2020,1,3)],'Close':[100.,101.]})
    bars['Date']=pd.to_datetime(bars.Date)
    mapped=pd.to_datetime(pd.Series(['2020-01-02','2020-01-03',None])).map(bars.set_index('Date').Close)
    np.testing.assert_equal(mapped.to_numpy(),[100.,101.,np.nan])
    write(OUT/'precheck.json', {'status':'PASS','synthetic_checks':8,'new_fits':0,'new_labels':0,'new_accounts':0,'new_calls':0})


def prepare():
    offline()
    assert not (OUT/'inputs.json').exists()
    check_locks('published_design')
    plan = read(EX/'protocols/design.json')
    refs = {}
    p, refs['EX031_inputs'] = source('EX031_20261018','others/inputs.csv')
    f = pd.read_csv(p).set_index('signal').copy()
    p, refs['EX031_metadata'] = source('EX031_20261018','others/inputs.json')
    oldmeta = read(p)
    assert oldmeta['data_reference'] == plan['data_reference']
    assert oldmeta['input_sha256'] == refs['EX031_inputs']['sha256']
    p, refs['EX031_calendar'] = source('EX031_20261018','others/calendar.csv')
    calendar_bytes = p.read_bytes()
    p, refs['EX031_labels'] = source('EX031_20261018','others/labels.csv')
    labels_bytes = p.read_bytes()
    labels = pd.read_csv(p)
    p, refs['stock_readiness'] = source('EX004_20261016','input-readiness')
    records = [r for r in read(p)['records'] if r['request']['dataset']=='stock.ohlcv']
    assert len(records) == 1
    record = records[0]
    r, b = record['request'], record['reference']
    ctx = create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig(bindings={}))
    fetched = ctx.data.fetch(DataRequest(Dataset(r['dataset']),r['symbol'],r['start'],r['end'],r['required_cutoff']),
        prepared=PreparedDataRef(UUID(b['space_id']),UUID(b['preparation_id']),b['manifest_sha256']))
    assert fetched.ready and fetched.identity.content_sha256 == record['content_sha256']
    stock = fetched.dataframe.sort_values('Date').reset_index(drop=True)
    stock['Date'] = pd.to_datetime(stock.Date)
    assert not stock.Date.duplicated().any()
    dates = pd.DatetimeIndex(pd.to_datetime(f.date))
    assert pd.DatetimeIndex(stock.Date).equals(dates) and len(f) == 1642
    prices = stock.set_index('Date').Close
    t = pd.Series(dates.map(prices), index=f.index, dtype=float)
    q = pd.Series(pd.to_datetime(f.q).map(prices), index=f.index, dtype=float)
    assert t.notna().all() and t.gt(0).all()
    assert q.notna().equals(pd.to_datetime(f.q).isin(prices.index))
    f['hfq_close_T'], f['hfq_close_Q'] = t, q
    f['stock_cumulative_return'], f['S'] = state(t,q)
    f['zs'] = f.z * f.S
    eligible_q = f.q.notna()
    assert (pd.to_datetime(f.loc[eligible_q,'q']) < pd.to_datetime(f.loc[eligible_q,'p'])).all()
    assert (pd.to_datetime(f.loc[eligible_q,'p']) < pd.to_datetime(f.loc[eligible_q,'date'])).all()
    f['feature_ready'] = np.isfinite(f[plan['baseline_columns']+['S','z']].to_numpy(float)).all(1)
    f['label_ready'] = f.Y3.notna() & f.maturity.ge(0)
    closed = labels.loc[labels.status.eq('CLOSED')]
    expected = closed.quantity*(closed.exit_price-closed.entry_price-.001*(closed.entry_price+closed.exit_price))/100000
    np.testing.assert_allclose(closed.net_return,expected,rtol=0,atol=2e-14)
    # No relabeling or replay. Check inherited H3 values and maturity.
    h3 = labels.loc[labels.horizon.eq(3)].set_index('signal')
    np.testing.assert_allclose(f.Y3,h3.net_return.reindex(f.index),rtol=0,atol=1e-15,equal_nan=True)
    np.testing.assert_allclose(f.maturity,h3.maturity.reindex(f.index),rtol=0,atol=0,equal_nan=True)
    f.reset_index().to_csv(OUT/'inputs.csv',index=False,lineterminator='\n')
    (OUT/'calendar.csv').write_bytes(calendar_bytes)
    (OUT/'labels.csv').write_bytes(labels_bytes)
    stock[['Date','Close']].to_csv(OUT/'stock_hfq_close.csv',index=False,lineterminator='\n')
    coverage=[]
    for year,g in f.groupby('year'):
        coverage.append(dict(year=int(year),sessions=len(g),parent=int(g.A.sum()),
            q_missing_parent=int((g.A & g.q.notna() & g.hfq_close_Q.isna()).sum()),
            common_mature_parent=int((g.A & g.feature_ready & g.label_ready).sum()),
            unfilled_parent=int((g.A & g.feature_ready & g.label_ready & ~g.entry_filled.fillna(False).astype(bool)).sum()),
            missing_label_parent=int((g.A & g.feature_ready & g.maturity.isna()).sum()),
            censored_parent=int((g.A & g.feature_ready & g.maturity.lt(0)).sum())))
    f.loc[f.A & (~f.feature_ready | ~f.label_ready), ['date','year','q','feature_ready','label_ready','maturity']].reset_index().to_csv(OUT/'excluded_parent.csv',index=False,lineterminator='\n')
    write(OUT/'inputs.json',dict(status='PASS',source_evidence=refs,inherited_evidence=oldmeta['source_evidence'],
        stock_binding=record, data_reference=plan['data_reference'],
        missing_exact_q=int((eligible_q & q.isna()).sum()),coverage=coverage,
        source_calls=0,new_labels=0,accounts=0,
        input_sha256=digest(OUT/'inputs.csv'),stock_close_sha256=digest(OUT/'stock_hfq_close.csv'),
        label_sha256=digest(OUT/'labels.csv'),calendar_sha256=digest(OUT/'calendar.csv'),
        cohort_note='Common B65+S+z finite features; z_old5 is diagnostic only, not an inclusion requirement.'))
    print(json.dumps({'input_status':'PASS','missing_exact_q':int((eligible_q & q.isna()).sum()),'coverage':coverage}))


def fit_one(task, f):
    slot, year, name, cols, train_ids, test_ids, cutoff = task
    x, xt = f.loc[train_ids,cols].to_numpy(float), f.loc[test_ids,cols].to_numpy(float)
    y = f.loc[train_ids,'Y3'].to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(xt).all() and np.isfinite(y).all()
    mean,scale = x.mean(0),x.std(0)
    scale[scale<1e-12]=1.
    xx=(x-mean)/scale
    coef=np.linalg.solve(xx.T@xx+10*np.eye(len(cols)),xx.T@(y-y.mean()))
    trained=xx@coef+y.mean()
    prediction=(xt-mean)/scale@coef+y.mean()
    write(OUT/f'fits/fit_{slot:02d}.json',dict(status='COMPLETE',slot=slot,year=year,model=name,
        columns=cols,train_signals=train_ids,test_signals=test_ids,cutoff=cutoff,
        max_training_maturity=int(f.loc[train_ids,'maturity'].max()),
        mean=mean.tolist(),scale=scale.tolist(),coef=coef.tolist(),y_mean=float(y.mean()),
        threshold=float(np.quantile(trained,.75)),predictions=prediction.tolist(),
        input_sha256=digest(OUT/'inputs.csv'),finished_utc=datetime.now(timezone.utc).isoformat()))


def fit():
    offline()
    assert not (OUT/'fits').exists(), 'No retry or repeat fits'
    check_locks('published_design')
    check_locks('run_lock')
    meta=read(OUT/'inputs.json')
    assert meta['status']=='PASS' and digest(OUT/'inputs.csv')==meta['input_sha256']
    plan=read(EX/'protocols/design.json')
    assert plan['execution_authorized'] and plan['proposed_fits_cap']==12
    f=pd.read_csv(OUT/'inputs.csv').set_index('signal')
    b=plan['baseline_columns']
    variants={'M0':b+['S'],'M1':b+['S','z'],'M2':b+['S','z','zs']}
    tasks=[]
    test_all=[]
    for year in plan['evaluation_years']:
        full=f.loc[f.year.eq(year) & f.feature_ready]
        cutoff=int(full.index.min())
        test=full.loc[full.label_ready]
        train=f.loc[f.feature_ready & f.label_ready & f.maturity.lt(cutoff)]
        assert len(train)>68 and train.maturity.max()<cutoff
        test_all.extend(test.index.tolist())
        for name,cols in variants.items():
            tasks.append((len(tasks)+1,year,name,cols,list(map(int,train.index)),list(map(int,test.index)),cutoff))
    assert len(tasks)==12
    (OUT/'fits').mkdir()
    for slot,year,name,*_ in tasks:
        write(OUT/f'fits/reserved_{slot:02d}.json',dict(slot=slot,year=year,model=name,reserved_utc=datetime.now(timezone.utc).isoformat(),failure_counts=True))
    failures=[]
    for task in tasks:
        try:
            fit_one(task,f)
        except Exception as exc:
            item=dict(slot=task[0],status='FAILED',error_type=type(exc).__name__,error=str(exc))
            write(OUT/f'fits/failed_{task[0]:02d}.json',item)
            failures.append(item)
    receipt=dict(status='PARTIAL' if failures else 'COMPLETE',fits_reserved=12,fits_completed=12-len(failures),failed_fits=len(failures),fits_remaining=0,
        models=list(variants),max_workers=1,native_threads=1,new_source_calls=0,new_labels=0,new_accounts=0,failures=failures)
    if not failures:
        p=f.loc[test_all].copy()
        for slot,year,name,*_ in tasks:
            r=read(OUT/f'fits/fit_{slot:02d}.json')
            ix=r['test_signals']
            p.loc[ix,'score_'+name]=r['predictions']
            p.loc[ix,'sel_'+name]=np.array(r['predictions'])>=r['threshold']
        p.reset_index().to_csv(OUT/'predictions.csv',index=False,lineterminator='\n')
        receipt.update(evaluation_rows=len(p),parent_rows=int(p.A.sum()),prediction_sha256=digest(OUT/'predictions.csv'))
    write(OUT/'fit_receipt.json',receipt)
    print(json.dumps(receipt))


if __name__=='__main__':
    {'precheck':precheck,'prepare':prepare,'fit':fit}[sys.argv[1]]()
