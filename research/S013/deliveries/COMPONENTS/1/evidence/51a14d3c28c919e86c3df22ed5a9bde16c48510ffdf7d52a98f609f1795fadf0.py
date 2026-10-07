"""Run predefined component diagnostics on authorized S013 prepared assets."""
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone, timedelta
import importlib.metadata
import json
import multiprocessing
from pathlib import Path
from uuid import UUID

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from dataflows import DataRequest, Dataset, PreparedDataRef, DataCoverageRequirement
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from components import manual_features, tsfresh_features, labels, FC_PARAMETERS, EXPRESSIONS
from prepare_data import ROOT, WORK, save

LABELS = ('return_5', 'return_10', 'return_20', 'downside_20')

def rho(x, y):
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[keep], np.asarray(y)[keep]
    if len(x) < 30 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(spearmanr(x, y).statistic)

def residual_ic(x, y, trend, volatility):
    frame = pd.DataFrame({'x':x,'y':y,'trend':trend,'volatility':volatility}).dropna()
    ranks = frame.rank(pct=True)
    controls = np.c_[np.ones(len(frame)), ranks[['trend','volatility']].to_numpy()]
    xr = ranks.x.to_numpy()-controls@np.linalg.lstsq(controls,ranks.x.to_numpy(),rcond=None)[0]
    yr = ranks.y.to_numpy()-controls@np.linalg.lstsq(controls,ranks.y.to_numpy(),rcond=None)[0]
    if np.std(xr)<1e-10 or np.std(yr)<1e-10:
        return None
    return float(np.corrcoef(xr,yr)[0,1])

def one_feature(task):
    name, x, labels_array, dates_array, end_array, trend, volatility, bootstrap_count = task
    dates = pd.to_datetime(dates_array)
    years = dates.year.to_numpy()
    data = {}
    for j, label in enumerate(LABELS):
        y = labels_array[:, j]
        valid = np.isfinite(x) & np.isfinite(y)
        full = rho(x, y)
        annual = {str(year): rho(x[(years==year)], y[(years==year)]) for year in np.unique(years)}
        rng = np.random.default_rng(13)
        xv, yv = np.asarray(x)[valid], y[valid]
        n = len(xv)
        bootstrap = []
        if n >= 60:
            for _ in range(bootstrap_count):
                starts = rng.integers(0, n, size=(n+39)//40)
                idx = np.concatenate([(s+np.arange(40)) % n for s in starts])[:n]
                value = rho(xv[idx], yv[idx])
                if value is not None:
                    bootstrap.append(value)
        walkforward = []
        for year in range(2021,2027):
            boundary = pd.Timestamp(year,1,1)
            train = valid & (dates < boundary) & (pd.to_datetime(end_array[:,j]) < boundary)
            test = valid & (years==year)
            if train.sum()<80 or test.sum()<30:
                continue
            q25, q75 = np.quantile(x[train],[.25,.75])
            low = test & (x<=q25)
            high = test & (x>=q75)
            walkforward.append({'year':year, 'train_n':int(train.sum()), 'test_n':int(test.sum()),
                'q25':float(q25), 'q75':float(q75), 'low_n':int(low.sum()), 'high_n':int(high.sum()),
                'low_mean':float(np.mean(y[low])) if low.any() else None,
                'high_mean':float(np.mean(y[high])) if high.any() else None,
                'high_minus_low':float(np.mean(y[high])-np.mean(y[low])) if low.any() and high.any() else None,
                'test_ic':rho(x[test],y[test])})
        consistent = sum(np.sign(z)==np.sign(full) for z in annual.values() if z is not None) if full is not None else 0
        data[label] = {'n':int(valid.sum()), 'ic':full, 'annual_ic':annual,
            'same_direction_years':int(consistent), 'block40_ic_interval95':list(map(float,np.quantile(bootstrap,[.025,.975]))) if bootstrap else None,
            'partial_rank_ic_given_momentum20_volatility20':residual_ic(x,y,trend,volatility),
            'walkforward':walkforward,
            'bootstrap_replicates':len(bootstrap)}
    return name,data

def main():
    repository = RepositoryContext.discover(ROOT)
    research = create_research_context(repository, ResearchBatchRef('S013'),
        resources=EvaluationResources(max_workers=8,native_threads_per_worker=1,random_seed=13))
    experiment = ExperimentRef('S013','EX002_20261007')
    record = json.loads((WORK/'data_preparation.json').read_text(encoding='utf-8'))
    assert record['daily']['status']=='READY'
    ref = record['daily']['reference']
    prepared = PreparedDataRef(UUID(ref['space_id']),UUID(ref['preparation_id']),ref['manifest_sha256'])
    request = DataRequest(Dataset.ETF_OHLCV,'510500.SH',record['warmup_start'],'2026-09-30','2026-09-30',
        coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=60,observations_through='2019-12-31'))
    market = research.data.fetch(request,prepared=prepared)
    assert market.ready
    frame = market.dataframe.copy().reset_index(drop=True)
    frame.Date = pd.to_datetime(frame.Date)
    frame.AvailableDate = pd.to_datetime(frame.AvailableDate)
    assert (frame.AvailableDate.dt.hour == 17).all()
    assert (frame.AvailableDate.dt.date == frame.Date.dt.date).all()
    supplement = {'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
        'availability':'后复权输入使用T日17:00可用政策，在T+1开盘前形成；不宣称15:00已取得复权因子。',
        'historical_publication_and_revision_verified':False,
        'preprocessing':'每个因子只消费截至T的滚动历史；阈值逐年仅拟合已完成标签的过去年份；不填补特征或标签缺失。',
        'statistics':'年均值和重叠标签为诊断；40日移动区块重采样仅描述抽样不确定性，不校正研究族多重选择。',
        'prices':'研究标签为后复权次日开盘价格相对变化，未扣策略成本、未模拟限价成交和复投账户。',
        'tsfresh_parameters':FC_PARAMETERS,'expr_codegen_expressions':EXPRESSIONS,
        'software':{k:importlib.metadata.version(k) for k in ('numpy','pandas','scipy','tsfresh','expr_codegen')},
        'resources':{'tsfresh_processes':8,'statistic_processes':8,'native_threads':1,'bootstrap_replicates':200,'seed':13}}
    supplement_ref = publish_evidence(research,MaterialEvidenceWrite(experiment,'pre-computation-method-and-availability',
        json.dumps(supplement,ensure_ascii=False,indent=2).encode(),'application/json','json'))
    save('method_supplement.json',supplement)
    save('method_supplement_reference.json',supplement_ref.to_dict())
    features = manual_features(frame,WORK/'generated_expressions.py')
    print('EXPR_REFERENCE=PASS',flush=True)
    tsfeatures = tsfresh_features(frame,workers=8)
    features = features.join(tsfeatures)
    print(f'TSFRESH_READY features={len(tsfeatures.columns)}',flush=True)
    prefix_checks=[]
    for n in (61,200,800,1400):
        cut = manual_features(frame.iloc[:n],WORK/'generated_expressions.py')
        np.testing.assert_allclose(cut,features.loc[:n-1,cut.columns],rtol=1e-12,atol=1e-12,equal_nan=True)
        prefix_checks.append(n)
    tscheck = tsfresh_features(frame.iloc[:801],positions=[60,200,800],workers=8)
    np.testing.assert_allclose(tscheck,tsfeatures.loc[tscheck.index,tscheck.columns],rtol=1e-12,atol=1e-12,equal_nan=True)
    label_data = labels(frame)
    pool = frame.Date.ge('2020-01-01')
    dataset = pd.concat([frame[['Date','AvailableDate']],features,label_data],axis=1).loc[pool].reset_index(drop=True)
    assert len(dataset)==record['pool_sessions']==1636
    assert dataset.Date.max()==pd.Timestamp('2026-09-30')
    assert not np.isinf(dataset[features.columns].to_numpy()).any()
    assert all(dataset[c].iloc[0] == dataset[c].iloc[0] for c in features.columns)
    dataset.to_csv(WORK/'component_observations.csv',index=False,float_format='%.17g',lineterminator='\n')
    ends = dataset[['end_5','end_10','end_20','end_downside_20']].to_numpy()
    tasks = [(name,dataset[name].to_numpy(),dataset[list(LABELS)].to_numpy(),dataset.Date.to_numpy(),ends,
              dataset.momentum_20.to_numpy(),dataset.volatility_20.to_numpy(),200) for name in features.columns]
    with ProcessPoolExecutor(max_workers=8,mp_context=multiprocessing.get_context('spawn')) as executor:
        diagnostics = dict(executor.map(one_feature,tasks))
    correlations = dataset[features.columns].corr(method='spearman')
    correlations.to_csv(WORK/'component_correlations.csv',float_format='%.8g',lineterminator='\n')
    result = {'feature_count':len(features.columns),'pool_sessions':len(dataset),
        'labels':list(LABELS),'feature_prefix_checks':prefix_checks,'tsfresh_prefix_checks':[60,200,800],
        'expr_reference':'PASS','causal_index_checks':'PASS',
        'label_counts':{k:int(dataset[k].notna().sum()) for k in LABELS},
        'daily_identity_sha256':market.identity.content_sha256,'diagnostics':diagnostics}
    save('component_results.json',result)
    print(json.dumps({'features':len(features.columns),'label_counts':result['label_counts'],
        'causality_checks':'PASS','statistic_tasks':len(tasks)},ensure_ascii=False),flush=True)
    for name,data in diagnostics.items():
        r,risk=data['return_10'],data['downside_20']
        print(json.dumps({'feature':name,'return10_ic':r['ic'],'return10_years':r['same_direction_years'],
            'downside20_ic':risk['ic'],'downside20_years':risk['same_direction_years']},ensure_ascii=False))

if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
