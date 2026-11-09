import json
from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from paper_trading_engine.web import create_server
from paper_trading_engine.web_api import PteWebApi


# Independent risk: PTE14; responsibility-level assertions.
def test_PTE14_C03_account_snapshot_scopes_and_orders_transactions_without_mutating_source():
    collections = (
        ("intents", "intent_id", "created_at", "INT"),
        ("orders", "channel_order_id", "created_at", "ORD"),
        ("fills", "fill_id", "occurred_at", "FIL"),
    )
    rows = {
        collection: [
            {
                "account_id": account_id,
                id_field: f"{prefix}-{number}",
                time_field: f"2026-09-17T09:{minute}:00+08:00",
            }
            for number, minute, account_id in [
                (1, 30, "alpha"),
                (3, 31, "alpha"),
                (2, 31, "alpha"),
                (4, 32, "beta"),
            ]
        ]
        for collection, id_field, time_field, prefix in collections
    }
    original = deepcopy(rows)
    store = SimpleNamespace(
        strategy_virtual_accounts=lambda: [{"account_id": "alpha"}],
        retirement_status=lambda _: None,
        query_audit_events=lambda **filters: [],
        account_intents=lambda account_id: [
            row for row in rows["intents"] if row["account_id"] == account_id
        ],
    )
    api = PteWebApi(
        SimpleNamespace(
            store=store,
            channel=None,
            virtual=SimpleNamespace(
                status=lambda account_id: {
                    "account_id": account_id,
                    "initial_cash": 100_000,
                    "total_assets": 100_000,
                    "orders": rows["orders"],
                    "fills": rows["fills"],
                }
            ),
        )
    )

    result = api.virtual_account_snapshot("alpha")

    for collection, id_field, _time_field, prefix in collections:
        assert [row[id_field] for row in result[collection]] == [
            f"{prefix}-3",
            f"{prefix}-2",
            f"{prefix}-1",
        ]
        assert all(row["account_id"] == "alpha" for row in result[collection])
    assert rows == original


class FakeEngine:
    def __init__(self):
        self.paused, self.cancelled, self.audit_filters = False, [], []
        self.acknowledged = []
        self.ledger_repairs = []
        self.decision_requests = []
        self.chart_refreshes = []
        self.chart_file = None

    def status(self):
        return {
            "environment": "SIMULATE",
            "market": "CN",
            "symbol": "588080.SH",
            "paused": self.paused,
            "orders": [],
        }

    def pause(self):
        self.paused = True
        return self.status()

    def resume(self):
        self.paused = False
        return self.status()

    def issue_cancel_token(self, account_id, order_id):
        return f"token-{account_id}-{order_id}"

    def confirm_cancel(self, account_id, order_id, token):
        if token != f"token-{account_id}-{order_id}":
            raise RuntimeError("invalid token")
        self.cancelled.append(order_id)
        return self.status()

    def pause_virtual(self, account_id):
        return {"account_id": account_id, "run_state": "PAUSED"}

    def resume_virtual(self, account_id):
        return {"account_id": account_id, "run_state": "RUNNING"}

    def acknowledge_execution_gap(self, account_id, intent_id, resolution_note):
        self.acknowledged.append((account_id, intent_id, resolution_note))

    def repair_account_ledger(self, account_id, intent_id):
        self.ledger_repairs.append((account_id, intent_id))
        return {"status": "REPAIRED", "account_id": account_id, "intent_id": intent_id}

    def drive_virtual_account_decision(self, account_id):
        if account_id == "blocked":
            raise RuntimeError("虚拟账户已阻塞")
        self.decision_requests.append(account_id)
        return {
            "status": "DECISION_COMPLETED",
            "account_id": account_id,
            "decision_id": "DEC-ONE",
            "signal_date": "2026-09-18",
            "valid_session": "2026-09-21",
            "action": "HOLD",
            "target_quantity": 0,
            "execution_reference_price": 1.68,
            "reused_decision": True,
        }

    def system_status(self):
        return {"scope": {"system": "pte"}, "runtime": "RUNNING"}

    def health(self):
        return {
            "runtime": "RUNNING",
            "watchdog_healthy": True,
            "scheduler_heartbeat_at": "2026-09-19T00:00:00+00:00",
        }

    def virtual_accounts(self):
        return {"default_account_id": "alpha", "accounts": [{"account_id": "alpha"}]}

    def virtual_account_snapshot(self, account_id):
        if account_id != "alpha":
            from paper_trading_engine.web_api import ResourceNotFound

            raise ResourceNotFound(account_id)
        return {"scope": {"account_id": account_id}}

    chart_fingerprint = "f" * 64

    def virtual_account_chart(self, account_id):
        if account_id != "alpha":
            from paper_trading_engine.web_api import ResourceNotFound

            raise ResourceNotFound(account_id)
        return {
            "scope": {"account_id": "alpha", "release_id": "S001-v1"},
            "status": "READY",
            "selection_data_cutoff": "2026-08-28",
            "context_sessions": 60,
            "chart_url": f"/charts/alpha/observation.html?v={self.chart_fingerprint}",
            "fingerprint": self.chart_fingerprint,
            "message": None,
        }

    def refresh_virtual_account_chart(self, account_id):
        if account_id != "alpha":
            from paper_trading_engine.web_api import ResourceNotFound

            raise ResourceNotFound(account_id)
        self.chart_refreshes.append(account_id)
        return {
            "scope": {"account_id": "alpha", "release_id": "S001-v1"},
            "status": "BUILDING",
            "selection_data_cutoff": "2026-08-28",
            "context_sessions": 60,
            "chart_url": None,
            "fingerprint": None,
            "message": "正在重新生成观察图",
        }

    def virtual_account_chart_path(self, account_id, fingerprint=None):
        if (
            account_id != "alpha"
            or self.chart_file is None
            or fingerprint != self.chart_fingerprint
        ):
            from paper_trading_engine.web_api import ResourceNotFound

            raise ResourceNotFound(account_id)
        return self.chart_file

    def channel_snapshot(self, channel):
        return {"scope": {"channel": channel}, "orders": [], "paused": self.paused}

    def comparison(self, account_ids):
        return {"accounts": [{"account_id": x} for x in account_ids]}

    def audit_events(self, filters):
        self.audit_filters.append(filters)
        category = filters.get("category")
        if category and category not in {"STRATEGY", "TRADING", "SYSTEM", "OTHER"}:
            raise ValueError(f"invalid audit category: {category}")
        limit = int(filters.get("limit", "50"))
        if not 1 <= limit <= 200:
            raise ValueError("audit event limit must be between 1 and 200")
        return {
            "scope": {"resource": "audit_events"},
            "events": [{"event_id": "EV-1", "category": category or "SYSTEM"}],
            "next_before_id": "EV-1",
        }


def request_json(url, method="GET", payload=None, token=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-PTE-Control-Token"] = token
    with urlopen(Request(url, data=data, method=method, headers=headers), timeout=3) as response:
        return response.status, json.loads(response.read())


# Independent risk: PTE12, PTE13; responsibility-level assertions.


# Independent risk: EC16; responsibility-level assertions.
def test_channel_capital_uses_static_principal_allocations(memory_store):
    store = memory_store()
    for account_id in ("s001-v1", "s001-v2"):
        store.create_virtual_account(
            account_id,
            account_id,
            "legacy",
            "a" * 64,
            100_000,
            strategy_id="S001",
            strategy_name_snapshot="综合基线策略",
            strategy_version=account_id[-2:],
            release_hash="b" * 64,
            qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2026-09-01",
        )
    with store._lock, store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET cash='64.5572',quantity=60500 WHERE account_id='s001-v2'"
        )
    status = {
        "account": {
            "environment": "SIMULATE",
            "market": "CN",
            "cash": 900_060.661,
            "frozen_cash": 0.0,
            "total_assets": 998_675.661,
        },
        "orders": [],
        "actual_quantity": 60_500,
    }
    api = PteWebApi(
        SimpleNamespace(
            store=store,
            virtual=None,
            channel=SimpleNamespace(status=lambda: status),
        )
    )

    snapshot = api.channel_snapshot("futu_simulate_cn")

    assert snapshot["capital_pool"] == pytest.approx(1_000_000)
    assert snapshot["allocated_capital"] == pytest.approx(200_000)
    assert snapshot["unallocated_capital"] == pytest.approx(800_000)
    assert snapshot["allocated_capital"] + snapshot["unallocated_capital"] == pytest.approx(
        snapshot["capital_pool"]
    )
    assert snapshot["logical_cash"] == pytest.approx(900_064.5572)
    assert snapshot["cash_difference"] == pytest.approx(-3.8962)
    assert "CHANNEL_CASH_MISMATCH" in snapshot["alerts"]
    assert {row["symbol"] for row in snapshot["accounts"]} == {"588080.SH"}
    assert {row["asset_type"] for row in snapshot["accounts"]} == {"etf"}
    assert {row["health"] for row in snapshot["accounts"]} == {"OK"}
    store.close()


# Independent risk: PTE12; responsibility-level assertions.


@pytest.fixture
def console_http():
    engine, requested = FakeEngine(), Event()
    server = create_server(
        engine, host="127.0.0.1", port=0, control_token="secret", restart_callback=requested.set
    )
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", engine, requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def test_PTE12_C01_non_json_body_does_not_dispatch(console_http):
    base, engine, _ = console_http
    request = Request(
        base + "/api/virtual-accounts/alpha/decision",
        data=b"{}",
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)
    assert error.value.code == 415
    assert engine.decision_requests == []


def test_PTE12_C02_extra_decision_fields_do_not_dispatch(console_http):
    base, engine, _ = console_http
    with pytest.raises(HTTPError) as error:
        request_json(base + "/api/virtual-accounts/alpha/decision", "POST", {"force": True})
    assert error.value.code == 400
    assert engine.decision_requests == []


def test_PTE12_C03_unknown_api_does_not_route_to_default_channel(console_http):
    base, engine, _ = console_http
    with pytest.raises(HTTPError) as error:
        request_json(base + "/api/unknown-operation", "POST", {})
    assert error.value.code == 404
    assert not engine.paused and engine.cancelled == []


def test_PTE12_C04_encoded_parent_path_is_not_served(console_http):
    base, _, _ = console_http
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/static/%2e%2e%2fweb.py", timeout=3)
    assert error.value.code == 404


def test_PTE12_C05_business_conflict_retains_reason(console_http):
    base, engine, _ = console_http
    with pytest.raises(HTTPError) as error:
        request_json(base + "/api/virtual-accounts/blocked/decision", "POST", {})
    assert error.value.code == 409
    assert "虚拟账户已阻塞" in json.loads(error.value.read())["error"]
    assert engine.decision_requests == []


@pytest.mark.parametrize("token", [None, "wrong"], ids=["PTE13-C01", "PTE13-C02"])
def test_restart_requires_matching_control_token(console_http, token):
    base, _, requested = console_http
    with pytest.raises(HTTPError) as error:
        request_json(base + "/api/system/restart", "POST", {}, token)
    assert error.value.code == 403
    assert not requested.is_set()


def test_PTE13_C04_wrong_token_cannot_repair_ledger(console_http):
    base, engine, _ = console_http
    with pytest.raises(HTTPError) as error:
        request_json(
            base + "/api/virtual-accounts/alpha/intents/I1/repair-ledger", "POST", {}, "wrong"
        )
    assert error.value.code == 403
    assert engine.ledger_repairs == []


def test_PTE13_C05_cancel_confirmation_is_bound_to_account(console_http):
    base, engine, _ = console_http
    route = base + "/api/channels/futu-simulate-cn"
    token = request_json(
        route + "/cancel-token", "POST", {"account_id": "alpha", "channel_order_id": "1"}
    )[1]["token"]
    with pytest.raises(HTTPError) as error:
        request_json(
            route + "/cancel",
            "POST",
            {"account_id": "beta", "channel_order_id": "1", "token": token},
        )
    assert error.value.code == 409
    assert engine.cancelled == []


def test_PTE14_C01_market_filter_scopes_accounts_comparison_and_audit():
    rows = [
        dict(
            account_id=name,
            name=name,
            channel_id=channel,
            channel_account_id=name,
            strategy_id="S900",
            strategy_version="v1",
            release_hash="a" * 64,
            symbol=symbol,
            run_state="RUNNING",
            health="OK",
            total_assets=100,
            quantity=0,
        )
        for name, channel, symbol in [
            ("cn", "futu_simulate_cn", "510500.SH"),
            ("us", "futu_US_sim_channel", "MU"),
        ]
    ]
    observed = []

    def query(**filters):
        observed.append(filters)
        return [{"id": 1, "market": "US", "account_id": "us"}]

    store = SimpleNamespace(
        strategy_virtual_accounts=lambda: rows,
        query_audit_events=query,
        audit_event_counts=lambda **kw: {"SYSTEM": 1},
    )
    api = PteWebApi(
        SimpleNamespace(
            store=store,
            channel=None,
            virtual=SimpleNamespace(metrics=lambda account_id: {"assets": 100}),
        )
    )
    assert [r["account_id"] for r in api.virtual_accounts("US")["accounts"]] == ["us"]
    assert [r["account_id"] for r in api.comparison([], "US")["accounts"]] == ["us"]
    events = api.audit_events({"market": "US"})
    assert events["events"][0]["account_id"] == "us"
    assert observed == [{"market": "US"}]
