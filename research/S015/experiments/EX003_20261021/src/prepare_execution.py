"""Prepare authorized execution bars; preserve quality failures without bypassing them."""
import json
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from pathlib import Path

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparePolicy


def encode(value):
    if is_dataclass(value):
        return {f.name: encode(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: encode(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [encode(v) for v in value]
    return value if value is None or isinstance(value,(str,int,float,bool)) else str(value)


def main():
    root = Path.cwd()
    ctx = create_research_context(RepositoryContext.discover(root),ResearchBatchRef('S015'))
    request = DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY,'159326.SZ',
                          '2025-01-02','2026-10-21','2026-10-21','30m')
    prepared = ctx.data.prepare((request,),policy=PreparePolicy.REUSE)
    record = {'request':encode(request),'prepared':encode(prepared)}
    if prepared.ready:
        fetched = ctx.data.fetch(request, prepared=prepared.reference)
        record['fetched_status'] = str(fetched.status)
        record['identity'] = encode(fetched.identity)
        record['rows'] = len(fetched.dataframe)
    path = Path(__file__).resolve().parent.parent/'others/execution_data_audit.json'
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps({'ready':prepared.ready,'status':str(prepared.status),
        'items':[{'status':str(x.status),'error':encode(x.error)} for x in prepared.items]},ensure_ascii=False))


if __name__=='__main__':
    main()
