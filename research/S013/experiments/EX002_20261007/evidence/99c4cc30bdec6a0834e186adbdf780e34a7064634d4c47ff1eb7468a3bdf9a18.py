"""Independent boundary, label and data-identity checks for component conclusions."""
import ast
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from dataflows import DataRequest, Dataset, PreparedDataRef, DataCoverageRequirement
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from prepare_data import ROOT, WORK, save

def main():
    record=json.loads((WORK/'data_preparation.json').read_text(encoding='utf-8'))
    reference=record['daily']['reference']
    prepared=PreparedDataRef(UUID(reference['space_id']),UUID(reference['preparation_id']),reference['manifest_sha256'])
    repository=RepositoryContext.discover(ROOT)
    research=create_research_context(repository,ResearchBatchRef('S013'),resources=EvaluationResources(8,1,13))
    frames={}
    for name,dataset in [('adjusted',Dataset.ETF_OHLCV),('unadjusted',Dataset.ETF_UNADJUSTED_DAILY)]:
        request=DataRequest(dataset,'510500.SH',record['warmup_start'],'2026-09-30','2026-09-30',
            coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=60,observations_through='2019-12-31'))
        result=research.data.fetch(request,prepared=prepared)
        assert result.ready
        assert result.identity.content_sha256==record['daily_fetch'][name]['identity']['content_sha256']
        frames[name]=result.dataframe.reset_index(drop=True)
    adjusted,raw=frames['adjusted'],frames['unadjusted']
    np.testing.assert_array_equal(pd.to_datetime(adjusted.Date),pd.to_datetime(raw.Date))
    for field in ('Open','High','Low'):
        np.testing.assert_allclose(adjusted[field]/raw[field],adjusted.Close/raw.Close,rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(adjusted.Volume*(adjusted.Close/raw.Close),raw.Volume,rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(adjusted.Amount,raw.Amount,rtol=1e-12,atol=1e-12)
    observation=pd.read_csv(WORK/'component_observations.csv',float_precision='round_trip',parse_dates=['Date','end_5','end_10','end_20','end_downside_20'])
    diagnostics=json.loads((WORK/'component_results.json').read_text(encoding='utf-8'))
    assert len(observation)==1636
    positions={pd.Timestamp(day):i for i,day in enumerate(adjusted.Date)}
    checked=0
    for _,row in observation.iterrows():
        i=positions[row.Date]
        assert i>=60
        for horizon in (5,10,20):
            if i+horizon+1<len(adjusted):
                expected=float(adjusted.Open.iloc[i+horizon+1]/adjusted.Open.iloc[i+1]-1)
                np.testing.assert_allclose(row[f'return_{horizon}'],expected,rtol=1e-10,atol=1e-11)
                assert row[f'end_{horizon}']==pd.Timestamp(adjusted.Date.iloc[i+horizon+1])
                assert row[f'end_{horizon}']<=pd.Timestamp('2026-09-30')
            else:
                assert pd.isna(row[f'return_{horizon}']) and pd.isna(row[f'end_{horizon}'])
            checked+=1
        if i+20<len(adjusted):
            expected=max(0.0,1-float(adjusted.Low.iloc[i+1:i+21].min())/float(adjusted.Open.iloc[i+1]))
            np.testing.assert_allclose(row.downside_20,expected,rtol=1e-10,atol=1e-11)
        else:
            assert pd.isna(row.downside_20)
        checked+=1
    for name,values in diagnostics['diagnostics'].items():
        for label in diagnostics['labels']:
            data=observation[[name,label]].dropna()
            np.testing.assert_allclose(spearmanr(data[name],data[label]).statistic,values[label]['ic'],rtol=1e-8,atol=1e-8)
            assert len(data)==values[label]['n']
    parsed=[]
    for source in WORK.glob('*.py'):
        ast.parse(source.read_text(encoding='utf-8'))
        parsed.append(source.name)
    # Boundary receipts are immutable and verified by their own manifest hashes.
    manifest_checks=0
    for revision in (1,2):
        directory=ROOT/f'research/S013/deliveries/MANDATE/{revision}'
        receipt=json.loads((directory/'receipt.json').read_text(encoding='utf-8'))
        for entry in receipt['files']:
            assert sha256((directory/entry['path']).read_bytes()).hexdigest()==entry['sha256']
            manifest_checks+=1
    minute=record['execution_30m']['items'][0]['identity']['metadata']
    quality=minute['ohlcv_quality']
    assert quality['minute']['completeness']==1 and quality['minute']['accuracy']>=.95
    assert len(quality['minute']['inaccurate_dates'])==5
    assert len(minute['repair_records'][0]['affected_dates'])==9
    result={'status':'PASS','label_boundary_checks':checked,'feature_label_ic_checks':29*4,
        'source_ast_checks':parsed,'immutable_manifest_files_checked':manifest_checks,
        'price_basis_alignment':'PASS','daily_identity':'PASS','warmup_excluded':'PASS',
        'adjustment_contract':'后复权OHLC乘复权因子，Volume除同一因子，Amount保持原值；两产品逐值对应通过',
        'minute_remaining_anomaly_count':5,'trusted_repair_date_count':9,
        'study_prefix_checks':diagnostics['feature_prefix_checks'],
        'study_tsfresh_prefix_checks':diagnostics['tsfresh_prefix_checks'],
        'statement':'技术及数值核验通过；不表示策略经济目标已达标。'}
    save('verification.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
