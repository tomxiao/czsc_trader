"""Explicit RSCH reuse of saved S015 inputs; no platform or frozen edits."""
from pathlib import Path
from datetime import date
from uuid import UUID
from dataclasses import asdict
import json
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, PreparePolicy
from strategy_runtime import StrategyInputBinding
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def main():
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'))
    old = ROOT/'research/S015/experiments/EX081_20261025/others/input_identity.json'
    binding = StrategyInputBinding.from_mapping(read(old)['coordinates'][0]['input_binding'])
    output = HOME/'others'
    output.mkdir(exist_ok=True)
    sources = {}
    frames = {}
    for name, request in binding.plan.requests.items():
        result = ctx.data.fetch(request, prepared=binding.prepared)
        if not result.ready:
            raise RuntimeError(str(result.error))
        frames[name] = result.dataframe
        sources[name] = {'request': asdict(request), 'prepared': binding.to_dict()['prepared']}
    # V4 auxiliary input requires explicit pre-window history. Extend only the
    # already approved daily warmup dates, with the existing RAW M30 provider.
    request = DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY, '159326.SZ',
        '2024-09-09', '2026-10-21', '2026-10-21', '30m')
    prep = ctx.data.prepare((request,), policy=PreparePolicy.REUSE)
    if not prep.ready:
        raise RuntimeError(str(prep))
    result = ctx.data.fetch(request, prepared=prep.reference)
    if not result.ready:
        raise RuntimeError(str(result.error))
    frames['intraday_complete'] = result.dataframe
    sources['intraday_complete'] = {'request':asdict(request), 'prepared':asdict(prep.reference)}
    audit=read(ROOT/'research/S015/experiments/EX003_20261021/others/execution_data_audit.json')
    saved=dict(audit['prepared']['reference'])
    saved['space_id']=UUID(saved['space_id']); saved['preparation_id']=UUID(saved['preparation_id'])
    q=DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY,'159326.SZ','2025-01-02','2026-10-21','2026-10-21','30m')
    final=ctx.data.fetch(q,prepared=PreparedDataRef(**saved))
    if not final.ready: raise RuntimeError(str(final.error))
    fresh=frames['intraday_complete']
    oldminute=frames['intraday']
    # Preserve original experiment bytes for the overlap; refreshed volumes
    # differ slightly, despite identical OHLC. Only new preheat is admitted.
    overlap=fresh.set_index(pd.to_datetime(fresh.Date)).loc[pd.to_datetime(oldminute.Date)]
    delta=(oldminute[['Open','High','Low','Close','Volume','Amount']].reset_index(drop=True)-overlap[['Open','High','Low','Close','Volume','Amount']].reset_index(drop=True)).abs().max().to_dict()
    frames['intraday_complete']=pd.concat([
        fresh.loc[pd.to_datetime(fresh.Date)<pd.Timestamp('2025-01-02')],oldminute,
        final.dataframe.loc[pd.to_datetime(final.dataframe.Date)>=pd.Timestamp('2026-10-21')]],ignore_index=True)
    sources['intraday_complete']['composition']={'preheat':'new preparation through 2024-12-31',
        'original_signal_overlap':sources['intraday'],'final_day':audit['prepared']['reference'],
        'unused_refreshed_overlap_max_differences':delta}
    requests = {
        'raw_complete': DataRequest(Dataset.ETF_UNADJUSTED_DAILY,'159326.SZ','2024-09-09','2026-10-21','2026-10-21'),
        'hfq_complete': DataRequest(Dataset.ETF_OHLCV,'159326.SZ','2024-09-09','2026-10-21','2026-10-21'),
        'limits_complete': DataRequest(Dataset.SECURITY_PRICE_LIMITS,'159326.SZ','2024-09-09','2026-10-21','2026-10-21'),
        'calendar_extended': DataRequest(Dataset.TRADING_CALENDAR,'SZSE','2024-09-09','2026-10-22','2026-10-22'),
    }
    prepared = ctx.data.prepare(tuple(requests.values()),policy=PreparePolicy.REUSE)
    if not prepared.ready:
        raise RuntimeError(str(prepared))
    for name, request in requests.items():
        result=ctx.data.fetch(request,prepared=prepared.reference)
        if not result.ready:
            raise RuntimeError(str(result.error))
        frames[name]=result.dataframe
        sources[name]={'request':asdict(request),'prepared':asdict(prepared.reference)}
    original = read(ROOT/'research/S015/experiments/EX082_20261025/others/results.json')['rows']
    refs = {}
    for row in original:
        ref = EvidenceRef.from_dict(row['evidence'])
        refs[row['scenario_id']] = row['evidence']
    for name, frame in frames.items():
        frame.to_parquet(output/(name+'.parquet'),index=False)
        print(name,len(frame),flush=True)
    (output/'input_sources.json').write_text(json.dumps({'inputs':sources,'old_accounts':refs},ensure_ascii=False,indent=2,default=str),encoding='utf-8')

if __name__=='__main__':
    main()
