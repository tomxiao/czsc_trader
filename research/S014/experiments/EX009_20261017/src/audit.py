"""Recompute model/economic contrasts and verify the new public data binding."""
from hashlib import sha256
import json
import sys
import numpy as np
import pandas as pd
from inputs import ROOT, EXPERIMENT, RUN, previous, prior_csv, load_index
from market_features import features, predict, masks, MODELS
from market_stats import compare
from study import groups, precheck
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EXPERIMENT/'others/audit.json'
    if target.exists():
        raise RuntimeError('Preserve audit')
    checks=[]
    (data,dates,observation,*_),prior=previous()
    index=load_index()
    assert dates.equals(pd.DatetimeIndex(pd.to_datetime(index.Date)))
    assert len(index)==1642
    ready=json.loads((EXPERIMENT/'others/upstream_verification.json').read_text(encoding='utf-8'))
    assert ready['status']=='PASS' and all(ready['checks'].values())
    assert ready['source_calls_used']==1 and ready['remaining_source_calls']==5
    assert ready['source_calls'][0]['api']=='index_daily' and ready['source_calls'][0]['symbol']=='000001.SH'
    checks+=['native_index_binding_full_calendar','actual_source_call_budget']
    for f in ('published_design.json','implementation_published.json','attribution_published.json'):
        for name,value in json.loads((EXPERIMENT/'protocols'/f).read_text(encoding='utf-8')).items():
            path=EXPERIMENT/('protocols/design.json' if name=='design' else 'protocols/implementation.json' if name=='implementation' else f'src/{name}.py')
            assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    checks.append('predeclared_material_hashes')
    stock=prior_csv(prior,'features').drop(columns='signal')
    expected=features(data['stock.ohlcv'],index,stock)
    saved=pd.read_csv(RUN/'features.csv').drop(columns='signal')
    pd.testing.assert_frame_equal(expected,saved,check_exact=False,rtol=1e-10,atol=1e-12)
    checks+=precheck(data['stock.ohlcv'],index,stock)
    checks.append('all1642features_recomputed')
    labels=prior_csv(prior,'labels')
    cols=list(dict.fromkeys(x for v in MODELS.values() for x in v))
    finite=np.isfinite(expected[cols].to_numpy()).all(axis=1)
    queue=labels.loc[labels.maturity.ge(0)&labels.signal.map(lambda x:bool(finite[int(x)]))].copy()
    for col in expected:
        queue[col]=expected[col].to_numpy()[queue.signal.to_numpy(dtype=int)]
    queue['year']=[dates[int(s)].year for s in queue.signal]
    predictions=pd.read_csv(RUN/'predictions.csv')
    r=json.loads((EXPERIMENT/'others/computation_result.json').read_text(encoding='utf-8'))
    fits=0
    for split in r['splits']:
        available=queue.loc[queue.horizon.eq(split['horizon'])].sort_values('signal')
        test=available.loc[available.year.eq(split['year'])]
        cutoff=int(test.signal.min())
        train=available.loc[available.maturity.lt(cutoff)]
        found=predictions.loc[predictions.horizon.eq(split['horizon'])&predictions.year.eq(split['year'])]
        assert len(train)==split['train'] and len(test)==len(found)==split['test']
        assert train.maturity.max()==split['latest_maturity']<cutoff==split['first_test_signal']
        for col in ('signal','entry','quantity','maturity','entry_filled','status','entry_price','exit_price','net_return','adverse'):
            pd.testing.assert_series_equal(test[col].reset_index(drop=True),found[col].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        for name,columns in MODELS.items():
            a,b=predict((name,train[columns].to_numpy(),test[columns].to_numpy(),train.net_return.to_numpy()))
            threshold=float(np.quantile(a,.75))
            assert abs(threshold-split['thresholds'][name])<1e-12
            key=name.replace('-','_')
            np.testing.assert_allclose(b,found[f'prediction_{key}'],rtol=0,atol=1e-10)
            np.testing.assert_array_equal(b>=threshold,found[f'selected_{key}'])
            fits+=1
    assert fits==r['model_fits']==112 and len(predictions)==r['test_rows']==3633
    checks+=['labels_inherited_without_economic_change','all16maturity_boundaries','all112models_thresholds_selections']
    annual=pd.read_csv(EXPERIMENT/'others/annual.csv')
    for h,raw in predictions.groupby('horizon'):
        part=raw.sort_values('signal').reset_index(drop=True)
        y=part.net_return.to_numpy()
        event=masks(part)
        event['stock-repair-residual']=event['stock-repair']
        for result in (x for x in r['comparisons'] if x['horizon']==h):
            name=result['name']
            if result['kind']=='model':
                key=name.replace('-','_')
                baseline='tree_stock' if name.startswith('tree') else 'ridge_stock'
                a,b=part[f'selected_{key}'].to_numpy(),part[f'selected_{baseline}'].to_numpy()
                mode='allocation'; values=y
                seed=13+int(h)
            else:
                a,b=(x.to_numpy() for x in event[name]); mode='conditional'
                values=y-part.prediction_ridge_relative.to_numpy() if name.endswith('residual') else y
                seed=41+int(h)
            # Direct arithmetic, independently of bootstrap routine.
            if mode=='allocation':
                manual=float((values*(a.astype(float)-b.astype(float))).mean())
            else:
                weighted=[]
                for _,g in part.groupby('year'):
                    ga,gb=a[g.index],b[g.index]
                    if ga.any() and gb.any():
                        weighted.append((float(values[g.index][ga].mean()-values[g.index][gb].mean()),int((ga|gb).sum())))
                manual=sum(x*w for x,w in weighted)/sum(w for _,w in weighted)
            assert abs(manual-result['difference'])<1e-12
            recalculated=compare((groups(part,values,a,b),mode,1.,seed))
            for key in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history352'):
                if result[key] is None:
                    assert recalculated[key] is None
                else:
                    np.testing.assert_allclose(result[key],recalculated[key],rtol=0,atol=1e-10)
            for year,g in part.groupby('year'):
                row=annual.loc[annual.kind.eq(result['kind'])&annual.horizon.eq(h)&annual.name.eq(name)&annual.year.eq(str(year))].iloc[0]
                ga,gb=a[g.index],b[g.index]
                assert row.selected==ga.sum() and row.filled==g.loc[ga,'entry_filled'].sum()
                if ga.any():
                    assert abs(row.selected_mean-values[g.index][ga].mean())<1e-12
                else:
                    assert pd.isna(row.selected_mean)
                assert abs(row.per_origin-(values[g.index]*ga).mean())<1e-12
    checks+=['all56contrast_points_independent_arithmetic','all56bootstrap_reproductions','year_counts_means_cash_allocation']
    cash=pd.read_csv(RUN/'cash_attribution.csv')
    _,prices,*_=observation
    for row in cash.to_dict('records'):
        s,e,m=(int(row[k]) for k in ('signal','entry','maturity'))
        found=predictions.loc[predictions.signal.eq(s)&predictions.horizon.eq(row['horizon'])].iloc[0]
        q=float(found.quantity);buy=float(found.entry_price);sell=float(found.exit_price);close=float(prices[e,3])
        first=q*(close-buy)/100000;later=q*(sell-close)/100000;fees=q*(buy+sell)*.001/100000
        np.testing.assert_allclose([first,later,fees,first+later-fees],[row['first_cash'],row['later_cash'],row['fees'],row['net_return']],rtol=0,atol=1e-10)
        beta=float(expected.beta.iloc[s])
        mfirst=q*buy*np.expm1(beta*np.log(index.Close.iloc[e]/index.Open.iloc[e]))/100000
        mlater=q*close*np.expm1(beta*np.log(index.Open.iloc[m]/index.Close.iloc[e]))/100000
        np.testing.assert_allclose([mfirst,mlater,first-mfirst,later-mlater],
            [row['market_first_proxy'],row['market_later_proxy'],row['first_residual'],row['later_residual']],rtol=0,atol=1e-10)
        assert row['synchronous_open_endpoints']==(abs(buy-prices[e,0])<1e-9 and abs(sell-prices[m,0])<1e-9)
    checks+=['cash_market_proxy_and_residual_identity','opening_endpoint_timing_flags']
    manifest=[]
    for p in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),
              *(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        manifest.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()})
    output={'status':'PASS','checks':checks,'model_recomputations':fits,'contrast_recomputations':len(r['comparisons']),
        'cash_rows':len(cash),'source_calls_in_audit':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in output.items() if k!='manifest'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
