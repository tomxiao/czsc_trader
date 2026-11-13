import json
from dataclasses import FrozenInstanceError
from decimal import Decimal
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from execution_channels.futu.audit import AuditContractError, AuditEvent, AuditRecorder
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.performance_export import (
    _canonical_sha256, calculate_metrics, export_performance,
)
from pte_support import adopt_test_decision, claim_test_intent
from strategy_manager import PerformanceEvidence


def test_account_metrics_use_the_same_realized_orders_for_win_rate_and_ratio():
    snapshots = [{"session": "2026-09-04", "total_assets": "1050"}]
    fills = [
        {"side": side, "order_id": order_id, "realized_pnl": pnl, "occurred_at": occurred_at}
        for side, order_id, pnl, occurred_at in (
            ("BUY", "still-open", "0", "2026-09-03T07:00:00Z"),
            ("SELL", "profitable", "90", "2026-09-04T06:00:00Z"),
            ("SELL", "profitable", "-30", "2026-09-04T06:05:00Z"),
            ("SELL", "losing", "-20", "2026-09-04T06:10:00Z"),
            ("SELL", "flat", "0", "2026-09-04T06:15:00Z"),
            ("SELL", "after-cutoff", "-200", "2026-09-07T06:00:00Z"),
        )
    ]
    store = SimpleNamespace(
        virtual_account=lambda _: {"initial_cash": "1000", "quantity": 100},
        account_snapshots=lambda _: snapshots,
        account_fills=lambda _: fills,
        equity_account_rules=lambda _: None,
    )
    account = AccountEngine(store, None)
    metrics = account.metrics("sample")
    assert metrics["closed_trades"] == 3
    assert metrics["win_rate"] == pytest.approx(1 / 3)
    assert metrics["win_loss_ratio"] == pytest.approx(3)

    fills[:] = [fills[0]]
    metrics = account.metrics("sample")
    assert metrics["closed_trades"] == 0
    assert metrics["win_rate"] is None
    assert metrics["win_loss_ratio_status"] == "NO_CLOSED_TRADES"


# Independent risk: PTE26; responsibility-level assertions.
@pytest.mark.parametrize("start,initial,expected_return", [
    ("2026-09-02", 200.0, 0.0),
], ids=['PTE26-C01'])
def test_performance_window_uses_auditable_opening_assets(tmp_path, start, initial, expected_return):
    history = [
        {"session": (date(2026, 9, 1) + timedelta(days=i)).isoformat(), "total_assets": "200"}
        for i in range(21)
    ]
    store = SimpleNamespace(
        virtual_account=lambda _: dict(
            strategy_id="S001", strategy_name_snapshot="Audit", strategy_version="v1",
            release_hash="a" * 64, qualification_snapshot="PAPER_READY", initial_cash="100",
            created_at="2026-09-01", observation_start="2026-09-01",
        ),
        account_snapshots=lambda _: history,
        account_fills=lambda _: [],
        account_intents=lambda _: [{"payload": {"fee_rate": "0.0005"}}],
    )
    result = export_performance(
        store, "audit", tmp_path / "window.json", recorded_by="tester", start=start,
        end="2026-09-21",
    )
    evidence, source = result["evidence"], result["source"]
    assert evidence["initial_capital"] == initial
    assert evidence["total_return"] == expected_return
    assert source["account"]["initial_cash"] == "100"
    assert evidence["source_hash"] == _canonical_sha256(source)
    recomputed = calculate_metrics(
        float(source["opening_assets"]["total_assets"]), source["snapshots"], source["closed_trade_pnl"],
    )
    assert all(
        (source["statistics"] if key in source["statistics"] else evidence)[key] == value
        for key, value in recomputed.items()
    )
    if start == "2026-09-02":
        assert source["opening_assets"] == {
            "basis": "ACCOUNT_SNAPSHOT", "session": "2026-09-01", "total_assets": "200",
        }
        assert evidence["maximum_drawdown"] == 0
        assert evidence["sharpe_ratio"] is None
    else:
        assert source["opening_assets"]["basis"] == "INITIAL_CASH"


# Independent risk: PTE26; responsibility-level assertions.
@pytest.mark.parametrize("start,end", [
    ("2026-10-01", "2026-09-01"),
], ids=['PTE26-C02'])
def test_performance_export_rejects_invalid_period_before_reading_store(tmp_path, start, end):
    with pytest.raises(ValueError):
        export_performance(object(), "audit", tmp_path / "absent.json", recorded_by="test",
                           start=start, end=end)
    assert not (tmp_path / "absent.json").exists()


def _export_window(memory_store, tmp_path, count, flat, version):
    store = memory_store()
    store.create_virtual_account(
        "forward", "Synthetic forward", version.release_id, version.release_hash, "100000",
        strategy_id=version.strategy_id, strategy_name_snapshot="Synthetic",
        strategy_version=version.version, release_hash=version.release_hash,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-02",
    )
    adopt_test_decision(store, account_id="forward", decision_id="synthetic",
                        valid_session="2026-09-04", orders=[{"side": "BUY", "quantity": 100,
                        "order_type": ("LIMIT" if "BUY" == "BUY" else "MARKET"), "limit_price": float("1"), "time_in_force": "DAY"}])
    store.set_virtual_paused("forward", False)
    store.create_account_intent(
        account_id="forward", decision_id="synthetic", order_sequence=0,
        symbol="588080.SH", side="BUY", quantity=100,
        limit_price="1", valid_session="2026-09-04", fee_rate="0.0005",
    )
    sessions = [
        day.isoformat() for i in range(40)
        if (day := date(2026, 9, 3) + timedelta(days=i)).weekday() < 5
    ][:count + 1]
    values = [110000] + [
        110000 if flat else 110000 + (i % 3 - 1) * 300 + i * 200
        for i in range(count)
    ]
    for session, assets in zip(sessions, values):
        store.save_account_snapshot("forward", session, {"total_assets": str(assets)})
    output = tmp_path / "forward-evidence.json"
    try:
        result = export_performance(
            store, "forward", output, recorded_by="tester", start=sessions[1], end=sessions[-1],
        )
    finally:
        store.close()
    evidence, source = result["evidence"], result["source"]
    assert set(evidence) == set(PerformanceEvidence.FIELDS)
    assert evidence["initial_capital"] == 110000
    assert source["account"]["initial_cash"] == "100000.0000"
    assert source["opening_assets"] == {
        "basis": "ACCOUNT_SNAPSHOT", "session": sessions[0], "total_assets": "110000",
    }
    assert source["statistics"] == {
        "observation_count": count,
        "annualization_status": "VALID" if count >= 20 else "INSUFFICIENT_OBSERVATIONS",
    }
    assert evidence["source_hash"] == _canonical_sha256(source)
    assert (evidence["calmar_ratio"] is None) is (count < 20 or flat)
    if count >= 20 and not flat:
        assert evidence["calmar_ratio"] > 0
        assert evidence["sharpe_ratio"] is not None
    return result, output


# Independent risk: PTE26; responsibility-level assertions.
def test_PTE26_C03_ft_pte07_performance_evidence_is_self_contained_and_release_bound(memory_store, tmp_path):
    class CaptureStore:
        def __init__(self):
            self.events = []

        def append_audit_event(self, event):
            self.events.append(event)
            return event.to_dict()

    capture = CaptureStore()
    recorder = AuditRecorder(capture)
    audit = recorder.record(
        "DECISION_GENERATED",
        source="engine",
        decision_id="DEC-1",
        details={"token": "secret-token", "nested": {"password": "secret"}},
    )
    assert audit["category"] == "STRATEGY"
    assert audit["severity"] == "INFO"
    assert audit["details"] == {
        "token": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    assert audit["correlation_id"] == "DEC-1"
    with pytest.raises(AuditContractError, match="catalog"):
        recorder.record("UNKNOWN", source="engine")
    with pytest.raises(AuditContractError, match="classification_reason"):
        recorder.record("UNCLASSIFIED_EVENT", source="engine", details={})
    with pytest.raises(FrozenInstanceError):
        capture.events[0].event_type = "CHANGED"
    assert isinstance(capture.events[0], AuditEvent)

    store = memory_store()
    store.create_virtual_account(
        "s001-forward", "S001-v1模拟账户", "baseline", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略", strategy_version="v1",
        release_hash="b" * 64, qualification_snapshot="PAPER_READY",
        selection_data_cutoff="2026-09-02",
    )
    store.set_virtual_paused("s001-forward", False)
    for index, (session, side, price) in enumerate((("2026-09-03", "BUY", "1.0"), ("2026-09-04", "SELL", "1.1"))):
        order_id = f"ORDER-{side}"
        adopt_test_decision(store, account_id="s001-forward", decision_id=f"DEC-{side}",
                            valid_session=session, orders=[{"side": side, "quantity": 1000,
                            "order_type": ("LIMIT" if side == "BUY" else "MARKET"), "limit_price": float(price), "time_in_force": "DAY"}])
        intent = store.create_account_intent(
            account_id="s001-forward", decision_id=f"DEC-{side}", order_sequence=0,
            symbol="588080.SH", side=side, quantity=1000,
            limit_price=price, valid_session=session, fee_rate="0.0005",
        )
        assert claim_test_intent(store, intent["intent_id"])
        store.bind_channel_order(intent["intent_id"], order_id, {
            "channel_order_id": order_id, "symbol": "588080.SH", "side": side,
            "quantity": 1000, "limit_price": float(price), "status": "FILLED_ALL",
            "cumulative_filled_quantity": 0, "average_fill_price": 0,
            "remark": intent["intent_id"],
        })
        store.apply_fill_increment(
            order_id, cumulative_quantity=1000, average_price=price,
            occurred_at=f"{session}T07:00:00+00:00",
        )
        account = store.virtual_account("s001-forward")
        store.save_account_snapshot("s001-forward", session, {
            "close": price, "cash": account["cash"], "quantity": account["quantity"],
            "total_assets": str(Decimal(account["cash"]) + Decimal(price) * account["quantity"]),
        })
    output = tmp_path / "evidence.json"
    result = export_performance(store, "s001-forward", output, recorded_by="tester")
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert result["evidence"]["phase"] == "PAPER_FORWARD"
    assert result["evidence"]["strategy_id"] == "S001"
    assert result["evidence"]["closed_trades"] == 1
    assert result["evidence"]["win_loss_ratio_status"] == "NO_LOSSES"
    assert len(result["evidence"]["source_hash"]) == 64
    store.close()
