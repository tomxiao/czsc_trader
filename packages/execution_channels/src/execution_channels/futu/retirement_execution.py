"""Operator retirement: drain orders, liquidate confirmed holdings, return cash."""
from datetime import datetime
from decimal import Decimal
import json

from ..instruments import TimeInterval
from .account_retirement import AccountRetirementRequest, AccountRetirementResult, AccountRetirementStatus as Phase, RetirementSession
from .broker import TERMINAL_INTENT_STATUSES, TERMINAL_ORDER_STATUSES
from .lifecycle import AccountHealth, IntentControlState, RunState


class RetirementExecution:
    def set_retirement_session(self, account_id: str, session: RetirementSession) -> None:
        self.store.set_retirement_session(account_id, session)

    def retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        if type(request) is not AccountRetirementRequest:
            raise TypeError('retirement requires AccountRetirementRequest')
        if self._draining:
            raise RuntimeError('PTE is stopping; account retirement is unavailable')
        with self.store._lock:
            result = self.store.begin_retirement(request)
            if result.status is Phase.RETIRED:
                return result
            try:
                self._settle_retiring_accounts()
                self._refresh_orders(expire_orders=False)
                self._advance_retirement(request.account_id)
            except Exception as exc:
                self.store.set_retirement_progress(request.account_id, Phase.BLOCKED, str(exc))
            return self.store.retirement_status(request.account_id)

    def _settle_retiring_accounts(self):
        for account in self.store.strategy_virtual_accounts():
            if account['run_state'] == RunState.RETIRING and Decimal(account['receivable']):
                self.store.settle_equity_receivables(account['account_id'], at=self.now())

    def _advance_retirements(self):
        for account in self.store.strategy_virtual_accounts():
            if account['run_state'] != RunState.RETIRING:
                continue
            try:
                with self.store._lock:
                    self._advance_retirement(account['account_id'])
            except Exception as exc:
                self.store.set_retirement_progress(account['account_id'], Phase.BLOCKED, str(exc))

    def _drain_retirement_orders(self, account_id):
        waiting = False
        released = False
        for intent in self.store.account_intents(account_id):
            if intent['status'] in TERMINAL_INTENT_STATUSES:
                continue
            if self.store.is_retirement_decision(account_id, intent['decision_id']):
                waiting = True
                continue
            order_id = intent.get('channel_order_id')
            if intent['status'] in {'PENDING_SUBMIT', 'WAITING_DEPENDENCY'} and not order_id:
                event = self.audit.build('ORDER_INTENT_SUPERSEDED', source='account_retirement',
                    actor_type='OPERATOR', account_id=account_id, decision_id=intent['decision_id'],
                    details={'intent_id': intent['intent_id'], 'reason': 'ACCOUNT_RETIREMENT'})
                self.store.release_account_intent(intent['intent_id'], 'SUPERSEDED', audit_event=event)
                released = True
                continue
            waiting = True
            if not order_id or intent['status'] in {'SUBMISSION_UNCERTAIN', 'SUBMITTING', 'TIMEOUT',
                                                    'CANCELLING_ALL', 'CANCELLING_PART'}:
                continue
            # Persist the cancellation intent before the network call. A restart must
            # reconcile an uncertain cancellation instead of issuing another sell.
            requests = self.store.query_audit_events(event_type='CANCEL_REQUESTED', order_id=order_id, limit=1)
            if requests and requests[0]['source'] == 'account_retirement':
                continue
            self.audit.record('CANCEL_REQUESTED', source='account_retirement', actor_type='OPERATOR',
                outcome='UNKNOWN', account_id=account_id, decision_id=intent['decision_id'], order_id=order_id,
                details={'reason': 'ACCOUNT_RETIREMENT'})
            self.broker.cancel_order(order_id)
            self.store.update_account_intent_status(intent['intent_id'], IntentControlState.CANCELLING_ALL)
        if released:
            self._refresh_orders(expire_orders=False)
        return waiting

    def _advance_retirement(self, account_id):
        def progress(status, reason=''):
            self.store.set_retirement_progress(account_id, status, reason)

        if self._draining:
            return
        if self._drain_retirement_orders(account_id):
            own = any(self.store.is_retirement_decision(account_id, i['decision_id'])
                      and i['status'] not in TERMINAL_INTENT_STATUSES for i in self.store.account_intents(account_id))
            progress(Phase.LIQUIDATING if own else Phase.DRAINING, '等待渠道确认现有订单结果')
            if own:
                self.submit_pending(reconcile=False, retirement_account_id=account_id)
            return
        account = self.store.virtual_account(account_id)
        if account['health'] != AccountHealth.OK or self.store.attention_account_intents(account_id):
            progress(Phase.BLOCKED, account.get('last_error') or '存在待处理执行异常')
            return
        if self.store.is_paused():
            progress(Phase.BLOCKED, '渠道已暂停')
            return
        if self.store.get_setting('channel_reconciliation_status') != 'OK':
            progress(Phase.BLOCKED, '渠道对账未通过')
            return
        if not account['quantity']:
            if Decimal(account['frozen_cash']) or Decimal(account['receivable']):
                progress(Phase.WAITING_SETTLEMENT, '等待冻结资金释放或卖出资金结算')
                return
            if any(o['status'] not in TERMINAL_ORDER_STATUSES for o in self.store.account_orders(account_id)):
                progress(Phase.DRAINING, '等待渠道订单终态')
                return
            expected_cash = self.store.capital_pool_balance().unallocated_cash + sum(
                (Decimal(a['cash']) + Decimal(a['frozen_cash']) for a in self.store.virtual_accounts()
                 if a['run_state'] != RunState.RETIRED), Decimal('0'))
            actual = Decimal(str(self._snapshot.account.cash))
            if not actual.is_finite() or abs(actual - expected_cash) > Decimal('.01'):
                progress(Phase.BLOCKED, '资金回笼前渠道现金对账未通过')
                return
            request = AccountRetirementRequest(**json.loads(self.store.retirement_request(account_id)['request']))
            self.store._retire_account(request)
            return
        if self.config is not None and self.config.session != 'RTH':
            progress(Phase.BLOCKED, '当前渠道时段策略不允许市价单；退役要求 RTH 渠道配置')
            return
        # Deterministic rejections require operator review; retirement is not a
        # retry policy, even when the existing order classifier cleared attention.
        prior = [i for i in self.store.account_intents(account_id)
                 if self.store.is_retirement_decision(account_id, i['decision_id'])]
        if prior and not prior[-1].get('resolved_at') and prior[-1]['status'] in {'REJECTED', 'SUBMISSION_FAILED', 'SUBMIT_FAILED', 'FAILED', 'DISABLED', 'DELETED'}:
            progress(Phase.BLOCKED, '清仓订单失败，请核查渠道拒单或执行约束')
            return
        row = self.store.retirement_request(account_id)
        if row['session'] is None:
            if row['status'] != Phase.BLOCKED:
                progress(Phase.WAITING_MARKET, '等待宿主提供实际交易时段及费率')
            return
        value = json.loads(row['session'])
        session = RetirementSession(TimeInterval(datetime.fromisoformat(value['start']), datetime.fromisoformat(value['end'])),
            Decimal(value['fee_rate']), None if value['settlement_at'] is None else datetime.fromisoformat(value['settlement_at']))
        if not session.interval.start <= self.now() < session.interval.end:
            progress(Phase.WAITING_MARKET, '当前不在已确认的市价单交易时段')
            return
        positions = [p for p in self._snapshot.positions if p.symbol == account['symbol']]
        if len(positions) != 1 or positions[0].sellable_quantity is None:
            progress(Phase.BLOCKED, '渠道未返回明确可卖数量')
            return
        available = positions[0].sellable_quantity
        # Local ownership and exchange settlement restrictions both apply.
        rules = self.store.equity_account_rules(account_id)
        if rules is not None and account.get('account_v4_json') is not None:
            from .equity_account_state import load_document
            document = load_document(account)
            locked = sum(lock['quantity'] for lock in document['buy_locks']
                         if datetime.fromisoformat(lock['at']) > self.now())
            available = min(available, account['quantity'] - locked)
        quantity = min(account['quantity'], available)
        if quantity != account['quantity']:
            step = 100 if rules is None else rules.execution.quantity_step
            quantity = quantity // step * step
        if quantity <= 0:
            progress(Phase.WAITING_SELLABLE, '当前没有可卖持仓，等待渠道或交收状态更新')
            return
        self.store.create_retirement_order(account_id, quantity, session)
        progress(Phase.LIQUIDATING)
        self.submit_pending(reconcile=False, retirement_account_id=account_id)
