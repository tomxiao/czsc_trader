"""Resource-scoped read model for the PTE operations console."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json

from .lifecycle import AccountHealth
from .audit import AuditCategory, AuditOutcome, AuditSeverity, EVENT_CATALOG
from .channel import FUTU_SIMULATE_CN_CHANNEL_ID, STRATEGY_ACCOUNT_TYPE, channel_profile
from .channel_accounts import DEFAULT_CHANNEL_ACCOUNT
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
    def __init__(self, operations, *, multichannel_runtime=None) -> None:
        self.operations = operations
        self.store = operations.store
        self.virtual = operations.virtual
        self.channel = operations.channel
        self.runtime = multichannel_runtime

    def _channel_services(self, channel_account_id: str):
        if self.runtime is None or channel_account_id not in self.runtime.services:
            raise ResourceNotFound(channel_account_id)
        return self.runtime.services[channel_account_id]

    @staticmethod
    def _validate_market(market: str | None) -> None:
        if market not in (None, "CN", "US"):
            raise ValueError("market must be CN or US")

    @property
    def _root_store(self):
        return self.store if self.runtime is None else self.runtime.store

    def channel_accounts(self, market: str | None = None) -> dict[str, object]:
        self._validate_market(market)
        rows = self._root_store.channel_accounts()
        return {"channels": [{key: row[key] for key in ("channel_account_id", "channel_id", "market", "currency")}
                             for row in rows if market is None or row["market"] == market]}

    def _account_rows(self, market: str | None):
        self._validate_market(market)
        return [row for row in self._root_store.strategy_virtual_accounts()
                if market is None or channel_profile(row["channel_id"]).market == market]

    def _account_chart_error(self, account_id: str) -> str | None:
        chart = getattr(self.runtime or self.operations, "account_chart", None)
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

    def system_status(self, market: str | None = None) -> dict[str, object]:
        if market is not None:
            return self._market_system_status(market)
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
        if any(row["health"] == AccountHealth.BLOCKED for row in accounts):
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

    def _market_system_status(self, market: str) -> dict[str, object]:
        channels = self.channel_accounts(market)["channels"]
        accounts = self._account_rows(market)
        root = self._root_store
        channel_ids = {row["channel_account_id"] for row in channels}
        active_accounts = {row["account_id"]: row for row in accounts if row["run_state"] != "RETIRED"}
        alerts = []
        for channel_id in sorted(channel_ids):
            channel = self.channel_account_snapshot(channel_id, include_activity=False)
            alerts.extend({"code": code, "channel_account_id": channel_id, "message": channel.get("connection_error")}
                          for code in channel["alerts"])
        for account_id, row in active_accounts.items():
            chart_error = self._account_chart_error(account_id)
            if row.get("last_error"):
                alerts.append({"code": "VIRTUAL_ACCOUNT_BLOCKED", "account_id": account_id, "message": row["last_error"]})
            if chart_error:
                alerts.append({"code": "ACCOUNT_CHART_UNAVAILABLE", "account_id": account_id, "message": chart_error})
        for intent in root.unresolved_account_intents():
            if intent["account_id"] in active_accounts:
                alerts.append({"code": "ORDER_SUBMISSION_UNRESOLVED", "account_id": intent["account_id"],
                               "intent_id": intent["intent_id"]})
        health = self.health()
        if not health["watchdog_healthy"]:
            alerts.append({"code": "SCHEDULER_STALLED"})
        failures = [row for row in root.operation_failures()
                    if ":" not in row["operation"] or row["operation"].partition(":")[2] in active_accounts.keys() | channel_ids]
        return {"scope": {"system": "pte", "market": market}, "as_of": _now(), **health,
                "alerts": alerts, "scheduler_failures": failures,
                "events": root.query_audit_events(category=AuditCategory.SYSTEM, market=market, limit=50)}

    def audit_events(self, filters: dict[str, str]) -> dict[str, object]:
        allowed = {
            "category", "event_type", "severity", "outcome", "account_id",
            "strategy_id", "channel", "decision_id", "order_id", "correlation_id",
            "before_id", "limit", "channel_account_id", "market",
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
        channel_account_id = query.pop("channel_account_id", None)
        market = query.get("market")
        self._validate_market(market)
        store = self._root_store if market is not None else self.store
        if channel_account_id is not None:
            store = self._channel_services(channel_account_id).store
        for name in ("before_id", "limit"):
            if name in query:
                try:
                    query[name] = int(query[name])
                except ValueError as exc:
                    raise ValueError(f"audit event {name} must be an integer") from exc
        events = store.query_audit_events(**query)
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
            "category_counts": store.audit_event_counts(**count_query),
            "next_before_id": events[-1]["id"] if len(events) == limit else None,
        }

    def virtual_accounts(self, market: str | None = None) -> dict[str, object]:
        accounts = []
        for row in self._account_rows(market):
            decision = json.loads(row.get("last_decision_payload") or "{}")
            chart_error = self._account_chart_error(row["account_id"])
            profile = channel_profile(row["channel_id"])
            accounts.append({
                "account_id": row["account_id"], "name": row["name"],
                "strategy_id": row["strategy_id"],
                "symbol": row["symbol"],
                "release_id": f'{row["strategy_id"]}-{row["strategy_version"]}',
                "release_hash": row["release_hash"], "run_state": row["run_state"],
                "health": row["health"], "total_assets": row["total_assets"],
                "quantity": row["quantity"], "latest_action": decision.get("action"),
                "alert_count": int(bool(row.get("last_error"))) + int(bool(chart_error)),
                "channel_account_id": row["channel_account_id"], "market": profile.market, "currency": profile.currency,
            })
        return {
            "scope": {"resource": "virtual_accounts", **({"market": market} if market else {})}, "as_of": _now(),
            "default_account_id": accounts[0]["account_id"] if accounts else None,
            "accounts": accounts,
        }

    def virtual_account_snapshot(self, account_id: str) -> dict[str, object]:
        try:
            store, accounts = self.store, self.virtual
            if self.runtime is None:
                if account_id not in {row["account_id"] for row in store.strategy_virtual_accounts()}:
                    raise ResourceNotFound(account_id)
                channel_scope = {}
            else:
                account = self.runtime.store.virtual_account(account_id)
                if account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                    raise ResourceNotFound(account_id)
                channel_account_id = account["channel_account_id"]
                services = self._channel_services(channel_account_id)
                store, accounts = services.store, services.accounts
                channel_scope = {
                    "channel_account_id": channel_account_id,
                    "decision_contract": "V4" if account["equity_rules_json"] is not None else "LEGACY",
                }
            status = accounts.status(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        strategy_id = status.get("strategy_id")
        if status.get("channel_id"):
            profile = channel_profile(status["channel_id"])
            channel_scope.update(market=profile.market, currency=profile.currency)
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
        events = store.query_audit_events(account_id=account_id, limit=200)
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
            row = store.account_decision(account_id, decision["decision_id"])
            decision = {
                **decision,
                **{key: row[key] for key in (
                    "status", "state_reason", "state_changed_at", "state_events",
                )},
            }
        return {
            "scope": {"account_id": account_id, "strategy_id": strategy_id,
                      "release_id": release_id, "release_hash": status.get("release_hash"),
                      **channel_scope},
            "as_of": _now(),
            "account": {key: status.get(key) for key in account_keys},
            "decision": decision,
            "orders": _descending_transaction_rows(
                [row for row in status.get("orders", []) if row.get("account_id") == account_id],
                time_field="created_at", id_field="channel_order_id",
            ),
            "intents": _descending_transaction_rows(
                store.account_intents(account_id), time_field="created_at", id_field="intent_id",
            ),
            "fills": _descending_transaction_rows(
                [row for row in status.get("fills", []) if row.get("account_id") == account_id],
                time_field="occurred_at", id_field="fill_id",
            ),
            "metrics": metrics,
            "alerts": account_alerts,
            "events": events,
        }

    def channel_account_snapshot(self, channel_account_id: str, *, include_activity=True) -> dict[str, object]:
        if self.runtime is None and channel_account_id == DEFAULT_CHANNEL_ACCOUNT:
            store, execution = self.store, self.channel
        else:
            services = self._channel_services(channel_account_id)
            store, execution = services.store, services.execution
        status = execution.status()
        channel_id = store.execution_channel_id
        profile = channel_profile(channel_id)
        snapshot = self._channel_snapshot(store, status, channel_id, exact=True, include_activity=include_activity)
        accounts = snapshot["accounts"]
        return {**snapshot, "scope": {"channel_account_id": channel_account_id, "channel_id": channel_id},
                "market": profile.market, "currency": profile.currency, "environment": status.get("environment"),
                "cash_reconciliation_status": status.get("cash_reconciliation_status"),
                "broker_cash": (status.get("account") or {}).get("cash"),
                "accounts": [row["account_id"] for row in accounts], "strategy_accounts": accounts}

    def _chart_service(self, account_id: str):
        try:
            account = self._root_store.virtual_account(account_id)
        except KeyError as exc:
            raise ResourceNotFound(account_id) from exc
        chart = (self.runtime or self.operations).account_chart
        if chart is None or account["account_type"] != STRATEGY_ACCOUNT_TYPE:
            raise ResourceNotFound(account_id)
        return chart

    def virtual_account_chart(self, account_id: str) -> dict[str, object]:
        return self._chart_service(account_id).status(account_id)

    def refresh_virtual_account_chart(self, account_id: str) -> dict[str, object]:
        return self._chart_service(account_id).refresh(account_id)

    def virtual_account_chart_path(
        self, account_id: str, fingerprint: str | None = None,
    ):
        return self._chart_service(account_id).chart_path(account_id, fingerprint)

    def channel_snapshot(self, channel: str) -> dict[str, object]:
        if channel != FUTU_SIMULATE_CN_CHANNEL_ID:
            raise ResourceNotFound(channel)
        return self._channel_snapshot(self.store, self.channel.status(), channel)

    @staticmethod
    def _channel_snapshot(store, status, channel, *, exact=False, include_activity=True):
        events = store.query_audit_events(channel=channel, limit=200) if not exact else []
        rows = store.virtual_accounts()
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
            for row in rows
            if row.get("channel_id") == channel
            and row.get("account_type", STRATEGY_ACCOUNT_TYPE) == STRATEGY_ACCOUNT_TYPE
        ]
        channel_accounts = [
            row for row in rows
            if row.get("channel_id") == channel
            and row.get("run_state") != "RETIRED"
        ]
        pool = store.capital_pool_balance()
        def number(value):
            return Decimal(str(value)) if exact else float(value)
        capital_pool = number(pool.registered_capital)
        allocated = number(pool.allocated_capital)
        strategy_allocated = sum(number(row["initial_cash"]) for row in accounts if row["run_state"] != "RETIRED")
        unallocated = number(pool.unallocated_cash)
        # PTE reserves cash before a future-session order reaches Futu.  The
        # reservation changes the virtual account's available cash, but the
        # money is still present in the shared broker account.  Include both
        # available and internally frozen cash when reconciling with Futu.
        logical_cash = unallocated + sum(
            number(row["cash"]) + number(row["frozen_cash"]) for row in channel_accounts
        )
        logical_total_assets = unallocated + sum(
            number(row["total_assets"]) for row in channel_accounts
        )
        broker_account = status.get("account") or {}
        broker_cash = broker_account.get("cash")
        broker_total_assets = broker_account.get("total_assets")
        cash_difference = (
            number(broker_cash) - logical_cash if broker_cash is not None else None
        )
        asset_difference = (
            number(broker_total_assets) - logical_total_assets
            if broker_total_assets is not None else None
        )
        alerts = list(status.get("alerts", []))
        if cash_difference is not None and abs(cash_difference) > number("0.01"):
            alerts.append("CHANNEL_CASH_MISMATCH")
        return {
            "scope": {"channel": channel, "account_type": "broker_simulation"},
            "as_of": _now(),
            "account": status.get("account"), "actual_quantity": status.get("actual_quantity"),
            "accounts": accounts,
            "capital_pool": capital_pool,
            "recovered_pnl": number(pool.recovered_pnl),
            "allocated_capital": allocated,
            "strategy_allocated_capital": strategy_allocated,
            "unallocated_capital": unallocated,
            "logical_cash": logical_cash,
            "logical_total_assets": logical_total_assets,
            "cash_difference": cash_difference,
            "asset_difference": asset_difference,
            "last_reconcile_at": status.get("last_reconcile_at") or store.get_setting("last_reconcile_at"),
            "positions": status.get("positions", []),
            "orders": status.get("orders", []) if include_activity else [],
            "fills": store.account_fills() if include_activity else [],
            "paused": status.get("paused"),
            "reconciliation_status": status.get("reconciliation_status"),
            "reconciliation_account": store.channel_reconciliation_account(channel),
            "connection_error": status.get("channel_error") or status.get("last_error"), "alerts": list(dict.fromkeys(alerts)),
            "scheduler_failures": status.get("scheduler_failures", []), "events": events,
        }

    def comparison(self, account_ids: list[str], market: str | None = None) -> dict[str, object]:
        known = {row["account_id"]: row for row in self._account_rows(market)}
        selected = list(dict.fromkeys(account_ids)) if account_ids else sorted(known)
        missing = next((item for item in selected if item not in known), None)
        if missing:
            raise ResourceNotFound(missing)
        accounts = []
        for account_id in selected:
            row = known[account_id]
            service = self.virtual if self.runtime is None else self._channel_services(row["channel_account_id"]).accounts
            accounts.append({"account_id": account_id, "name": row["name"],
                             "release_id": f'{row["strategy_id"]}-{row["strategy_version"]}',
                             "metrics": service.metrics(account_id)})
        return {
            "scope": {"resource": "comparison", **({"market": market} if market else {})}, "as_of": _now(),
            "metric_basis": "ACCOUNT_OBSERVATION_WINDOW",
            "priority_metrics": ["maximum_drawdown", "calmar_ratio", "win_loss_ratio", "total_return"],
            "accounts": accounts,
        }
