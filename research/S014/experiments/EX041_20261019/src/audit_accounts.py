"""Independent-cycle boundary audit; exact original economics for new-source NOOP."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "research/S014/experiments/EX040_20261019/src"))
# Load by file identity, avoiding the identically named current module.
import importlib.util  # noqa: E402

SOURCE = ROOT / "research/S014/experiments/EX040_20261019/src/audit_accounts.py"
spec = importlib.util.spec_from_file_location("ex040_audit_reused", SOURCE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def audit(account, mode, entry_date):
    assert entry_date == "2025-05-30"
    if mode == "NOOP":
        return shared.audit(account, "NOOP", "")
    assert mode == "HOLD_ORIGINAL_CYCLE_H10"
    c = shared.Checks()
    base = shared.original()
    old = base["runs"][0]
    run = account["runs"][0]
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
            account["request_identity"][field] == base["request_identity"][field],
            "same execution/pricing " + field,
        )
    d = entry_date
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
            "original prefix through actual filled entry " + key,
        )
    c.rows(
        [r for r in run["signals"]["data"] if r["signal_date"][:10] < d],
        [r for r in old["signals"]["data"] if r["signal_date"][:10] < d],
        "original pre-entry signals",
    )
    rows = tables["decisions"]
    first = next(r for r in rows if r["signal_date"][:10] == d)
    before = next(r for r in old["ledgers"]["decisions"]["data"] if r["signal_date"][:10] == d)
    c.require(
        first["buy_filled_today"]
        and before["buy_filled_today"]
        and first["held_at_close"]
        and first["support_break"],
        "same actual May30 filled entry and truthful support break",
    )
    c.require(
        first["target_position"] == 1
        and not first["exit_pending"]
        and first["protected_cycle_active"] == 1
        and first["support_exit_suppressed"] == 1,
        "May30 only support exit intent suppressed",
    )
    changed = {"target_position", "action", "exit_pending"}
    c.rows(
        [{k: v for k, v in first.items() if k in before and k not in changed}],
        [{k: v for k, v in before.items() if k not in changed}],
        "all other entry original state exact",
    )
    fixed = {key: first[key] for key in ("entry_index", "deadline_index", "reservation_index")}
    c.require(
        fixed["deadline_index"] == fixed["entry_index"] + 9
        and fixed["reservation_index"] == fixed["entry_index"] + 10,
        "actual fill fixed H10 clock",
    )
    target_buys = [f for f in tables["fills"] if f["side"] == "BUY" and f["fill_time"][:10] == d]
    c.require(len(target_buys) == 1, "one actual original-date buy")
    cycle = target_buys[0]["cycle_id"]
    target_sales = [f for f in tables["fills"] if f["cycle_id"] == cycle and f["side"] == "SELL"]
    c.require(len(target_sales) <= 1, "at most one actual target-cycle exit")
    previous = None
    suppressed = []
    for r in rows:
        day = r["signal_date"][:10]
        c.require(r["cycle_mode_active"] == 1, "fixed cycle mode declared throughout")
        if day >= d:
            c.require(r["target_entry_seen"] == 1, "actual entry flag retained")
            c.require(
                all(r["fixed_cycle_" + k] == v for k, v in fixed.items()),
                "original fixed cycle clocks never reset",
            )
        if r["protected_cycle_active"]:
            c.require(
                r["held_at_close"]
                and r["entry_index"] == fixed["entry_index"]
                and not r["target_cycle_completed"],
                "protected state restricted to original inventory",
            )
            if r["warmup_sessions"] < fixed["deadline_index"]:
                c.require(
                    r["target_position"] == 1 and not r["exit_pending"],
                    "keep original inventory before mandatory deadline",
                )
                c.require(
                    bool(r["support_exit_suppressed"]) == bool(r["support_break"]),
                    "support break observation retained, suppression exact",
                )
            else:
                c.require(
                    r["exit_pending"]
                    and r["target_position"] == 0
                    and r["deadline_exit_pending"] == 1,
                    "mandatory deadline wins over protection",
                )
        if r["support_exit_suppressed"]:
            suppressed.append(day)
            c.require(
                r["protected_cycle_active"]
                and r["support_break"]
                and r["warmup_sessions"] < fixed["deadline_index"],
                "all suppressed dates belong only to predeadline original cycle",
            )
        if r["buy_filled_today"]:
            c.require(
                r["entry_index"] == r["warmup_sessions"]
                and r["deadline_index"] == r["entry_index"] + 9
                and r["reservation_index"] == r["entry_index"] + 10,
                "new real entry anchors original policy",
            )
        if r["entry_signal"]:
            c.require(
                not r["held_at_close"]
                and not r["failed_buy_reset"]
                and r["ready"]
                and r["support_ok"]
                and r["warmup_sessions"] >= r["reservation_index"],
                "ordinary reentry eligibility",
            )
        if r["held_at_close"] and not r["protected_cycle_active"] and r["support_break"]:
            c.require(r["exit_pending"], "all other original cycles retain support exit")
        if previous and not r["buy_filled_today"]:
            c.require(
                r["reservation_index"] == previous["reservation_index"],
                "reservation not moved by sale/protection",
            )
        if previous and previous["exit_pending"] and not r["sell_filled_today"]:
            c.require(
                r["held_at_close"]
                and r["exit_pending"]
                and r["entry_index"] == previous["entry_index"]
                and r["deadline_index"] == previous["deadline_index"],
                "unfilled sale retains pending and original clocks",
            )
        previous = r
    return c.result(
        mode,
        reference_result_hash=base["result_hash"],
        fixed_entry_date=d,
        original_cycle_entry_index=fixed["entry_index"],
        original_cycle_deadline_index=fixed["deadline_index"],
        original_cycle_reservation_index=fixed["reservation_index"],
        support_exit_suppressed_dates=suppressed,
        actual_original_cycle_exit=target_sales[0]["fill_time"][:10] if target_sales else None,
    )
