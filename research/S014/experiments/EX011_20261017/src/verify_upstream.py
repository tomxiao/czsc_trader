"""One guarded, same-account announcement feasibility request; no return data."""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from dataflows.tushare_common import get_tushare_pro

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
FIELDS = 'ann_date,ts_code,name,title,url,rec_time'
PARAMS = {'ts_code': '600722.SH', 'start_date': '20200101', 'end_date': '20261015'}


def main():
    target = EXPERIMENT / 'others/upstream_verification.json'
    guard = EXPERIMENT / 'others/attempt_started.json'
    if target.exists() or guard.exists():
        raise RuntimeError('Preserve the original attempt; no implicit retry')
    guard.write_text(json.dumps({'started_utc': datetime.now(timezone.utc).isoformat(),
        'api': 'anns_d', 'params': PARAMS, 'fields': FIELDS}, indent=2) + '\n', encoding='utf-8', newline='\n')
    calls = []
    original = requests.sessions.Session.request
    result = {'status': 'FAILED', 'api': 'anns_d', 'params': PARAMS, 'requested_fields': FIELDS.split(','),
        'purpose': 'UPSTREAM_FEASIBILITY_ONLY', 'prior_calls_used': 48, 'total_budget': 50,
        'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'catalogue_received': False,
        'history_coverage': 'UNVERIFIED', 'historical_publication_time': 'UNVERIFIED'}

    def counted(session, method, url, **kwargs):
        payload = kwargs.get('json') or {}
        params = payload.get('params', {})
        if (len(calls) >= 1 or payload.get('api_name') != 'anns_d'
                or any(params.get(k) != v for k, v in PARAMS.items())
                or set(params) - set(PARAMS) - {'ts_type_name'}
                or payload.get('fields') != FIELDS):
            raise RuntimeError('Request outside predeclared scope')
        attempt = {'api': 'anns_d', 'params': PARAMS, 'fields': FIELDS,
            'started_utc': datetime.now(timezone.utc).isoformat()}
        calls.append(attempt)
        response = original(session, method, url, **kwargs)
        attempt['http_status'] = response.status_code
        # Do not retain arbitrary vendor messages or request/authentication payloads.
        try:
            body = response.json()
            attempt['vendor_code'] = body.get('code')
            message = str(body.get('msg', ''))
            if any(s in message for s in ('没有访问该接口的权限', '无权限', '权限不足', '没有权限', '开通权限')):
                attempt['vendor_message_class'] = 'PERMISSION_DENIED'
            elif any(s in message for s in ('每分钟', '访问频率', '频次', 'rate limit')):
                attempt['vendor_message_class'] = 'RATE_LIMIT'
            else:
                attempt['vendor_message_class'] = 'NOT_CLASSIFIED'
        except ValueError:
            attempt['vendor_message_class'] = 'NON_JSON'
        return response

    requests.sessions.Session.request = counted
    try:
        frame = get_tushare_pro(ROOT / '.env').anns_d(**PARAMS, fields=FIELDS)
        result.update(status='CATALOGUE_RECEIVED' if len(frame) else 'EMPTY_DATA',
            catalogue_received=True, rows=len(frame), columns=list(frame.columns),
            possible_row_limit_truncation=len(frame) >= 2000)
        frame.to_csv(EXPERIMENT / 'others/catalogue.csv', index=False, lineterminator='\n')
        if not frame.empty:
            missing = set(FIELDS.split(',')) - set(frame.columns)
            result['missing_columns'] = sorted(missing)
            if not missing:
                dates = frame.ann_date.astype(str).str.replace('-', '', regex=False).str[:8]
                result.update(unique_symbols=sorted(frame.ts_code.dropna().unique().tolist()),
                    earliest=dates.min(), latest=dates.max(), counts_by_year=dates.str[:4].value_counts().sort_index().to_dict(),
                    outside_date_bounds=int(((dates < '20200101') | (dates > '20261015')).sum()),
                    missing_rec_time=int((frame.rec_time.isna() | frame.rec_time.astype(str).str.strip().eq('')).sum()),
                    duplicate_urls=int(frame.url.duplicated().sum()), duplicate_rows=int(frame.duplicated().sum()))
    except Exception as error:
        # Error text may contain credentials; expose only typed, allowlisted context.
        context = getattr(error, 'context', {})
        result['error_type'] = type(error).__name__
        result['error_context'] = {k: context[k] for k in ('vendor', 'api', 'http_status', 'vendor_code') if k in context}
        if calls and calls[-1].get('vendor_message_class') == 'PERMISSION_DENIED':
            result['status'] = 'PERMISSION_DENIED'
    finally:
        requests.sessions.Session.request = original
        result.update(source_calls=calls, new_source_calls=len(calls),
            cumulative_source_calls=48 + len(calls), remaining_source_calls=2 - len(calls))
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
