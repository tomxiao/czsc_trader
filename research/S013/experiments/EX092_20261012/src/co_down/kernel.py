"""EX092 fixed negative co-down interaction diagnostics; frozen EX091 mathematics."""
import numpy as np
import pandas as pd

ORIGINAL = (
    'momentum20','range_position60','acf1','volatility20','intraday_return',
    'overnight_gap','intraday_energy20','intraday_rms20','confirmation_score',
    'daily_close_location','feature_intraday_down_energy20',
    'feature_overnight_down_energy20','turnover20','volume_ratio20',
)
CONTROLS = (*ORIGINAL,'mean_a20','mean_b20','rms_a20','rms_b20','freq_a20','freq_b20',
    'late_recovery','early_volume_reclaim','early_down_share','max_down_run_share',
    'total_down','total_up','samebar_cov')
MODELS = ('pastmean','controls','augmented')


def forecasts(features, labels, numeric):
    axis = features.index
    if not axis.equals(labels.index) or axis.has_duplicates or not axis.is_monotonic_increasing:
        raise ValueError('Exact ordered aligned axis required')
    if features.columns.tolist() != [*CONTROLS,'X'] or np.isinf(features.to_numpy(float)).any():
        raise ValueError('Fixed28 features, finite or explicit NA required')
    x = features.to_numpy(float)
    complete = np.isfinite(x).all(axis=1)
    y = labels.return_4.to_numpy(float)
    ends = labels.label_end_return_4
    if np.isinf(y).any() or (np.isfinite(y) & ((ends <= axis).to_numpy() | ends.isna().to_numpy())).any():
        raise ValueError('Finite labels require future exact authenticated maturity')
    scores = pd.DataFrame(np.nan,index=axis,columns=MODELS)
    traces = []
    for year in range(2021,2027):
        days = axis[axis.year == year]
        first = days[0] if len(days) else None
        train = complete & np.isfinite(y) & (axis.year >= 2020) & (axis.year < year)
        train &= (ends < first).to_numpy() if first is not None else False
        test = complete & (axis.year == year)
        row = {'year':year,'first_test':first.isoformat() if first is not None else None,
            'train_positions':np.flatnonzero(train).tolist(),'test_positions':np.flatnonzero(test).tolist(),
            'future_test_count_gate':False,'models':{},'reason':None}
        if first is None or train.sum() < 40:
            row['reason'] = 'NO_YEAR' if first is None else 'INSUFFICIENT_MATURE_TRAINING'
            traces.append(row)
            continue
        tr = np.column_stack([numeric.ecdf(col,col) for col in x[train].T])
        te = np.column_stack([numeric.ecdf(col,val) for col,val in zip(x[train].T,x[test].T)])
        target = y[train]
        scores.loc[test,'pastmean'] = target.mean()
        for name,width in (('controls',len(CONTROLS)),('augmented',len(CONTROLS)+1)):
            a,b = tr[:,:width],te[:,:width]
            mean = a.mean(axis=0)
            centered = a - mean
            slope = np.linalg.solve(centered.T@centered+10*np.eye(width),centered.T@(target-target.mean()))
            scores.loc[test,name] = target.mean()+(b-mean)@slope
            row['models'][name] = {'train_mean':mean.tolist(),'target_mean':float(target.mean()),'slope':slope.tolist()}
        traces.append(row)
    return scores,traces


def quantities(y, p, positions):
    y,p = y[positions],p[positions]
    paired = np.isfinite(y)&np.isfinite(p).all(axis=1)
    mse = np.mean((p[paired]-y[paired,None])**2,axis=0) if paired.sum()>=20 else None
    selected = [np.isfinite(y)&np.isfinite(p[:,j])&(p[:,j]>0) for j in range(3)]
    means = [float(y[mask].mean()) if mask.sum()>=20 else None for mask in selected]
    return {
        'augmented_mse_improvement_vs_controls':float(1-mse[2]/mse[1]) if mse is not None and mse[1]>0 else None,
        'augmented_mse_improvement_vs_pastmean':float(1-mse[2]/mse[0]) if mse is not None and mse[0]>0 else None,
        'augmented_positive_mean':means[2],
        'augmented_positive_minus_controls':means[2]-means[1] if means[2] is not None and means[1] is not None else None,
    }


def analyze(features,labels,scores,traces,numeric,clock):
    axis = features.index
    x,y,p = features.X.to_numpy(float),labels.return_4.to_numpy(float),scores.to_numpy(float)
    controls = features[list(CONTROLS)].to_numpy(float)
    positions = np.arange(len(axis))
    masks = {'all':positions,**{'year_'+str(t):positions[axis.year==t] for t in range(2020,2027)},
             **{'phase_'+str(k):positions[positions%5==k] for k in range(5)}}
    sampled = numeric.block_indices(len(axis))
    raw = numeric.correlation(x,y)
    partial = numeric.correlation(x,y,controls)
    schedules = {name:{c:clock.schedule(axis,p[:,j],y,c) for c in clock.CLOCKS} for j,name in enumerate(MODELS)}
    records = [quantities(y,p,ids) for ids in sampled] if sampled is not None else []
    summary = {}
    for key,value in quantities(y,p,positions).items():
        good = [row[key] for row in records if row[key] is not None]
        ok = value is not None and len(good)>=400
        summary[key] = {'value':value,'valid_replicates':len(good),
            'ci95':np.quantile(good,[.025,.975],method='linear').tolist() if ok else None,
            'status':'AVAILABLE' if ok else 'INSUFFICIENT_DATA'}
    return {'signals':len(axis),'controls':list(CONTROLS),'component':'X','fixed_hypothesis':'negative',
        'raw':raw,'partial':partial,'raw_bootstrap':numeric.bootstrap(x,y,None,sampled),
        'partial_bootstrap':numeric.bootstrap(x,y,controls,sampled),
        'panels':{key:{'raw':numeric.correlation(x[ids],y[ids]),
             'partial':numeric.correlation(x[ids],y[ids],controls[ids]),
             'quantities':quantities(y,p,ids)} for key,ids in masks.items()},
        'fit_trace':traces,'bootstrap':{'summary':summary,'records':records,'blocks':40,'repetitions':500,'seed':13,'refitted':0},
        'schedules':schedules,'new_models':sum(2 for row in traces if row['reason'] is None),
        'new_accounts':0,'provider_calls':0,'objective_achieved':False,
        'scope':'full development pool; no ex-post profitable-year selection in decisions'}
