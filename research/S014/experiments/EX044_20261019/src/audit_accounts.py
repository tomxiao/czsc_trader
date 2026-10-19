"""Internal funded-state gate; strict fresh control is EX043 actual run004."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
SHARED = ROOT / "research/S014/experiments/EX040_20261019/src/audit_accounts.py"
spec = importlib.util.spec_from_file_location("ex044_shared_account_audit", SHARED)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def frozen_baseline():
    design = json.loads(
        (ROOT / "research/S014/materials/20261019_2024_diagnosis/design_decision.json").read_bytes()
    )
    ref = EvidenceRef.from_dict(design["baseline"]["account_ref"])
    path = ref.resolve(ROOT)
    assert sha256(path.read_bytes()).hexdigest() == ref.sha256
    return json.loads(path.read_bytes())


def audit(account, parameters):
    c = shared.Checks()
    base = frozen_baseline()
    baseline, run = base["runs"][0], account["runs"][0]
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
            "frozen control execution contract " + field,
        )
    for table in ("account_daily", "fills", "orders", "attempts"):
        c.rows(
            run["buyhold"][table]["data"],
            baseline["buyhold"][table]["data"],
            "same embedded buyhold " + table,
        )
    c.require(
        run["buyhold"]["metrics"] == baseline["buyhold"]["metrics"], "same embedded buyhold metrics"
    )
    control = parameters == dict(entry_guard="BASE", exit_domain="POSITIVE_P", cost_stop="BASE")
    rows = tables["decisions"]
    reference = baseline["ledgers"]["decisions"]["data"]
    first = None
    for row, prior in zip(rows, reference, strict=True):
        c.require(
            row["signal_date"] == prior["signal_date"]
            and row["valid_session"] == prior["valid_session"],
            "original D to E clock",
        )
        for field in (
            "ready",
            "support_ok",
            "support_break",
            "support_floor",
            "warmup_sessions",
            "ma20_prior",
            "ma20_prior_lag5",
            "atr20_prior",
            "ret5_log",
            "sigma20_pre5",
            "z5",
            "ma_known",
            "atr_known",
            "atr_positive",
            "sigma20_known",
            "sigma20_positive",
            "shock_known",
        ):
            c.require(row[field] == prior[field], "unchanged market-only feature " + field)
        if first is None and row["target_position"] != prior["target_position"]:
            first = row["signal_date"][:10]
    if control or first is None:
        for table, values in tables.items():
            c.rows(values, baseline["ledgers"][table]["data"], "exact frozen baseline " + table)
        c.rows(run["signals"]["data"], baseline["signals"]["data"], "exact frozen baseline signals")
    else:
        for table, datekey, inclusive in (
            ("decisions", "signal_date", False),
            ("orders", "signal_date", False),
            ("fills", "fill_time", True),
            ("account_daily", "date", True),
        ):

            def before(row, datekey=datekey, inclusive=inclusive):
                day = row[datekey][:10]
                return day <= first if inclusive else day < first

            c.rows(
                [r for r in tables[table] if before(r)],
                [r for r in baseline["ledgers"][table]["data"] if before(r)],
                "original prefix to first role difference " + table,
            )
    previous = None
    for row in rows:
        held = bool(row["held_at_close"])
        inherited = bool(
            previous and previous["exit_pending"] and not row["sell_filled_today"] and held
        )
        deadline = bool(held and row["warmup_sessions"] >= row["deadline_index"])
        eligible = held and not inherited and not deadline
        candidate = bool(
            not held
            and not row["failed_buy_reset"]
            and row["ready"]
            and row["support_ok"]
            and row["warmup_sessions"] >= row["reservation_index"]
        )
        high = bool(row["shock_known"] and row["z5"] > 2)
        blocked = candidate and parameters["entry_guard"] == "BLOCK_SHOCK" and high
        positive_shock = bool(eligible and high and row["net_profit"] > 0)
        selected_shock = bool(
            eligible and high and (parameters["exit_domain"] == "ANY_P" or row["net_profit"] > 0)
        )
        cost_condition = bool(
            eligible and row["atr_positive"] and row["cost_loss_price"] >= row["atr20_prior"]
        )
        selected_cost = parameters["cost_stop"] == "NET_LOSS_1ATR" and cost_condition
        risk = selected_shock or selected_cost
        grace = bool(eligible and row["buy_filled_today"] and row["support_break"])
        ordinary_support = bool(eligible and row["support_break"] and not grace)
        expected = dict(
            pending_inherited=inherited,
            deadline_exit=deadline,
            profit_exit_eligible=eligible,
            original_entry_candidate=candidate,
            candidate_shock=candidate and high,
            entry_guard_blocked=blocked,
            acceleration_condition=eligible and high,
            shock_condition=positive_shock,
            selected_profit_exit=positive_shock,
            selected_shock_exit=selected_shock,
            cost_stop_condition=cost_condition,
            selected_cost_exit=selected_cost,
            selected_risk_exit=risk,
            shock_exit_added_vs_positive=selected_shock and not positive_shock,
            cost_exit_added_vs_baseline=selected_cost and not (positive_shock or ordinary_support),
            risk_exit_added_vs_baseline=risk and not (positive_shock or ordinary_support),
            cost_support_overlap=selected_cost and eligible and row["support_break"],
            cost_grace_override=selected_cost and grace,
            entry_grace_eligible=grace,
            entry_grace_applied=grace and not risk,
            support_exit_suppressed=eligible and row["support_break"] and grace and not risk,
            ordinary_support_exit=ordinary_support,
        )
        for key, value in expected.items():
            c.require(bool(row[key]) == bool(value), "fixed selected role state " + key)
        c.require(
            bool(row["entry_signal"]) == bool(candidate and not blocked),
            "gate changes only admissible flat intent",
        )
        if held:
            pending = inherited or deadline or risk or ordinary_support
            c.require(
                bool(row["exit_pending"]) == pending
                and row["target_position"] == (0.0 if pending else 1.0),
                "mandatory then selected risk then grace/support target",
            )
        else:
            c.require(
                row["target_position"] == float(candidate and not blocked),
                "flat target is original intent after gate",
            )
            c.require(
                row["cost_loss_price"] is None and row["cost_loss_atr"] is None,
                "no phantom entry cost outside real held state",
            )
        if row["buy_filled_today"]:
            c.require(
                row["entry_index"] == row["warmup_sessions"]
                and row["deadline_index"] == row["entry_index"] + 9
                and row["reservation_index"] == row["entry_index"] + 10,
                "actual BUY alone creates original anchors",
            )
            c.require(row["giveback_price"] == 0, "actual entry D Close-only peak drawdown zero")
        if previous and not row["buy_filled_today"]:
            c.require(
                row["reservation_index"] == previous["reservation_index"],
                "blocked gate or SELL never creates reservation",
            )
        if inherited:
            c.require(
                row["entry_index"] == previous["entry_index"]
                and row["deadline_index"] == previous["deadline_index"]
                and row["exit_pending"],
                "blocked SELL locks pending and old anchors",
            )
        previous = row
    return c.result(
        "EX044_FIXED_ROLES",
        parameters=parameters,
        strict_control_against_EX043004=control,
        baseline_result_hash=base["result_hash"],
        first_target_divergence_D=first,
        economic_path_equals_frozen=first is None,
        actual_funded_state_and_feature_math="independent A/B reviews required",
    )
