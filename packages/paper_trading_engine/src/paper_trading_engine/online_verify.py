"""Explicit HTTP acceptance of a running local PTE instance."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection, HTTPException
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() <= set(required) | set(optional):
        raise ValueError(f'expected fields {required}, optional fields {optional}')
    return value


def _identity(value, length):
    if type(value) is not str or re.fullmatch(f'[0-9a-f]{{{length}}}', value) is None:
        raise ValueError(f'expected {length}-character lowercase hexadecimal identity')


def _moment(value):
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError('timestamp must include its time zone')
    return moment


def _entries(value):
    if type(value) is not dict or not value:
        raise ValueError('expected a nonempty object keyed by account ID')
    for key, entry in value.items():
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', key):
            raise ValueError(f'invalid account ID: {key}')
        yield entry


def _validate(plan, drive_dev):
    _object(plan, ('release', 'channels', 'accounts'))
    release = _object(plan['release'], ('mode',), ('release_id', 'git_commit', 'manifest_sha256', 'repo_root'))
    if release['mode'] == 'PTE':
        _object(release, ('mode', 'release_id', 'git_commit', 'manifest_sha256'))
        if type(release['release_id']) is not str or not release['release_id']:
            raise ValueError('release_id is required')
        _identity(release['git_commit'], 40)
        _identity(release['manifest_sha256'], 64)
    elif release['mode'] == 'DEV':
        _object(release, ('mode', 'repo_root'))
        if type(release['repo_root']) is not str or not release['repo_root']:
            raise ValueError('repo_root is required')
    else:
        raise ValueError('release mode must be DEV or PTE')
    if drive_dev and release['mode'] != 'DEV':
        raise ValueError('--drive-dev requires an isolated DEV release')
    for entry in _entries(plan['channels']):
        _object(entry, ('channel_id', 'market', 'currency'))
        if (entry['channel_id'], entry['market'], entry['currency']) not in (
            ('futu_simulate_cn', 'CN', 'CNY'), ('futu_US_sim_channel', 'US', 'USD'),
        ):
            raise ValueError('invalid channel, market and currency combination')
    for entry in _entries(plan['accounts']):
        _object(entry, ('channel_account_id', 'release_hash', 'run_state'),
                ('decision', 'quantity', 'orders', 'fills'))
        _identity(entry['release_hash'], 64)
        if entry['channel_account_id'] not in plan['channels']:
            raise ValueError('account channel is outside the declared scope')
        if entry['run_state'] not in ('PAUSED', 'RUNNING', 'RETIRING', 'RETIRED'):
            raise ValueError('invalid account run state')
        if drive_dev and ('decision' not in entry or entry['run_state'] != 'RUNNING'):
            raise ValueError('--drive-dev requires running V5 accounts and explicit decision expectations')
        if any(type(entry[k]) is not int or entry[k] < 0 for k in ('quantity', 'orders', 'fills') if k in entry):
            raise ValueError('quantity, orders and fills must be nonnegative integers')
        if 'decision' in entry:
            decision = _object(entry['decision'], ('interval', 'action', 'target_quantity'),
                               ('fresh', 'case_key', 'judgment'))
            interval = _object(decision['interval'], ('start', 'end'))
            if _moment(interval['start']) >= _moment(interval['end']):
                raise ValueError('invalid decision interval')
            if decision['action'] not in ('BUY', 'SELL', 'WAIT', 'HOLD', 'ROTATE'):
                raise ValueError('invalid expected decision action')
            if type(decision['target_quantity']) is not int or decision['target_quantity'] < 0:
                raise ValueError('invalid expected target quantity')
            if 'fresh' in decision and (not drive_dev or type(decision['fresh']) is not bool):
                raise ValueError('fresh is a boolean option for --drive-dev')
            if any(type(decision[key]) is not str or not decision[key] for key in ('case_key', 'judgment') if key in decision):
                raise ValueError('case_key and judgment must be nonempty strings')


class _HttpError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _request(port, path, *, post=False):
    connection = HTTPConnection('127.0.0.1', port, timeout=15)
    try:
        headers = {'Content-Type': 'application/json'} if post else {}
        connection.request('POST' if post else 'GET', path, b'{}' if post else None, headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        if response.status != 200:
            raise _HttpError(response.status, payload.get('error', 'request failed'))
        if type(payload) is not dict:
            raise ValueError('PTE response must be a JSON object')
        return payload
    finally:
        connection.close()


def _selected(payload, expected):
    return {key: payload.get(key) for key in expected}


def verify(port: int, plan: dict, *, drive_dev: bool = False) -> dict:
    """Verify only the declared release, channels, accounts and decision intervals."""
    _validate(plan, drive_dev)
    checks = []

    def record(check, expected, actual, *, blocked=False, evidence=None):
        status = 'BLOCKED' if blocked else 'PASS' if actual == expected else 'FAIL'
        result = dict(check=check, status=status, expected=expected, actual=actual)
        if evidence is not None:
            result['evidence'] = evidence
        checks.append(result)
        return status == 'PASS'

    def get(check, path, *, post=False):
        try:
            return _request(port, path, post=post)
        except _HttpError as exc:
            record(check, 'HTTP 200', dict(http_status=exc.status, error=str(exc)),
                   blocked=post and exc.status == 409)
        except (OSError, HTTPException, ValueError) as exc:
            record(check, 'valid HTTP response', str(exc), blocked=isinstance(exc, OSError))
        return None

    health = get('health.http', '/api/health')
    if health is not None:
        correct_release = record('health.release', plan['release'], _selected(health.get('release') or {}, plan['release']))
        heartbeat = health.get('scheduler_heartbeat_at')
        try:
            fresh = timedelta(0) <= datetime.now(timezone.utc) - _moment(heartbeat) <= timedelta(seconds=45)
        except (ValueError, TypeError):
            fresh = False
        ready = record('health.runtime', ['RUNNING', True, True, True], [
            health.get('runtime'), health.get('watchdog_healthy'), fresh, bool(health.get('instance_id')),
        ])
        if correct_release and ready:
            ready_channels = set()
            for channel_id, expected in plan['channels'].items():
                prefix = f'channel.{channel_id}'
                channel = get(prefix + '.http', f'/api/channel-accounts/{quote(channel_id, safe="")}/snapshot')
                if channel is None:
                    continue
                scope = channel.get('scope') or {}
                record(prefix + '.identity', {'channel_account_id': channel_id, **expected},
                       {**_selected(channel, expected), **scope})
                status = channel.get('reconciliation_status')
                record(prefix + '.reconciliation', 'OK', status, blocked=status in (None, 'UNAVAILABLE'),
                       evidence=_selected(channel, ('last_reconcile_at', 'cash_reconciliation_status', 'cash_difference')))
                broker_cash = channel.get('broker_cash')
                record(prefix + '.broker_snapshot', 'SIMULATE', channel.get('environment'),
                       blocked=broker_cash is None)
                record(prefix + '.alerts', [], channel.get('alerts'))
                record(prefix + '.scheduler_failures', [], channel.get('scheduler_failures'))
                if all(check['status'] == 'PASS' for check in checks if check['check'].startswith(prefix + '.')):
                    ready_channels.add(channel_id)
            for account_id, expected in plan['accounts'].items():
                if drive_dev and expected['channel_account_id'] not in ready_channels:
                    record(f'account.{account_id}.drive', 'ready channel', expected['channel_account_id'], blocked=True)
                    continue
                try:
                    _verify_account(account_id, expected, drive_dev, get, record)
                except (KeyError, TypeError, ValueError) as exc:
                    record(f'account.{account_id}.schema', 'valid account and audit payloads', str(exc))
            final_health = get('health.final.http', '/api/health')
            if final_health is not None:
                record('health.same_instance', health['instance_id'], final_health.get('instance_id'))

    status = 'FAIL' if any(c['status'] == 'FAIL' for c in checks) else (
        'BLOCKED' if any(c['status'] == 'BLOCKED' for c in checks) else 'PASS'
    )
    return dict(status=status, mode='DEV_DRIVE' if drive_dev else 'READ_ONLY',
                instance_id=None if health is None else health.get('instance_id'),
                release=None if health is None else health.get('release'), checks=checks)


def _verify_account(account_id, expected, drive_dev, get, record):
    prefix = f'account.{account_id}'
    path = f'/api/virtual-accounts/{quote(account_id, safe="")}'
    snapshot = get(prefix + '.http', path + '/snapshot')
    if snapshot is None:
        return
    fields = {key: expected[key] for key in ('channel_account_id', 'release_hash', 'run_state')}
    fields.update(account_id=account_id, health='OK')
    if drive_dev:
        fields['decision_contract'] = 'V5'
    if not record(prefix + '.binding', fields, _selected({**snapshot['account'], **snapshot['scope']}, fields)):
        return
    driven = None
    if drive_dev:
        driven = get(prefix + '.drive', path + '/decision', post=True)
        if driven is None:
            return
        snapshot = get(prefix + '.persisted', path + '/snapshot')
        if snapshot is None:
            return
    if 'quantity' in expected:
        record(prefix + '.quantity', expected['quantity'], snapshot['account'].get('quantity'))
    for key in ('orders', 'fills'):
        if key in expected:
            record(prefix + '.' + key, expected[key], len(snapshot[key]))
    if 'decision' not in expected:
        return
    decision = snapshot.get('decision') or {}
    target = expected['decision']
    actual_interval = decision.get('equity_execution_interval')
    awaiting = actual_interval is None or _moment(actual_interval['start']) < _moment(target['interval']['start'])
    if not record(prefix + '.interval', target['interval'], actual_interval, blocked=not drive_dev and awaiting):
        return
    expected_result = dict(action=target['action'], target_quantity=target['target_quantity'],
                           release_hash=expected['release_hash'])
    record(prefix + '.decision', expected_result,
           _selected({**decision, 'release_hash': (decision.get('strategy') or {}).get('release_hash')}, expected_result))
    expected_explanation = {key: target[key] for key in ('case_key', 'judgment') if key in target}
    if expected_explanation:
        explanation = (decision.get('strategy_output') or {}).get('explanation') or {}
        record(prefix + '.explanation', expected_explanation, _selected(explanation, expected_explanation))
    if driven is not None:
        states = ['DECISION_COMPLETED'] if target.get('fresh') else ['DECISION_COMPLETED', 'DECISION_REUSED']
        evidence = {'decision_id': decision.get('decision_id'), 'release_hash': expected['release_hash'],
                    'prepared_data_identity': decision.get('prepared_data_identity')}
        record(prefix + '.drive_identity', evidence, _selected(driven, evidence))
        record(prefix + '.drive_outcome', True, driven.get('status') in states,
               evidence={'allowed': states, 'status': driven.get('status')})
    query = urlencode(dict(channel_account_id=expected['channel_account_id'], account_id=account_id,
                           event_type='MARKET_DATA_PREPARED', limit=200))
    prepared = get(prefix + '.prepared.http', '/api/audit-events?' + query)
    if prepared is not None:
        identity = decision.get('prepared_data_identity')
        matching = [event['id'] for event in prepared['events'] if identity
                    and (event.get('details') or {}).get('data_identity') == identity
                    and event['details'].get('interval') == target['interval']]
        record(prefix + '.prepared', True, bool(matching), blocked=not matching,
               evidence={'prepared_data_identity': identity, 'event_ids': matching})
    query = urlencode(dict(channel_account_id=expected['channel_account_id'], account_id=account_id,
                           decision_id=decision['decision_id'], event_type='DECISION_GENERATED'))
    events = get(prefix + '.decision_audit.http', '/api/audit-events?' + query)
    if events is not None:
        ids = [event['id'] for event in events['events'] if event.get('release_hash') == expected['release_hash']]
        record(prefix + '.decision_audit', True, bool(ids), blocked=not ids,
               evidence={'decision_id': decision['decision_id'], 'event_ids': ids})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--json-output', type=Path, required=True)
    parser.add_argument('--drive-dev', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        plan = json.loads(args.plan.read_bytes())
        _validate(plan, args.drive_dev)
        with args.json_output.open('x', encoding='utf-8') as stream:
            report = verify(args.port, plan, drive_dev=args.drive_dev)
            json.dump(report, stream, ensure_ascii=False, indent=2)
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    for check in report['checks']:
        print(f"{check['status']:7} {check['check']}")
    print(f"{report['status']} {args.json_output}")
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
