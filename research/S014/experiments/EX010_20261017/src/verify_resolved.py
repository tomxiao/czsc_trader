"""Verify actual account access and full index coverage before numerical research."""
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
from dataflows import PreparePolicy
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef
from resolved_inputs import ROOT, EXPERIMENT, previous, request


def main():
    target = EXPERIMENT / 'others/upstream_verification_resolved.json'
    if target.exists():
        raise RuntimeError('Preserve prior verification; no implicit retry')
    binding = json.loads((EXPERIMENT / 'protocols/published_design.json').read_text(encoding='utf-8'))
    for name, value in binding.items():
        path = EXPERIMENT / ('protocols/design.json' if name == 'design' else f'src/{name}.py')
        if EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() != path.read_bytes():
            raise RuntimeError('Published design changed')
    (_, dates, *_), _ = previous()
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))
    original = requests.sessions.Session.request
    calls = []
    result = {'status':'FAILED', 'request':{'dataset':'index.domestic_daily','symbol':'000813.CSI',
        'start':'2020-01-01','end':'2026-10-15','required_cutoff':'2026-10-15'},
        'policy':'REFRESH','call_cap':3,'verified_at':datetime.now(timezone.utc).isoformat(),
        'availability_limit':'T completed market close assumed; source publication and revision history not proven.'}
    def counted(session, method, url, **kwargs):
        payload = kwargs.get('json') or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        api = payload.get('api_name', 'UNSPECIFIED')
        if len(calls) >= 3:
            raise RuntimeError('Remaining3 source-call cap reached')
        if api != 'index_daily':
            raise RuntimeError('Unexpected source API outside approved index request')
        params = payload.get('params', {})
        calls.append({'ordinal':len(calls)+1,'api':api,'symbol':params.get('ts_code'),
            'start_date':params.get('start_date'),'end_date':params.get('end_date')})
        return original(session, method, url, **kwargs)
    requests.sessions.Session.request = counted
    try:
        prepared = context.data.prepare((request(),), policy=PreparePolicy.REFRESH)
        result['prepare_status'] = str(prepared.status)
        if not prepared.ready:
            result['errors'] = [{'status':str(i.status),'code':i.error.code,'message':i.error.message} for i in prepared.items if i.error]
            raise RuntimeError('Public preparation failed; preserved structured errors')
        bound = prepared.reference
        result['reference'] = {'space_id':str(bound.space_id),'preparation_id':str(bound.preparation_id),'manifest_sha256':bound.manifest_sha256}
        fetched = context.data.fetch(request(), prepared=bound)
        if not fetched.ready:
            raise RuntimeError('Prepared fetch failed')
        frame = fetched.dataframe.sort_values('Date').reset_index(drop=True)
        identity = fetched.identity
        result['identity'] = {k:getattr(identity,k) for k in ('dataset','source','symbol','data_start','data_cutoff','content_sha256')}
        result['identity']['metadata'] = dict(identity.metadata)
        result['rows'], result['fields'] = len(frame), list(frame.columns)
        actual = pd.DatetimeIndex(pd.to_datetime(frame.Date))
        numeric = frame[['Open','High','Low','Close','PreviousClose','Volume','Amount','Change','PercentChange']].to_numpy(dtype=float)
        checks = {'live_account_access':len(calls)>0,'source_symbol':identity.symbol=='000813.CSI' and identity.dataset=='index.domestic_daily',
            'unique_dates':not actual.has_duplicates,'exact_calendar':actual.equals(dates),'expected1642':len(frame)==1642,
            'finite':bool(np.isfinite(numeric).all()),'positive_prices':bool((numeric[:,:5]>0).all()),
            'nonnegative_activity':bool((numeric[:,5:7]>=0).all()),
            'ohlc_bounds':bool((frame.Low<=frame[['Open','Close']].min(axis=1)).all() and (frame.High>=frame[['Open','Close']].max(axis=1)).all()),
            'previous_close_continuity':bool(np.allclose(frame.PreviousClose.iloc[1:],frame.Close.iloc[:-1],rtol=0,atol=.001)),
            'change_identity':bool(np.allclose(frame.Change,frame.Close-frame.PreviousClose,rtol=0,atol=.001)),
            'percent_change_identity':bool(np.allclose(frame.PercentChange,frame.Close/frame.PreviousClose-1,rtol=0,atol=.0000051))}
        result['checks'] = checks
        result['missing_dates'] = dates.difference(actual).strftime('%Y-%m-%d').tolist()
        result['extra_dates'] = actual.difference(dates).strftime('%Y-%m-%d').tolist()
        result['status'] = 'PASS' if all(checks.values()) else 'FAILED'
    finally:
        requests.sessions.Session.request = original
        result['source_calls'] = json.loads((EXPERIMENT / 'others/upstream_verification.json').read_text(encoding='utf-8'))['source_calls'] + json.loads((EXPERIMENT / 'others/vendor_identity.json').read_text(encoding='utf-8'))['source_calls'] + calls
        result['source_calls_used'] = 2+len(calls)
        result['remaining_source_calls'] = 3-len(calls)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ('status','source_calls_used','remaining_source_calls','rows','checks') if k in result},ensure_ascii=False))
    if result['status'] != 'PASS':
        raise RuntimeError('Index coverage verification did not pass')


if __name__ == '__main__':
    main()
