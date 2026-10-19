"""Read two completed actual account records; no simulation, market API or fitting."""

import hashlib
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path("research/S014/materials/20261020_2026_diagnosis")
EX = Path("research/S014/experiments/EX048_20261020")
CHECKS = {}
HASHES = {}


def check(key, condition):
    assert bool(condition), key
    CHECKS[key] = CHECKS.get(key, 0) + 1


def read(path):
    raw = path.read_bytes()
    HASHES[path.as_posix()] = hashlib.sha256(raw).hexdigest()
    return raw


def load(path):
    return json.loads(read(path))


def day(value):
    return str(value)[:10]


def main():
    destination = BASE / "review/interaction_actual_result_evidence.json"
    if destination.exists():
        raise FileExistsError(destination)
    design = load(BASE / "interaction_design_decision.json")
    check("fixed method root lock", HASHES[(BASE / "interaction_design_decision.json").as_posix()] == "07e29822842e997e7757bf45dc39d22f84af6af7d7f78df45c49b472b1af6da4")
    index = load(EX / "others/accounts_index.json")
    check("fixed two actual SUCCEEDED", len(index["records"]) == 2 and all(r["status"] == "SUCCEEDED" and r["audit"]["status"] == "PASS" for r in index["records"]))
    result = []
    # Both actual arms and their independent audits are required before reading results.
    reports = [load(BASE / f"accounting/interaction_account_{i:03d}_independent_review.json") for i in range(2)]
    check("both independently audited actual PASS", all(r["status"] == "PASS" for r in reports))
    for i, report in enumerate(reports):
        ref = EvidenceRef.from_dict(report["account_ref"])
        raw = ref.resolve(ROOT).read_bytes()
        check("actual published bytes", hashlib.sha256(raw).hexdigest() == ref.sha256)
        account = json.loads(raw)
        tables = {k: v["data"] for k, v in account["runs"][0]["ledgers"].items()}
        fills_by_date = {}
        for f in tables["fills"]:
            fills_by_date.setdefault(day(f["fill_time"]), []).append(f)
        active = None
        last_sign, completed, suppressed = 0, [], []
        for d in tables["decisions"]:
            date = day(d["signal_date"])
            today = fills_by_date.get(date, [])
            buys, sells = [f for f in today if f["side"] == "BUY"], [f for f in today if f["side"] == "SELL"]
            for buy in buys:
                check("actual new entry no existing position", active is None)
                active = buy
            for sell in sells:
                check("actual closure matches prior actual entry", active is not None and active["cycle_id"] == sell["cycle_id"])
                unit = sell["price"] * .999 - active["price"] * 1.001
                money = (sell["price"] - active["price"]) * active["quantity"] - active["fees"] - sell["fees"]
                last_sign = (unit > 0) - (unit < 0)
                check("actual perunit and funded net strict sign", last_sign == ((money > 0) - (money < 0)))
                completed.append({"cycle_id": active["cycle_id"], "entry_E": day(active["fill_time"]), "exit_E": date, "entry_price": active["price"], "exit_price": sell["price"], "quantity": active["quantity"], "net_cash": money, "strict_sign": last_sign})
                active = None
            check("own completed sign versus actual fill chronology", int(d["last_completed_sign"]) == last_sign)
            check("completion flag versus actual sells", bool(d["completed_cycle_today"]) == bool(sells))
            check("held D follows actual fill chronology", bool(d["held_at_close"]) == bool(active))
            check("selected raw role separate", not bool(d["selected_shock_exit"]))
            check("fixed OFF actual risk is cost only", bool(d["selected_risk_exit"]) == bool(d["selected_cost_exit"] or d["selected_shock_exit"]))
            if d["shock_action_suppressed"]:
                check("both interaction arms preserve OFF suppression", bool(d["shock_condition"]) and d["target_position"] == 1 and active is not None)
                suppressed.append({"D": date, "next_E": d["valid_session"], "cycle_id": active["cycle_id"], "entry_E": day(active["fill_time"]), "holding_age": d["holding_age"], "net_profit_D": d["net_profit"], "z5_D": d["z5"], "reservation_index": d["reservation_index"], "deadline_index": d["deadline_index"]})
            check("constant pause profile authenticated", bool(d["pause_loss_profile"]) == (i == 0) and not d["pause_profit_profile"])
            if i == 1:
                check("BASE no pause action", not d["pause_armed"] and not d["pause_armed_before_candidate"] and not d["pause_slot_consumed"])
            if d["pause_slot_consumed"]:
                check("actual own-loss one-shot slot", last_sign == -1 and active is None and not d["pause_armed"] and not d["entry_signal"])
        yearly = []
        for y in design["profiles"]:
            check("only locked profile names", y in ("AFTER_NET_LOSS_SKIP1", "BASE"))
        for year in range(2020, 2027):
            yr = [r for r in report["original_annual_goal_audit"] if r["year"] == year]
            check("all original seven annual rows", len(yr) == 1)
            sy = [r for r in suppressed if r["D"].startswith(str(year))]
            yearly.append({"year": year, "suppressed_D": len(sy), "suppressed_distinct_actual_cycles": len({r["cycle_id"] for r in sy}), "actual_BUYs": sum(f["side"] == "BUY" and day(f["fill_time"]).startswith(str(year)) for f in tables["fills"]), "actual_SELLs": sum(f["side"] == "SELL" and day(f["fill_time"]).startswith(str(year)) for f in tables["fills"]), "fees": sum(f["fees"] for f in tables["fills"] if day(f["fill_time"]).startswith(str(year))), "annual": yr[0]})
        cases = [c for c in completed if (c["entry_E"].startswith("2026") or c["exit_E"].startswith("2026") or "2025-05-01" <= c["entry_E"] <= "2025-06-30")]
        result.append({"policy": report["policy_id"], "account_ref": report["account_ref"], "result_hash": report["result_hash"], "summary": report["summary"], "boundary2026": report["boundary2026_actuals"], "prefix": report["prefix"], "annual_counts_and_metrics": yearly, "actual_completed_cases": cases, "suppressed_states": suppressed, "cutoff_open_actual_entry": active})
    HASHES[Path(__file__).relative_to(ROOT).as_posix()] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output = {"status": "PASS", "reviewed_hashes": HASHES, "checks": CHECKS, "check_count": sum(CHECKS.values()), "policies": result, "interpretation_limit": "Actual per-policy completed chronology and selected action audit; observed suppression-D rows are repeated states within cycles, not independent samples or alternative exit returns.", "new_accounts": 0, "new_market_calls": 0, "prepared_fetches": 0, "new_replays": 0, "fits": 0}
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "checks": output["check_count"], "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "summaries": [{"policy": r["policy"], "summary": r["summary"]} for r in result]}))


if __name__ == "__main__":
    main()
