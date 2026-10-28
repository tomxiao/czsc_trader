"""Explicit offline US channel using the normal durable order/fill lifecycle."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from .broker import BrokerOrderRejectedError, BrokerSubmissionUncertainError, OrderIntent, TERMINAL_ORDER_STATUSES
from .equity_contracts import EQUITY_OFFLINE_CHANNEL_ID, EquityOrderReport
from .lifecycle import IntentControlState


class EquityExecution:
    """Channel I/O boundary only; decisions and accounting remain AccountEngine/PaperStore."""
    def __init__(self, store, channel, *, now):
        if getattr(channel, "channel_id", None) != EQUITY_OFFLINE_CHANNEL_ID:
            raise ValueError("equity execution requires the explicit offline US channel")
        store._require_account_channel(EQUITY_OFFLINE_CHANNEL_ID)
        self.store, self.channel, self.now = store, channel, now

    def reconcile(self, *, cash: Decimal, quantity: int, account_id: str):
        account = self.store.virtual_account(account_id)
        if self.store.equity_account_rules(account_id) is None:
            raise ValueError("equity channel cannot reconcile a CN account")
        if type(cash) is not Decimal or not cash.is_finite() or cash < 0 or type(quantity) is not int or quantity < 0:
            raise ValueError("invalid independent channel snapshot")
        if cash != Decimal(account["cash"]) + Decimal(account["frozen_cash"]) or quantity != account["quantity"]:
            self.store.set_setting("channel_reconciliation_status", "BLOCKED")
            raise ValueError("channel snapshot differs from owning equity account")
        self.store.set_setting("channel_reconciliation_status", "OK")
        self.store.set_setting("futu_cash_reconciliation_status", "OK")

    def submit_pending(self, account_id):
        result = []
        for row in self.store.account_intents(account_id):
            if row["status"] != "PENDING_SUBMIT":
                continue
            if not self.store.claim_account_intent(row["intent_id"], moment=self.now()):
                continue
            intent = OrderIntent(row["intent_id"], row["decision_id"], row["symbol"], row["side"],
                row["quantity"], float(row["limit_price"]), row["payload"]["order_type"], "DAY", account_id)
            try:
                order = self.channel.place_order(intent)
            except BrokerOrderRejectedError:
                self.store.release_account_intent(row["intent_id"], "REJECTED")
                raise
            except Exception as exc:
                self.store.update_account_intent_status(row["intent_id"], IntentControlState.SUBMISSION_UNCERTAIN)
                raise BrokerSubmissionUncertainError("equity submission outcome requires reconciliation") from exc
            value = asdict(order)
            self.store.bind_channel_order(intent.intent_id, order.channel_order_id, value)
            result.append(order.channel_order_id)
        return tuple(result)

    def apply_report(self, report: EquityOrderReport):
        if type(report) is not EquityOrderReport:
            raise TypeError("equity execution requires a typed cumulative report")
        order = self.store.account_order(report.channel_order_id)
        if self.store.equity_account_rules(order["account_id"]) is None:
            raise ValueError("equity report belongs to a different market account")
        previous = int(order["cumulative_filled_quantity"])
        if order["status"] in TERMINAL_ORDER_STATUSES and (report.status != order["status"] or report.cumulative_quantity != previous):
            raise ValueError("terminal equity order cannot change without explicit reconciliation")
        last_report = order.get("equity_report_at")
        if last_report is not None and report.occurred_at < datetime.fromisoformat(last_report):
            raise ValueError("equity channel event time cannot move backwards")
        decision = self.store.account_decision(order["account_id"],order["decision_id"])["payload"]
        interval = decision["equity_execution_interval"]
        start, end = (datetime.fromisoformat(interval[k]) for k in ("start","end"))
        if report.occurred_at < start or (report.cumulative_quantity > previous and report.occurred_at >= end):
            raise ValueError("equity fill event is outside its order interval")
        if report.cumulative_quantity < previous:
            raise ValueError("equity cumulative report cannot decrease")
        if report.cumulative_quantity == previous and previous and report.average_price != Decimal(str(order["average_fill_price"])):
            raise ValueError("same cumulative equity fill carries different price")
        if report.status == "FILLED_ALL" and report.cumulative_quantity != int(order["quantity"]):
            raise ValueError("fully filled status differs from ordered quantity")
        if report.status == "FILLED_PART" and not 0 < report.cumulative_quantity < int(order["quantity"]):
            raise ValueError("partial status requires a strict partial quantity")
        with self.store.atomic_decision_update():
            fill = self.store.apply_fill_increment(report.channel_order_id,
                cumulative_quantity=report.cumulative_quantity, average_price=report.average_price,
                occurred_at=report.occurred_at.isoformat(),
                settlement_at=None if report.settlement_at is None else report.settlement_at.isoformat())
            payload = dict(self.store.account_order(report.channel_order_id))
            payload.update(status=report.status, cumulative_filled_quantity=report.cumulative_quantity,
                           average_fill_price=str(report.average_price), updated_at=report.occurred_at.isoformat(),
                           equity_report_at=report.occurred_at.isoformat())
            self.store.update_channel_order_report(report.channel_order_id, payload)
        return fill
