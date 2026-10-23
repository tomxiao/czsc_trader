"""Six question-led tsfresh expressions, not an unrestricted feature sweep."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import inspect
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
import tsfresh
from tsfresh import extract_features
from tsfresh.feature_extraction import feature_calculators as fc

HERE = Path(__file__).resolve().parents[1]
SETTINGS = {
    'u': {'autocorrelation':[{'lag':1}], 'cid_ce':[{'normalize':True}],
          'number_crossing_m':[{'m':0.0}],
          'energy_ratio_by_chunks':[{'num_segments':2,'segment_focus':1}]},
    'q': {'number_crossing_m':[{'m':0.0}], 'cid_ce':[{'normalize':True}]},
}
COLUMNS = {
    'u__autocorrelation__lag_1':'return_autocorrelation1',
    'u__cid_ce__normalize_True':'return_roughness',
    'u__number_crossing_m__m_0.0':'return_zero_crossings',
    'u__energy_ratio_by_chunks__num_segments_2__segment_focus_1':'afternoon_energy_share',
    'q__number_crossing_m__m_0.0':'open_reference_crossings',
    'q__cid_ce__normalize_True':'path_roughness',
}
FEATURES = list(COLUMNS.values())
TIMES = ('10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00')


def extract(long, workers=2):
    if long[['position','step','kind','value']].isna().any().any():
        raise ValueError('Missing input cannot be imputed')
    if not np.isfinite(long.value).all():
        raise ValueError('Nonfinite input')
    counts=long.groupby(['position','kind']).size()
    if not counts.eq(8).all() or set(long.kind)!=set(SETTINGS):
        raise ValueError('Exactly eight observations for both predeclared kinds required')
    result=extract_features(long,column_id='position',column_sort='step',column_kind='kind',
        column_value='value',kind_to_fc_parameters=SETTINGS,default_fc_parameters={},
        n_jobs=workers,disable_progressbar=True,impute_function=None)
    if set(result.columns)!=set(COLUMNS):
        raise AssertionError(result.columns.tolist())
    return result.rename(columns=COLUMNS)[FEATURES].sort_index()


def encode(bars):
    rows=[];dates=[]
    for pos,(date,g) in enumerate(bars.groupby(pd.to_datetime(bars.Date).dt.strftime('%Y-%m-%d'),sort=True)):
        if tuple(pd.to_datetime(g.Date).dt.strftime('%H:%M'))!=TIMES:
            raise ValueError('Wrong eight-bar timing')
        opening=float(g.Open.iloc[0]);closes=g.Close.to_numpy(float)
        if opening<=0 or not np.isfinite(opening) or not np.isfinite(closes).all() or (closes<=0).any():
            raise ValueError('Invalid prices')
        u=np.diff(np.log(np.r_[opening,closes]));q=np.log(closes/opening)
        for kind,values in [('u',u),('q',q)]:
            for step,value in enumerate(values):rows.append(dict(position=pos,step=step,kind=kind,value=float(value)))
        dates.append(date)
    return pd.DataFrame(rows),dates


def direct(values):
    u=values['u'];q=values['q']
    return np.array([fc.autocorrelation(u,1),fc.cid_ce(u,True),fc.number_crossing_m(u,0.),
      list(fc.energy_ratio_by_chunks(u,[{'num_segments':2,'segment_focus':1}]))[0][1],
      fc.number_crossing_m(q,0.),fc.cid_ce(q,True)],float)


def preflight():
    patterns=[np.array([1,-2,1,3,-1,2,-3,1],float)*.001,np.zeros(8),np.ones(8)*.001]
    rows=[]
    for pos,u in enumerate(patterns):
        for kind,values in [('u',u),('q',np.cumsum(u))]:
            for step,value in enumerate(values):rows.append(dict(position=pos,step=step,kind=kind,value=value))
    long=pd.DataFrame(rows);one=extract(long,0);two=extract(long,2)
    np.testing.assert_allclose(one,two,rtol=1e-12,atol=1e-12,equal_nan=True)
    for i,u in enumerate(patterns):np.testing.assert_allclose(two.iloc[i],direct({'u':u,'q':np.cumsum(u)}),rtol=1e-12,atol=1e-12,equal_nan=True)
    assert np.isnan(two.loc[1,'return_autocorrelation1']) and np.isnan(two.loc[1,'afternoon_energy_share'])
    assert np.isnan(two.loc[2,'return_autocorrelation1'])
    invalid=long.copy();invalid.loc[0,'value']=np.nan
    try:extract(invalid,2)
    except ValueError:pass
    else:raise AssertionError('NaN input was accepted')
    calculators={name:dict(signature=str(inspect.signature(getattr(fc,name))),
      source_sha256=sha256(inspect.getsource(getattr(fc,name)).encode()).hexdigest(),
      documentation=inspect.getdoc(getattr(fc,name))) for name in {k for spec in SETTINGS.values() for k in spec}}
    result={'status':'PASS','tsfresh_version':tsfresh.__version__,'workers':2,'native_threads':1,
      'sample_days':3,'serial_parallel_equal_cells':18,'calculator_equal_cells':18,
      'undefined_values_preserved':True,'missing_input_rejected':True,'settings':SETTINGS,'columns':COLUMNS,
      'calculators':calculators,'unfilled_library_outputs':{str(i):[c for c in FEATURES if pd.isna(two.loc[i,c])] for i in range(3)}}
    (HERE/'others/api_preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print('TSFRESH_TWO_PROCESS_PREFLIGHT_PASS',flush=True)


if __name__=='__main__':preflight()
