"""Joint path audit: new NOOP versus R, then exact H10 path until fixed force D."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "research/S014/experiments/EX040_20261019/src/audit_accounts.py"
spec = importlib.util.spec_from_file_location("ex040_shared_joint_audit", SOURCE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def h10_reference():
    receipt = json.loads(
        (
            ROOT / "research/S014/experiments/EX041_20261019/others/accounts/run-001.json"
        ).read_bytes()
    )
    assert receipt["status"] == "SUCCEEDED" and receipt["audit"]["status"] == "PASS"
    ref = EvidenceRef.from_dict(receipt["evidence"])
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    account = json.loads(raw)
    assert account["result_hash"] == receipt["result_hash"]
    return account


def audit(account, mode, entry_date):
    assert entry_date == "2025-05-30"
    if mode == "NOOP":
        return shared.audit(account, "NOOP", "")
    assert mode == "JOINT"
    c = shared.Checks()
    original = shared.original()
    h10 = h10_reference()
    run, old = account["runs"][0], h10["runs"][0]
    tables = shared.internal(run, c)
    for field in (
        "symbol",
        "asset_type",
        "initial_cash",
        "costs",
        "benchmark",
        "windows",
        "data_cutoff",
        "market_rules",
        "execution_mode",
        "price_basis",
        "pricing",
    ):
        c.require(
            account["request_identity"][field] == original["request_identity"][field],
            "same original execution/pricing " + field,
        )
    d = "2025-06-19"
    for key, datekey, inclusive in (
        ("decisions", "signal_date", False),
        ("orders", "signal_date", False),
        ("fills", "fill_time", True),
        ("account_daily", "date", True),
    ):

        def select(r, datekey=datekey, inclusive=inclusive):
            return r[datekey][:10] <= d if inclusive else r[datekey][:10] < d

        c.rows(
            [r for r in tables[key] if select(r)],
            [r for r in old["ledgers"][key]["data"] if select(r)],
            "exact H10 prefix including actual June19 inventory " + key,
        )
    c.rows(
        [r for r in run["signals"]["data"] if r["signal_date"][:10] < d],
        [r for r in old["signals"]["data"] if r["signal_date"][:10] < d],
        "exact H10 pre-force signals",
    )
    rows = tables["decisions"]
    old_rows = old["ledgers"]["decisions"]["data"]
    before = next(r for r in old_rows if r["signal_date"][:10] == d)
    chosen = next(r for r in rows if r["signal_date"][:10] == d)
    c.require(
        before["buy_filled_today"]
        and before["held_at_close"]
        and not before["exit_pending"]
        and before["target_position"] == 1
        and before["target_cycle_completed"],
        "actual H10 path fixed June19 new inventory qualifies",
    )
    c.require(
        chosen["held_at_close"]
        and chosen["exit_pending"]
        and chosen["target_position"] == 0
        and chosen["action"] == "SELL"
        and chosen["joint_trigger_today"] == 1
        and chosen["joint_node_eligible"] == 1,
        "joint force creates next-session sell, never same-day imaginary cash",
    )
    changed = {"target_position", "action", "exit_pending"}
    c.rows(
        [{k: v for k, v in chosen.items() if k in before and k not in changed}],
        [{k: v for k, v in before.items() if k not in changed}],
        "all H10 original and protection state unchanged at force except sell intent",
    )
    c.require(sum(bool(r["joint_trigger_today"]) for r in rows) == 1, "one force trigger only")
    c.require(
        all(bool(r["joint_done"]) == (r["signal_date"][:10] >= d) for r in rows),
        "force completion causal and persistent",
    )
    fixed = {
        "entry_index": before["entry_index"],
        "deadline_index": before["deadline_index"],
        "reservation_index": before["reservation_index"],
    }
    for a, b in zip(rows, original["runs"][0]["ledgers"]["decisions"]["data"], strict=True):
        for key in ("ready", "support_ok", "warmup_sessions", "support_break", "support_floor"):
            c.require(a[key] == b[key], "truthful full-window market-only observation " + key)
    previous = None
    for r in rows:
        day = r["signal_date"][:10]
        if day >= d:
            c.require(
                r["joint_target_cycle_entry_index"] == fixed["entry_index"]
                and r["joint_target_deadline_index"] == fixed["deadline_index"]
                and r["joint_target_reservation_index"] == fixed["reservation_index"],
                "actual June inventory clocks fixed, no reset",
            )
        if r["buy_filled_today"]:
            c.require(
                r["entry_index"] == r["warmup_sessions"]
                and r["deadline_index"] == r["entry_index"] + 9
                and r["reservation_index"] == r["entry_index"] + 10,
                "only actual new fills establish original clocks",
            )
        if r["entry_signal"]:
            c.require(
                not r["held_at_close"]
                and not r["failed_buy_reset"]
                and r["ready"]
                and r["support_ok"]
                and r["warmup_sessions"] >= r["reservation_index"],
                "ordinary reentry and original reservation",
            )
        if r["held_at_close"] and not r["protected_cycle_active"] and r["support_break"]:
            c.require(r["exit_pending"], "all other holdings keep original support-exit rule")
        if previous and not r["buy_filled_today"]:
            c.require(
                r["reservation_index"] == previous["reservation_index"],
                "sale never changes reservation",
            )
        if previous and previous["exit_pending"] and not r["sell_filled_today"]:
            c.require(
                r["held_at_close"]
                and r["exit_pending"]
                and r["entry_index"] == previous["entry_index"]
                and r["deadline_index"] == previous["deadline_index"],
                "blocked sale preserves pending and original anchors",
            )
        previous = r
    target_buys = [r for r in tables["fills"] if r["side"] == "BUY" and r["fill_time"][:10] == d]
    c.require(len(target_buys) == 1, "one actual current inventory buy on June19")
    target_sales = [
        r
        for r in tables["fills"]
        if r["side"] == "SELL" and r["cycle_id"] == target_buys[0]["cycle_id"]
    ]
    c.require(len(target_sales) <= 1, "one real current inventory sale maximum")
    return c.result(
        mode,
        original_reference_result_hash=original["result_hash"],
        H10_reference_result_hash=h10["result_hash"],
        force_decision_date=d,
        actual_current_inventory_quantity=target_buys[0]["quantity"],
        actual_forced_inventory_sale=target_sales[0]["fill_time"][:10] if target_sales else None,
    )
