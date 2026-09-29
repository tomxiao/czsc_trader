"""Read-only focused verification of the stage-two delivery; no signal selection."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import statsmodels.api as sm
from research_experiment import load_experiment_input,load_experiment
from czsc_trader.experiment_archive import validate_experiment_archive

ROOT=Path(__file__).resolve().parents[3]
P10=ROOT/'experiments/S011/20260929_S011_EX10'
P12=ROOT/'experiments/S011/20260929_S011_EX12'
WINDOWS=(('2025-07-01','2026-01-01'),('2026-01-01','2026-07-01'),('2026-07-01','2026-09-29'))
CONTROLS=['daily__return_5','daily__vol_20']
PRIMARY=['market__large_return_1','EX01__tail_return_90','external__spx_1','daily__range_mean_5']

def read(name):
    return pd.read_csv(P10/'artifacts'/name,index_col='Date',parse_dates=['Date'])

def predict(train,test,fields,label):
    y=train[label].to_numpy();intercept=np.mean(y)
    if not fields:return np.full(len(test),intercept),np.nan
    a=train[fields].to_numpy();b=test[fields].to_numpy();center=np.mean(a,axis=0);scale=np.std(a,axis=0);scale[scale==0]=1
    a=(a-center)/scale;b=(b-center)/scale
    design=np.vstack((a,np.sqrt(10)*np.eye(len(fields))))
    target=np.concatenate((y-intercept,np.zeros(len(fields))))
    weight=np.linalg.lstsq(design,target,rcond=None)[0]
    return intercept+b@weight,weight[-1]

def partial(z,factor,label,controls,orientation):
    z=z[list(dict.fromkeys([factor,label,*controls]))].dropna().rank(pct=True)
    xx=sm.add_constant(z[controls].to_numpy())
    a=sm.OLS(z[factor].to_numpy()*orientation,xx).fit().resid
    b=sm.OLS(z[label].to_numpy(),xx).fit().resid
    return np.corrcoef(a,b)[0,1]

def main():
    for ex in range(1,13):validate_experiment_archive(ROOT/f'experiments/S011/20260929_S011_EX{ex:02}')
    for path,sha in [(P10,'e4a532e7cc888cd5d770bb4c0e2cf41ce37cff0a731792197922d2e85bd9e78c'),(P12,'19f9d2da8376080b046864ff01df40ed0be56506685e5c0c4252456126a8b067')]:
        load_experiment_input(path/'artifacts',expected_receipt_sha256=sha)
        load_experiment(path)
    failure=ROOT/'experiments/S011/20260929_S011_EX11/experiment_manifest.json'
    assert hashlib.sha256(failure.read_bytes()).hexdigest()=='b02d79a63cabd0e3296298fb0fbfb465c5a6c3f8a56da7e39b3024628931f31f'
    panel=json.loads((P12/'component_panel.json').read_text(encoding='utf-8'))
    assert panel['component_count']==len(panel['components'])==4
    assert set(panel['roles_covered'])=={c['role'] for c in panel['components']}
    assert len({c['field'] for c in panel['components']})==4
    for key in ('survey','role_evidence','role_folds','source_definition_checks','full_screening','calculation_code','human_review'):
        assert (P12/panel['evidence'][key]).is_file(),key
    x=read('factor_matrix.csv.gz');y=read('future_labels.csv.gz');data=x.join(y);pos=np.arange(len(data))
    evidence=pd.read_csv(P12/'artifacts/role_evidence.csv');folds=pd.read_csv(P12/'artifacts/role_folds.csv')
    assert len(evidence)==63 and len(folds)==189
    compared=0
    for _,r in evidence.iterrows():
        h=int(r.Label.rsplit('_',1)[1]);review=[]
        for start,end in WINDOWS:
            positions=np.flatnonzero((data.index>=start)&(data.index<end));positions=positions[positions+h<=positions[-1]]
            part=data.iloc[positions].dropna(subset=[r.Factor,r.Label]);review.append(part)
            f=folds.loc[folds.Factor.eq(r.Factor)&folds.Label.eq(r.Label)&folds.Start.eq(start)].iloc[0]
            assert len(part)==f.N
            assert np.isclose(r.Orientation*spearmanr(part[r.Factor],part[r.Label]).statistic,f.RawIC,atol=1e-12)
            cc=list(dict.fromkeys([r.Factor,r.Label,*CONTROLS]));train=data.iloc[pos+h<np.flatnonzero(data.index>=start)[0]][cc].dropna();test=data.iloc[positions][cc].dropna()
            assert len(train)==f.TrainN and len(test)==f.PredictN
            for kind,fields in [('mean',[]),('factor',[r.Factor]),('base',CONTROLS),('plus',list(dict.fromkeys([*CONTROLS,r.Factor])))]:
                pred,weight=predict(train,test,fields,r.Label)
                assert np.isclose(((test[r.Label].to_numpy()-pred)**2).mean(),f[kind+'Mse'],rtol=1e-9,atol=1e-13)
                assert np.isclose(pred.mean(),f[kind+'PredictionMean'],rtol=1e-9,atol=1e-13)
                if kind=='factor':assert np.isclose(weight*r.Orientation,f.OrientedCoefficient,rtol=1e-9,atol=1e-13)
                compared+=1
        review=pd.concat(review)
        assert len(review)==r.N
        assert np.isclose(r.Orientation*spearmanr(review[r.Factor],review[r.Label]).statistic,r.RawIC,atol=1e-12)
        for column,controls in [('SimplePartialIC',CONTROLS),('PanelPartialIC',CONTROLS+[n for n in PRIMARY if n!=r.Factor])]:
            assert np.isclose(partial(review,r.Factor,r.Label,controls,r.Orientation),r[column],atol=1e-11)
    for component in panel['components']:
        claim=component['primary_evidence'];row=evidence.loc[evidence.Factor.eq(component['field'])&evidence.Label.eq(claim['label'])].iloc[0]
        assert int(row.N)==claim['n']
        for key,column in [('raw_rank_ic','RawIC'),('panel_partial_ic','PanelPartialIC'),('leave_month_min_ic','LeaveMonthMinIC')]:
            assert abs(row[column]-claim[key])<.0000006,(component['component_id'],key)
        assert component['limitations'] and component['not_authorized_uses']
    screened=pd.read_csv(P12/'artifacts/full_screening_ledger.csv')
    assert screened.Factor.is_unique and set(screened.Factor)==set(x.columns) and len(screened)==185
    definitions=pd.read_csv(P12/'artifacts/definition_checks.csv');assert len(definitions)==9 and definitions.MaxAbsError.max()<1e-12
    assert len(pd.read_csv(P12/'artifacts/leave_month.csv'))==945
    assert len(pd.read_csv(P12/'artifacts/binary_diagnostic.csv'))==56
    initial=json.loads((P12/'prior_input_identities.json').read_text())
    for relative,sha in initial['source_sha256'].items():assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==sha,relative
    print(json.dumps({'result':'PASS','old_source_identities_unchanged':len(initial['source_sha256']),'archives_checked':12,'receipts_checked':2,'source_bindings_checked':2,'pooled_rank_and_partial_paths':len(evidence),'independent_lstsq_model_comparisons':compared,'folds':len(folds),'screened_fields':len(screened),'component_records_verified':len(panel['components'])},indent=2))

if __name__=='__main__':main()
