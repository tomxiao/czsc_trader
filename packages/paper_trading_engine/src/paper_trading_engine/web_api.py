"""Resource-scoped read model for the PTE operations console."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from .audit import AuditCategory, AuditOutcome, AuditSeverity, EVENT_CATALOG
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID, STRATEGY_ACCOUNT_TYPE
from .trading_window import SHANGHAI


class ResourceNotFound(KeyError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _descending_transaction_rows(
    rows: list[dict[str, object]], *, time_field: str, id_field: str,
) -> list[dict[str, object]]:
    """Give every account-table a stable newest-transaction-first order."""
    def key(row: dict[str, object]) -> tuple[float, str]:
        value = row.get(time_field)
        try:
            moment = datetime.fromisoformat(str(value))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=SHANGHAI)
            stamp = moment.astimezone(timezone.utc).timestamp()
        except (TypeError, ValueError):
            stamp = float("-inf")
        return stamp, str(row.get(id_field) or "")

    return sorted(rows, key=key, reverse=True)


def _is_stale(value: str | None, *, seconds: float) -> bool:
    if not value:
        return True
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        return True
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=SHANGHAI)
    return (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() > seconds


class PteWebApi:
    def __init__(self, operations) -> None:
        self.operations = operations
        self.store = operations.store
        self.virtual = operations.virtual
        self.channel = operations.channel

    def _account_chart_error(self, account_id: str) -> str | None:
        chart = getattr(self.operations, "account_chart", None)
        if chart is None or not hasattr(chart, "current_error"):
            return None
        return chart.current_error(account_id)

    def health(self) -> dict[str, object]:
        heartbeat = self.store.get_setting("scheduler_heartbeat_at")
        return {
            "runtime": "RUNNING",
            "watchdog_healthy": not _is_stale(heartbeat, seconds=45),
            "scheduler_heartbeat_at": heartbeat,
            "release": dict(getattr(self.operations, "runtime_identity", {})),
        }

    def system_status(self) -> dict[str, object]:
        channel = self.channel_snapshot(FUTU_SIMULATE_CN_CHANNEL_ID)
        failures = channel.get("scheduler_failures", self.store.operation_failures())
        alerts = list(channel.get("alerts", []))
        accounts = [
            row for row in self.store.strategy_virtual_accounts()
            if row.get("run_state") != "RETIRED"
        ]
        prepared_by_account = {
            str(row["account_id"]): self.store.get_setting(
                f"last_data_prepare_date:{row['account_id']}"
            )
            for row in accounts
        }
        decided_by_account = {
            str(row["account_id"]): self.store.get_setting(
                f"last_account_decision_date:{row['account_id']}"
            )
            for row in accounts
        }
        errors = {
            str(row["account_id"]): self.store.get_setting(
                f"data_preparation_error:{row['account_id']}"
            )
            for row in accounts
        }
        if any(errors.values()):
            alerts.append("DATA_PREPARATION_FAILED")
        if any(row.get("health") == "BLOCKED" for row in accounts):
            alerts.append("VIRTUAL_ACCOUNT_BLOCKED")
        if self.store.unresolved_account_intents():
            alerts.append("ORDER_SUBMISSION_UNRESOLVED")
        if any(
            self._account_chart_error(row["account_id"])
            for row in self.store.strategy_virtual_accounts()
        ):
            alerts.append("ACCOUNT_CHART_UNAVAILABLE")
        heartbeat = self.store.get_setting("scheduler_heartbeat_at")
        scheduler_stalled = _is_stale(heartbeat, seconds=45)
        if scheduler_stalled:
            alerts.append("SCHEDULER_STALLED")
        if any(
            prepared_by_account[account_id]
            and prepared_by_account[account_id] != decided_by_account[account_id]
            for account_id in prepared_by_account
        ):
            alerts.append("DECISION_GENERATION_OVERDUE")
        cutoffs = [value for value in prepared_by_account.values() if value]
        prepared_through = min(cutoffs) if cutoffs else None
        data_identities = {
            account_id: self.store.get_setting(f"last_prepared_data_id:{account_id}")
            for account_id in prepared_by_account
        }
        preparation_times = [
            value
            for account_id in prepared_by_account
            if (value := self.store.get_setting(f"last_data_preparation:{account_id}"))
        ]
        alerts = list(dict.fromkeys(alerts))
        channel_alerts = channel.get("alerts", [])
        return {
            "scope": {"system": "pte"},
            "as_of": _now(),
            "runtime": "RUNNING",
            "watchdog_healthy": not scheduler_stalled,
            "scheduler_heartbeat_at": heartbeat,
            "release": dict(getattr(self.operations, "runtime_identity", {})),
            "data_cutoff": prepared_through,
            "prepared_data_ids": json.dumps(data_identities, sort_keys=True),
            "last_data_preparation": max(preparation_times) if preparation_times else None,
            "scheduler_failures": failures,
            "futu_connection": (
                "UNAVAILABLE"
                if "CHANNEL_UNAVAILABLE" in channel_alerts
                else "DEGRADED"
                if channel.get("reconciliation_status") != "OK" or channel_alerts
                else "CONNECTED"
            ),
            "alerts": alerts,
            "events": [
                event for event in self.store.recent_events(200)
                if event["category"] == AuditCategory.SYSTEM
            ],
        }

    def audit_events(self, filters: dict[str, str]) -> dict[str, object]:
        allowed = {
            "category", "event_type", "severity", "outcome", "account_id",
            "strategy_id", "channel", "decision_id", "order_id", "correlation_id",
            "before_id", "limit",
        }
        unknown = sorted(set(filters) - allowed)
        if unknown:
            raise ValueError(f"unknown audit filter: {unknown[0]}")
        enum_filters = {
            "category": AuditCategory,
            "severity": AuditSeverity,
            "outcome": AuditOutcome,
        }
        for name, enum_type in enum_filters.items():
            value = filters.get(name)
            if value:
                try:
                    enum_type(value)
                except ValueError as exc:
                    raise ValueError(f"invalid audit {name}: {value}") from exc
        event_type = filters.get("event_type")
        if event_type and event_type not in EVENT_CATALOG:
            raise ValueError(f"invalid audit event_type: {event_type}")
        query = dict(filters)
        for name in ("before_id", "limit"):
            if name in query:
                try:
                    query[name] = int(query[name])
                except ValueError as exc:
                    raise ValueError(f"audit event {name} must be an integer") from exc
        events = self.store.query_audit_events(**query)
        count_query = {
            key: value for key, value in query.items()
            if key not in {"category", "before_id", "limit"}
        }
        limit = int(query.get("limit", 50))
        return {
            "scope": {"resource": "audit_events", **{
                key: value for key, value in filters.items()
                if key not in {"before_id", "limit"}
            }},
            "as_of": _now(),
            "events": events,
            "category_counts": self.store.audit_event_counts(**count_query),
            "next_before_id": events[-1]["id"] if len(events) == limit else None,
        }

    def virtual_accounts(self) -> dict[str, object]:
        accounts = []
        for row in self.store.strategy_virtual_accounts():
            status = self.virtual.status(row["account_id"])
            decision = status.get("last_decision") or {}
            chart_error = self._account_chart_error(row["account_id"])
            accounts.append({
                "account_id": row["account_id"], "name": row["name"],
                "strategy_id": row["strategy_id"],
                "symbol": row["symbol"],
                "release_id": f'{row["strategy_id"]}-{row["strategy_version"]}',
                "release_hash": row["release_hash"], "run_state": row["run_state"],
                "health": row["health"], "total_assets": row["total_assets"],
                "quantity": row["quantity"], "latest_action": decision.get("action"),
                "alert_count": int(bool(row.get("last_error"))) + int(bool(chart_error)),
            })
        return {
            "scope": {"resource": "virtual_accounts"}, "as_of": _now(),
            "default_account_id": accounts[0]["account_id"] if accounts else None,
            "accounts": accounts,
        }

    def virtual_account_snapshot(self, account_id: str) -> dict[str, object]:
        try:
            if account_id not in {
                row["account_id"] for row in self.store.strategy_virtual_accounts()
            }:
                raise ResourceNotFound(account_id)
            status = self.virtual.status(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        strategy_id = status.get("strategy_id")
        version = status.get("strategy_version")
        release_id = f"{strategy_id}-{version}"
        account_keys = {
            "account_id", "name", "strategy_id", "strategy_name_snapshot", "strategy_version",
            "release_hash", "qualification_snapshot", "symbol", "initial_cash", "cash",
            "frozen_cash", "total_assets", "quantity", "average_cost", "realized_pnl",
            "cycle_target", "run_state", "observation_start", "last_settlement_session", "health",
            "last_error", "channel_id", "created_at", "updated_at",
            "selection_data_cutoff", "released_cash",
        }
        events = self.store.query_audit_events(account_id=account_id, limit=200)
        chart_error = self._account_chart_error(account_id)
        metrics = dict(status.get("metrics", {}))
        initial_cash = float(status["initial_cash"])
        ending_assets = status["released_cash"] if status.get("run_state") == "RETIRED" else status["total_assets"]
        metrics["current_total_return"] = (
            float(ending_assets) / initial_cash - 1 if initial_cash else None
        )
        account_alerts = []
        if status.get("last_error"):
            account_alerts.append({"code": "ACCOUNT_BLOCKED", "message": status["last_error"]})
        if chart_error:
            account_alerts.append({"code": "ACCOUNT_CHART_UNAVAILABLE", "message": chart_error})
        decision = status.get("last_decision")
        if decision:
            row = self.store.account_decision(account_id, decision["decision_id"])
            decision = {
                **decision,
                **{key: row[key] for key in (
                    "status", "state_reason", "state_changed_at", "state_events",
                )},
            }
        return {
            "scope": {"account_id": account_id, "strategy_id": strategy_id,
                      "release_id": release_id, "release_hash": status.get("release_hash")},
            "as_of": _now(),
            "account": {key: status.get(key) for key in account_keys},
            "decision": decision,
            "orders": _descending_transaction_rows(
                [row for row in status.get("orders", []) if row.get("account_id") == account_id],
                time_field="created_at", id_field="channel_order_id",
            ),
            "intents": _descending_transaction_rows(
                self.store.account_intents(account_id), time_field="created_at", id_field="intent_id",
            ),
            "fills": _descending_transaction_rows(
                [row for row in status.get("fills", []) if row.get("account_id") == account_id],
                time_field="occurred_at", id_field="fill_id",
            ),
            "metrics": metrics,
            "alerts": account_alerts,
            "events": events,
        }

    def virtual_account_chart(self, account_id: str) -> dict[str, object]:
        try:
            self.store.virtual_account(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        if self.operations.account_chart is None:
            raise ResourceNotFound(account_id)
        return self.operations.account_chart.status(account_id)

    def refresh_virtual_account_chart(self, account_id: str) -> dict[str, object]:
        try:
            self.store.virtual_account(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        if self.operations.account_chart is None:
            raise ResourceNotFound(account_id)
        return self.operations.account_chart.refresh(account_id)

    def virtual_account_chart_path(
        self, account_id: str, fingerprint: str | None = None,
    ):
        try:
            self.store.virtual_account(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        if self.operations.account_chart is None:
            raise ResourceNotFound(account_id)
        return self.operations.account_chart.chart_path(account_id, fingerprint)

    def channel_snapshot(self, channel: str) -> dict[str, object]:
        if channel != FUTU_SIMULATE_CN_CHANNEL_ID:
            raise ResourceNotFound(channel)
        status = self.channel.status()
        events = self.store.query_audit_events(channel=FUTU_SIMULATE_CN_CHANNEL_ID, limit=200)
        accounts = [
            {
                "account_id": row["account_id"], "name": row["name"],
                "release_id": f'{row["strategy_id"]}-{row["strategy_version"]}',
                "symbol": row["symbol"], "asset_type": row["asset_type"],
                "initial_cash": row["initial_cash"], "cash": row["cash"],
                "frozen_cash": row["frozen_cash"], "total_assets": row["total_assets"],
                "quantity": row["quantity"],
                "run_state": row["run_state"],
                "health": row["health"], "last_error": row["last_error"],
            }
            for row in self.store.virtual_accounts()
            if row.get("channel_id") == FUTU_SIMULATE_CN_CHANNEL_ID
            and row.get("account_type", STRATEGY_ACCOUNT_TYPE) == STRATEGY_ACCOUNT_TYPE
        ]
        channel_accounts = [
            row for row in self.store.virtual_accounts()
            if row.get("channel_id") == FUTU_SIMULATE_CN_CHANNEL_ID
            and row.get("run_state") != "RETIRED"
        ]
        pool = self.store.capital_pool_balance()
        capital_pool = float(pool.registered_capital)
        allocated = float(pool.allocated_capital)
        strategy_allocated = sum(float(row["initial_cash"]) for row in accounts if row["run_state"] != "RETIRED")
        unallocated = float(pool.unallocated_cash)
        # PTE reserves cash before a future-session order reaches Futu.  The
        # reservation changes the virtual account's available cash, but the
        # money is still present in the shared broker account.  Include both
        # available and internally frozen cash when reconciling with Futu.
        logical_cash = unallocated + sum(
            float(row["cash"]) + float(row["frozen_cash"]) for row in channel_accounts
        )
        logical_total_assets = unallocated + sum(
            float(row["total_assets"]) for row in channel_accounts
        )
        broker_account = status.get("account") or {}
        broker_cash = broker_account.get("cash")
        broker_total_assets = broker_account.get("total_assets")
        cash_difference = (
            float(broker_cash) - logical_cash if broker_cash is not None else None
        )
        asset_difference = (
            float(broker_total_assets) - logical_total_assets
            if broker_total_assets is not None else None
        )
        alerts = list(status.get("alerts", []))
        if cash_difference is not None and abs(cash_difference) > 0.01:
            alerts.append("CHANNEL_CASH_MISMATCH")
        return {
            "scope": {"channel": FUTU_SIMULATE_CN_CHANNEL_ID, "account_type": "broker_simulation"},
            "as_of": _now(),
            "account": status.get("account"), "actual_quantity": status.get("actual_quantity"),
            "accounts": accounts,
            "capital_pool": capital_pool,
            "recovered_pnl": float(pool.recovered_pnl),
            "allocated_capital": allocated,
            "strategy_allocated_capital": strategy_allocated,
            "unallocated_capital": unallocated,
            "logical_cash": logical_cash,
            "logical_total_assets": logical_total_assets,
            "cash_difference": cash_difference,
            "asset_difference": asset_difference,
            "last_reconcile_at": status.get("last_reconcile_at") or self.store.get_setting("last_reconcile_at"),
            "orders": status.get("orders", []), "fills": self.store.account_fills(),
            "paused": status.get("paused"),
            "reconciliation_status": status.get("reconciliation_status"),
            "reconciliation_account": self.store.channel_reconciliation_account(
                FUTU_SIMULATE_CN_CHANNEL_ID
            ),
            "connection_error": status.get("channel_error"), "alerts": list(dict.fromkeys(alerts)),
            "scheduler_failures": status.get("scheduler_failures", []), "events": events,
        }

    def comparison(self, account_ids: list[str]) -> dict[str, object]:
        known = {row["account_id"] for row in self.store.strategy_virtual_accounts()}
        selected = list(dict.fromkeys(account_ids)) if account_ids else sorted(known)
        missing = next((item for item in selected if item not in known), None)
        if missing:
            raise ResourceNotFound(missing)
        statuses = [self.virtual.status(account_id) for account_id in selected]
        accounts = []
        for status in statuses:
            accounts.append({"account_id": status["account_id"], "name": status["name"],
                             "release_id": f'{status["strategy_id"]}-{status["strategy_version"]}',
                             "metrics": status["metrics"]})
        return {
            "scope": {"resource": "comparison"}, "as_of": _now(),
            "metric_basis": "ACCOUNT_OBSERVATION_WINDOW",
            "priority_metrics": ["maximum_drawdown", "calmar_ratio", "win_loss_ratio", "total_return"],
            "accounts": accounts,
        }
