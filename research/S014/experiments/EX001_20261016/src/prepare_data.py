"""Prepare bounded native DFLS assets; preserve explicit non-ready outcomes."""
from dataclasses import asdict
from pathlib import Path
from uuid import UUID
import json
import os

from dotenv import dotenv_values
from tushare.pro.client import DataApi
from dataflows import DataRequest, Dataset, PreparePolicy, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
WORK = ROOT / '.tmp/600722-pilot-20261016'
CALL_CAP = 50


def main():
    assert not (WORK / 'dfls.json').exists(), 'Review existing run before another preparation'
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'),
                                      providers=ProviderConfig(env_file=ROOT / '.env'))
    requests = [DataRequest(dataset, '600722.SH', '2020-01-01', '2026-09-30', '2026-09-30')
                for dataset in (Dataset.STOCK_UNADJUSTED_DAILY, Dataset.STOCK_OHLCV)]
    requests += [DataRequest(Dataset.STOCK_UNADJUSTED_INTRADAY, '600722.SH', day, day, day, frequency='30m')
                 for day in ('2020-01-02', '2020-02-03', '2021-02-09', '2026-09-30')]
    ledger, records = [], []
    original = DataApi.query
    token = os.getenv('TUSHARE_TOKEN', '').strip() or str(dotenv_values(ROOT / '.env').get('TUSHARE_TOKEN') or '')

    def tracked_query(self, api_name, fields='', **parameters):
        if len(ledger) >= CALL_CAP:
            raise RuntimeError('Technical pilot upstream call budget exhausted')
        entry = dict(api=api_name, parameters=parameters, fields=fields)
        ledger.append(entry)
        try:
            frame = original(self, api_name, fields=fields, **parameters)
            entry.update(status='RETURNED', rows=len(frame) if frame is not None else None)
            return frame
        except Exception as exc:
            entry.update(status='FAILED', exception=type(exc).__name__)
            raise

    DataApi.query = tracked_query
    try:
        for index, request in enumerate(requests):
            record = dict(request=asdict(request))
            records.append(record)
            try:
                prepared = context.data.prepare((request,), policy=PreparePolicy.REUSE)
                record.update(status=prepared.status.value,
                              items=[dict(status=item.status.value, error=asdict(item.error) if item.error else None)
                                     for item in prepared.items])
                if prepared.ready:
                    result = context.data.fetch(request, prepared=prepared.reference)
                    record.update(reference=asdict(prepared.reference), rows=len(result.dataframe),
                                  content_sha256=result.identity.content_sha256,
                                  metadata=dict(result.identity.metadata))
                    result.dataframe.to_csv(WORK / f'prepared_{index}.csv', index=False)
            except Exception as exc:
                record.update(status='FAILED', exception=type(exc).__name__, message=str(exc).replace(token, '<redacted>')[:500])
            print(json.dumps({k: record[k] for k in ('request', 'status', 'rows', 'message') if k in record}, default=str), flush=True)
    finally:
        DataApi.query = original
        output = dict(upstream_call_cap=CALL_CAP, upstream_calls=len(ledger), ledger=ledger, records=records,
                      rule='No quality bypass, no synthetic filling, no automatic range shortening; singleton preparations preserve successful native references.')
        (WORK / 'dfls.json').write_text(json.dumps(output, ensure_ascii=False, indent=2,
                                                 default=lambda value: str(value) if isinstance(value, (UUID, Path)) else str(value)) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
