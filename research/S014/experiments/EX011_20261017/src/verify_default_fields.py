"""Final approved call: omit optional timestamp to diagnose first rejection."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from dataflows.tushare_common import get_tushare_pro

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
PARAMS = {'ts_code': '600722.SH', 'start_date': '20200101', 'end_date': '20261015'}
FIELDS = 'ann_date,ts_code,name,title,url'


def main():
    target = EXPERIMENT / 'others/default_fields_verification.json'
    guard = EXPERIMENT / 'others/default_fields_started.json'
    first = json.loads((EXPERIMENT/'others/upstream_verification.json').read_text(encoding='utf-8'))
    if target.exists() or guard.exists() or first['remaining_source_calls'] != 1 or first['catalogue_received']:
        raise RuntimeError('No duplicate attempt or unauthorized followup')
    guard.write_text(json.dumps({'started_utc': datetime.now(timezone.utc).isoformat(), 'params': PARAMS,
        'fields': FIELDS}, indent=2)+'\n', encoding='utf-8', newline='\n')
    original = requests.sessions.Session.request
    calls = []
    result = {'status': 'FAILED', 'purpose': 'OMIT_OPTIONAL_TIMESTAMP_ERROR_DIAGNOSIS_ONLY',
        'catalogue_received': False, 'history_coverage': 'UNVERIFIED', 'historical_publication_time': 'UNVERIFIED'}

    def counted(session, method, url, **kwargs):
        payload = kwargs.get('json') or {}
        params = payload.get('params', {})
        if (calls or payload.get('api_name') != 'anns_d' or payload.get('fields') != FIELDS
                or any(params.get(k) != v for k, v in PARAMS.items())
                or set(params) - set(PARAMS) - {'ts_type_name'}):
            raise RuntimeError('Out-of-scope final call')
        attempt = {'api': 'anns_d', 'params': PARAMS, 'fields': FIELDS,
            'started_utc': datetime.now(timezone.utc).isoformat()}
        calls.append(attempt)
        response = original(session, method, url, **kwargs)
        attempt['http_status'] = response.status_code
        try:
            body = response.json()
            attempt['vendor_code'] = body.get('code')
            message = str(body.get('msg', ''))
            # A short Chinese-only projection cannot expose ASCII tokens, URLs,
            # hostnames or identifiers. Never save the arbitrary raw error message.
            attempt['vendor_message_chinese_projection'] = ''.join(re.findall('[\u4e00-\u9fff]', message))[:160]
            low = message.lower()
            attempt['vendor_message_class'] = ('PERMISSION_RELATED' if '权限' in message or 'permission' in low or 'forbidden' in low
                else 'QUOTA_RELATED' if any(s in message for s in ('每分钟', '频次', '限额', '次数', '额度'))
                else 'FIELD_RELATED' if '字段' in message or 'field' in low
                else 'AUTH_RELATED' if 'token' in low or '认证' in message
                else 'NOT_CLASSIFIED')
        except ValueError:
            attempt['vendor_message_class'] = 'NON_JSON'
        return response

    requests.sessions.Session.request = counted
    try:
        frame = get_tushare_pro(ROOT/'.env').anns_d(**PARAMS, fields=FIELDS)
        result.update(status='CATALOGUE_RECEIVED' if len(frame) else 'EMPTY_DATA', catalogue_received=True,
            rows=len(frame), columns=list(frame.columns), possible_row_limit_truncation=len(frame) >= 2000)
        frame.to_csv(EXPERIMENT/'others/default_fields_catalogue.csv', index=False, lineterminator='\n')
    except Exception as error:
        result['error_type'] = type(error).__name__
        context = getattr(error, 'context', {})
        result['error_context'] = {k: context[k] for k in ('vendor', 'api', 'http_status', 'vendor_code') if k in context}
        if calls:
            result['status'] = calls[-1].get('vendor_message_class', 'FAILED')
    finally:
        requests.sessions.Session.request = original
        result.update(source_calls=calls, new_source_calls=len(calls), experiment_source_calls=first['new_source_calls']+len(calls),
            cumulative_source_calls=first['cumulative_source_calls']+len(calls), remaining_source_calls=first['remaining_source_calls']-len(calls))
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
