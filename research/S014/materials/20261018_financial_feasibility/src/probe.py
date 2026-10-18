"""Bounded same-account upstream feasibility; never an executable research dataset."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

import requests
from dataflows.tushare_common import get_tushare_pro

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]

def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    args = parser.parse_args()
    request_path = (ROOT / args.request).resolve()
    assert request_path.is_relative_to(OUT / 'requests')
    spec = json.loads(request_path.read_text(encoding='utf-8'))
    api, params, fields = spec['api'], spec['params'], spec['fields']
    assert api in {'income', 'balancesheet', 'cashflow', 'fina_indicator', 'forecast', 'express'}
    assert params == {'ts_code': '600722.SH', 'start_date': '20200101', 'end_date': '20261015'}
    attempt_dir = OUT / 'attempts'
    attempt_dir.mkdir(exist_ok=True)
    used = sorted(attempt_dir.glob('call_*.json'))
    assert len(used) < 6, 'Call budget exhausted'
    for previous in used:
        assert json.loads(previous.read_text(encoding='utf-8'))['request_path'] != args.request, 'No implicit repeat'
    call_id = len(used) + 1
    target = attempt_dir / f'call_{call_id:02d}.json'
    receipt = {'call': call_id, 'api': api, 'params': params, 'fields': fields,
        'request_path': args.request, 'purpose': spec['purpose'], 'status': 'PREPARED',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'http_requests': 0}
    original = requests.sessions.Session.request
    def guarded(session, method, url, **kwargs):
        payload = kwargs.get('json') or {}
        observed = {k:v for k,v in (payload.get('params') or {}).items() if k != 'ts_type_name'}
        assert not receipt['http_requests'], 'No implicit retries'
        assert payload.get('api_name') == api and observed == params and payload.get('fields') == fields
        assert method.upper() == 'POST'
        assert all(adapter.max_retries.total == 0 for adapter in session.adapters.values())
        kwargs['allow_redirects'] = False
        receipt.update(status='STARTED', http_requests=1)
        # Reserve the budget before the wire call; an interrupted attempt remains counted.
        with target.open('x', encoding='utf-8') as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        try:
            response = original(session, method, url, **kwargs)
        except requests.RequestException as error:
            receipt['transport_error_type'] = type(error).__name__
            raise
        receipt['http_status'] = response.status_code
        try:
            body = response.json()
            receipt['vendor_code'] = body.get('code')
            msg = str(body.get('msg', ''))
            receipt['vendor_message_class'] = (
                'PERMISSION_RELATED' if '权限' in msg or 'permission' in msg.lower()
                else 'RATE_LIMIT' if any(s in msg for s in ['每分钟', '频次', '限额', '次数'])
                else 'OTHER')
            receipt['vendor_message_chinese_projection'] = ''.join(re.findall('[\u4e00-\u9fff]', msg))[:120]
            if body.get('code') == 0 and isinstance(body.get('data'), dict):
                raw_path = OUT / 'responses' / f'call_{call_id:02d}.json'
                # Only public data table, never token, endpoint, request payload or arbitrary message.
                write(raw_path, body['data'])
                receipt['response_path'] = raw_path.relative_to(ROOT).as_posix()
                receipt['response_sha256'] = sha256(raw_path.read_bytes()).hexdigest()
        except ValueError:
            receipt['response_type'] = 'NON_JSON'
        return response
    requests.sessions.Session.request = guarded
    try:
        frame = get_tushare_pro(ROOT / '.env').query(api, fields=fields, **params)
        receipt.update(status='RECEIVED' if len(frame) else 'EMPTY', rows=len(frame), columns=list(frame.columns))
        csv = OUT / 'responses' / f'call_{call_id:02d}.csv'
        frame.to_csv(csv, index=False, lineterminator='\n')
        receipt['csv_path'] = csv.relative_to(ROOT).as_posix()
        receipt['csv_sha256'] = sha256(csv.read_bytes()).hexdigest()
        for key in ['ann_date', 'f_ann_date', 'end_date']:
            if key in frame and len(frame):
                receipt[key + '_range'] = [str(frame[key].min()), str(frame[key].max())]
        if 'ts_code' in frame:
            receipt['unique_symbols'] = sorted(frame.ts_code.astype(str).unique().tolist())
        if 'mapping_ts_code' in frame:
            receipt['mapped_contract_count'] = int(frame.mapping_ts_code.nunique())
    except Exception as error:
        receipt['status'] = 'FAILED'
        receipt['error_type'] = type(error).__name__
        context = getattr(error, 'context', {})
        receipt['error_context'] = {k:context[k] for k in ['vendor','api','http_status','vendor_code'] if k in context}
    finally:
        requests.sessions.Session.request = original
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if target.exists():
            write(target, receipt)
        else:
            write(OUT / 'attempts' / f'prewire_failure_{request_path.stem}.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))

if __name__ == '__main__':
    (OUT / 'responses').mkdir(exist_ok=True)
    main()
