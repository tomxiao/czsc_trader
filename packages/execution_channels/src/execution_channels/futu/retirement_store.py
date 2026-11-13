"""Durable operator-owned liquidation requests, separate from strategy decisions."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4

from .account_retirement import (AccountRetirementRequest, AccountRetirementResult,
                                 AccountRetirementStatus, RetirementSession)
from .channel import STRATEGY_ACCOUNT_TYPE
from .lifecycle import DecisionState, RunState
from .broker import TERMINAL_INTENT_STATUSES

RETIREMENT_CONTRACT = 'account.retirement.v1'


def migrate_retirement(connection):
    """Expand the lifecycle constraint without changing any account or history."""
    if not connection.in_transaction:
        raise RuntimeError('retirement migration requires caller transaction')
    ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name='virtual_accounts'").fetchone()[0]
    old = "'PAUSED','RUNNING','RETIRED'"
    if old in ddl:
        objects = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='virtual_accounts' "
                                     "AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        new = ddl.replace('virtual_accounts', 'virtual_accounts_retirement_v9', 1).replace(
            old, "'PAUSED','RUNNING','RETIRING','RETIRED'")
        connection.execute(new)
        connection.execute('INSERT INTO virtual_accounts_retirement_v9 SELECT * FROM virtual_accounts')
        connection.execute('DROP TABLE virtual_accounts')
        connection.execute('ALTER TABLE virtual_accounts_retirement_v9 RENAME TO virtual_accounts')
        for row in objects:
            connection.execute(row[0])
    connection.execute('CREATE TABLE IF NOT EXISTS account_retirement_requests ('
        'account_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request TEXT NOT NULL,'
        'status TEXT NOT NULL, reason TEXT NOT NULL, session TEXT, updated_at TEXT NOT NULL)')


class RetirementStore:
    def retirement_request(self, account_id):
        with self._lock:
            self._check_owned('account', account_id)
            row = self._connection.execute('SELECT * FROM account_retirement_requests WHERE account_id=?',
                                           (account_id,)).fetchone()
        return None if row is None else dict(row)

    def retirement_status(self, account_id: str) -> AccountRetirementResult | None:
        with self._lock:
            account = self.virtual_account(account_id)
            row = self.retirement_request(account_id)
            if row is None and account['run_state'] != RunState.RETIRED:
                return None
            remaining = sum(a['run_state'] != RunState.RETIRED and a['strategy_id'] == account['strategy_id']
                            and a['strategy_version'] == account['strategy_version'] for a in self.strategy_virtual_accounts())
            return AccountRetirementResult(
                AccountRetirementStatus.RETIRED if account['run_state'] == RunState.RETIRED else AccountRetirementStatus(row['status']),
                account_id, Decimal(self._retirement_cash(account_id) or '0'), remaining,
                int(account['quantity']), '' if row is None else row['reason'])

    def begin_retirement(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        if type(request) is not AccountRetirementRequest:
            raise TypeError('retirement requires AccountRetirementRequest')
        with self._lock, self._write_context(False):
            account = self.virtual_account(request.account_id)
            if account['account_type'] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError('only a strategy account can retire')
            if account['release_hash'] != request.expected_release_hash:
                raise ValueError('retirement release hash differs from account')
            if account['run_state'] == RunState.RETIRED or self.retirement_request(request.account_id) is not None:
                return self.retirement_status(request.account_id)
            now = datetime.now(timezone.utc).isoformat()
            self._connection.execute(
                'INSERT INTO account_retirement_requests(account_id,request_id,request,status,reason,session,updated_at) '
                'VALUES(?,?,?,?,?,NULL,?)',
                (request.account_id, uuid4().hex, json.dumps(asdict(request)), 'DRAINING', '', now))
            self._connection.execute("UPDATE virtual_accounts SET run_state='RETIRING',updated_at=? WHERE account_id=?",
                                     (now, request.account_id))
            self._insert_audit_event(self._new_audit_event('ACCOUNT_RETIREMENT_REQUESTED', source='account_retirement',
                correlation_id=f'retirement:{request.account_id}',
                actor_type='OPERATOR', account_id=request.account_id, release_hash=request.expected_release_hash,
                details={'actor': request.actor, 'reason': request.reason, 'liquidation': 'MARKET'}))
        return self.retirement_status(request.account_id)

    def set_retirement_progress(self, account_id: str, status: AccountRetirementStatus, reason: str = '') -> None:
        if type(status) is not AccountRetirementStatus:
            raise TypeError('retirement progress requires typed status')
        with self._lock, self._write_context(False):
            row = self.retirement_request(account_id)
            if row is None:
                raise ValueError('account has no retirement request')
            if (row['status'], row['reason']) == (status.value, reason):
                return
            self._connection.execute('UPDATE account_retirement_requests SET status=?,reason=?,updated_at=? WHERE account_id=?',
                (status.value, reason, datetime.now(timezone.utc).isoformat(), account_id))
            self._insert_audit_event(self._new_audit_event('ACCOUNT_RETIREMENT_PROGRESS', source='account_retirement',
                correlation_id=f'retirement:{account_id}',
                actor_type='ENGINE', account_id=account_id, details={'status': status.value, 'reason': reason}))

    def set_retirement_session(self, account_id: str, session: RetirementSession) -> None:
        if type(session) is not RetirementSession:
            raise TypeError('retirement requires RetirementSession')
        with self._lock, self._write_context(False):
            account = self.virtual_account(account_id)
            if account['run_state'] != RunState.RETIRING:
                raise ValueError('only retiring accounts accept a retirement session')
            # A session is execution input, not an authorization to change account binding.
            value = {'start': session.interval.start.isoformat(), 'end': session.interval.end.isoformat(),
                     'fee_rate': str(session.fee_rate),
                     'settlement_at': None if session.settlement_at is None else session.settlement_at.isoformat()}
            self._connection.execute('UPDATE account_retirement_requests SET session=? WHERE account_id=?',
                                     (json.dumps(value), account_id))

    def clear_retirement_session(self, account_id):
        self._check_owned('account', account_id)
        with self._lock, self._write_context(False):
            self._connection.execute('UPDATE account_retirement_requests SET session=NULL WHERE account_id=?', (account_id,))

    def is_retirement_decision(self, account_id, decision_id):
        with self._lock:
            row = self.retirement_request(account_id)
            if row is None:
                return False
            decision = self._connection.execute('SELECT payload FROM decisions WHERE account_id=? AND decision_id=?',
                                                (account_id, decision_id)).fetchone()
            if decision is None:
                return False
            account = self.virtual_account(account_id)
        payload = json.loads(decision[0])
        return (payload.get('contract_version') == RETIREMENT_CONTRACT
                and payload.get('retirement_request_id') == row['request_id']
                and payload['strategy']['release_hash'] == account['release_hash']
                and payload.get('origin') == 'OPERATOR_RETIREMENT'
                and len(payload.get('orders', ())) == 1
                and payload['orders'][0]['side'] == 'SELL'
                and payload['orders'][0]['order_type'] == 'MARKET')

    def retirement_execution_allowed(self, account_id, decision_id):
        return (self.virtual_account(account_id)['run_state'] == RunState.RETIRING
                and self.is_retirement_decision(account_id, decision_id))

    def create_retirement_order(self, account_id, quantity, session: RetirementSession):
        """Create a maintenance plan and MARKET SELL intent atomically; never run SRT."""
        with self._lock, self._write_context(False):
            account = self.virtual_account(account_id)
            request = self.retirement_request(account_id)
            if account['run_state'] != RunState.RETIRING or request is None:
                raise ValueError('account has no active retirement')
            if type(quantity) is not int or not 0 < quantity <= account['quantity']:
                raise ValueError('retirement order exceeds confirmed holding')
            if any(i['status'] not in TERMINAL_INTENT_STATUSES
                   for i in self.account_intents(account_id)):
                raise ValueError('retirement requires every previous intent to be terminal')
            decision_id = 'RETIRE-' + uuid4().hex
            rules = self.equity_account_rules(account_id)
            from zoneinfo import ZoneInfo
            zone = rules.timezone if rules is not None else ZoneInfo('Asia/Shanghai')
            day = session.interval.start.astimezone(zone).date().isoformat()
            payload = {'contract_version': RETIREMENT_CONTRACT, 'decision_id': decision_id,
                'retirement_request_id': request['request_id'], 'origin': 'OPERATOR_RETIREMENT',
                'strategy': {k: account[k] for k in ('strategy_id', 'release_hash')},
                'symbol': account['symbol'], 'signal_date': day, 'valid_session': day,
                'actual_quantity': account['quantity'], 'available_cash': account['cash'],
                'action': 'SELL', 'target_position': 0., 'target_quantity': 0, 'delta_quantity': -quantity,
                'fee_rate': str(session.fee_rate), 'reason': json.loads(request['request'])['reason'],
                'equity_execution_interval': {'start': session.interval.start.isoformat(), 'end': session.interval.end.isoformat()},
                'settlement_at': None if session.settlement_at is None else session.settlement_at.isoformat(),
                'orders': [{'side': 'SELL', 'quantity': quantity, 'order_type': 'MARKET', 'limit_price': 0.}]}
            payload['strategy']['version'] = account['strategy_version']
            prior = self._connection.execute('SELECT decision_id FROM decision_adoptions WHERE account_id=? AND valid_session=? ORDER BY window_start DESC LIMIT 1',
                                              (account_id, day)).fetchone()
            if prior is not None:
                current = self.account_decision(account_id, prior[0])
                if current['status'] == DecisionState.PENDING:
                    self._transition_decision(account_id, prior[0], DecisionState.CANCELLED, 'ACCOUNT_RETIREMENT')
                elif current['status'] == DecisionState.EXECUTING:
                    raise ValueError('unfinished decision blocks retirement order')
            self._connection.execute('INSERT INTO decisions(account_id,decision_id,payload,signal_date,valid_session,generated_at,legacy_status) '
                "VALUES(?,?,?,?,?,?,'NOT_APPLICABLE')", (account_id, decision_id, json.dumps(payload), day, day,
                                                        datetime.now(timezone.utc).isoformat()))
            self._append_decision_state(account_id, decision_id, DecisionState.PENDING, 'OPERATOR_RETIREMENT')
            from .execution_adoptions import adoption_window
            self._connection.execute(
                'INSERT INTO decision_adoptions(account_id,valid_session,decision_id,window_start,window_end) VALUES(?,?,?,?,?) '
                'ON CONFLICT(account_id,valid_session,window_start,window_end) DO UPDATE SET decision_id=excluded.decision_id',
                (account_id, day, decision_id, *adoption_window(payload)))
            intent = self.create_account_intent(account_id=account_id, decision_id=decision_id, order_sequence=0,
                symbol=account['symbol'], side='SELL', quantity=quantity, limit_price=0, valid_session=day,
                fee_rate=session.fee_rate, order_type='MARKET')
            self._insert_audit_event(self._new_audit_event('ACCOUNT_RETIREMENT_ORDER_CREATED', source='account_retirement',
                correlation_id=f'retirement:{account_id}',
                actor_type='ENGINE', account_id=account_id, decision_id=decision_id,
                details={'intent_id': intent['intent_id'], 'quantity': quantity, 'order_type': 'MARKET'}))
        return intent
