"""Diagnose the exact authorized index identity using the same Tushare account."""
import json
from datetime import datetime,timezone
import requests
from dataflows.tushare_common import get_tushare_pro
from inputs import ROOT,EXPERIMENT


def main():
    target=EXPERIMENT/'others/vendor_identity.json'
    if target.exists():
        raise RuntimeError('Preserve identity attempt; no implicit retry')
    first=json.loads((EXPERIMENT/'others/upstream_verification.json').read_text(encoding='utf-8'))
    assert first['source_calls_used']==1 and first['remaining_source_calls']==4
    original=requests.sessions.Session.request;calls=[]
    def counted(session,method,url,**kwargs):
        payload=kwargs.get('json') or {};params=payload.get('params',{})
        if payload.get('api_name')!='index_basic' or params.get('symbol')!='000813' or params.get('market')!='CSI' or len(calls)>=4:
            raise RuntimeError('Out-of-scope or exhausted metadata verification')
        calls.append({'api':'index_basic','symbol':'000813','market':'CSI'})
        return original(session,method,url,**kwargs)
    result={'status':'FAILED','requested_symbol':'000813.SH','purpose':'Identitycatalogueonly,nothistoricalnumericalfeatures',
        'verified_at':datetime.now(timezone.utc).isoformat()}
    requests.sessions.Session.request=counted
    try:
        frame=get_tushare_pro(ROOT/'.env').index_basic(symbol='000813',market='CSI',fields='ts_code,name,fullname,market,publisher,list_date')
        result['records']=frame.to_dict('records')
        if len(frame)!=1 or frame.iloc[0].ts_code!='000813.CSI' or frame.iloc[0].fullname!='中证细分化工产业主题指数' or frame.iloc[0].market!='CSI':
            raise RuntimeError('Unique same-index identity not established')
        result['canonical_symbol']='000813.CSI';result['status']='PASS'
    finally:
        requests.sessions.Session.request=original
        result['source_calls']=calls;result['source_calls_used']=first['source_calls_used']+len(calls)
        result['remaining_source_calls']=5-result['source_calls_used']
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
