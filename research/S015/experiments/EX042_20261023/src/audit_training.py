"""Independent expanding-training schedule, hash, coefficient and prefix audit."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3]
CHECKS=0
def read(path):return json.loads(path.read_bytes())
def equal(a,b):
    global CHECKS
    if isinstance(a,str):assert a==b,(a,b)
    else:np.testing.assert_allclose(a,b,rtol=3e-8,atol=2e-11,equal_nan=True)
    CHECKS+=1
def least_squares(frame,columns):
    values=frame[columns].to_numpy(float);center=np.mean(values,axis=0);scale=np.std(values,axis=0);scale[scale==0]=1
    design=np.c_[np.ones(len(values)),(values-center)/scale]
    augmented=np.vstack((design,np.diag([0.]+[np.sqrt(10.)]*len(columns))))
    response=np.r_[frame.y.to_numpy(),np.zeros(len(columns)+1)]
    beta=np.linalg.lstsq(augmented,response,rcond=None)[0]
    return center,scale,beta,design@beta
def predict(schedule,features,date):
    available=[r for r in schedule if r['date']<=date]
    if not available:return np.array([np.nan,np.nan,np.nan]),None
    record=available[-1];assert record['train_known_max']<record['date']<=date
    values=[]
    for role in ('path','risk'):
        model=record['models'][role];row=np.asarray([features[c] for c in model['columns']],float)
        values.append(float(np.r_[1.,(row-np.asarray(model['center']))/np.asarray(model['scale'])]@np.asarray(model['beta'])))
    return np.array([*values,record['models']['risk']['threshold']]),record['date']
def main():
    refs=read(HERE/'others/training_refs.json')
    for name,folder in [('models.py','src'),('stage3_plan.json','protocols')]:assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/folder/name).read_bytes()
    plan=read(HERE/'protocols/stage3_plan.json');source=plan['sources']
    x=pd.read_csv(EvidenceRef.from_dict(source['others/model_features.csv']).resolve(ROOT));labels=pd.read_csv(EvidenceRef.from_dict(source['others/labels.csv']).resolve(ROOT));schedules={family:read(HERE/f'others/models_{family}.json') for family in ('A','B')}
    manifest=read(HERE/'others/training_manifest.json');lookup={(r['family'],r['role'],r['release']):r for r in manifest};assert len(lookup)==len(manifest)
    dates=x.date.tolist();assert len(x)==434 and x.position.tolist()==list(range(434))
    datasets={target:x.merge(labels[labels.target==target].drop(columns='date'),on='position',validate='one_to_one') for target in ('net3','loss3')}
    release_positions=[];previous_release=None
    for position,date in enumerate(dates):
        training={target:g[(g.position<position)&g.y.notna()&(g.known_date<date)] for target,g in datasets.items()}
        if all(len(frame)>=30 for frame in training.values()) and (previous_release is None or position-previous_release>=20):
            release_positions.append(position);previous_release=position
            for family,schedule in schedules.items():
                record=schedule[len(release_positions)-1];equal(record['date'],date);equal(record['train_known_max'],max(z.known_date.max() for z in training.values()))
                assert record['train_known_max']<date and set(record['models'])=={'path','risk'}
                for role,target in [('path','net3'),('risk','loss3')]:
                    tr=training[target];cols=plan['models'][family][role];model=record['models'][role];assert model['columns']==cols
                    center,scale,beta,fitted=least_squares(tr,cols)
                    equal(model['center'],center);equal(model['scale'],scale);equal(model['beta'],beta)
                    if role=='risk':equal(model['threshold'],np.median(fitted))
                    m=lookup[family,role,date]
                    expected={'family':family,'role':role,'release':date,'position':position,'train_n':len(tr),'positions_sha256':sha256(tr.position.to_numpy(dtype='<i8').tobytes()).hexdigest(),'training_xy_sha256':sha256(tr[cols+['y']].to_numpy(dtype='<f8').tobytes()).hexdigest(),'max_known':tr.known_date.max(),'alpha':10}
                    for k,v in expected.items():equal(m[k],v)
                    assert m['columns']==cols
                    # Materialized prefix has no later feature rows or labels and reproduces the exact training population.
                    prefix=datasets[target][datasets[target].date<=date]
                    prefix=prefix[prefix.y.notna()&(prefix.known_date<date)&(prefix.position<position)]
                    equal(prefix.position.to_numpy(),tr.position.to_numpy());equal(prefix[cols+['y']].to_numpy(),tr[cols+['y']].to_numpy())
    for schedule in schedules.values():assert [r['date'] for r in schedule]==[dates[i] for i in release_positions]
    assert len(manifest)==len(release_positions)*4
    predictions=pd.read_csv(HERE/'others/model_predictions.csv');assert len(predictions)==868 and not predictions[['position','family']].duplicated().any()
    feature_rows=x.to_dict('records');prediction_arrays={};prefix_checks=0
    for family,schedule in schedules.items():
        observed=predictions[predictions.family==family].sort_values('position').reset_index(drop=True);equal(observed.position,np.arange(434));assert observed.date.tolist()==dates
        values=[]
        for position,date in enumerate(dates):
            pred,release=predict(schedule,feature_rows[position],date);values.append(pred)
            assert bool(observed.ready.iloc[position])==(release is not None)
            if release is None:assert pd.isna(observed.model_date.iloc[position])
            else:equal(observed.model_date.iloc[position],release)
        expected=np.array(values);equal(observed[['path','risk','risk_threshold']].to_numpy(),expected);prediction_arrays[family]=expected
        # For every cutoff, physically remove all future model releases and feature rows,
        # then recompute every earlier prediction using only the truncated material.
        for cutoff,date in enumerate(dates):
            truncated=[r for r in schedule if r['date']<=date];prefix_features=feature_rows[:cutoff+1]
            replay=np.array([predict(truncated,row,row['date'])[0] for row in prefix_features])
            equal(replay,expected[:cutoff+1]);prefix_checks+=1
    summary=read(HERE/'others/training_summary.json')
    equal(summary['first_release'],dates[release_positions[0]]);equal(summary['releases'],len(release_positions));equal(summary['fitted_models'],len(manifest));equal(summary['mature_min'],30);equal(summary['retrain_step'],20);equal(summary['alpha'],10)
    assert summary['input_refs']==source
    paths=[Path(__file__),HERE/'src/models.py',HERE/'protocols/stage3_plan.json',*[HERE/'others'/name for name in ('models_A.json','models_B.json','training_manifest.json','model_predictions.csv','training_summary.json')]]
    output={'status':'PASS','checks':CHECKS,'first_release':dates[release_positions[0]],'first_release_position':release_positions[0],'releases':len(release_positions),'model_fits_independently_reconstructed':len(manifest),'prediction_rows':len(predictions),'full_prefix_replays':prefix_checks,'training_samples_strictly_known_before_release':True,'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in paths},'method':'Authenticated features and TXE-derived labels; independent mature-sample release schedule, little-endian sample/XY hashes, augmented least-squares Ridge, training-fitted risk median, every prediction and every cutoff replay with future schedules/features removed.','limitations':['Uses the previously independently audited fixed label definitions; does not independently reconstruct original TXE fills here.','Runtime feature recomputation, candidate payload identity and account execution require their separate audits.','Thirty initial matured samples and selected mechanisms use seen development data; prefix causality does not establish independent predictive validity.']}
    (HERE/'others/training_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(output,ensure_ascii=False))
if __name__=='__main__':main()
