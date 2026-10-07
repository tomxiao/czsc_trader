"""HFQ/raw sensitivity, preserving the primary HFQ study unchanged."""
import json
from uuid import UUID
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from dataflows import DataRequest, Dataset, PreparedDataRef, DataCoverageRequirement
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from components import manual_features, tsfresh_features, labels
from prepare_data import ROOT, WORK, save

def main():
    record=json.loads((WORK/'data_preparation.json').read_text(encoding='utf-8'))
    r=record['daily']['reference']
    ref=PreparedDataRef(UUID(r['space_id']),UUID(r['preparation_id']),r['manifest_sha256'])
    research=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S013'))
    frames=[]
    for dataset in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY):
        market=research.data.fetch(DataRequest(dataset,'510500.SH',record['warmup_start'],'2026-09-30','2026-09-30',
            coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=60,observations_through='2019-12-31')),prepared=ref)
        assert market.ready
        frame=market.dataframe.copy().reset_index(drop=True)
        frame.Date=pd.to_datetime(frame.Date)
        frames.append(frame)
    adjusted,raw=frames
    mixed=adjusted.copy()
    mixed.Volume=raw.Volume
    original=pd.read_csv(WORK/'component_observations.csv',float_precision='round_trip',parse_dates=['Date'])
    source=json.loads((WORK/'component_results.json').read_text(encoding='utf-8'))['diagnostics']
    output={'primary_retained':True,'observed_factor_changes':int((adjusted.Close/raw.Close).diff().abs().gt(1e-12).sum()),
        'interpretation':'原研究使用DFLS后复权价格及逆向复权Volume，Amount原值。未复权价格比较仅作敏感性；其标签不含分红，不能替代正式账户基准。',
        'raw_price':{},'raw_volume':{}}
    raw_features=manual_features(raw,WORK/'generated_expressions.py')
    raw_tsfresh=tsfresh_features(raw,workers=8)
    raw_label=labels(raw)
    pool=raw.Date.ge('2020-01-01')
    for feature in ('range_position_60','momentum_60','turnover_ratio_20','tsfresh20_autocorrelation__lag_1'):
        series=raw_tsfresh[feature] if feature.startswith('tsfresh') else raw_features[feature]
        view=pd.DataFrame({'feature':series,'label':raw_label.return_10,'Date':raw.Date}).loc[pool].dropna()
        output['raw_price'][feature]={'return10_ic':float(spearmanr(view.feature,view.label).statistic),
            'primary_hfq_ic':source[feature]['return_10']['ic'],
            'annual_ic':{str(y):float(spearmanr(g.feature,g.label).statistic) for y,g in view.groupby(view.Date.dt.year)}}
    mixed_features=manual_features(mixed,WORK/'generated_expressions.py').loc[pool].reset_index(drop=True)
    for feature in ('volume_ratio_5_20','signed_volume_5','trend_x_volume'):
        valid=original.return_10.notna()
        output['raw_volume'][feature]={'return10_ic':float(spearmanr(mixed_features.loc[valid,feature],original.loc[valid,'return_10']).statistic),
            'primary_hfq_volume_ic':source[feature]['return_10']['ic'],
            'feature_rank_correlation':float(spearmanr(mixed_features[feature],original[feature]).statistic),
            'maximum_feature_difference':float(np.max(np.abs(mixed_features[feature]-original[feature])))}
    save('price_basis_sensitivity.json',output)
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
