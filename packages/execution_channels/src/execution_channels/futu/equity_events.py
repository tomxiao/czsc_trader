"""Broker quantity reconciliation and trade settlement in the owning ledger."""
from datetime import datetime
from decimal import Decimal
import json
from uuid import NAMESPACE_URL, uuid5


def allocate_quantities(weights, total):
    """Largest remainder allocation, with stable identity ordering for ties."""
    if type(total) is not int or total < 0 or any(type(v) is not int or v < 0 for v in weights.values()):
        raise ValueError('position allocation requires nonnegative integer quantities')
    denominator = sum(weights.values())
    if denominator == 0:
        if total:
            raise ValueError('broker position has no confirmed account owner')
        return {key: 0 for key in weights}
    result = {key: value * total // denominator for key, value in weights.items()}
    remaining = total - sum(result.values())
    ranked = sorted(weights, key=lambda key: (-(weights[key] * total % denominator), key))
    for key in ranked[:remaining]:
        result[key] += 1
    return result


class EquityEventStore:
    def require_no_pending_dividend(self, account_id: str) -> None:
        """Reject migration of an unsettled legacy nontrade receivable."""
        self.virtual_account(account_id)
        with self._lock:
            rows = self._connection.execute(
                'SELECT payload FROM equity_account_events WHERE account_id=?', (account_id,)).fetchall()
        for row in rows:
            event = json.loads(row['payload'])
            if event.get('recognized_kind') == 'CASH_DIVIDEND' and not event['paid'] and Decimal(event['amount']):
                raise ValueError(f'{account_id}: unsettled legacy dividend requires ledger reconciliation')

    def reconcile_equity_positions(self, symbol, *, quantity: int, at: datetime):
        """Align a confirmed broker holding without attributing its cause."""
        from .broker import TERMINAL_INTENT_STATUSES
        from .equity_account_state import record_v4_position_reconciliation
        if type(at) is not datetime or at.utcoffset() is None:
            raise ValueError('position reconciliation requires an aware timestamp')
        if type(quantity) is not int or quantity < 0:
            raise ValueError('broker quantity must be a nonnegative integer')
        with self._lock, self._write_context(False):
            accounts = sorted((a for a in self.strategy_virtual_accounts()
                if a['symbol'] == symbol and a.get('run_state') != 'RETIRED'), key=lambda a: a['account_id'])
            before = {a['account_id']: int(a['quantity']) for a in accounts}
            if sum(before.values()) == quantity:
                return ()
            if not accounts or sum(before.values()) == 0:
                raise ValueError('broker position has no confirmed account owner')
            if any(intent['status'] not in TERMINAL_INTENT_STATUSES for a in accounts
                   for intent in self.account_intents(a['account_id'])):
                raise ValueError('position difference requires confirmation of every outstanding order')
            if self.account_invariant_violations():
                raise ValueError('position reconciliation requires consistent existing ledgers')
            allocated = allocate_quantities(before, quantity)
            changed = []
            for account in accounts:
                account_id = account['account_id']
                old, new = before[account_id], allocated[account_id]
                if old == new:
                    continue
                # Preserve acquisition cost. An unknown adjustment is never a
                # sale, a fill, or realized trading profit.
                cost = Decimal(account['average_cost']) * old / new if new else Decimal(0)
                event_id = 'position:' + str(uuid5(NAMESPACE_URL,
                    f'{account_id}:{at.isoformat()}:{old}:{new}'))
                ledger_id = str(uuid5(NAMESPACE_URL, f'equity-event:{account_id}:{event_id}'))
                event = {'ledger_entry_id': ledger_id, 'recognized_kind': 'POSITION_ADJUSTMENT',
                    'reason': 'UNKNOWN', 'receivable_delta': '0', 'broker_quantity': quantity,
                    'quantity_before': old, 'quantity_after': new, 'occurred_at': at.isoformat()}
                target = account.get('cycle_target')
                target = None if target is None or not new else int(target) * new // old
                cycle_json = account.get('entry_cycle_json')
                if cycle_json is not None:
                    from dataclasses import replace
                    from ..entry_cycle import EntryCycleState
                    cycle = EntryCycleState.from_dict(json.loads(cycle_json))
                    cycle_json = (json.dumps(replace(cycle, target_quantity=cycle.target_quantity * new // old).to_dict())
                        if new else None)
                self._connection.execute('UPDATE virtual_accounts SET quantity=?,average_cost=?,cycle_target=?,entry_cycle_json=?,updated_at=? WHERE account_id=?',
                    (new, str(cost), target, cycle_json, at.isoformat(), account_id))
                self._equity_ledger(account_id, event_id, 'POSITION_ADJUSTMENT', Decimal(0), new-old,
                    Decimal(account['cash']), new, at)
                self._connection.execute('INSERT INTO equity_account_events VALUES(?,?,?)',
                    (account_id, event_id, json.dumps(event, sort_keys=True)))
                record_v4_position_reconciliation(self, account_id, quantity_before=old, quantity_after=new, at=at)
                changed.append(event | {'account_id': account_id})
            return tuple(changed)

    def settle_equity_receivables(self, account_id, *, at):
        """Settle sales only; nontrade cash uses channel reconciliation."""
        if type(at) is not datetime or at.utcoffset() is None:
            raise ValueError('settlement requires aware timestamp')
        with self._lock, self._write_context(False):
            if self.equity_account_rules(account_id) is None:
                raise ValueError('settlement requires an admitted equity account')
            self.require_no_pending_dividend(account_id)
            account = self.virtual_account(account_id)
            cash, receivable = Decimal(account['cash']), Decimal(account['receivable'])
            count = 0
            rows = self._connection.execute('SELECT event_id,payload FROM equity_account_events WHERE account_id=? ORDER BY event_id',
                (account_id,)).fetchall()
            for row in rows:
                event = json.loads(row['payload'])
                if event.get('kind') != 'RECEIVABLE' or event['paid'] or datetime.fromisoformat(event['pay_at']) > at:
                    continue
                if 'definition' in event or event.get('recognized_kind') == 'CASH_DIVIDEND':
                    raise ValueError('nontrade receivable is outside trade settlement')
                amount = Decimal(event['amount'])
                if amount > receivable:
                    raise ValueError('payment exceeds account receivable')
                cash += amount
                receivable -= amount
                event['paid'] = True
                self._connection.execute('UPDATE equity_account_events SET payload=? WHERE account_id=? AND event_id=?',
                    (json.dumps(event, sort_keys=True), account_id, row['event_id']))
                payment_id = row['event_id'] + ':payment'
                self._equity_ledger(account_id, payment_id, 'SALE_SETTLEMENT', amount, 0,
                    cash, int(account['quantity']), datetime.fromisoformat(event['pay_at']))
                payment = {'ledger_entry_id': str(uuid5(NAMESPACE_URL, f'equity-event:{account_id}:{payment_id}')),
                    'recognized_kind': 'SALE_SETTLEMENT', 'reason': 'TRADE_SETTLEMENT', 'receivable_delta': str(-amount)}
                self._connection.execute('INSERT INTO equity_account_events VALUES(?,?,?)',
                    (account_id, payment_id, json.dumps(payment, sort_keys=True)))
                count += 1
            self._connection.execute('UPDATE virtual_accounts SET cash=?,receivable=? WHERE account_id=?',
                (str(cash), str(receivable), account_id))
            return count

    def _equity_ledger(self, account_id, event_id, kind, cash_delta, quantity_delta, cash, quantity, at):
        self._connection.execute('INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,'
            'cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (str(uuid5(NAMESPACE_URL, f'equity-event:{account_id}:{event_id}')), account_id, kind, None, None,
             str(cash_delta), '0', quantity_delta, '0', str(cash), quantity, at.isoformat()))
