from dataclasses import asdict, replace
from decimal import Decimal
import json
import shutil
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from paper_trading_engine import AccountRetirementRequest, AccountRetirementStatus
from paper_trading_engine.cli import main as pte_main
from paper_trading_engine.futu_execution import FutuExecution, ChannelReconciliationError
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.web import create_server
from paper_trading_engine.web_api import PteWebApi
from paper_trading_engine.store import PaperStore
from pte_support import FakeBroker, decision


def create(store, account_id="one", capital=100000):
    return store.create_virtual_account(
        account_id, account_id, "S001-v1", "a" * 64, capital,
        strategy_id="S001", strategy_version="v1", release_hash="a" * 64,
        strategy_name_snapshot="test", qualification_snapshot="PAPER_READY",
        selection_data_cutoff="2026-09-02",
    )


@pytest.fixture
def setup(new_store, retirement_database, tmp_path):
    store = new_store(tmp_path / "runtime.db", seed=retirement_database)
    broker = FakeBroker()
    execution = FutuExecution(store, broker)
    request = AccountRetirementRequest("one", "a" * 64, "test", "stop this account")
    yield store, broker, execution, request
    store.close()


@pytest.fixture(scope="module")
def retirement_database(empty_paper_database, frozen_seed_root):
    """Prepare a paused account once; retirement still runs on a private WAL DB."""
    path = frozen_seed_root / "retirement.db"
    shutil.copyfile(empty_paper_database, path)
    store = PaperStore(path)
    create(store)
    store.set_virtual_paused("one", True)
    store.close()
    return path


@pytest.mark.parametrize("pnl", [Decimal("0"), Decimal("1250.4321"), Decimal("-2100.5678"), Decimal("-100000")])
def test_retirement_returns_actual_cash_preserves_history_and_reallocates(setup, pnl):
    store, broker, execution, request = setup
    cash = Decimal("100000") + pnl
    with store._connection as c:
        c.execute("UPDATE virtual_accounts SET cash=?,total_assets=?,realized_pnl=? WHERE account_id='one'",
                  (str(cash), str(cash), str(pnl)))
        c.execute(
            "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,cash_delta,"
            "frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) "
            "VALUES('fixture','one','REALIZED_PNL',?,'0',0,'0',?,0,'now')", (str(pnl), str(cash)),
        )
    store.save_account_decision("one", asdict(decision()))
    before = store._connection.execute("SELECT payload FROM decisions").fetchone()[0]
    broker.value = replace(broker.value, account=replace(
        broker.value.account, cash=float(Decimal("1000000") + pnl), total_assets=float(Decimal("1000000") + pnl),
    ))
    result = execution.retire_account(request)
    assert result.status is AccountRetirementStatus.RETIRED
    assert result.released_cash == cash
    assert result.remaining_strategy_accounts == 0
    assert not broker.placed and not broker.cancelled
    account = store.virtual_account("one")
    assert account["cash"] == "0.0000" and account["status"] == "RETIRED"
    assert account["initial_cash"] == "100000.0000"
    assert Decimal(account["realized_pnl"]) == pnl
    row = store._connection.execute("SELECT payload,status FROM decisions").fetchone()
    assert row[0] == before and row[1] == "INVALIDATED"
    assert store.capital_pool_balance().unallocated_cash == Decimal("1000000") + pnl
    assert store.capital_pool_balance().recovered_pnl == pnl
    with pytest.raises(ValueError, match="running"):
        execution.retire_account(request)
    with pytest.raises(ValueError, match="retired"):
        store.set_virtual_paused("one", False)
    with pytest.raises(ValueError, match="inactive"):
        store.save_account_decision("one", asdict(decision()))
    create(store, "new", Decimal("1000000") + pnl)
    assert store.capital_pool_balance().unallocated_cash == 0
    with pytest.raises(ValueError, match="unallocated"):
        create(store, "too-much", 1)
    execution.refresh_orders()
    assert execution.status()["cash_reconciliation_status"] == "OK"
    api = PteWebApi(SimpleNamespace(store=store, channel=execution, virtual=AccountEngine(store, None)))
    channel = api.channel_snapshot("futu_simulate_cn")
    assert channel["unallocated_capital"] == 0
    assert channel["recovered_pnl"] == float(pnl)
    snapshot = api.virtual_account_snapshot("one")
    assert snapshot["metrics"]["current_total_return"] == pytest.approx(float(pnl / Decimal("100000")))
    assert Decimal(snapshot["account"]["released_cash"]) == cash


@pytest.mark.parametrize("failure", ["position", "frozen", "not_paused", "wrong_hash", "pending", "attention", "cash", "disconnected"])
def test_retirement_rejects_unsafe_state_without_releasing_capital(setup, failure, monkeypatch):
    store, broker, execution, request = setup
    if failure == "position":
        with store._connection:
            store._connection.execute("UPDATE virtual_accounts SET quantity=100 WHERE account_id='one'")
    elif failure == "frozen":
        with store._connection:
            store._connection.execute("UPDATE virtual_accounts SET frozen_cash='10' WHERE account_id='one'")
    elif failure == "not_paused":
        store.set_virtual_paused("one", False)
    elif failure == "wrong_hash":
        request = replace(request, expected_release_hash="b" * 64)
    elif failure in {"pending", "attention"}:
        with store._connection as c:
            c.execute(
                "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,symbol,side,quantity,"
                "limit_price,valid_session,payload,status,attention_required,created_at,updated_at) "
                "VALUES('i','one','d',0,'588080.SH','BUY',100,'1','2099-01-01','{}',?,?,'now','now')",
                ("PENDING_SUBMIT" if failure == "pending" else "REJECTED", int(failure == "attention")),
            )
    elif failure == "cash":
        broker.value = replace(broker.value, account=replace(broker.value.account, cash=999000))
    else:
        monkeypatch.setattr(broker, "order_snapshot", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises((ValueError, RuntimeError, ChannelReconciliationError)):
        execution.retire_account(request)
    assert store.virtual_account("one")["status"] == "RUNNING"
    assert store._connection.execute("SELECT COUNT(*) FROM account_retirements").fetchone()[0] == 0
    assert store.capital_pool_balance().recovered_pnl == 0
    assert not broker.placed


def test_failed_retirement_transaction_rolls_back_and_shared_strategy_stays_in_use(setup, monkeypatch):
    store, broker, execution, request = setup
    create(store, "two")
    original = store._insert_audit_event
    def fail(event):
        if event.event_type == "ACCOUNT_RETIRED":
            raise RuntimeError("audit unavailable")
        return original(event)
    monkeypatch.setattr(store, "_insert_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        execution.retire_account(request)
    assert store.virtual_account("one")["status"] == "RUNNING"
    assert store._connection.execute("SELECT COUNT(*) FROM account_retirements").fetchone()[0] == 0
    monkeypatch.setattr(store, "_insert_audit_event", original)
    for method in ("_cancel_expired_planned_orders", "_expire_unsubmitted_intents"):
        monkeypatch.setattr(execution, method, lambda *_: pytest.fail("retirement must only reconcile"))
    assert execution.retire_account(request).remaining_strategy_accounts == 1
    assert store.virtual_account("two")["status"] == "RUNNING"
    assert broker.cancelled == broker.placed == []


@pytest.mark.parametrize("field,value", [("account_id", "../one"), ("expected_release_hash", "old"),
                                        ("actor", ""), ("reason", None)])
def test_retirement_contract_rejects_invalid_input(field, value):
    values = dict(account_id="one", expected_release_hash="a" * 64, actor="test", reason="stop")
    values[field] = value
    with pytest.raises(ValueError):
        AccountRetirementRequest(**values)


def test_retirement_http_requires_control_token_and_cli_uses_public_endpoint(setup, capsys):
    store, broker, execution, request = setup
    store.set_setting("control_token", "test-token")
    operations = SimpleNamespace(retire_account=execution.retire_account, store=store,
                                 channel=execution, virtual=SimpleNamespace())
    server = create_server(operations, host="127.0.0.1", port=0, control_token="test-token")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/api/virtual-accounts/one/retire"
        body = {"expected_release_hash": request.expected_release_hash, "actor": "test", "reason": "stop"}
        with pytest.raises(HTTPError) as caught:
            urlopen(Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))
        assert caught.value.code == 403
        assert pte_main([
            "control", "retire-account", "--repo-root", str(store.path.parent),
            "--database", str(store.path), "--port", str(port), "--account-id", "one",
            "--expected-release-hash", "a" * 64, "--actor", "test", "--reason", "stop",
        ]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS" and payload["command"] == "pte.control.retire-account"
        result = payload["result"]
        assert result["status"] == "RETIRED" and result["released_cash"] == "100000.0000"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
