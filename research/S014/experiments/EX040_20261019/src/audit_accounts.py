"""Strict original economic projection and one-shot C0056 execution audit."""

from hashlib import sha256
import json
import math
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
SOURCE = (
    ROOT / "research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json"
)
IDS = {"decision_id", "order_id", "fill_id", "cycle_id"}
DIAG = {"intervention_today", "intervention_done"}


def original():
    source = json.loads(SOURCE.read_bytes())
    ref = EvidenceRef.from_dict(source["original_account_evidence"])
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    result = json.loads(raw)
    assert result["result_hash"] == source["original_result_hash"]
    assert len(result["runs"]) == 1
    return result


class Checks:
    def __init__(self):
        self.n = 0
        self.errors = []
        self.links = {}
        self.reverse = {}

    def require(self, condition, message):
        self.n += 1
        if not condition and len(self.errors) < 40:
            self.errors.append(message)

    def rows(self, actual, expected, label):
        self.require(len(actual) == len(expected), label + " row count")
        for i, (a, b) in enumerate(zip(actual, expected)):
            for key, value in b.items():
                self.require(key in a, f"{label}[{i}] missing {key}")
                if key not in a:
                    continue
                if key in IDS:
                    if value is None:
                        self.require(a[key] is None, f"{label}[{i}].{key} null")
                        continue
                    mapping = self.links.setdefault(key, {})
                    reverse = self.reverse.setdefault(key, {})
                    self.require(
                        mapping.get(value, a[key]) == a[key],
                        f"{label}[{i}].{key} consistent forward mapping",
                    )
                    self.require(
                        reverse.get(a[key], value) == value,
                        f"{label}[{i}].{key} unique reverse mapping",
                    )
                    mapping[value] = a[key]
                    reverse[a[key]] = value
                else:
                    self.require(
                        a[key] == value, f"{label}[{i}].{key} exact economic/content equality"
                    )

    def result(self, kind, **extra):
        return {
            "status": "FAIL" if self.errors else "PASS",
            "kind": kind,
            "checks": self.n,
            "errors": self.errors,
            "original_projection_numeric_tolerance": 0,
            "identity_link_fields_mapped_separately": sorted(IDS),
            "arithmetic_only_currency_epsilon": 1e-7,
            **extra,
        }


def internal(run, c):
    tables = {k: v["data"] for k, v in run["ledgers"].items()}
    for table, key in (
        ("decisions", "decision_id"),
        ("orders", "order_id"),
        ("fills", "fill_id"),
        ("trades", "cycle_id"),
    ):
        c.require(len({r[key] for r in tables[table]}) == len(tables[table]), f"unique {table} ID")
    decisions = {r["decision_id"]: r for r in tables["decisions"]}
    orders = {r["order_id"]: r for r in tables["orders"]}
    by_date = {}
    for f in tables["fills"]:
        o = orders.get(f["order_id"])
        c.require(o is not None, "fill points to real order")
        if o:
            c.require(
                all(
                    f[k] == o[k]
                    for k in ("side", "quantity", "decision_id", "cycle_id", "signal_date")
                ),
                "fill/order link content",
            )
            c.require(f["fill_time"][:10] == o["execution_date"][:10], "fill/order session clock")
        c.require(
            abs(f["fees"] - f["quantity"] * f["price"] * 0.001) <= 1e-7, "original fee arithmetic"
        )
        c.require(f["quantity"] > 0 and f["quantity"] % 100 == 0, "original whole-lot execution")
        by_date.setdefault(f["fill_time"][:10], []).append(f)
    for o in tables["orders"]:
        d = decisions.get(o["decision_id"])
        c.require(d is not None, "order points to real decision")
        if d:
            c.require(
                o["signal_date"] == d["signal_date"] and o["execution_date"] == d["valid_session"],
                "next-session execution clock",
            )
    cash, qty = 100000.0, 0
    for row in tables["account_daily"]:
        c.require(
            row["cash_before"] == cash and row["quantity_before"] == qty,
            "daily opening content continuity",
        )
        for f in by_date.get(row["date"][:10], []):
            direction = 1 if f["side"] == "BUY" else -1
            cash -= direction * f["price"] * f["quantity"] + f["fees"]
            qty += direction * f["quantity"]
        c.require(
            math.isfinite(row["equity"])
            and abs(row["cash"] - cash) <= 1e-7
            and row["quantity"] == qty,
            "daily cash/quantity from actual fills",
        )
        c.require(
            abs(row["equity"] - (row["cash"] + qty * row["close"])) <= 1e-7,
            "closing wealth arithmetic",
        )
        cash = row["cash"]
    c.require(
        len(tables["account_daily"]) == len(tables["decisions"]) == 1642,
        "complete original session coverage",
    )
    c.require(
        any(r["date"][:10] == "2025-12-31" for r in tables["account_daily"]),
        "fixed terminal date covered",
    )
    return tables


def audit(account, mode, decision_date):
    base = original()
    c = Checks()
    c.require(len(account["runs"]) == 1, "one full window/cost")
    run, old = account["runs"][0], base["runs"][0]
    tables = internal(run, c)
    c.require(
        account["request_identity"]["price_basis"] == base["request_identity"]["price_basis"],
        "same price basis",
    )
    c.require(
        account["request_identity"]["pricing"] == base["request_identity"]["pricing"],
        "same price/quantity projection",
    )
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
    ):
        c.require(
            account["request_identity"][field] == base["request_identity"][field],
            "same original execution contract " + field,
        )
    c.require(set(tables) == set(old["ledgers"]), "same ledger families")
    if mode == "NOOP":
        for key, rows in tables.items():
            c.rows(rows, old["ledgers"][key]["data"], key)
        c.rows(run["signals"]["data"], old["signals"]["data"], "signals")
        for key in ("account_daily", "orders", "fills", "attempts"):
            if key in old["buyhold"]:
                c.rows(run["buyhold"][key]["data"], old["buyhold"][key]["data"], "buyhold " + key)
        c.require(
            not any(r.get(k, False) for r in tables["decisions"] for k in DIAG),
            "NOOP flags always false",
        )
    else:
        d = decision_date
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
                "pre-D " + key,
            )
        c.rows(
            [r for r in run["signals"]["data"] if r["signal_date"][:10] < d],
            [r for r in old["signals"]["data"] if r["signal_date"][:10] < d],
            "pre-D signals",
        )
        rows = tables["decisions"]
        chosen = [r for r in rows if r.get("intervention_today")]
        c.require(
            len(chosen) == 1 and chosen[0]["signal_date"][:10] == d,
            "exactly one intervention at fixed D",
        )
        baseline = next(
            r for r in old["ledgers"]["decisions"]["data"] if r["signal_date"][:10] == d
        )
        actual = next(r for r in rows if r["signal_date"][:10] == d)
        c.require(
            all(bool(r.get("intervention_done")) == (r["signal_date"][:10] >= d) for r in rows),
            "intervention done flag causal and persistent",
        )
        if mode == "SKIP_BUY_ONCE":
            c.require(
                not baseline["held_at_close"]
                and baseline["entry_signal"]
                and baseline["target_position"] == 1
                and not baseline["failed_buy_reset"],
                "baseline SKIP node eligible",
            )
            c.require(
                not actual["entry_signal"]
                and actual["target_position"] == 0
                and not actual["failed_buy_reset"]
                and actual["holding_horizon"] == 0,
                "SKIP cancel without invented failure/holding",
            )
            changed = {"action", "entry_signal", "target_position", "holding_horizon"}
        elif mode == "FORCE_SELL_ONCE":
            c.require(
                baseline["held_at_close"]
                and not baseline["exit_pending"]
                and baseline["target_position"] == 1,
                "baseline FORCE node eligible",
            )
            c.require(
                actual["held_at_close"]
                and actual["exit_pending"]
                and actual["target_position"] == 0
                and actual["action"] == "SELL",
                "FORCE pending sell, no imaginary same-day sale",
            )
            changed = {"action", "target_position", "exit_pending"}
        else:
            raise ValueError("Unknown audited mode")
        c.rows(
            [{k: v for k, v in actual.items() if k not in changed | DIAG}],
            [{k: v for k, v in baseline.items() if k not in changed}],
            "intervention other original fields unchanged",
        )
        previous = None
        for r in rows:
            if r["buy_filled_today"]:
                c.require(
                    r["entry_index"] == r["warmup_sessions"]
                    and r["deadline_index"] == r["entry_index"] + 9
                    and r["reservation_index"] == r["entry_index"] + 10,
                    "actual new fill establishes H10 anchors",
                )
            if r["entry_signal"]:
                c.require(
                    not r["held_at_close"]
                    and not r["failed_buy_reset"]
                    and r["ready"]
                    and r["support_ok"]
                    and r["warmup_sessions"] >= r["reservation_index"],
                    "ordinary reentry eligibility and reservation",
                )
            if previous and not r["buy_filled_today"]:
                c.require(
                    r["reservation_index"] == previous["reservation_index"],
                    "reservation changes only at actual buy",
                )
            if previous and previous["exit_pending"] and not r["sell_filled_today"]:
                c.require(
                    r["held_at_close"]
                    and r["exit_pending"]
                    and r["entry_index"] == previous["entry_index"]
                    and r["deadline_index"] == previous["deadline_index"],
                    "blocked SELL keeps original anchors/pending",
                )
            previous = r
    return c.result(
        mode, reference_result_hash=base["result_hash"], intervention_decision_date=decision_date
    )
