"""Acquire only the explicitly approved December execution warmup; hard HTTP cap."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
import requests
from dataflows import DataRequest, Dataset, PreparePolicy, SourceNotReadyError
from czsc_trader.application import (RepositoryContext, create_research_context,
    update_research_intent, ResearchIntentUpdate, publish_evidence)
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
LEDGER=EX/'others/prewindow_calls.json'
RESULT=EX/'others/prewindow_inputs.json'

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')

def main():
    resume='--resume' in sys.argv
    if (LEDGER.exists() or RESULT.exists()) and not resume:
        raise RuntimeError('Inspect prior attempt; never reset the call counter')
    repo=RepositoryContext.discover(ROOT)
    ctx=create_research_context(repo, ResearchBatchRef('S014'))
    exp=ExperimentRef('S014', EX.name)
    authorization={'user_reply':'同意补齐，最多15次调用', 'actual_http_call_cap':15,
        'calendar_and_status':['2019-12-01','2019-12-31'],
        'prices':'Only last tradable prewindow day, HFQ and raw',
        'evaluation':['2020-01-01','2026-10-15'], 'fees_and_execution_and_targets':'unchanged'}
    write(EX/'protocols/prewindow_authorization.json',authorization)
    ref=publish_evidence(ctx,MaterialEvidenceWrite(exp,'prewindow-authorization',
        (EX/'protocols/prewindow_authorization.json').read_bytes(),'application/json','json'))
    intent=json.loads((ROOT/'research/registrations/S014/family.json').read_text(encoding='utf-8'))['research_intent']
    intent['stage_three_prewindow_authorization']={**authorization,'evidence':ref.to_dict()}
    intent['pending']=[]
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户批准最小执行预窗口及最多15次实际上游调用，继续四方案账户对照')
    calls=json.loads(LEDGER.read_text(encoding='utf-8'))['calls'] if resume else []
    if resume and RESULT.exists():
        backup=EX/'others/prewindow_attempt1.json'
        if backup.exists():raise RuntimeError('Review repeated failures before further resume')
        backup.write_bytes(RESULT.read_bytes())
    memo={}; original=requests.sessions.Session.request
    def observed(self,method,url,**kwargs):
        payload=kwargs.get('json',{})
        api=payload.get('api_name'); params=payload.get('params',{})
        if api not in {'daily','adj_factor','trade_cal','stock_basic','suspend_d'}:
            raise RuntimeError(f'Unapproved warmup API: {api}')
        if api!='stock_basic':
            for key in ('start_date','end_date'):
                value=params.get(key)
                if value and not ('20191201'<=value<='20191231'):
                    raise RuntimeError('HTTP request outside authorized warmup')
        key=json.dumps({'api':api,'params':params,'fields':payload.get('fields')},sort_keys=True)
        if key in memo:return memo[key]
        if len(calls)>=15:raise SourceNotReadyError('S014 approved 15-call warmup budget exhausted',reason='explicit_call_cap')
        entry={'number':len(calls)+1,'api':api,'parameters':params,'status':'STARTED'}
        calls.append(entry);write(LEDGER,{'cap':15,'calls':calls})
        try:
            response=original(self,method,url,**kwargs)
            entry.update(status='RETURNED',http_status=response.status_code)
            if response.ok and response.json().get('code')==0:memo[key]=response
            return response
        except requests.RequestException as exc:
            entry.update(status='FAILED',exception_type=type(exc).__name__);raise
        finally:write(LEDGER,{'cap':15,'calls':calls})
    records=[]
    def acquire(dataset,symbol,start,end):
        req=DataRequest(dataset,symbol,start,end,end)
        prepared=ctx.data.prepare((req,),policy=PreparePolicy.REUSE)
        row={'request':asdict(req),'status':prepared.status.value,
            'errors':[asdict(i.error) for i in prepared.items if i.error]}
        records.append(row)
        if not prepared.ready:raise RuntimeError(json.dumps(row,default=str))
        result=ctx.data.fetch(req,prepared=prepared.reference)
        assert result.ready
        row.update(reference=asdict(prepared.reference),identity={
            'content_sha256':result.identity.content_sha256,
            'metadata':dict(result.identity.metadata)},rows=len(result.dataframe))
        print(dataset.value, len(result.dataframe),'actual_calls',len(calls),flush=True)
        return result.dataframe
    requests.sessions.Session.request=observed
    try:
        calendar=acquire(Dataset.TRADING_CALENDAR,'SSE','2019-12-01','2019-12-31')
        status=acquire(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01','2019-12-31')
        last=str(status.loc[status.Status.eq('TRADING'),'Date'].iloc[-1])[:10]
        assert last in set(calendar.loc[calendar.IsOpen.eq(1),'Date'].astype(str).str[:10])
        acquire(Dataset.STOCK_OHLCV,'600722.SH',last,last)
        acquire(Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH',last,last)
    finally:
        requests.sessions.Session.request=original
        write(RESULT,{'authorization':ref.to_dict(),'records':records,'calls':calls,
            'status':'READY' if len(records)==4 and all(r['status']=='READY' for r in records) else 'INCOMPLETE'})

if __name__=='__main__':main()
