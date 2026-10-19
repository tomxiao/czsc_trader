"""Internal EX046 funded-state/control gate; independent A/B audits remain required."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
SHARED = ROOT / "research/S014/experiments/EX040_20261019/src/audit_accounts.py"
spec = importlib.util.spec_from_file_location("ex046_shared_account_audit", SHARED)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def sign(value):
    return -1 if value < 0 else 1 if value > 0 else 0


def frozen_baseline():
    design = json.loads((EX / "protocols/design.json").read_bytes())
    ref = EvidenceRef.from_dict(design["baseline_account_ref"])
    path = ref.resolve(ROOT)
    assert sha256(path.read_bytes()).hexdigest() == ref.sha256
    result = json.loads(path.read_bytes())
    assert result["result_hash"] == design["baseline_result_hash"]
    return result


def divergence_dates(rows, reference, daily, reference_daily):
    feedback = next((r["signal_date"][:10] for r in rows if r.get("completed_net_known", False) or r["pause_armed_before_candidate"]), None)
    original = next((r["signal_date"][:10] for r, p in zip(rows, reference, strict=True)
                     if any(r[k] != v for k, v in p.items() if k not in shared.IDS)), None)
    target = next((r["signal_date"][:10] for r, p in zip(rows, reference, strict=True) if r["target_position"] != p["target_position"]), None)
    keys = ("cash", "cash_before", "quantity", "quantity_before", "equity")
    funded = next((r["date"][:10] for r, p in zip(daily, reference_daily, strict=True) if any(r[k] != p[k] for k in keys)), None)
    return feedback, original, target, funded


def audit(account, parameters):
    c = shared.Checks()
    base = frozen_baseline()
    baseline, run = base["runs"][0], account["runs"][0]
    tables = shared.internal(run, c)
    for field in ("symbol", "asset_type", "initial_cash", "costs", "benchmark", "windows", "data_cutoff", "market_rules", "execution_mode", "price_basis", "pricing"):
        c.require(account["request_identity"][field] == base["request_identity"][field], "original execution contract " + field)
    for table in ("account_daily", "fills", "orders", "attempts"):
        c.rows(run["buyhold"][table]["data"], baseline["buyhold"][table]["data"], "embedded buyhold exact " + table)
    c.require(run["buyhold"]["metrics"] == baseline["buyhold"]["metrics"], "embedded buyhold metrics exact")
    rows = tables["decisions"]
    reference = baseline["ledgers"]["decisions"]["data"]
    daily = tables["account_daily"]
    reference_daily = baseline["ledgers"]["account_daily"]["data"]
    first_feedback, first_original, first_target, first_funded = divergence_dates(rows, reference, daily, reference_daily)
    first_armed = next((r["signal_date"][:10] for r in rows if r["pause_armed_before_candidate"]), None)
    control = parameters == {"pause_profile": "BASE"}
    if control or first_original is None:
        for table, values in tables.items():
            c.rows(values, baseline["ledgers"][table]["data"], "fresh cost baseline exact " + table)
        c.rows(run["signals"]["data"], baseline["signals"]["data"], "fresh cost baseline signals exact")
    else:
        for table, datekey, inclusive in (("decisions", "signal_date", False), ("orders", "signal_date", False), ("fills", "fill_time", True), ("account_daily", "date", True)):
            def before(row, datekey=datekey, inclusive=inclusive):
                day = row[datekey][:10]
                return day <= first_original if inclusive else day < first_original
            c.rows([r for r in tables[table] if before(r)], [r for r in baseline["ledgers"][table]["data"] if before(r)], "old state prefix " + table)
    fills_by_day = {}
    for fill in tables["fills"]:
        fills_by_day.setdefault(fill["fill_time"][:10], []).append(fill)
    previous = None
    armed = False
    planned = -1
    entry_fill = None
    last_sign = 0
    known = False
    daily_by_date = {r["date"][:10]: r for r in daily}
    for row, prior, value in zip(rows, reference, daily, strict=True):
        D = row["signal_date"][:10]
        c.require(
            D == value["signal_date"][:10] == prior["signal_date"][:10]
            and row["valid_session"][:10] == value["date"][:10]
            and row["valid_session"] == prior["valid_session"],
            "complete original D signal to next-E daily clock",
        )
        if D in daily_by_date:
            decision_day_state = daily_by_date[D]
        else:
            c.require(D == "2019-12-31" and row is rows[0], "only original prewindow D has initial state")
            decision_day_state = {"cash": 100000.0, "quantity": 0}
        c.require(decision_day_state["cash"] >= 0, "D actual cash or explicit original100000 prewindow state")
        for field in ("ready", "support_ok", "support_break", "support_floor", "warmup_sessions", "ma20_prior", "ma20_prior_lag5", "atr20_prior", "ret5_log", "sigma20_pre5", "z5", "ma_known", "atr_known", "atr_positive", "sigma20_known", "sigma20_positive", "shock_known"):
            c.require(row[field] == prior[field], "inherited feature exact " + field)
        today = fills_by_day.get(D, [])
        buys = [f for f in today if f["side"] == "BUY"]
        sells = [f for f in today if f["side"] == "SELL"]
        c.require(len(today) <= 1, "original one actual full-position fill per D")
        c.require(bool(row["buy_filled_today"]) == bool(buys) and bool(row["sell_filled_today"]) == bool(sells), "runtime flags match actual funded fills")
        c.require(bool(row["held_at_close"]) == bool(decision_day_state["quantity"] > 0), "runtime position matches actual funded inventory")
        if buys:
            c.require(entry_fill is None, "actual BUY from flat")
            entry_fill = buys[0]
            planned = -1
        completed = None
        if sells:
            c.require(entry_fill is not None, "actual SELL completes actual own BUY")
            if entry_fill is not None:
                f = sells[0]
                c.require(f["quantity"] == entry_fill["quantity"] > 0, "completed same positive funded quantity")
                completed = f["price"] * f["quantity"] - f["fees"] - (entry_fill["price"] * entry_fill["quantity"] + entry_fill["fees"])
                per_unit = f["price"] * .999 - entry_fill["price"] * 1.001
                c.require(sign(completed) == sign(per_unit) == sign(row["completed_net_unit"]), "strict real completed net signs agree without epsilon")
                last_sign = sign(completed)
                known = True
                armed = (parameters["pause_profile"] == "AFTER_NET_LOSS_SKIP1" and last_sign < 0) or (parameters["pause_profile"] == "AFTER_NET_PROFIT_SKIP1" and last_sign > 0)
                entry_fill = None
        c.require(bool(row["completed_cycle_today"]) == bool(sells), "completion only actual SELL")
        c.require(bool(row["completed_loss_today"]) == bool(sells and last_sign < 0) and bool(row["completed_profit_today"]) == bool(sells and last_sign > 0) and bool(row["completed_zero_today"]) == bool(sells and last_sign == 0), "completed sign flags exact")
        c.require(bool(row["completed_net_known"]) == known and row["last_completed_sign"] == last_sign, "own completed memory causal")
        c.require((row["completed_net_unit"] is not None) == bool(sells), "raw completion value only known on actual close")
        before = row["warmup_sessions"] + 10 if buys else previous["reservation_index"] if previous else -1
        candidate = bool(not row["held_at_close"] and not row["failed_buy_reset"] and row["ready"] and row["support_ok"] and row["warmup_sessions"] >= before)
        consumed = candidate and armed
        c.require(bool(row["pause_armed_before_candidate"]) == armed and row["reservation_before_pause"] == before, "pre-candidate feedback and old reservation")
        if consumed:
            before = row["warmup_sessions"] + 11
            planned = before
            armed = False
        c.require(row["reservation_index"] == before and row["planned_slot_until"] == planned, "only real BUY or one-shot slot changes clock")
        c.require(bool(row["pause_armed"]) == armed and bool(row["pause_slot_consumed"]) == consumed, "one-shot disarm after consumption")
        c.require(bool(row["planned_slot_active"]) == bool(not row["held_at_close"] and planned >= 0 and row["warmup_sessions"] < planned), "planned window is no actual position")
        c.require(bool(row["original_entry_candidate"]) == candidate and bool(row["entry_signal"]) == (candidate and not consumed), "old candidate then pause only flat intent")
        c.require(not row["entry_guard_blocked"] and row["cost_stop_active"] and not row["entry_guard_active"] and not row["exit_domain_any"], "cost baseline flags fixed")
        if consumed:
            c.require(row["target_position"] == 0 and not row["held_at_close"] and row["entry_index"] == -1 and row["deadline_index"] == -1 and row["entry_fill_price"] is None and not row["failed_buy_reset"], "skipped slot creates no actual cycle")
        if row["held_at_close"]:
            inherited = bool(previous and previous["exit_pending"] and not sells)
            expired = row["warmup_sessions"] >= row["deadline_index"]
            eligible = not inherited and not expired
            shock = bool(eligible and row["shock_known"] and row["z5"] > 2 and row["net_profit"] > 0)
            cost = bool(eligible and row["atr_positive"] and row["cost_loss_price"] >= row["atr20_prior"])
            grace = bool(eligible and buys and row["support_break"])
            pending = inherited or expired or shock or cost or (eligible and row["support_break"] and not grace)
            c.require(bool(row["exit_pending"]) == pending and row["target_position"] == (0.0 if pending else 1.0), "original pending deadline cost shock grace support exits")
        previous = row
    return c.result("EX046_FIXED_COMPLETED_SIGN_PAUSES", parameters=parameters, strict_control_against_EX044004=control,
        baseline_result_hash=base["result_hash"], first_feedback_state_D=first_feedback, first_armed_D=first_armed, first_original_state_divergence_D=first_original,
        first_target_divergence_D=first_target, first_funded_state_E=first_funded, target_path_equals_frozen=first_target is None,
        funded_wealth_path_equals_frozen=first_funded is None, actual_funded_state_and_feature_math="independent A/B reviews required")
