"""Explicit offline CN/US channel using the normal durable order/fill lifecycle."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from .broker import BrokerOrderRejectedError, BrokerSubmissionUncertainError, OrderIntent, TERMINAL_ORDER_STATUSES
from .equity_contracts import EQUITY_OFFLINE_CHANNELS, EquityOrderReport, EquityReconciliationError
from .lifecycle import IntentControlState
from .order_reports import apply_order_report


class EquityExecution:
    """Channel I/O boundary only; decisions and accounting remain AccountEngine/PaperStore."""
    def __init__(self, store, channel, *, now):
        if getattr(channel, "channel_id", None) not in EQUITY_OFFLINE_CHANNELS:
            raise ValueError("equity execution requires the explicit offline CN/US channel")
        store._require_account_channel(channel.channel_id)
        self.store, self.channel, self.now = store, channel, now

    def reconcile(self, *, cash: Decimal, quantity: int, account_id: str):
        account = self.store.virtual_account(account_id)
        if account["channel_id"] != self.channel.channel_id:
            raise ValueError("equity account belongs to another channel")
        if self.store.equity_account_rules(account_id) is None:
            raise ValueError("equity channel cannot reconcile a CN account")
        if type(cash) is not Decimal or not cash.is_finite() or cash < 0 or type(quantity) is not int or quantity < 0:
            raise ValueError("invalid independent channel snapshot")
        if cash != Decimal(account["cash"]) + Decimal(account["frozen_cash"]) or quantity != account["quantity"]:
            self.store.set_setting("channel_reconciliation_status", "BLOCKED")
            raise EquityReconciliationError("channel snapshot differs from owning equity account")
        self.store.set_setting("channel_reconciliation_status", "OK")
        self.store.set_setting("futu_cash_reconciliation_status", "OK")

    def submit_pending(self, account_id):
        if self.store.virtual_account(account_id)["channel_id"] != self.channel.channel_id:
            raise ValueError("equity account belongs to another channel")
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
        if self.store.virtual_account(order["account_id"])["channel_id"] != self.channel.channel_id:
            raise ValueError("equity report belongs to another channel")
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
        payload = dict(order)
        payload.update(status=report.status, cumulative_filled_quantity=report.cumulative_quantity,
                       average_fill_price=str(report.average_price), updated_at=report.occurred_at.isoformat(),
                       equity_report_at=report.occurred_at.isoformat())
        return apply_order_report(self.store, payload, occurred_at=report.occurred_at.isoformat(),
            settlement_at=None if report.settlement_at is None else report.settlement_at.isoformat())
