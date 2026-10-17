"""Recompute industry exposure, model scores, labels, contrasts and cash identity."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous,old_csv,indices
from sector_features import features,predict,masks,MODELS
from sector_stats import compare
from study import groups,precheck
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EXPERIMENT/'others/audit.json'
    if target.exists():
        raise RuntimeError('Preserve audit')
    checks=[]
    (data,dates,observation,*_),prior=previous();market,sector=indices(prior)
    assert dates.equals(pd.DatetimeIndex(pd.to_datetime(market.Date))) and dates.equals(pd.DatetimeIndex(pd.to_datetime(sector.Date)))
    ready=json.loads((EXPERIMENT/'others/upstream_verification_resolved.json').read_text(encoding='utf-8'))
    failed=json.loads((EXPERIMENT/'others/upstream_verification.json').read_text(encoding='utf-8'))
    identity=json.loads((EXPERIMENT/'others/vendor_identity.json').read_text(encoding='utf-8'))
    assert failed['status']=='FAILED' and failed['errors'][0]['code']=='EMPTY_DATA' and failed['source_calls_used']==1
    assert identity['status']=='PASS' and identity['records'][0]['fullname']=='中证细分化工产业主题指数' and identity['canonical_symbol']=='000813.CSI'
    assert ready['status']=='PASS' and all(ready['checks'].values()) and ready['source_calls_used']==3 and ready['remaining_source_calls']==2
    assert [c['api'] for c in ready['source_calls']]==['index_daily','index_basic','index_daily']
    assert ready['identity']['symbol']=='000813.CSI' and len(sector)==1642
    checks+=['public_native_index_binding_calendar_and_hash','same_index_catalogue_resolution','failed_attempt_preserved_and_all3calls_counted']
    special={'design':'protocols/design.json','implementation':'protocols/implementation.json','identity-resolution':'protocols/identity_resolution.json',
        'identity-program':'src/resolve_identity.py','failed-upstream':'others/upstream_verification.json','vendor-identity':'others/vendor_identity.json'}
    for filename in ('published_design','identity_published','canonical_published','implementation_published','attribution_published'):
        for name,value in json.loads((EXPERIMENT/f'protocols/{filename}.json').read_text(encoding='utf-8')).items():
            path=EXPERIMENT/special.get(name,f'src/{name}.py')
            assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes(),name
    checks.append('all_predeclared_material_hashes')
    inherited=old_csv(prior,'followup-features').drop(columns='signal')
    f=features(data['stock.ohlcv'],market,sector,inherited)
    saved=pd.read_csv(RUN/'features.csv').drop(columns='signal')
    pd.testing.assert_frame_equal(f,saved,check_exact=False,rtol=1e-9,atol=1e-12)
    checks+=precheck(data['stock.ohlcv'],market,sector,inherited)
    # Independent covariance normal-equation solution for every prior60 exposure.
    r=np.column_stack([np.log(v.Close/v.Close.shift()).to_numpy() for v in (data['stock.ohlcv'],market,sector)])
    verified=0
    for t in range(61,len(f)):
        if f.exposure_status.iloc[t]!='READY':
            continue
        y,x=r[t-60:t,0],r[t-60:t,1:]
        centered=x-x.mean(axis=0);cy=y-y.mean()
        b=np.linalg.solve(centered.T@centered,centered.T@cy)
        a=float(y.mean()-x.mean(axis=0)@b)
        np.testing.assert_allclose([a,*b],f.loc[t,['alpha2','beta_market2','beta_sector2']].to_numpy(dtype=float),rtol=1e-8,atol=1e-10)
        residual=y-a-x@b
        np.testing.assert_allclose(centered.T@residual,np.zeros(2),rtol=0,atol=1e-10)
        verified+=1
    checks+=['all_prior60_OLS_covariance_solutions','all_factor_residual_orthogonality']
    source=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(source['evidence']['run-labels']).resolve(ROOT))
    cols=list(dict.fromkeys(c for v in MODELS.values() for c in v))
    valid=np.isfinite(f[cols].to_numpy()).all(axis=1)
    queue=labels.loc[labels.horizon.isin([1,3])&labels.maturity.ge(0)&labels.signal.map(lambda s:bool(valid[int(s)]))].copy()
    queue['year']=[dates[int(s)].year for s in queue.signal]
    for c in f:
        queue[c]=f[c].to_numpy()[queue.signal.to_numpy(dtype=int)]
    p=pd.read_csv(RUN/'predictions.csv')
    result=json.loads((EXPERIMENT/'others/computation_result.json').read_text(encoding='utf-8'))
    oldp=old_csv(prior,'followup-predictions');fits=0;reproductions=0
    for split in result['splits']:
        h,year=split['horizon'],split['year']
        q=queue.loc[queue.horizon.eq(h)].sort_values('signal');test=q.loc[q.year.eq(year)]
        start,end=int(test.signal.min()),int(test.signal.max());train=q.loc[q.maturity.lt(start)]
        found=p.loc[p.horizon.eq(h)&p.year.eq(year)]
        assert len(train)==split['train'] and len(test)==len(found)==split['test']
        assert train.maturity.max()==split['latest_maturity']<start==split['first_test_signal']
        sq,iq=(float(np.quantile(train[c],.1)) for c in ('ret1','innovation1'))
        assert abs(sq-split['stockq10'])<1e-12 and abs(iq-split['sectorq10'])<1e-12
        for c in ('signal','entry','quantity','maturity','entry_filled','status','entry_price','exit_price','net_return','adverse'):
            pd.testing.assert_series_equal(test[c].reset_index(drop=True),found[c].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        universe=f.iloc[np.flatnonzero(valid)[0]:end+1];first=int(universe.index.min())
        for algo in ('ridge','tree'):
            for name,cs in MODELS.items():
                trained,history=predict((f'{algo}-{name}',train[cs].to_numpy(),universe[cs].to_numpy(),train.net_return.to_numpy()))
                key=f'{algo}_{name}';values=history[test.signal.to_numpy(dtype=int)-first]
                threshold=float(np.quantile(trained,.75))
                assert abs(threshold-split['thresholds'][key])<1e-12
                np.testing.assert_allclose(values,found[f'prediction_{key}'],rtol=0,atol=1e-10)
                np.testing.assert_array_equal(values>=threshold,found[f'frozen_{key}'])
                rolling=np.array([np.quantile(history[int(s)-first-126:int(s)-first],.75) for s in test.signal])
                np.testing.assert_allclose(rolling,found[f'rolling_threshold_{key}'],rtol=0,atol=1e-10)
                np.testing.assert_array_equal(values>=rolling,found[f'rolling_{key}'])
                if name in ('stock','market'):
                    oldkey=f'{algo}_'+('strong' if name=='stock' else 'relative')
                    old=oldp.loc[oldp.horizon.eq(h)&oldp.year.eq(year)]
                    np.testing.assert_allclose(values,old[f'prediction_{oldkey}'],rtol=0,atol=1e-10)
                    reproductions+=1
                fits+=1
        for name,(a,b) in masks(test,sq,iq).items():
            np.testing.assert_array_equal(a,found[f'event_{name}']);np.testing.assert_array_equal(b,found[f'control_{name}'])
    assert fits==112 and reproductions==32 and len(p)==1822
    checks+=['all112models_refit_and32predecessor_scores_identical','frozen_and_manual126prior_thresholds','all8maturity_and_q10_boundaries','inherited_labels_quantities_fees_censoring','all6event_masks_each_split']
    for result in result['comparisons']:
        g=p.loc[p.horizon.eq(result['horizon'])].sort_values('signal').reset_index(drop=True);y=g.net_return.to_numpy()
        if result['kind']=='model':
            a=g[f'{result["mode"]}_{result["algo"]}_{result["left"]}'].to_numpy()
            b=np.ones(len(g),dtype=bool) if result['right']=='all' else g[f'{result["mode"]}_{result["algo"]}_{result["right"]}'].to_numpy()
            mode='allocation';seed=313+result['horizon']
            manual=float((y*(a.astype(float)-b.astype(float))).mean())
        else:
            a,b=g[f'event_{result["name"]}'].to_numpy(),g[f'control_{result["name"]}'].to_numpy()
            if result['mode']=='residual':
                y=y-g.prediction_ridge_market.to_numpy()
            mode='conditional';seed=413+result['horizon'];weighted=[]
            for _,part in g.groupby('year'):
                sa,sb=a[part.index],b[part.index]
                if sa.any() and sb.any():
                    weighted.append((float(y[part.index][sa].mean()-y[part.index][sb].mean()),int((sa|sb).sum())))
            manual=sum(x*w for x,w in weighted)/sum(w for _,w in weighted)
        assert abs(manual-result['difference'])<1e-12
        check=compare((groups(g,y,a,b),mode,1.,seed))
        for k in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history520'):
            if result[k] is None:
                assert check[k] is None
            else:
                np.testing.assert_allclose(check[k],result[k],rtol=0,atol=1e-10)
    checks+=['all80contrast_points_independent_arithmetic','all80bootstrap_intervals_reproduced']
    annual=pd.read_csv(EXPERIMENT/'others/annual.csv')
    for row in annual.to_dict('records'):
        allp=p.loc[p.horizon.eq(row['horizon'])].sort_values('signal').reset_index(drop=True)
        g=allp if row['year']=='ALL' else allp.loc[allp.year.eq(int(row['year']))]
        if row['kind']=='model':
            a=g[f'{row["mode"]}_{row["algo"]}_{row["name"]}'].to_numpy()
            mask=np.ones(len(g),dtype=bool) if row['scope']=='all' else g.gap_down_repair.eq(1).to_numpy()
            a,b=a&mask,~a&mask;y=g.net_return.to_numpy()
            assert row['n']==mask.sum()
        else:
            a,b=allp[f'event_{row["name"]}'].to_numpy(),allp[f'control_{row["name"]}'].to_numpy()
            if row['kind']=='decluster':
                retained=[]
                for s in allp.loc[a|b,'signal']:
                    if not retained or int(s)>retained[-1]+10:
                        retained.append(int(s))
                keep=allp.signal.isin(retained).to_numpy();a,b=a&keep,b&keep
            a,b=a[g.index],b[g.index];y=g.net_return.to_numpy()
            if row['mode']=='residual':
                y=y-g.prediction_ridge_market.to_numpy()
        assert row['selected']==a.sum() and row['control']==b.sum() and row['filled']==g.loc[a,'entry_filled'].sum()
        for mask,key in ((a,'selected_mean'),(b,'control_mean')):
            if mask.any():
                assert abs(row[key]-y[mask].mean())<1e-12
            else:
                assert pd.isna(row[key])
        if pd.notna(row.get('per_origin')):
            assert abs(row['per_origin']-(y*a).mean())<1e-12
    checks+=['all_annual_selected_unselected_and_repair_groups','all_event_decluster_counts_and_means']
    cash=pd.read_csv(RUN/'cash_attribution.csv');_,prices,*_=observation
    for row in cash.to_dict('records'):
        found=p.loc[p.signal.eq(row['signal'])&p.horizon.eq(row['horizon'])].iloc[0]
        e,m=int(found.entry),int(found.maturity);q=float(found.quantity);buy=float(found.entry_price);sell=float(found.exit_price);close=float(prices[e,3])
        first=q*(close-buy)/100000;later=q*(sell-close)/100000;cost=q*(buy+sell)*.001/100000
        mf=np.log(market.Close.iloc[e]/market.Open.iloc[e]);ml=np.log(market.Open.iloc[m]/market.Close.iloc[e])
        sf=np.log(sector.Close.iloc[e]/sector.Open.iloc[e]);sl=np.log(sector.Open.iloc[m]/sector.Close.iloc[e])
        onefirst=q*buy*np.expm1(found.beta*mf)/100000;onelater=q*close*np.expm1(found.beta*ml)/100000
        twofirst=q*buy*np.expm1(found.beta_market2*mf+found.beta_sector2*sf)/100000
        twolater=q*close*np.expm1(found.beta_market2*ml+found.beta_sector2*sl)/100000
        np.testing.assert_allclose([first,later,cost,first+later-cost,onefirst,onelater,twofirst,twolater,first-twofirst,later-twolater],
            [row['first_cash'],row['later_cash'],row['fees'],row['net_return'],row['market_first'],row['market_later'],row['both_first'],row['both_later'],row['both_first_residual'],row['both_later_residual']],rtol=0,atol=1e-10)
        assert row['open_endpoints']==(abs(buy-prices[e,0])<1e-9 and abs(sell-prices[m,0])<1e-9)
    ar=json.loads((EXPERIMENT/'others/attribution_result.json').read_text(encoding='utf-8'))
    for row in ar['annual']:
        part=cash.loc[cash.horizon.eq(row['horizon'])&cash.year.eq(row['year'])]
        if row['mode']=='open-endpoints':
            part=part.loc[part.open_endpoints]
        assert len(part)==row['n']
        for key in row:
            if key in part.columns and key not in ('year','horizon','n'):
                assert abs(row[key]-part[key].mean())<1e-10
        for key in ('market_later_residual','both_later_residual'):
            assert abs(row[f'{key}_rmse']-np.sqrt(np.mean(part[key]**2)))<1e-10
    checks+=['all_cash_attribution_recomputed','all_opening_endpoint_timing_flags','all_attribution_annual_means_and_dispersion']
    manifest=[]
    for path in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),*(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        manifest.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest()})
    output={'status':'PASS','checks':checks,'prior60exposure_checks':verified,'model_recomputations':fits,'predecessor_reproductions':reproductions,
        'contrast_recomputations':80,'cash_rows':len(cash),'source_calls':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in output.items() if k!='manifest'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
