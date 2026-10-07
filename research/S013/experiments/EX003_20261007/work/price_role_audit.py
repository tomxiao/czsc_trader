"""Disclose price adjustment versus cash-ledger semantics, without rewriting inputs."""
import json
from uuid import UUID
import numpy as np
import pandas as pd
from dataflows import DataRequest,Dataset,PreparedDataRef,DataCoverageRequirement
from common import ROOT,context,save,cache_read

def main():
    research=context()
    rec=json.loads((ROOT/'research/S013/experiments/EX002_20261007/work/data_preparation.json').read_text(encoding='utf-8'))
    ref=rec['daily']['reference']
    prepared=PreparedDataRef(UUID(ref['space_id']),UUID(ref['preparation_id']),ref['manifest_sha256'])
    coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=60,observations_through='2019-12-31')
    frames=[]
    for dataset in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY):
        fetched=research.data.fetch(DataRequest(dataset,'510500.SH',rec['warmup_start'],
            '2026-09-30','2026-09-30',coverage=coverage),prepared=prepared)
        assert fetched.ready
        frames.append(fetched.dataframe.set_index(pd.to_datetime(fetched.dataframe.Date)))
    adjusted,raw=frames
    factor=adjusted.Close/raw.Close
    changes=~np.isclose(factor.to_numpy()[1:],factor.to_numpy()[:-1],rtol=1e-9,atol=1e-9)
    events=[]
    for loc in np.flatnonzero(changes)+1:
        events.append({'date':str(raw.index[loc].date()),'factor_before':float(factor.iloc[loc-1]),
            'factor_after':float(factor.iloc[loc]),'raw_previous_close':float(raw.Close.iloc[loc-1]),
            'raw_close':float(raw.Close.iloc[loc]),'economic_event_type':'UNVERIFIED'})
    bound,result=cache_read(ROOT/'.tmp/s013-stage3/precheck.pkl.gz')
    pool=raw.loc['2020-01-02':'2026-09-30']
    adjpool=adjusted.loc['2020-01-02':'2026-09-30']
    ratio=float(adjpool.Close.iloc[-1]/adjpool.Open.iloc[0])
    rawratio=float(pool.Close.iloc[-1]/pool.Open.iloc[0])
    bh=result.runs[0].buyhold
    save('price_role_audit.json',{'scope':'S013 only','factor_changes':events,
        'raw_unrounded_price_return':rawratio-1,'adjusted_unrounded_price_return':ratio-1,
        'raw_unrounded_cagr':rawratio**(252/1636)-1,'adjusted_unrounded_cagr':ratio**(252/1636)-1,
        'formal_buyhold_cash_ledger_cagr':(float(bh.account_daily.equity.iloc[-1])/1_000_000)**(252/1636)-1,
        'formal_cash_ledger':'现金只由买卖及费用更新；未单独处理派息、份额调整等权益事件',
        'qualification_boundary':'本阶段资格仅指已确认公共SRT/TXE成交及现金账本口径，不声称完整含派息总回报；复权倍数不能替代真实权益事件和入账时点',
        'source_evidence':['packages/trading_execution_engine/src/trading_execution_engine/historical.py',
            'src/czsc_trader/backtesting/benchmarks.py'],
        'no_mutation_of_market_or_account':True})
    print(json.dumps({'factor_changes':len(events),'raw_price_return':rawratio-1,
        'adjusted_price_return':ratio-1,'formal_cash_cagr':(float(bh.account_daily.equity.iloc[-1])/1_000_000)**(252/1636)-1}),flush=True)

if __name__=='__main__':
    main()
