"""Bounded live acquisition through the public DFLS financial-record contract."""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import requests

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import (DataRequest, Dataset, FinancialDisclosureParameters, FinancialReportKind,
                       PreparePolicy, ProviderBinding, ProviderConfig)
from dataflows.financial_disclosures import fetch_company_financial_disclosures
from dataflows.tushare_common import get_tushare_pro

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]
UP = OUT / 'upstream'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)+'\n', encoding='utf-8')


class AuditedClient:
    def __init__(self):
        self.client = get_tushare_pro(ROOT / '.env')
        self.calendar = None

    def trade_cal(self, **kwargs):
        if self.calendar is None:
            self.calendar = self.client.query('trade_cal', fields='cal_date,is_open', exchange='SSE',
                                              start_date='20180630', end_date='20261124')
        values = self.calendar.cal_date.astype(str)
        return self.calendar.loc[values.between(kwargs['start_date'], kwargs['end_date'])].copy()

    def __getattr__(self, api):
        if api not in {kind.value for kind in FinancialReportKind}:
            raise AssertionError(f'Unexpected upstream API {api}')
        return lambda **kwargs: self.client.query(api, **kwargs)


def main():
    assert json.loads((OUT/'authorization.json').read_bytes())['status']=='AUTHORIZED_PRE_STAGE2_WORK'
    assert not (OUT/'others/preparation.json').exists(), 'Preserve original receipt; explicit successor required'
    (UP/'attempts').mkdir(exist_ok=True)
    (UP/'responses').mkdir(exist_ok=True)
    expected = tuple(pd.period_range('2018Q2','2026Q2',freq='Q-DEC').end_time.strftime('%Y-%m-%d'))
    assert len(expected)==33
    queries=tuple(DataRequest(Dataset.COMPANY_FINANCIAL_DISCLOSURES,'600722.SH','2018-07-01','2026-10-15',
        None, frequency='event',parameters=FinancialDisclosureParameters(kind,'2018-06-30','2026-06-30',
        **({'report_type':None} if kind is FinancialReportKind.FINANCIAL_INDICATOR else {}), expected_periods=expected))
        for kind in FinancialReportKind)
    write(OUT/'others/requests.json',[asdict(query) for query in queries])
    original=requests.sessions.Session.request
    def guarded(session,method,url,**kwargs):
        payload=kwargs.get('json') or {}
        api=payload.get('api_name')
        params={key:value for key,value in (payload.get('params') or {}).items() if key!='ts_type_name'}
        assert api in {kind.value for kind in FinancialReportKind}|{'trade_cal'}
        assert method.upper()=='POST'
        assert all(adapter.max_retries.total==0 for adapter in session.adapters.values())
        if api=='trade_cal':
            assert params=={'exchange':'SSE','start_date':'20180630','end_date':'20261124'}
        else:
            assert params['ts_code']=='600722.SH' and params['start_date']=='20180630'
            assert params['end_date']==('20260630' if api=='fina_indicator' else '20261015')
            assert params['limit']==100
            assert params.get('report_type')==('1' if api!='fina_indicator' else None)
        target=UP/'attempts'/f'{api}.json'
        assert not target.exists(), 'No implicit retry'
        assert len(list((UP/'attempts').glob('*.json')))<5
        receipt={'api':api,'params':params,'fields':payload.get('fields'),'status':'STARTED',
                 'started_utc':datetime.now(timezone.utc).isoformat(),'http_requests':1}
        with target.open('x',encoding='utf-8') as handle:
            json.dump(receipt,handle,ensure_ascii=False,indent=2)
        kwargs['allow_redirects']=False
        try:
            response=original(session,method,url,**kwargs)
            receipt['http_status']=response.status_code
            body=response.json()
            receipt['vendor_code']=body.get('code')
            if body.get('code')==0 and isinstance(body.get('data'),dict):
                path=UP/'responses'/f'{api}.json'
                write(path,body['data'])
                receipt.update(status='RECEIVED',response_path=path.relative_to(ROOT).as_posix(),
                               response_sha256=sha256(path.read_bytes()).hexdigest(),rows=len(body['data']['items']))
            else:
                receipt['status']='SOURCE_REJECTED'
            return response
        except Exception as error:
            receipt.update(status='FAILED',error_type=type(error).__name__)
            raise
        finally:
            receipt['finished_utc']=datetime.now(timezone.utc).isoformat()
            write(target,receipt)
    client=AuditedClient()
    def provider(request):
        frame,metadata=fetch_company_financial_disclosures(request,pro=client)
        record=UP/'attempts'/f'{request.parameters.report_kind.value}.json'
        receipt=json.loads(record.read_bytes())
        metadata.update(acquisition_receipt_path=record.relative_to(ROOT).as_posix(),
            acquisition_receipt_sha256=sha256(record.read_bytes()).hexdigest(),
            raw_transport_table_sha256=receipt['response_sha256'],
            original_document_acceptance='PENDING_INDEPENDENT_FIELD_AND_VERSION_AUDIT')
        return frame,metadata
    revision=sha256(Path(__file__).read_bytes()).hexdigest()
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),
        providers=ProviderConfig(bindings={Dataset.COMPANY_FINANCIAL_DISCLOSURES:
            ProviderBinding('tushare-financial-live-audited-v1',revision,provider)}))
    requests.sessions.Session.request=guarded
    try:
        prepared=context.data.prepare(queries,policy=PreparePolicy.REFRESH)
        summary={'status':prepared.status.value,'items':[],
                 'scope':'READY observed records is distinct from historical document acceptance',
                 'space':str(context.data.binding.space.path),'new_api_calls':len(list((UP/'attempts').glob('*.json')))}
        if prepared.reference:
            ref=prepared.reference
            summary['reference']={'space_id':str(ref.space_id),'preparation_id':str(ref.preparation_id),
                                  'manifest_sha256':ref.manifest_sha256}
        for item in prepared.items:
            result={'kind':item.request.parameters.report_kind.value,'status':item.status.value}
            if item.error:
                result['error']={'code':item.error.code,'message':item.error.message,'context':dict(item.error.context)}
            if item.ready:
                fetched=context.data.fetch(item.request,prepared=prepared.reference) if prepared.ready else None
                if fetched is not None:
                    assert fetched.ready,fetched.error
                    path=OUT/'others'/f'{result["kind"]}_observed.csv'
                    fetched.dataframe.to_csv(path,index=False,lineterminator='\n')
                    result.update(rows=len(fetched.dataframe),periods=int(fetched.dataframe.end_date.nunique()),
                        content_sha256=fetched.identity.content_sha256,metadata=dict(fetched.identity.metadata),
                        csv_path=path.relative_to(ROOT).as_posix(),csv_sha256=sha256(path.read_bytes()).hexdigest())
            summary['items'].append(result)
        write(OUT/'others/preparation.json',summary)
        print(json.dumps({'status':summary['status'],'new_api_calls':summary['new_api_calls'],
                          'items':[{key:item[key] for key in ('kind','status','rows','periods','error') if key in item}
                                   for item in summary['items']]},ensure_ascii=True))
    finally:
        requests.sessions.Session.request=original


if __name__=='__main__':
    main()
