"""Verify the final omitted-stock-information counterfactual without new data."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous
from stock_lag import augmented
from sector_features import predict
from stock_lag_stats import compare
from study import groups
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EXPERIMENT/'others/stock_lag_audit.json'
    if target.exists():
        raise RuntimeError('Preserve audit')
    checks=[]
    for name,value in json.loads((EXPERIMENT/'protocols/stock_lag_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/stock_lag_design.json' if name=='stock-lag-design' else f'src/{name}.py')
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,*_),prior=previous();f,variants=augmented(pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    pd.testing.assert_frame_equal(f,pd.read_csv(RUN/'stock_lag_features.csv').drop(columns='signal'),check_exact=False,rtol=1e-10,atol=1e-12)
    for n in (801,1200):
        truncated,_=augmented(pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n]);pd.testing.assert_frame_equal(f.iloc[:n],truncated)
    checks+=['predeclared_materials_and_new_feature_prefixes']
    source=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(source['evidence']['run-labels']).resolve(ROOT))
    queue=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)&labels.signal.ge(62)].copy();queue['year']=[dates[int(s)].year for s in queue.signal]
    for c in f:
        queue[c]=f[c].to_numpy()[queue.signal.to_numpy(dtype=int)]
    p=pd.read_csv(RUN/'stock_lag_predictions.csv');old=pd.read_csv(RUN/'followup_predictions.csv')
    result=json.loads((EXPERIMENT/'others/stock_lag_result.json').read_text(encoding='utf-8'));fits=0
    for split in result['splits']:
        test=queue.loc[queue.year.eq(split['year'])];start,end=int(test.signal.min()),int(test.signal.max());train=queue.loc[queue.maturity.lt(start)]
        found=p.loc[p.year.eq(split['year'])];universe=f.iloc[62:end+1]
        assert len(test)==len(found)==split['test'] and len(train)==split['train']
        assert train.maturity.max()==split['latest_maturity']<start==split['first_signal']
        for c in ('signal','entry','quantity','maturity','entry_filled','net_return'):
            pd.testing.assert_series_equal(test[c].reset_index(drop=True),found[c].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        for name,cs in variants.items():
            trained,history=predict((f'ridge-{name}',train[cs].to_numpy(),universe[cs].to_numpy(),train.net_return.to_numpy()));fits+=1
            values=history[test.signal.to_numpy(dtype=int)-62];threshold=float(np.quantile(trained,.75))
            rolling=np.array([np.quantile(history[int(s)-62-126:int(s)-62],.75) for s in test.signal])
            np.testing.assert_allclose(values,found[f'prediction_{name}'],rtol=0,atol=1e-10)
            assert abs(threshold-split['thresholds'][name])<1e-12
            np.testing.assert_allclose(rolling,found[f'rolling_threshold_{name}'],rtol=0,atol=1e-10)
            np.testing.assert_array_equal(values>=threshold,found[f'frozen_{name}']);np.testing.assert_array_equal(values>=rolling,found[f'rolling_{name}']);np.testing.assert_array_equal(values>0,found[f'zero_{name}'])
            if name=='sectoralternative':
                np.testing.assert_allclose(values,old.loc[old.year.eq(split['year']),'prediction_ridge_lagboth'],rtol=0,atol=1e-10)
    checks+=['all16models_refit_and4prior_reproductions','all_labels_maturity_boundaries_and_three_selection_modes']
    for r in result['comparisons']:
        y=p.net_return.to_numpy();a=p[f'{r["mode"]}_{r["left"]}'].to_numpy()
        b=old[f'{r["mode"]}_ridge_lagmarket'].to_numpy() if r['right']=='lagmarket' else p[f'{r["mode"]}_{r["right"]}'].to_numpy()
        assert abs((y*(a.astype(float)-b.astype(float))).mean()-r['difference'])<1e-12
        check=compare((groups(p,y,a,b),'allocation',1.,613))
        for k in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history574'):
            np.testing.assert_allclose(check[k],r[k],rtol=0,atol=1e-10)
    checks.append('all12bootstrap_and_direct_allocation_points')
    a=pd.read_csv(EXPERIMENT/'others/stock_lag_annual.csv')
    for row in a.to_dict('records'):
        g=p if row['year']=='ALL' else p.loc[p.year.eq(int(row['year']))];mask=g[f'{row["mode"]}_{row["name"]}'].to_numpy()
        assert row['n']==len(g) and row['selected']==mask.sum() and row['filled']==g.loc[mask,'entry_filled'].sum()
        if mask.any():
            assert abs(row['selected_mean']-g.loc[mask,'net_return'].mean())<1e-12
        assert abs(row['per_origin']-(g.net_return*mask).mean())<1e-12
        assert abs(row['mae']-(g[f'prediction_{row["name"]}']-g.net_return).abs().mean())<1e-12
    checks.append('all_year_counts_cash_and_MAE')
    manifest=[]
    for path in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),*(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        manifest.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest()})
    output={'status':'PASS','checks':checks,'model_recomputations':fits,'prior_reproductions':4,'contrast_recomputations':12,'source_calls':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print('STOCK_LAG_AUDIT_PASS',len(checks))


if __name__=='__main__':
    main()
