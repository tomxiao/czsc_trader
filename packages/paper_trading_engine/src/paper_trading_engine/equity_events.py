"""Durable account-owned equity events, sharing PaperStore transactions/ledger."""
from datetime import datetime
from decimal import Decimal
import json
from uuid import NAMESPACE_URL, uuid5


class EquityEventStore:
    def apply_equity_event(self, account_id, *, event_id, kind, effective_at, available_at,
                           source_sha256, ratio=None, cash_per_share=None, pay_at=None):
        import re
        if not event_id or kind not in {"SPLIT", "CASH_DIVIDEND"}:
            raise ValueError("unsupported equity event")
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("equity event requires source content identity")
        if any(type(t) is not datetime or t.utcoffset() is None for t in (effective_at, available_at)):
            raise ValueError("equity event timestamps must be aware")
        if available_at > effective_at:
            raise ValueError("equity event was unavailable at its effective time")
        definition = {"kind": kind, "effective_at": effective_at.isoformat(), "available_at": available_at.isoformat(),
                      "source_sha256": source_sha256, "ratio": None if ratio is None else str(ratio),
                      "cash_per_share": None if cash_per_share is None else str(cash_per_share),
                      "pay_at": None if pay_at is None else pay_at.isoformat()}
        with self._lock, self._write_context(False):
            if self.equity_account_rules(account_id) is None:
                raise ValueError("equity event requires a US account")
            previous = self._connection.execute("SELECT payload FROM equity_account_events WHERE account_id=? AND event_id=?",
                                                (account_id, event_id)).fetchone()
            if previous:
                if json.loads(previous[0]).get("definition") != definition:
                    raise ValueError("equity event identity was reused with different facts")
                return False
            times = [datetime.fromisoformat(row[0]) for row in self._connection.execute(
                "SELECT occurred_at FROM fills WHERE account_id=?",(account_id,))]
            for row in self._connection.execute("SELECT payload FROM equity_account_events WHERE account_id=?",(account_id,)):
                prior = json.loads(row[0]).get("definition")
                if prior is not None:
                    times.append(datetime.fromisoformat(prior["effective_at"]))
            if times and effective_at < max(times):
                raise ValueError("equity event cannot be applied behind confirmed account events")
            account = self.virtual_account(account_id)
            quantity, cash = int(account["quantity"]), Decimal(account["cash"])
            cost, receivable = Decimal(account["average_cost"]), Decimal(account["receivable"])
            assets, realized = Decimal(account["total_assets"]), Decimal(account["realized_pnl"])
            old_quantity, old_cash = quantity, cash
            if kind == "SPLIT":
                from .broker import TERMINAL_INTENT_STATUSES
                if any(x["status"] not in TERMINAL_INTENT_STATUSES for x in self.account_intents(account_id)):
                    raise ValueError("split requires reconciliation of outstanding channel orders")
                multiplier = Decimal(str(ratio))
                if not multiplier.is_finite() or multiplier <= 0 or quantity * multiplier != (quantity * multiplier).to_integral_value():
                    raise ValueError("split has invalid ratio or unsupported fractional entitlement")
                quantity = int(quantity * multiplier)
                cost /= multiplier
                result = {"definition": definition}
            else:
                per_share = Decimal(str(cash_per_share))
                if (not per_share.is_finite() or per_share < 0 or type(pay_at) is not datetime
                        or pay_at.utcoffset() is None or pay_at < effective_at):
                    raise ValueError("cash dividend requires nonnegative amount and payment time")
                amount = per_share * quantity
                assets += amount
                realized += amount
                if pay_at == effective_at:
                    cash += amount
                else:
                    receivable += amount
                result = {"definition": definition, "kind": "RECEIVABLE", "amount": str(amount),
                          "pay_at": pay_at.isoformat(), "paid": pay_at == effective_at}
            self._connection.execute("INSERT INTO equity_account_events VALUES(?,?,?)",
                                     (account_id, event_id, json.dumps(result, sort_keys=True)))
            self._connection.execute("UPDATE virtual_accounts SET quantity=?,cash=?,average_cost=?,receivable=?,"
                "total_assets=?,realized_pnl=? WHERE account_id=?",
                (quantity, str(cash), str(cost), str(receivable), str(assets), str(realized), account_id))
            self._equity_ledger(account_id, event_id, kind, cash - old_cash, quantity - old_quantity,
                                cash, quantity, effective_at)
            return True

    def settle_equity_receivables(self, account_id, *, at):
        if type(at) is not datetime or at.utcoffset() is None:
            raise ValueError("settlement requires aware timestamp")
        with self._lock, self._write_context(False):
            if self.equity_account_rules(account_id) is None:
                raise ValueError("settlement requires a US account")
            account = self.virtual_account(account_id)
            cash, receivable = Decimal(account["cash"]), Decimal(account["receivable"])
            count = 0
            rows = self._connection.execute("SELECT event_id,payload FROM equity_account_events WHERE account_id=? ORDER BY event_id",
                                            (account_id,)).fetchall()
            for row in rows:
                event = json.loads(row["payload"])
                if event.get("kind") != "RECEIVABLE" or event["paid"] or datetime.fromisoformat(event["pay_at"]) > at:
                    continue
                amount = Decimal(event["amount"])
                if amount > receivable:
                    raise ValueError("payment exceeds account receivable")
                cash += amount
                receivable -= amount
                event["paid"] = True
                self._connection.execute("UPDATE equity_account_events SET payload=? WHERE account_id=? AND event_id=?",
                    (json.dumps(event, sort_keys=True), account_id, row["event_id"]))
                self._equity_ledger(account_id, row["event_id"] + ":payment", "EQUITY_PAYMENT", amount, 0,
                                    cash, int(account["quantity"]), datetime.fromisoformat(event["pay_at"]))
                count += 1
            self._connection.execute("UPDATE virtual_accounts SET cash=?,receivable=? WHERE account_id=?",
                                     (str(cash), str(receivable), account_id))
            return count

    def _equity_ledger(self, account_id, event_id, kind, cash_delta, quantity_delta, cash, quantity, at):
        self._connection.execute("INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
            "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid5(NAMESPACE_URL, f"equity-event:{account_id}:{event_id}")), account_id, kind, None, None,
             str(cash_delta), "0", quantity_delta, "0", str(cash), quantity, at.isoformat()))
