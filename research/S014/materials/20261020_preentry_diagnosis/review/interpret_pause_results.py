"""Read saved funded account evidence only; no market access or policy replay."""

import csv
import hashlib
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path("research/S014/materials/20261020_preentry_diagnosis")
OUT = BASE / "review"
CAP = "2025-12-31"
hashes = {}
checks = {}


def check(name, condition):
    assert condition, name
    checks[name] = checks.get(name, 0) + 1


def read(path):
    raw = path.read_bytes()
    hashes[path.as_posix()] = hashlib.sha256(raw).hexdigest()
    return raw


def load(path):
    return json.loads(read(path))


def table(path):
    return list(csv.DictReader(read(path).decode("utf-8-sig").splitlines()))


def day(value):
    return str(value)[:10]


def save(name, obj):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    annual = table(BASE / "accounting/pause_policy_yearly_summary.csv")
    summary = table(BASE / "accounting/pause_policy_summary.csv")
    total = load(BASE / "accounting/independent_pause_audit_summary.json")
    load(BASE / "accounting/pause_original_mandate_clarification.json")
    load(BASE / "accounting/preentry_research_findings.json")
    load(BASE / "accounting/preentry_accounting_summary_v2.json")
    load(BASE / "design_decision.json")
    load(OUT / "technical_revision_review.json")
    index = load(Path("research/S014/experiments/EX046_20261020/others/accounts_index.json"))
    check("three actual SUCCEEDED", len(index["records"]) == 3 and all(r["status"] == "SUCCEEDED" for r in index["records"]))
    check("old internal BASE failure preserved", index["records"][0]["audit"]["status"] == "FAIL")
    check("three A independent PASS", total["status"] == "PASS" and len(total["account_reports"]) == 3)
    check("18 annual and 3 summary", len(annual) == 18 and len(summary) == 3)
    evidence, policies, slots = [], [], []
    for i in range(3):
        report_path = BASE / f"accounting/pause_account_{i:03d}_independent_review.json"
        report = load(report_path)
        check("independent report PASS", report["status"] == "PASS")
        ref = EvidenceRef.from_dict(report["account_ref"])
        raw = ref.resolve(ROOT).read_bytes()
        check("actual account bytes", hashlib.sha256(raw).hexdigest() == ref.sha256)
        account = json.loads(raw)
        ledgers = {k: v["data"] for k, v in account["runs"][0]["ledgers"].items()}
        # Filter the authorized economic population BEFORE extraction or reporting.
        decisions = [r for r in ledgers["decisions"] if "2020-01-01" <= day(r["signal_date"]) <= CAP]
        fills = [r for r in ledgers["fills"] if "2020-01-01" <= day(r["fill_time"]) <= CAP]
        orders = [r for r in ledgers["orders"] if "2020-01-01" <= day(r["signal_date"]) <= CAP]
        daily = {day(r["date"]): r for r in ledgers["account_daily"] if "2020-01-01" <= day(r["date"]) <= CAP}
        cycles = [r for r in ledgers["trades"] if "2020-01-01" <= day(r["entry_date"]) <= CAP]
        by_index = {int(r["warmup_sessions"]): day(r["signal_date"]) for r in decisions}
        completed = []
        for trade in cycles:
            if trade["status"] != "CLOSED" or day(trade["exit_date"]) > CAP:
                continue
            cf = [f for f in fills if f["cycle_id"] == trade["cycle_id"]]
            buys, sells = [f for f in cf if f["side"] == "BUY"], [f for f in cf if f["side"] == "SELL"]
            check("actual complete BUY SELL", len(buys) == len(sells) == 1)
            buy, sell = buys[0], sells[0]
            net = (sell["price"] - buy["price"]) * buy["quantity"] - buy["fees"] - sell["fees"]
            net_unit = sell["price"] * .999 - buy["price"] * 1.001
            sign = (net_unit > 0) - (net_unit < 0)
            check("strict actual net sign", sign == ((net > 0) - (net < 0)))
            completed.append({"cycle_id": trade["cycle_id"], "entry_E": day(buy["fill_time"]), "exit_E": day(sell["fill_time"]), "entry_price": buy["price"], "exit_price": sell["price"], "quantity": buy["quantity"], "net_cash": net, "net_return": trade["net_return"], "strict_sign": sign})
        policy = report["policy_id"]
        ownslots = []
        for d in decisions:
            if not d["pause_slot_consumed"]:
                continue
            date, idx = day(d["signal_date"]), int(d["warmup_sessions"])
            prior = [c for c in completed if c["exit_E"] <= date]
            latest = max(prior, key=lambda c: c["exit_E"])
            check("slot own actual latest feedback", latest["strict_sign"] == int(d["last_completed_sign"]))
            check("slot intended signed direction", latest["strict_sign"] == (-1 if i == 1 else 1))
            check("slot i plus 11", d["reservation_index"] == idx + 11)
            check("slot candidate flat no target", bool(d["original_entry_candidate"]) and not d["held_at_close"] and d["target_position"] == 0)
            check("slot clears armed", not d["pause_armed"])
            check("slot no BUY order", not any(o["signal_date"] == date and o["side"] == "BUY" for o in orders))
            future_orders = [o for o in orders if o["side"] == "BUY" and o["signal_date"] > date]
            next_order = min(future_orders, key=lambda o: o["signal_date"]) if future_orders else None
            rec = {"policy": policy, "D": date, "next_E": d["valid_session"], "own_latest_completed": latest, "same_D_completion": latest["exit_E"] == date, "reservation_before": d["reservation_before_pause"], "reservation_after": d["reservation_index"], "eligible_again_D": by_index.get(idx + 11), "next_actual_BUY_order": next_order}
            ownslots.append(rec)
            slots.append(rec)
        years = []
        for year in range(2020, 2026):
            yf = [f for f in fills if day(f["fill_time"]).startswith(str(year))]
            yd = [d for d in decisions if d["signal_date"].startswith(str(year))]
            yc = [c for c in completed if c["exit_E"].startswith(str(year))]
            # Actual realized cash per cycle is descriptive: cross-year capital is not an annual return.
            years.append({"year": year, "actual_BUY_fills": sum(f["side"] == "BUY" for f in yf), "actual_SELL_fills": sum(f["side"] == "SELL" for f in yf), "fees": sum(f["fees"] for f in yf), "actual_held_D": sum(bool(d["held_at_close"]) for d in yd), "slots": sum(s["D"].startswith(str(year)) for s in ownslots), "same_D_completion_slots": sum(s["same_D_completion"] and s["D"].startswith(str(year)) for s in ownslots), "completed_profit_count": sum(c["strict_sign"] > 0 for c in yc), "completed_loss_count": sum(c["strict_sign"] < 0 for c in yc)})
        cases = {"2024_actual_closed_cycles": [c for c in completed if c["entry_E"].startswith("2024")], "2025_April_June_actual_closed_cycles": [c for c in completed if "2025-04-01" <= c["entry_E"] <= "2025-06-30"], "2025_April_June_slots": [s for s in ownslots if "2025-04-01" <= s["D"] <= "2025-06-30"]}
        policies.append({"policy": policy, "annual_descriptive_counts": years, "own_completed_cycles": len(completed), "slot_count": len(ownslots), "cases": cases, "terminal2025_actual_equity": daily[CAP]["equity"], "prefix": report["prefix"]})
        evidence.append({"account_ref": report["account_ref"], "result_hash": report["result_hash"]})
    hashes[Path(__file__).relative_to(ROOT).as_posix()] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save("pause_path_interpretation_evidence.json", {"status": "PASS", "scope": "Saved actual evidence arithmetic only;2020-25 extracted; no policy replay, no market fetch, no 2026 economic selection", "reviewed_hashes": hashes, "actual_evidence": evidence, "annual_table": annual, "summary_table": summary, "policies": policies, "slots": slots, "checks": checks, "check_count": sum(checks.values()), "resources": {"new_accounts": 0, "new_market_calls": 0, "prepared_fetches": 0, "new_policy_replays": 0, "fits": 0}})
    print(json.dumps({"checks": sum(checks.values()), "policies": [{"policy": p["policy"], "slot_count": p["slot_count"], "years": p["annual_descriptive_counts"]} for p in policies]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
