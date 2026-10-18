"""One explicitly authorized request per invocation; reserve budget before HTTP."""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from dataflows.tushare_common import get_tushare_pro

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PLAN = ROOT / 'research/S014/materials/20261018_methanol_completion_review/request_plan.json'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_response(frame, spec):
    expected_fields = spec['fields'].split(',')
    if len(frame.columns) != len(expected_fields) or set(frame.columns) != set(expected_fields):
        raise ValueError('Unexpected response fields')
    if not frame.ts_code.eq(spec['params']['ts_code']).all():
        raise ValueError('Response contract differs')
    dates = frame.trade_date.astype(str)
    if dates.duplicated().any() or sorted(dates) != spec['expected_dates']:
        raise ValueError('Response dates differ from exact approved coverage')
    numeric = frame[['close', 'settle', 'vol', 'amount', 'oi']].apply(pd.to_numeric, errors='raise')
    if (not np.isfinite(numeric.to_numpy(dtype=float)).all()
            or numeric[['close', 'settle']].le(0).any().any()
            or numeric[['vol', 'amount', 'oi']].lt(0).any().any()):
        raise ValueError('Invalid price or trading quantity')
    return {'expected_rows': spec['expected_rows'], 'actual_rows': len(frame),
            'missing_dates': [], 'unexpected_dates': [], 'duplicates': 0,
            'zero_volume_dates': dates.loc[numeric.vol.eq(0)].tolist()}


def select_request(number):
    authorization = read(OUT / 'authorization.json')
    assert authorization['acquisition_authorized'] is True
    assert sha256(PLAN.read_bytes()).hexdigest() == authorization['plan_sha256']
    assert authorization['max_calls'] == 20 and authorization['max_controlled_retries'] == 2
    plan = read(PLAN)
    assert 1 <= number <= 18
    spec = plan['requests'][number - 1]
    assert spec['request_number'] == number and spec['api'] == 'fut_daily'
    used = [read(p) for p in sorted((OUT / 'attempts').glob('call_*.json'))]
    assert len(used) < 20, 'Call cap exhausted'
    assert [r['call'] for r in used] == list(range(1, len(used) + 1)), 'Attempt ledger is not contiguous'
    prior = [r for r in used if r['request_number'] == number]
    assert len(prior) <= 1 and not any(r['status'] == 'RECEIVED' for r in prior), 'No duplicate successful request'
    failed = [r for r in used if r['status'] != 'RECEIVED'
              and not any(s['request_number'] == r['request_number'] and s['status'] == 'RECEIVED' for s in used)]
    if prior:
        assert prior[-1].get('retry_eligible') is True, 'Failure is not eligible for controlled retry'
        assert datetime.now(timezone.utc) >= datetime.fromisoformat(prior[-1]['retry_not_before']), 'Retry is too early'
        assert sum(r.get('is_retry', False) for r in used) < 2, 'Retry slots exhausted'
        if len(used) >= 2:
            assert not (used[-1].get('failure_class') and used[-1].get('failure_class') == used[-2].get('failure_class'))
        assert all(r['request_number'] == number for r in failed), 'Another unresolved failure blocks acquisition'
    else:
        assert not failed, 'Resolve/report previous failure before another request'
        successful_numbers = {r['request_number'] for r in used if r['status'] == 'RECEIVED'}
        assert number == min(set(range(1, 19)) - successful_numbers), 'Follow approved sequential order'
    return spec, used, bool(prior)


def acquire(number):
    spec, used, is_retry = select_request(number)
    call = len(used) + 1
    receipt_path = OUT / 'attempts' / f'call_{call:02d}.json'
    receipt = {'call': call, 'request_number': number, 'api': spec['api'], 'params': spec['params'],
               'fields': spec['fields'], 'status': 'PREPARED', 'is_retry': is_retry,
               'started_utc': datetime.now(timezone.utc).isoformat(), 'http_requests': 0,
               'retry_eligible': False, 'plan_sha256': sha256(PLAN.read_bytes()).hexdigest()}
    original = requests.sessions.Session.request

    def guarded(session, method, url, **kwargs):
        payload = kwargs.get('json') or {}
        params = {key: value for key, value in payload.get('params', {}).items() if key != 'ts_type_name'}
        assert receipt['http_requests'] == 0, 'No automatic retries'
        assert method.upper() == 'POST' and payload.get('api_name') == 'fut_daily'
        assert params == spec['params'] and payload.get('fields') == spec['fields'], 'Request differs from approved plan'
        assert all(adapter.max_retries.total == 0 for adapter in session.adapters.values())
        kwargs['allow_redirects'] = False
        receipt.update(status='STARTED', http_requests=1)
        with receipt_path.open('x', encoding='utf-8') as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        try:
            response = original(session, method, url, **kwargs)
        except requests.RequestException as error:
            receipt['failure_class'] = type(error).__name__
            receipt['retry_eligible'] = isinstance(error, (requests.Timeout, requests.ConnectionError))
            raise
        receipt['http_status'] = response.status_code
        if response.status_code == 429 or 500 <= response.status_code < 600:
            receipt.update(retry_eligible=True, failure_class=f'HTTP_{response.status_code}')
        retry_after = response.headers.get('Retry-After', '')
        if retry_after:
            try:
                earliest = (datetime.now(timezone.utc) + timedelta(seconds=int(retry_after))
                            if retry_after.isdigit() else parsedate_to_datetime(retry_after))
                if earliest.tzinfo is not None:
                    receipt['vendor_retry_not_before'] = earliest.isoformat()
            except (ValueError, OverflowError, TypeError):
                receipt['invalid_retry_after'] = True
        try:
            body = response.json()
            if isinstance(body, dict):
                if type(body.get('code')) is int:
                    receipt['vendor_code'] = body['code']
                else:
                    receipt['vendor_code_type_invalid'] = True
                message = str(body.get('msg', '')).lower()
                permission = any(s in message for s in ('权限', 'permission', 'token', '积分'))
                limited = any(s in message for s in ('每分钟', '频次', 'rate limit', 'too many requests'))
                if permission:
                    receipt.update(retry_eligible=False, failure_class='PERMISSION')
                elif limited and body.get('code') != 0:
                    receipt.update(retry_eligible=True, failure_class='RATE_LIMIT')
                if type(body.get('code')) is int and body['code'] == 0 and isinstance(body.get('data'), dict):
                    data = body['data']
                    columns, rows = data.get('fields'), data.get('items')
                    valid_shape = (isinstance(columns, list) and len(columns) == 7
                                   and all(isinstance(c, str) for c in columns)
                                   and set(columns) == set(spec['fields'].split(','))
                                   and isinstance(rows, list)
                                   and all(isinstance(r, list) and len(r) == 7 for r in rows))
                    safe_cells = valid_shape and all(
                        r[columns.index('ts_code')] == spec['params']['ts_code']
                        and isinstance(r[columns.index('trade_date')], str)
                        and len(r[columns.index('trade_date')]) == 8
                        and r[columns.index('trade_date')].isascii() and r[columns.index('trade_date')].isdigit()
                        and all(r[columns.index(c)] is None or type(r[columns.index(c)]) in (int, float)
                                for c in ['close', 'settle', 'vol', 'amount', 'oi']) for r in rows)
                    if safe_cells:
                        path = OUT / 'responses' / f'call_{call:02d}.json'
                        write(path, {'fields': columns, 'items': rows})
                        receipt.update(response_path=path.relative_to(ROOT).as_posix(),
                                       response_sha256=sha256(path.read_bytes()).hexdigest())
                    else:
                        receipt['source_table_rejected_before_persistence'] = True
                    if data.get('has_more') is True:
                        receipt.update(retry_eligible=False, failure_class='PAGINATION_REQUIRED')
        except ValueError:
            receipt['response_type'] = 'NON_JSON'
        return response

    requests.sessions.Session.request = guarded
    try:
        frame = get_tushare_pro(ROOT / '.env').query('fut_daily', fields=spec['fields'], **spec['params'])
        if receipt.get('failure_class') == 'PAGINATION_REQUIRED':
            raise ValueError('Unapproved pagination required')
        assert receipt.get('response_path') and receipt['http_requests'] == 1, 'No verified source table retained'
        receipt['quality'] = validate_response(frame, spec)
        receipt.update(rows=len(frame), columns=list(frame.columns))
        receipt.update(status='RECEIVED', retry_eligible=False)
    except Exception as error:
        receipt.update(status='FAILED', error_type=type(error).__name__)
        if isinstance(error, (ValueError, AssertionError)):
            receipt.update(retry_eligible=False, failure_class='LOCAL_OR_DATA_VALIDATION')
        # No exception strings, token, endpoint or request payload are persisted.
    finally:
        requests.sessions.Session.request = original
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if receipt['retry_eligible']:
            earliest = datetime.now(timezone.utc) + timedelta(seconds=60)
            if receipt.get('vendor_retry_not_before'):
                earliest = max(earliest, datetime.fromisoformat(receipt['vendor_retry_not_before']))
            receipt['retry_not_before'] = earliest.isoformat()
            if receipt.get('invalid_retry_after'):
                receipt['retry_eligible'] = False
        if receipt_path.exists():
            write(receipt_path, receipt)
        else:
            write(OUT / 'attempts' / f'prewire_failure_request_{number:02d}.json', receipt)
    print(json.dumps({key: receipt.get(key) for key in ['call', 'request_number', 'params', 'status',
        'http_status', 'vendor_code', 'rows', 'quality', 'retry_eligible', 'failure_class']}, ensure_ascii=False))
    return receipt['status'] == 'RECEIVED'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request_number', type=int)
    args = parser.parse_args()
    for name in ['attempts', 'responses']:
        (OUT / name).mkdir(exist_ok=True)
    lock = ROOT / '.tmp/s014-methanol-completion.lock'
    with lock.open('x', encoding='utf-8') as handle:
        handle.write('single acquisition process\n')
    try:
        return acquire(args.request_number)
    finally:
        lock.unlink()


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
