"""Economic gate only: original NOOP exactness and complete funded state lifecycle."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "research/S014/experiments/EX040_20261019/src/audit_accounts.py"
spec = importlib.util.spec_from_file_location("ex043_shared_original_audit", SOURCE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def audit(account, parameters):
    if parameters == {"hold_rule": "BASE", "exit_rule": "BASE"}:
        return shared.audit(account, "NOOP", "")
    c = shared.Checks()
    base = shared.original()
    original, run = base["runs"][0], account["runs"][0]
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
            "same original execution contract " + field,
        )
    rows = tables["decisions"]
    old_rows = original["ledgers"]["decisions"]["data"]
    c.require(len(rows) == len(old_rows), "same full decision coverage")
    first_difference = None
    for r, b in zip(rows, old_rows, strict=True):
        c.require(
            r["signal_date"] == b["signal_date"] and r["valid_session"] == b["valid_session"],
            "same D to E clock",
        )
        for field in ("ready", "support_ok", "support_break", "support_floor", "warmup_sessions"):
            c.require(r[field] == b[field], "original market-only observation exact " + field)
        if first_difference is None and r["target_position"] != b["target_position"]:
            first_difference = r["signal_date"][:10]
    if first_difference is None:
        for key, values in tables.items():
            c.rows(values, original["ledgers"][key]["data"], "identical original path " + key)
        c.rows(run["signals"]["data"], original["signals"]["data"], "identical original signals")
    else:
        d = first_difference
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
                [r for r in original["ledgers"][key]["data"] if select(r)],
                "exact original prefix through first state action " + key,
            )
    previous = None
    for r in rows:
        held = bool(r["held_at_close"])
        inherited = bool(
            previous and previous["exit_pending"] and not r["sell_filled_today"] and held
        )
        deadline = bool(held and r["warmup_sessions"] >= r["deadline_index"])
        eligible = bool(held and not inherited and not deadline)
        c.require(
            bool(r["pending_inherited"]) == inherited,
            "inherited pending defined before new support decision",
        )
        c.require(bool(r["deadline_exit"]) == deadline, "original mandatory H10 deadline")
        c.require(bool(r["profit_exit_eligible"]) == eligible, "profit trigger discretion domain")
        if held:
            expected_pending = (
                inherited
                or deadline
                or bool(r["selected_profit_exit"])
                or bool(r["ordinary_support_exit"])
            )
            c.require(
                bool(r["exit_pending"]) == expected_pending,
                "mandatory then profit then support priority",
            )
            c.require(
                r["target_position"] == (0.0 if expected_pending else 1.0),
                "held target matches pending/hold",
            )
            c.require(
                r["holding_age"] == r["warmup_sessions"] - r["entry_index"],
                "actual holding age known at D",
            )
            c.require(
                r["peak_close"] is not None
                and r["giveback_price"] is not None
                and r["giveback_price"] >= 0,
                "real held Close peak finite and drawdown nonnegative",
            )
            c.require(
                bool(r["profit_exit_added_vs_base_support"])
                == bool(r["selected_profit_exit"] and not r["support_break"]),
                "risk addition relative to BASE support defined",
            )
            c.require(
                bool(r["profit_exit_added_vs_selected_hold"])
                == bool(r["selected_profit_exit"] and not r["ordinary_support_exit"]),
                "risk addition relative to selected hold defined",
            )
            if r["selected_profit_exit"]:
                c.require(
                    eligible and not r["support_exit_suppressed"],
                    "risk exit overrides generic support protection",
                )
            if r["entry_grace_applied"]:
                c.require(
                    parameters["hold_rule"] == "ENTRY_GRACE"
                    and r["buy_filled_today"]
                    and r["support_break"]
                    and eligible,
                    "entry grace only actual BUY day",
                )
            if r["trend_cycle_activated"]:
                c.require(
                    parameters["hold_rule"] == "TREND_CYCLE"
                    and r["buy_filled_today"]
                    and r["support_break"]
                    and r["trend_cycle_eligible"],
                    "trend protection created on eligible real BUY only",
                )
        else:
            c.require(
                not r["peak_known"]
                and r["peak_close"] is None
                and r["entry_fill_price"] is None
                and not r["trend_cycle_active"],
                "no phantom peak or protection outside actual inventory",
            )
        if r["buy_filled_today"]:
            c.require(
                r["entry_index"] == r["warmup_sessions"]
                and r["deadline_index"] == r["entry_index"] + 9
                and r["reservation_index"] == r["entry_index"] + 10,
                "real buy creates original H10 and reservation",
            )
            c.require(r["giveback_price"] == 0, "entry D peak is actual Close, drawdown zero")
        if r["entry_signal"]:
            c.require(
                not held
                and not r["failed_buy_reset"]
                and r["ready"]
                and r["support_ok"]
                and r["warmup_sessions"] >= r["reservation_index"],
                "original entry/reservation eligibility unchanged",
            )
        if previous and not r["buy_filled_today"]:
            c.require(
                r["reservation_index"] == previous["reservation_index"],
                "reservation changes only with actual new BUY",
            )
        if inherited:
            c.require(
                r["entry_index"] == previous["entry_index"]
                and r["deadline_index"] == previous["deadline_index"]
                and r["exit_pending"],
                "blocked sale retains old clocks and pending",
            )
        previous = r
    return c.result(
        "FIXED_EXANTE_POLICY",
        parameters=parameters,
        first_target_divergence_D=first_difference,
        economic_path_equals_original=first_difference is None,
        reference_result_hash=base["result_hash"],
        feature_math_audit="separate independent B observability audit required",
        annual_metric_audit="separate independent A funded-account audit required",
    )
