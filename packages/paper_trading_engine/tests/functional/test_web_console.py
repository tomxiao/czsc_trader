import http.client
import json
from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from paper_trading_engine.web import create_server
from paper_trading_engine.audit import AuditRecorder
from paper_trading_engine.web_api import PteWebApi


def test_account_snapshot_scopes_and_orders_transactions_without_mutating_source():
    collections = (
        ("intents", "intent_id", "created_at", "INT"),
        ("orders", "channel_order_id", "created_at", "ORD"),
        ("fills", "fill_id", "occurred_at", "FIL"),
    )
    rows = {
        collection: [
            {"account_id": account_id, id_field: f"{prefix}-{number}",
             time_field: f"2026-09-17T09:{minute}:00+08:00"}
            for number, minute, account_id in [(1, 30, "alpha"), (3, 31, "alpha"),
                                               (2, 31, "alpha"), (4, 32, "beta")]
        ]
        for collection, id_field, time_field, prefix in collections
    }
    original = deepcopy(rows)
    store = SimpleNamespace(
        strategy_virtual_accounts=lambda: [{"account_id": "alpha"}],
        query_audit_events=lambda **filters: [],
        account_intents=lambda account_id: [
            row for row in rows["intents"] if row["account_id"] == account_id
        ],
    )
    api = PteWebApi(SimpleNamespace(
        store=store, channel=None,
        virtual=SimpleNamespace(status=lambda account_id: {
            "account_id": account_id, "initial_cash": 100_000, "total_assets": 100_000,
            "orders": rows["orders"], "fills": rows["fills"],
        }),
    ))

    result = api.virtual_account_snapshot("alpha")

    for collection, id_field, _time_field, prefix in collections:
        assert [row[id_field] for row in result[collection]] == [
            f"{prefix}-3", f"{prefix}-2", f"{prefix}-1",
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
        return {"environment": "SIMULATE", "market": "CN", "symbol": "588080.SH",
                "paused": self.paused, "orders": []}
    def pause(self):
        self.paused = True
        return self.status()
    def resume(self):
        self.paused = False
        return self.status()
    def issue_cancel_token(self, account_id, order_id): return f"token-{account_id}-{order_id}"
    def confirm_cancel(self, account_id, order_id, token):
        if token != f"token-{account_id}-{order_id}":
            raise RuntimeError("invalid token")
        self.cancelled.append(order_id)
        return self.status()
    def pause_virtual(self, account_id): return {"account_id": account_id, "paused": True}
    def resume_virtual(self, account_id): return {"account_id": account_id, "paused": False}
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
            "status": "DECISION_COMPLETED", "account_id": account_id,
            "decision_id": "DEC-ONE", "signal_date": "2026-09-18",
            "valid_session": "2026-09-21", "action": "HOLD",
            "target_quantity": 0, "execution_reference_price": 1.68,
            "reused_decision": True,
        }
    def system_status(self): return {"scope": {"system": "pte"}, "runtime": "RUNNING"}
    def health(self):
        return {
            "runtime": "RUNNING", "watchdog_healthy": True,
            "scheduler_heartbeat_at": "2026-09-19T00:00:00+00:00",
        }
    def virtual_accounts(self): return {"default_account_id": "alpha", "accounts": [{"account_id": "alpha"}]}
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
            "status": "READY", "selection_data_cutoff": "2026-08-28",
            "context_sessions": 60,
            "chart_url": f"/charts/alpha/observation.html?v={self.chart_fingerprint}",
            "fingerprint": self.chart_fingerprint, "message": None,
        }
    def refresh_virtual_account_chart(self, account_id):
        if account_id != "alpha":
            from paper_trading_engine.web_api import ResourceNotFound
            raise ResourceNotFound(account_id)
        self.chart_refreshes.append(account_id)
        return {
            "scope": {"account_id": "alpha", "release_id": "S001-v1"},
            "status": "BUILDING", "selection_data_cutoff": "2026-08-28",
            "context_sessions": 60, "chart_url": None,
            "fingerprint": None, "message": "正在重新生成观察图",
        }
    def virtual_account_chart_path(self, account_id, fingerprint=None):
        if (
            account_id != "alpha" or self.chart_file is None
            or fingerprint != self.chart_fingerprint
        ):
            from paper_trading_engine.web_api import ResourceNotFound
            raise ResourceNotFound(account_id)
        return self.chart_file
    def channel_snapshot(self, channel): return {"scope": {"channel": channel}, "orders": []}
    def comparison(self, account_ids): return {"accounts": [{"account_id": x} for x in account_ids]}
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


def test_ft_pte05_console_resources_interventions_events_and_restart(new_store, tmp_path):
    store = new_store(tmp_path / "audit.db")
    recorder = AuditRecorder(store)
    recorder.record(
        "DECISION_GENERATED", source="test", account_id="alpha",
        strategy_id="S001", correlation_id="DEC-1",
    )
    audit_api = PteWebApi(SimpleNamespace(store=store, virtual=None, channel=None))
    count = len(store.recent_events())
    result = audit_api.audit_events({
        "category": "STRATEGY", "account_id": "alpha",
        "correlation_id": "DEC-1", "limit": "20",
    })
    assert result["events"][0]["event_type"] == "DECISION_GENERATED"
    assert result["category_counts"] == {
        "STRATEGY": 1, "TRADING": 0, "SYSTEM": 0, "OTHER": 0,
    }
    assert len(store.recent_events()) == count
    with pytest.raises(ValueError, match="invalid audit category"):
        audit_api.audit_events({"category": "INVALID"})
    with pytest.raises(ValueError, match="invalid audit event_type"):
        audit_api.audit_events({"event_type": "UNKNOWN_EVENT"})
    with pytest.raises(ValueError, match="between 1 and 200"):
        audit_api.audit_events({"limit": "0"})
    channel_api = PteWebApi(SimpleNamespace(
        store=store, virtual=None,
        channel=SimpleNamespace(status=lambda: {
            "account": None, "orders": [], "quote_health": "DEGRADED_QUOTE",
        }),
    ))
    assert "quote_health" not in channel_api.channel_snapshot("futu_simulate_cn")
    store.close()

    account_store = new_store(tmp_path / "account-index.db")
    account_store.create_virtual_account(
        "s007-v1", "S007-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S007", strategy_name_snapshot="多源机会风险门控",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
        symbol="588080.SH", asset_type="etf",
    )
    account_api = PteWebApi(SimpleNamespace(
        store=account_store,
        virtual=SimpleNamespace(status=lambda _account_id: {"last_decision": None}),
        channel=None,
    ))
    account_index = account_api.virtual_accounts()
    assert account_index["accounts"][0]["symbol"] == "588080.SH"
    account_store.close()

    requested, engine = Event(), FakeEngine()
    engine.chart_file = tmp_path / "observation.html"
    engine.chart_file.write_text("<html>alpha chart</html>", encoding="utf-8")
    server = create_server(engine, host="127.0.0.1", port=0, control_token="secret",
                           restart_callback=requested.set, instance_id="old")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode()
        assert "模拟交易控制台" in html and "审计事件" in html
        assert 'id="releaseVersion"' in html
        for asset, content_type in (("app.js", "javascript"), ("styles.css", "text/css")):
            with urlopen(base + f"/static/{asset}", timeout=3) as response:
                assert response.status == 200
                assert content_type in response.headers["Content-Type"]
                assert response.read().strip()
        with pytest.raises(HTTPError) as obsolete_asset:
            urlopen(base + "/static/plotly.min.js", timeout=3)
        assert obsolete_asset.value.code == 404
        assert html.index("Futu模拟盘CN") < html.index("审计事件") < html.index("账户比较")
        with urlopen(base + "/audit-events", timeout=3) as response:
            assert response.status == 200
        assert request_json(base + "/api/system/status")[1]["instance_id"] == "old"
        health = request_json(base + "/api/health")[1]
        assert health["instance_id"] == "old"
        assert set(health) == {
            "runtime", "watchdog_healthy", "scheduler_heartbeat_at", "instance_id",
        }
        assert request_json(base + "/api/virtual-accounts")[1]["default_account_id"] == "alpha"
        assert request_json(base + "/api/virtual-accounts/alpha/snapshot")[1]["scope"]["account_id"] == "alpha"
        chart = request_json(base + "/api/virtual-accounts/alpha/chart")[1]
        assert chart["scope"]["account_id"] == "alpha"
        refresh_status, refresh = request_json(
            base + "/api/virtual-accounts/alpha/chart/refresh", "POST", {},
        )
        assert refresh_status == 202
        assert refresh["status"] == "BUILDING"
        assert engine.chart_refreshes == ["alpha"]
        with pytest.raises(HTTPError) as invalid_chart_refresh:
            request_json(
                base + "/api/virtual-accounts/alpha/chart/refresh", "POST",
                {"force": True},
            )
        assert invalid_chart_refresh.value.code == 400
        with urlopen(base + chart["chart_url"], timeout=3) as response:
            assert response.read().decode() == "<html>alpha chart</html>"
            assert response.headers["ETag"] == f'"{engine.chart_fingerprint}"'
            assert "immutable" in response.headers["Cache-Control"]
        conditional = Request(
            base + chart["chart_url"],
            headers={"If-None-Match": f'"{engine.chart_fingerprint}"'},
        )
        with pytest.raises(HTTPError) as unchanged:
            urlopen(conditional, timeout=3)
        assert unchanged.value.code == 304
        assert request_json(base + "/api/channels/futu-simulate-cn/snapshot")[1]["scope"]["channel"] == "futu_simulate_cn"
        audit = request_json(
            base + "/api/audit-events?category=STRATEGY&account_id=alpha&correlation_id=DEC-1&limit=20"
        )[1]
        assert audit["events"][0]["category"] == "STRATEGY"
        assert audit["next_before_id"] == "EV-1"
        assert engine.audit_filters[-1] == {
            "category": "STRATEGY", "account_id": "alpha",
            "correlation_id": "DEC-1", "limit": "20",
        }
        for query in ("category=INVALID", "limit=0"):
            with pytest.raises(HTTPError) as invalid:
                request_json(base + "/api/audit-events?" + query)
            assert invalid.value.code == 400
        assert request_json(base + "/api/pause", "POST", {})[1]["paused"] is True
        assert request_json(base + "/api/resume", "POST", {})[1]["paused"] is False
        token = request_json(base + "/api/cancel-token", "POST", {"account_id": "alpha", "channel_order_id": "1"})[1]["token"]
        request_json(base + "/api/cancel", "POST", {"account_id": "alpha", "channel_order_id": "1", "token": token})
        assert engine.cancelled == ["1"]
        request_json(
            base + "/api/virtual-accounts/alpha/intents/PTE-1/acknowledge",
            "POST", {"resolution_note": "已人工确认"},
        )
        assert engine.acknowledged == [("alpha", "PTE-1", "已人工确认")]
        with pytest.raises(HTTPError) as repair_denied:
            request_json(
                base + "/api/virtual-accounts/alpha/intents/PTE-1/repair-ledger",
                "POST", {}, "wrong",
            )
        assert repair_denied.value.code == 403
        repaired = request_json(
            base + "/api/virtual-accounts/alpha/intents/PTE-1/repair-ledger",
            "POST", {}, "secret",
        )[1]
        assert repaired["status"] == "REPAIRED"
        assert engine.ledger_repairs == [("alpha", "PTE-1")]
        with pytest.raises(HTTPError) as invalid_decision_request:
            request_json(
                base + "/api/virtual-accounts/alpha/decision", "POST",
                {"force": True},
            )
        assert invalid_decision_request.value.code == 400
        driven = request_json(
            base + "/api/virtual-accounts/alpha/decision", "POST", {},
        )[1]
        assert driven == {
            "status": "DECISION_COMPLETED", "account_id": "alpha",
            "decision_id": "DEC-ONE", "signal_date": "2026-09-18",
            "valid_session": "2026-09-21", "action": "HOLD",
            "target_quantity": 0, "execution_reference_price": 1.68,
            "reused_decision": True,
        }
        assert engine.decision_requests == ["alpha"]
        with pytest.raises(HTTPError) as blocked_decision:
            request_json(
                base + "/api/virtual-accounts/blocked/decision", "POST", {},
            )
        assert blocked_decision.value.code == 409
        with pytest.raises(HTTPError) as denied:
            request_json(base + "/api/system/restart", "POST", {}, "wrong")
        assert denied.value.code == 403
        assert request_json(base + "/api/system/restart", "POST", {}, "secret")[0] == 202
        assert requested.wait(1)
        with pytest.raises(HTTPError) as missing:
            request_json(base + "/api/virtual-accounts/missing/snapshot")
        assert missing.value.code == 404
        with pytest.raises(HTTPError) as unsafe:
            request_json(base + "/api/virtual-accounts/%2E%2E/chart")
        assert unsafe.value.code in {400, 404}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_channel_capital_uses_static_principal_allocations(new_store, tmp_path):
    store = new_store(tmp_path / "capital.db")
    for account_id in ("s001-v1", "s001-v2"):
        store.create_virtual_account(
            account_id, account_id, "legacy", "a" * 64, 100_000,
            strategy_id="S001", strategy_name_snapshot="综合基线策略",
            strategy_version=account_id[-2:], release_hash="b" * 64,
            qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
        )
    with store._lock, store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET cash='64.5572',quantity=60500 WHERE account_id='s001-v2'"
        )
    status = {
        "account": {
            "environment": "SIMULATE", "market": "CN",
            "cash": 900_060.661, "frozen_cash": 0.0,
            "total_assets": 998_675.661,
        },
        "orders": [], "actual_quantity": 60_500,
    }
    api = PteWebApi(SimpleNamespace(
        store=store, virtual=None,
        channel=SimpleNamespace(status=lambda: status),
    ))

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
    assert {row["health"] for row in snapshot["accounts"]} == {"READY"}
    store.close()


def test_channel_cash_reconciliation_includes_internal_frozen_cash(new_store, tmp_path):
    store = new_store(tmp_path / "frozen-cash.db")
    store.create_virtual_account(
        "s003-v1", "S003-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S003", strategy_name_snapshot="成分资金流宽度早盘延续",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-08",
        symbol="510500.SH", asset_type="etf",
    )
    with store._lock, store._connection:
        store._connection.execute(
            "UPDATE virtual_accounts SET cash='50152.5888',frozen_cash='49847.4112' "
            "WHERE account_id='s003-v1'"
        )
    status = {
        "account": {
            "environment": "SIMULATE", "market": "CN",
            "cash": 1_000_000.0, "frozen_cash": 0.0,
            "total_assets": 1_000_000.0,
        },
        "orders": [], "actual_quantity": 0,
    }
    api = PteWebApi(SimpleNamespace(
        store=store, virtual=None,
        channel=SimpleNamespace(status=lambda: status),
    ))

    snapshot = api.channel_snapshot("futu_simulate_cn")

    assert snapshot["logical_cash"] == pytest.approx(1_000_000.0)
    assert snapshot["cash_difference"] == pytest.approx(0.0)
    assert "CHANNEL_CASH_MISMATCH" not in snapshot["alerts"]
    store.close()


def test_static_resource_rejects_parent_absolute_and_encoded_paths():
    server = create_server(SimpleNamespace(system_status=lambda: {}), port=0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for suffix in (
            "../web.py", "..\\web.py", "%2e%2e%2fweb.py", "C:/Windows/win.ini",
            "../../../../../pyproject.toml", "app.js:stream", "%252e%252e/web.py",
        ):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("GET", "/static/" + suffix)
                response = connection.getresponse()
                assert response.status == 404, suffix
                response.read()
            finally:
                connection.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
