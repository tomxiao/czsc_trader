"""Independently verify adaptive tests, score calibration and explicit mechanisms."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EXPERIMENT,RUN,previous,prior_csv
from market_features import predict
from followup import augmented,VARIANTS,STRONG
from followup_stats import compare
from mechanism_stats import compare as mechanism_compare
from mechanisms import event_masks
from study import groups
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EXPERIMENT/'others/followup_audit.json'
    if target.exists():
        raise RuntimeError('Preserve existing audit')
    checks=[]
    for f,design in [('followup_published.json','followup-design'),('mechanism_published.json','mechanism-design')]:
        for name,value in json.loads((EXPERIMENT/'protocols'/f).read_text(encoding='utf-8')).items():
            path=EXPERIMENT/(f'protocols/{"followup" if design=="followup-design" else "mechanism"}_design.json' if name==design else f'src/{name}.py')
            assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    checks.append('followup_predeclarations')
    (data,dates,*_),prior=previous()
    feature=augmented(data['stock.ohlcv'],pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    pd.testing.assert_frame_equal(feature,pd.read_csv(RUN/'followup_features.csv').drop(columns='signal'),check_exact=False,rtol=1e-10,atol=1e-12)
    for n in (801,1200):
        pd.testing.assert_frame_equal(feature.iloc[:n],augmented(data['stock.ohlcv'].iloc[:n],pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n]))
    checks.append('strong_stock_and_stale_market_features_causal')
    labels=prior_csv(prior,'labels')
    labels=labels.loc[labels.maturity.ge(0)&labels.signal.ge(61)].copy()
    labels['year']=[dates[int(s)].year for s in labels.signal]
    for c in feature:
        labels[c]=feature[c].to_numpy()[labels.signal.to_numpy(dtype=int)]
    predictions=pd.read_csv(RUN/'followup_predictions.csv')
    result=json.loads((EXPERIMENT/'others/followup_result.json').read_text(encoding='utf-8'))
    fits=0
    for split in result['splits']:
        h,year=split['horizon'],split['year']
        queue=labels.loc[labels.horizon.eq(h)].sort_values('signal')
        test=queue.loc[queue.year.eq(year)]
        start,end=int(test.signal.min()),int(test.signal.max())
        train=queue.loc[queue.maturity.lt(start)]
        found=predictions.loc[predictions.horizon.eq(h)&predictions.year.eq(year)]
        assert len(train)==split['train'] and len(test)==len(found)==split['test']
        assert train.maturity.max()==split['latest_maturity']<start==split['first_test_signal']
        for c in ('signal','maturity','entry','entry_filled','net_return','quantity','entry_price','exit_price'):
            pd.testing.assert_series_equal(test[c].reset_index(drop=True),found[c].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        universe=feature.iloc[61:end+1]
        for algo in ('ridge','tree'):
            for name,cols in VARIANTS.items():
                trained,history=predict((f'{algo}-{name}',train[cols].to_numpy(),universe[cols].to_numpy(),train.net_return.to_numpy()))
                key=f'{algo}_{name}';threshold=float(np.quantile(trained,.75))
                point=history[test.signal.to_numpy(dtype=int)-61]
                np.testing.assert_allclose(point,found[f'prediction_{key}'],rtol=0,atol=1e-10)
                assert abs(threshold-split['frozen_thresholds'][key])<1e-12
                np.testing.assert_array_equal(point>=threshold,found[f'frozen_{key}'])
                # Explicitly slice only prior126 completed scores for each origin.
                rolling=np.array([np.quantile(history[int(s)-61-126:int(s)-61],.75) for s in test.signal])
                np.testing.assert_allclose(rolling,found[f'rolling_threshold_{key}'],rtol=0,atol=1e-10)
                np.testing.assert_array_equal(point>=rolling,found[f'rolling_{key}'])
                fits+=1
    assert fits==112
    checks+=['all112followup_models_refit','all_rolling126_thresholds_manual_prior_slices','frozen_thresholds_and_economic_labels','all8followup_maturity_boundaries']
    annual=pd.read_csv(EXPERIMENT/'others/followup_annual.csv')
    contribution=pd.read_csv(EXPERIMENT/'others/followup_contributions.csv')
    for r in result['comparisons']:
        p=predictions.loc[predictions.horizon.eq(r['horizon'])].sort_values('signal').reset_index(drop=True)
        y=p.net_return.to_numpy();algo,mode=r['algo'],r['mode']
        a=p[f'{mode}_{algo}_{r["left"]}'].to_numpy()
        b=np.ones(len(p),dtype=bool) if r['right']=='all' else p[f'{mode}_{algo}_{r["right"]}'].to_numpy()
        delta=y*(a.astype(float)-b.astype(float))
        assert abs(delta.mean()-r['difference'])<1e-12
        check=compare((groups(p,y,a,b),'allocation',1.,113+r['horizon']))
        for k in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history408'):
            np.testing.assert_allclose(check[k],r[k],rtol=0,atol=1e-10)
        for year,g in p.groupby('year'):
            point=contribution.loc[contribution.horizon.eq(r['horizon'])&contribution.algo.eq(algo)&contribution['mode'].eq(mode)&
                contribution.left.eq(r['left'])&contribution.right.eq(r['right'])&contribution.year.eq(year)]
            assert abs(point.contribution_per_origin.sum()-delta[g.index].mean())<1e-12
    for r in annual.to_dict('records'):
        p=predictions.loc[predictions.horizon.eq(r['horizon'])]
        if r['year']!='ALL':
            p=p.loc[p.year.eq(int(r['year']))]
        sel=p[f'{r["mode"]}_{r["algo"]}_{r["variant"]}'].to_numpy()
        mask=np.ones(len(p),dtype=bool) if r['scope']=='all' else p.gap_down_repair.eq(1).to_numpy()
        a=sel&mask;b=~sel&mask
        assert r['n']==mask.sum() and r['selected']==a.sum() and r['filled']==p.loc[a,'entry_filled'].sum()
        if a.any():
            assert abs(p.loc[a,'net_return'].mean()-r['selected_mean'])<1e-12
        if b.any():
            assert abs(p.loc[b,'net_return'].mean()-r['unselected_mean'])<1e-12
        assert abs((p.net_return*a).mean()-r['per_origin'])<1e-12
    checks+=['all56followup_bootstraps_and_points','all_followup_selected_unselected_and_A_subset_means','all_added_removed_cash_contribution_sums']
    mechanism=pd.read_csv(RUN/'mechanism_predictions.csv')
    mresult=json.loads((EXPERIMENT/'others/mechanism_result.json').read_text(encoding='utf-8'))
    feature['market_previous5']=feature.market_ret5.shift()
    feature['relative_close1']=np.log1p(feature.ret1)-feature.beta*feature.market_ret1
    feature['relative_close5']=np.log1p(feature.ret5)-feature.beta*feature.market_ret5
    for c in ('market_previous5','relative_close1','relative_close5'):
        labels[c]=feature[c].to_numpy()[labels.signal.to_numpy(dtype=int)]
    mf=0
    for split in mresult['splits']:
        h,year=split['horizon'],split['year']
        queue=labels.loc[labels.horizon.eq(h)].sort_values('signal')
        test=queue.loc[queue.year.eq(year)]
        start=int(test.signal.min());train=queue.loc[queue.maturity.lt(start)]
        sq,mq=(float(np.quantile(train[c],.1)) for c in ('ret1','market_ret1'))
        assert abs(sq-split['stockq10'])<1e-12 and abs(mq-split['marketq10'])<1e-12
        assert train.maturity.max()==split['latest_maturity']<start==split['first_signal']
        found=mechanism.loc[mechanism.horizon.eq(h)&mechanism.year.eq(year)]
        for c in ('signal','maturity','net_return','entry_filled','entry_price','exit_price'):
            pd.testing.assert_series_equal(test[c].reset_index(drop=True),found[c].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        for name,(a,b) in event_masks(test,sq,mq).items():
            np.testing.assert_array_equal(a,found[f'selected_{name}'])
            np.testing.assert_array_equal(b,found[f'control_{name}'])
        expected=predict(('ridge-strong',train[STRONG].to_numpy(),test[STRONG].to_numpy(),train.net_return.to_numpy()))[1]
        np.testing.assert_allclose(expected,found.stock_prediction,rtol=0,atol=1e-10)
        mf+=1
    for r in mresult['comparisons']:
        p=mechanism.loc[mechanism.horizon.eq(r['horizon'])].sort_values('signal').reset_index(drop=True)
        a=p[f'selected_{r["name"]}'].to_numpy();b=p[f'control_{r["name"]}'].to_numpy()
        y=p.net_return.to_numpy()
        if r['mode']=='residual':
            y=y-p.stock_prediction.to_numpy()
        check=mechanism_compare((groups(p,y,a,b),'conditional',1.,213+r['horizon']))
        for k in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history440'):
            if r[k] is None:
                assert check[k] is None
            else:
                np.testing.assert_allclose(check[k],r[k],rtol=0,atol=1e-10)
    checks+=['all16mechanism_thresholds_boundaries_and_masks','all16strong_stock_predictions','all32mechanism_bootstraps']
    manifest=[]
    for p in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),
              *(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        manifest.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()})
    result={'status':'PASS','checks':checks,'followup_model_recomputations':fits,'mechanism_stock_recomputations':mf,
        'followup_contrast_recomputations':56,'mechanism_contrast_recomputations':32,'source_calls':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k!='manifest'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
