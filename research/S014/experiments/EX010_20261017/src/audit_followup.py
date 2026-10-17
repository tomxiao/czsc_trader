"""Verify the adaptive lagged-industry counterfactuals and score thresholds."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous
from followup import feature_and_models
from sector_features import predict
from followup_stats import compare
from study import groups
from czsc_trader.research_tools import EvidenceRef


def main():
    target=EXPERIMENT/'others/followup_audit.json'
    if target.exists():
        raise RuntimeError('Preserve existing audit')
    checks=[]
    for name,value in json.loads((EXPERIMENT/'protocols/followup_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/followup_design.json' if name=='followup-design' else f'src/{name}.py')
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,*_),prior=previous()
    feature,variants=feature_and_models(pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    pd.testing.assert_frame_equal(feature,pd.read_csv(RUN/'followup_features.csv').drop(columns='signal'),check_exact=False,rtol=1e-10,atol=1e-12)
    for n in (801,1200):
        truncated,_=feature_and_models(pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n])
        pd.testing.assert_frame_equal(feature.iloc[:n],truncated)
    checks+=['followup_published_identity','new_lag_features_prefix_causal']
    source=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(source['evidence']['run-labels']).resolve(ROOT))
    cs=list(dict.fromkeys(c for v in variants.values() for c in v));valid=np.isfinite(feature[cs].to_numpy()).all(axis=1)
    queue=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)&labels.signal.map(lambda s:bool(valid[int(s)]))].copy()
    queue['year']=[dates[int(s)].year for s in queue.signal]
    for c in feature:
        queue[c]=feature[c].to_numpy()[queue.signal.to_numpy(dtype=int)]
    result=json.loads((EXPERIMENT/'others/followup_result.json').read_text(encoding='utf-8'))
    p=pd.read_csv(RUN/'followup_predictions.csv');fits=0
    assert result['first_feature_signal']==np.flatnonzero(valid)[0]==62
    for split in result['splits']:
        test=queue.loc[queue.year.eq(split['year'])];start,end=int(test.signal.min()),int(test.signal.max())
        train=queue.loc[queue.maturity.lt(start)];universe=feature.iloc[62:end+1]
        found=p.loc[p.year.eq(split['year'])]
        assert len(test)==split['test']==len(found) and len(train)==split['train']
        assert train.maturity.max()==split['latest_maturity']<start==split['first_signal']
        for c in ('signal','maturity','entry','quantity','entry_filled','net_return','entry_price','exit_price'):
            pd.testing.assert_series_equal(test[c].reset_index(drop=True),found[c].reset_index(drop=True),check_names=False,check_exact=False,rtol=1e-10,atol=1e-12)
        for algo in ('ridge','tree'):
            for name,cols in variants.items():
                trained,history=predict((f'{algo}-{name}',train[cols].to_numpy(),universe[cols].to_numpy(),train.net_return.to_numpy()))
                key=f'{algo}_{name}';values=history[test.signal.to_numpy(dtype=int)-62];threshold=float(np.quantile(trained,.75))
                rolling=np.array([np.quantile(history[int(s)-62-126:int(s)-62],.75) for s in test.signal])
                assert abs(threshold-split['thresholds'][key])<1e-12
                np.testing.assert_allclose(values,found[f'prediction_{key}'],rtol=0,atol=1e-10)
                np.testing.assert_array_equal(values>=threshold,found[f'frozen_{key}'])
                np.testing.assert_allclose(rolling,found[f'rolling_threshold_{key}'],rtol=0,atol=1e-10)
                np.testing.assert_array_equal(values>=rolling,found[f'rolling_{key}']);np.testing.assert_array_equal(values>0,found[f'zero_{key}'])
                fits+=1
    assert fits==56 and len(p)==912
    checks+=['all56models_on_common_first62_queue','all4maturity_boundaries_and_inherited_labels','all_frozen_manual126_and_zero_selections']
    for r in result['comparisons']:
        y=p.net_return.to_numpy();a=p[f'{r["mode"]}_{r["algo"]}_{r["left"]}'].to_numpy();b=p[f'{r["mode"]}_{r["algo"]}_{r["right"]}'].to_numpy()
        manual=float((y*(a.astype(float)-b.astype(float))).mean());assert abs(manual-r['difference'])<1e-12
        check=compare((groups(p,y,a,b),'allocation',1.,513))
        for k in ('difference','without2026','drop3_per_year','valid_fraction','interval95','interval_history562'):
            np.testing.assert_allclose(r[k],check[k],rtol=0,atol=1e-10)
    checks.append('all42bootstrap_intervals_and_independent_points')
    annual=pd.read_csv(EXPERIMENT/'others/followup_annual.csv')
    for row in annual.to_dict('records'):
        g=p if row['year']=='ALL' else p.loc[p.year.eq(int(row['year']))]
        s=g[f'{row["mode"]}_{row["algo"]}_{row["name"]}'].to_numpy();mask=np.ones(len(g),dtype=bool) if row['scope']=='all' else g.gap_down_repair.eq(1).to_numpy()
        a,b=s&mask,~s&mask;y=g.net_return.to_numpy()
        assert row['n']==mask.sum() and row['selected']==a.sum() and row['filled']==g.loc[a,'entry_filled'].sum()
        for chosen,key in ((a,'selected_mean'),(b,'control_mean')):
            if chosen.any():
                assert abs(row[key]-y[chosen].mean())<1e-12
            else:
                assert pd.isna(row[key])
        assert abs(row['per_origin']-(y*a).mean())<1e-12
        assert abs(row['mae']-(g[f'prediction_{row["algo"]}_{row["name"]}']-g.net_return).abs().mean())<1e-12
    checks.append('all_selected_unselected_repair_means_counts_and_MAE')
    diagnostics=pd.read_csv(EXPERIMENT/'others/followup_participation.csv')
    for row in diagnostics.to_dict('records'):
        a=p[f'{row["mode"]}_{row["algo"]}_{row["left"]}'].to_numpy();b=p[f'{row["mode"]}_{row["algo"]}_{row["right"]}'].to_numpy()
        y=p.net_return.to_numpy();delta=y*(a.astype(float)-b.astype(float));g=p.loc[p.year.eq(row['year'])]
        changed=(a!=b)&p.year.eq(row['year']).to_numpy();retained=[]
        for s in p.loc[changed,'signal']:
            if not retained or int(s)>retained[-1]+10:
                retained.append(int(s))
        keep=p.signal.isin(retained).to_numpy()
        assert row['changed']==changed.sum() and abs(row['delta']-delta[g.index].mean())<1e-12
        assert abs(row['decluster_delta']-(delta[g.index]*keep[g.index]).mean())<1e-12
    checks.append('changed_participation_and_decluster_cash')
    manifest=[]
    for path in [*(EXPERIMENT/'src').glob('*.py'),*(EXPERIMENT/'protocols').glob('*.json'),*(EXPERIMENT/'others').glob('*.json'),*(EXPERIMENT/'others').glob('*.csv'),*RUN.glob('*.csv')]:
        manifest.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest()})
    output={'status':'PASS','checks':checks,'model_recomputations':fits,'contrast_recomputations':42,'source_calls':0,'strategy_accounts':0,'manifest':manifest}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in output.items() if k!='manifest'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
