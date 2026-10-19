"""Bounded, audited project-account collection for the authorized EX039 tests."""
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import gzip
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
RAW = EX / 'others/raw'
ALLOWED = {'opt_basic','opt_daily','fund_div','etf_share_size','fund_daily','trade_cal'}
IDENTITY = {'source':'TUSHARE_PROJECT_CONFIG_CLIENT','mcp_account_relation':'UNKNOWN',
            'credential_values_logged':False,'exact_wire_bytes_claimed':False}


def read(path):
    return json.loads(path.read_bytes())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as h:
        h.write(canonical(value))


def scrub(value, token):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'token|secret|password|authorization|cookie|header',k,re.I)
                else scrub(v,token) for k,v in value.items()}
    if isinstance(value,list):
        return [scrub(v,token) for v in value]
    return value.replace(token,'[REDACTED]') if isinstance(value,str) and token else value


def locks():
    from czsc_trader.research_tools import EvidenceRef
    published=read(EX/'protocols/published_design.json')
    assert published and (EX/'protocols/design.json').relative_to(ROOT).as_posix() in published
    for path, value in published.items():
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==(ROOT/path).read_bytes()
    assert read(EX/'protocols/design.json')['authorization']=='ETF和期权的检验授权你一次性完成，我看结果'


class Capture:
    """Single-process context; two independent lanes have disjoint fixed caps."""
    def __init__(self,lane,cap):
        self.lane,self.cap=lane,cap
        self.count=0
        self.seen=set()
        self.expected=None
        self.last=0.0
        self.rows=[]

    def __enter__(self):
        import requests
        assert not list((RAW/'requests').glob(self.lane+'_*.json')), 'No automatic collection rerun'
        self.original=requests.sessions.Session.request
        def guarded(session,method,url,**kwargs):
            body=kwargs.get('json',{})
            api=body.get('api_name')
            params={k:v for k,v in body.get('params',{}).items() if k!='ts_type_name'}
            fields=body.get('fields','')
            if method.upper()!='POST' or api not in ALLOWED:
                raise RuntimeError('Unplanned transport operation blocked')
            if self.expected is not None and (api,params,fields)!=self.expected:
                raise RuntimeError('SDK request differs from declared business task')
            key=canonical([api,params,fields])
            if key in self.seen or self.count>=self.cap:
                raise RuntimeError('Duplicate request or fixed source budget exhausted')
            if any(a.max_retries.total != 0 for a in session.adapters.values()):
                raise RuntimeError('Transport retries forbidden')
            pause=1.0-(time.monotonic()-self.last)
            if pause>0:
                time.sleep(pause)
            self.last=time.monotonic()
            self.count+=1
            self.seen.add(key)
            ident=f'{self.lane}_{self.count:04d}'
            response_path=RAW/'responses'/f'{ident}.json.gz'
            request={'id':ident,'api_name':api,'params':params,'fields':fields.split(',') if fields else [],
                     'reserved_utc':datetime.now(timezone.utc).isoformat(),
                     'response_path':response_path.relative_to(ROOT).as_posix(),'status':'RESERVED',**IDENTITY}
            write(RAW/'requests'/f'{ident}.json',request)
            kwargs['allow_redirects']=False
            result={'id':ident,'api_name':api,'status':'FAILED',**IDENTITY}
            try:
                response=self.original(session,method,url,**kwargs)
                result['http_status']=response.status_code
                try:
                    payload=scrub(response.json(),body.get('token',''))
                except ValueError:
                    result.update(response_format='NON_JSON_NOT_SAVED',body_bytes=len(response.content),
                                  body_sha256=sha256(response.content).hexdigest())
                    raise RuntimeError('Non-JSON source response') from None
                compressed=gzip.compress(canonical(payload),mtime=0)
                response_path.parent.mkdir(parents=True,exist_ok=True)
                with response_path.open('xb') as h:
                    h.write(compressed)
                result['response_sha256']=sha256(compressed).hexdigest()
                result['vendor_code']=payload.get('code') if isinstance(payload,dict) else None
                data=payload.get('data') if isinstance(payload,dict) else None
                result['rows']=len(data.get('items',[])) if isinstance(data,dict) else None
                result['status']='SUCCESS' if response.status_code==200 and result['vendor_code']==0 else 'FAILED'
                return response
            except Exception as e:
                result['exception_type']=type(e).__name__
                raise RuntimeError('Source transport failed; details suppressed') from None
            finally:
                result['completed_utc']=datetime.now(timezone.utc).isoformat()
                write(RAW/'results'/f'{ident}.json',result)
                self.rows.append(result)
        requests.sessions.Session.request=guarded
        return self

    def __exit__(self,*args):
        import requests
        requests.sessions.Session.request=self.original
        write(EX/'others'/f'{self.lane}_source_receipt.json',{
            'status':'PARTIAL' if args[0] is not None or any(x['status']!='SUCCESS' for x in self.rows) else 'COMPLETE',
            'lane':self.lane,'http_reservations':self.count,'cap':self.cap,'automatic_retry':False,
            'redirects':False,'results':self.rows,**IDENTITY})

    def query(self,client,api,params,fields):
        self.expected=(api,params,','.join(fields))
        try:
            result=client.query(api,fields=','.join(fields),**params)
        except Exception as e:
            raise RuntimeError('Declared source task failed: '+type(e).__name__) from None
        finally:
            self.expected=None
        assert self.rows and self.rows[-1]['status']=='SUCCESS'
        print(json.dumps({'phase':'SOURCE_RETURN','calls':self.count,'api':api,'rows':len(result)},ensure_ascii=True),flush=True)
        return result


def groups(needed,calendar):
    ranks={d:i for i,d in enumerate(calendar)}
    out=[]
    for d in needed:
        if out and len(out[-1])==1 and ranks[d]==ranks[out[-1][-1]]+1:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def collect():
    import pandas as pd
    from dataflows.tushare_common import get_tushare_pro
    locks()
    f=pd.read_csv(ROOT/'research/S014/experiments/EX032_20261018/others/inputs.csv')
    a=f.loc[f.A.astype(bool)]
    dates=sorted(set(a.p.dropna())|set(a.q.dropna()))
    dates=[d for d in dates if '2020-01-01'<=d<='2026-10-15']
    calendar=sorted(set(f.p.dropna())|set(f.q.dropna()))
    contracts=sorted(set(a.contract.dropna()))
    assert len(dates)==684 and len(contracts)==22, 'Declared collection inventory changed'
    write(EX/'others/collection_inventory.json',{'required_dates':dates,'contracts':contracts,
        'grouping_calendar':'EX032 all-signal P/Q exact date inventory, not weekday inference',
        'groups':groups(dates,calendar),'source_sha256':sha256((ROOT/'research/S014/experiments/EX032_20261018/others/inputs.csv').read_bytes()).hexdigest()})
    client=get_tushare_pro(ROOT/'.env')
    with Capture('collect',1100) as capture:
        meta=['ts_code','name','opt_code','call_put','exercise_type','exercise_price','opt_multiplier',
              'list_date','delist_date','maturity_date','per_unit','quote_unit']
        for k in contracts:
            table=capture.query(client,'opt_basic',{'exchange':'CZCE','opt_code':'OP'+k,'limit':12000},meta)
            assert len(table)<12000, 'Contract metadata truncated'
        # Event endpoint is independent: retain a denial as missing event evidence,
        # then continue the already approved option-source tasks without retry.
        try:
            event=capture.query(client,'fund_div',{'ts_code':'510300.SH'},
                ['ts_code','ann_date','ex_date','div_proc','base_date','div_cash','base_unit'])
            if 'ex_date' in event:
                dates_event=sorted(set(pd.to_datetime(event.ex_date,errors='coerce').dropna().dt.strftime('%Y-%m-%d')))
                event_status='SOURCE_RETURNED_NOT_FULL_VINTAGE_CERTIFIED'
            else:
                dates_event=[]
                event_status='UNKNOWN_EMPTY_EVENT_SCHEMA'
        except RuntimeError:
            dates_event=[]
            event_status='UNKNOWN_SOURCE_FAILED_NO_RETRY'
        write(EX/'others/etf_events.json',{'status':event_status,'dividend_coverage_certified':False,
              'share_adjustment_coverage_certified':False,'cash_dividend_ex_dates':dates_event,
              'share_conversion_dates':[],'source_evidence':[],
              'limitation':'Current Tushare dividend catalogue is not a complete split/merge or historical vintage chain; empty is not no event.'})
        fields=['ts_code','trade_date','exchange','close','settle','vol','amount','oi']
        def fetch(segment):
            params={'exchange':'CZCE','start_date':segment[0].replace('-',''),'end_date':segment[-1].replace('-','')}
            table=capture.query(client,'opt_daily',params,fields)
            observed=set(table.trade_date.astype(str)) if 'trade_date' in table else set()
            missing=[d for d in segment if d.replace('-','') not in observed]
            if len(table)>=15000 or missing:
                if len(segment)==1:
                    raise RuntimeError('Single-date source completeness unresolved')
                for d in segment:
                    fetch([d])
        for segment in groups(dates,calendar):
            fetch(segment)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['collect','etf'])
    args=p.parse_args()
    if args.mode=='collect':
        collect()
    else:
        locks()
        import prepare_etf
        with Capture('etf',24):
            result=prepare_etf.prepare()
            print(json.dumps(prepare_etf.plain(result),ensure_ascii=True),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'status':'FAILED','error_type':type(e).__name__,'detail':'Source exception text suppressed; inspect sanitized receipts'}),flush=True)
        raise SystemExit(1) from None
