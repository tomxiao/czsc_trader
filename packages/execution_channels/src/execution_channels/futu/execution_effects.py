"""Read-only confirmed decision effects for both Futu simulation markets."""
from datetime import date, datetime
from decimal import Decimal

from ..daily_execution import PreviousDailyExecution, daily_execution_outcome
from ..execution_effects import DecisionExecutionEffect, OrderExecutionEffect, decision_execution_effect
from .broker import TERMINAL_INTENT_STATUSES, TERMINAL_ORDER_STATUSES, UNRESOLVED_INTENT_STATUSES
from .lifecycle import DecisionState, planned_orders


class ExecutionEffectStore:
    def previous_daily_execution(self, account_id: str, *, previous_session: date) -> PreviousDailyExecution | None:
        """Use the last evaluated target and permit retries only from the prior trading session."""
        if type(previous_session) is not date:
            raise TypeError('daily execution history requires a prior market session date')
        self._check_owned('account', account_id)
        session = previous_session.isoformat()
        with self._lock:
            prior = self._connection.execute('''
                SELECT a.decision_id, a.valid_session,
                    json_extract(d.payload, '$.strategy_output.execution_plan.target') AS target,
                    json_extract(d.payload, '$.strategy_output.execution_plan.entry_cash') AS entry_cash
                FROM decision_adoptions a JOIN decisions d
                    ON d.account_id = a.account_id AND d.decision_id = a.decision_id
                WHERE a.account_id = ? AND a.valid_session <= ?
                    AND target IS NOT NULL
                    AND COALESCE(json_extract(d.payload, '$.strategy_output.execution_plan.signal_status'),
                                 'EVALUATED') = 'EVALUATED'
                ORDER BY a.valid_session DESC LIMIT 1
            ''', (account_id, session)).fetchone()
            if prior is None:
                return None
            decision_id = prior['decision_id']
            decision = self.account_decision(account_id, decision_id)
            planned = planned_orders(decision['payload'])
            ordered = filled = 0
            terminal = True
            if planned and decision['status'] not in {DecisionState.SUPERSEDED, DecisionState.CANCELLED}:
                ordered = sum(order['quantity'] for order in planned)
                filled = self._connection.execute('''
                    SELECT COALESCE(SUM(quantity), 0) FROM fills WHERE account_id=? AND decision_id=?
                ''', (account_id, decision_id)).fetchone()[0]
                terminal = decision['status'] in {DecisionState.COMPLETED, DecisionState.INCOMPLETE}
                if terminal:
                    intents = self.account_intents(account_id, decision_id)
                    terminal = len(intents) == len(planned) and all(
                        intent['status'] in TERMINAL_INTENT_STATUSES for intent in intents)
                    reports = [self.account_order(intent['channel_order_id'])
                               for intent in intents if intent['channel_order_id']]
                    terminal = terminal and all(order['status'] in TERMINAL_ORDER_STATUSES for order in reports)
                    terminal = terminal and sum(order['cumulative_filled_quantity'] for order in reports) == filled
            entry_cash = prior['entry_cash']
            buy_cost = Decimal(0)
            if entry_cash is not None:
                from .equity_account_state import load_document, position_from_dict
                position = position_from_dict(load_document(self.virtual_account(account_id))['active'])
                if position is not None:
                    buy_cost = Decimal(str(position.buy_cost))
            return PreviousDailyExecution(prior['target'], daily_execution_outcome(ordered, filled, terminal=terminal),
                prior['valid_session'] == session, None if entry_cash is None else Decimal(entry_cash), buy_cost)

    def decision_execution_effect(self, account_id: str, decision_id: str, *,
                                  valuation_price: Decimal | float, at: datetime) -> DecisionExecutionEffect:
        """Return current confirmed state against this decision, not a historical snapshot.

        The caller supplies an execution-basis valuation price and current query
        time. This does not reconstruct an earlier account. Known later fills,
        account adjustments and dated order reports reject a backdated query.
        No broker/DFLS request is made and no order is resubmitted. Reserved cash
        remains part of equity.
        """
        if type(at) is not datetime or at.utcoffset() is None:
            raise TypeError('execution effect requires aware query time')
        with self._lock:
            account = self.virtual_account(account_id)
            if self.equity_account_rules(account_id) is None:
                raise ValueError('decision effect requires a current equity channel account')
            decision = self.account_decision(account_id, decision_id)
            payload = decision['payload']
            evidence = payload['strategy_output']['execution_plan']
            # An adopted next-session decision is observable before trading starts.
            fills = self.account_fills(account_id)
            if any(datetime.fromisoformat(x['occurred_at']) > at for x in fills):
                raise ValueError('current account contains fills later than requested observation')
            changes = self._connection.execute(
                'SELECT occurred_at FROM account_ledger WHERE account_id=? AND entry_type IN (?,?)',
                (account_id, 'SALE_SETTLEMENT', 'POSITION_ADJUSTMENT')).fetchall()
            if any(datetime.fromisoformat(x['occurred_at']) > at for x in changes):
                raise ValueError('current account contains adjustments later than requested observation')
            orders = {x['intent_id']: x for x in self.account_orders(account_id) if x['decision_id'] == decision_id}
            effects = []
            for intent in self.account_intents(account_id, decision_id):
                order = orders.pop(intent['intent_id'], None)
                record = intent if order is None else order
                if order is not None and any(order.get(name) and datetime.fromisoformat(order[name]) > at
                                             for name in ('report_applied_at', 'equity_report_at')):
                    raise ValueError('current decision contains order reports later than requested observation')
                status = str(record['status'])
                unknown = status in UNRESOLVED_INTENT_STATUSES
                terminal = status in (TERMINAL_INTENT_STATUSES if order is None else TERMINAL_ORDER_STATUSES)
                identity = intent['intent_id'] if order is None else order['channel_order_id']
                quantity = 0 if order is None else int(order['cumulative_filled_quantity'])
                reason = intent['payload'].get('termination_reason')
                if terminal and quantity < int(record['quantity']):
                    reason = reason or status
                effects.append(OrderExecutionEffect(identity, record['side'], int(record['quantity']), quantity,
                    status, not terminal, unknown, reason))
            if orders:
                raise ValueError('decision has a channel order without its owning intent')
            return decision_execution_effect(decision_id=decision_id, at=at,
                target_weight=evidence['target'], planning_result=evidence['planning_result'],
                actual_quantity=int(account['quantity']),
                cash=Decimal(account['cash'])+Decimal(account['frozen_cash']), available_cash=Decimal(account['cash']),
                receivable=Decimal(account['receivable']), valuation_price=valuation_price, orders=tuple(effects))
