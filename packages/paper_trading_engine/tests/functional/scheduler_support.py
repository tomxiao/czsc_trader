"""Small scheduler collaborators; no storage or strategy preparation."""
import json
from types import SimpleNamespace


class Engine:
    def __init__(self):
        self.calls = []
        self.failures = {}

    def refresh_orders(self):
        self.calls.append("orders")

    def refresh_account(self, account_id=None, *, prepared=None):
        if account_id is None:
            self.calls.append("account")
            return
        self.calls.append(("decision", account_id))
        error = self.failures.get(account_id)
        if error is not None:
            raise error

    def refresh_decisions(self):
        self.calls.append("decisions")

    def refresh_decision(self, account_id):
        self.calls.append(("decision", account_id))
        error = self.failures.get(account_id)
        if error is not None:
            raise error


class Store:
    def __init__(self):
        self.values, self.events, self.failures, self.audit_events = {}, [], {}, []
        self.accounts = []

    def get_setting(self, key):
        return self.values.get(key)

    def set_setting(self, key, value):
        self.values[key] = value

    def add_event(self, kind, payload):
        self.events.append((kind, payload))

    def set_operation_failure(self, operation, payload):
        self.failures[operation] = payload

    def clear_operation_failure(self, operation):
        self.failures.pop(operation, None)

    def operation_failures(self):
        return [{"operation": key, **value} for key, value in self.failures.items()]

    def append_audit_event(self, event):
        value = event.to_dict()
        self.audit_events.append(value)
        return value

    def scope(self, channel_account_id):
        return SimpleNamespace(execution_channel_id=channel_account_id,
                               append_audit_event=self.append_audit_event)

    def strategy_virtual_accounts(self):
        return [a for a in self.accounts if a.get("account_type", "STRATEGY") == "STRATEGY"]

    def virtual_account(self, account_id):
        return next(a for a in self.accounts if a["account_id"] == account_id)


def _account(account_id="s007-v1", **overrides):
    value = {
        "account_id": account_id,
        "symbol": "588080.SH",
        "asset_type": "etf",
        "run_state": "RUNNING",
        "strategy_id": "S007",
        "strategy_version": "v1",
        "release_hash": "b" * 64,
        "last_decision_payload": json.dumps({"signal_date": "2026-09-17"}),
    }
    value.update(overrides)
    return value
