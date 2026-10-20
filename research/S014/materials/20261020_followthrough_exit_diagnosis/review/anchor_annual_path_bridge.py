"""Saved actual ledger attribution only; no replay, new price request or label."""

import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "research/S014/materials/20261020_followthrough_exit_diagnosis"
EX = ROOT / "research/S014/experiments/EX051_20261020"
HASHES = {}


def bind(path, expected=None):
    content = path.read_bytes()
    actual = sha256(content).hexdigest()
    if expected is not None:
        assert actual == expected, str(path)
    HASHES[path.relative_to(ROOT).as_posix()] = actual
    return content


def dec(value):
    return Decimal(str(value))


def main():
    annual_path = BASE / "accounting/anchor_policy_yearly_summary.csv"
    content = bind(annual_path, "fc6f8825e1fd600f8190ae9e90d355d4e226f82dae5f21c54eba3212e9c096a4")
    official = {(r["diagID"], int(r["year"])): r for r in csv.DictReader(content.decode().splitlines())}
    cycles, annual, pauses, account_refs = [], [], [], {}
    for index in range(3):
        receipt = json.loads(bind(EX / f"others/accounts/run-{index:03}.json"))
        ref = receipt["evidence"]
        path = ROOT / "research/S014/assets/evidence/EX051_20261020" / ref["evidence_id"]
        account = json.loads(bind(path, ref["sha256"]))
        assert account["result_hash"] == receipt["result_hash"]
        account_refs[str(index)] = ref
        tables = {key: value["data"] for key, value in account["runs"][0]["ledgers"].items()}
        fills_by_day, fills_by_cycle = {}, {}
        for fill in tables["fills"]:
            fills_by_day.setdefault(fill["fill_time"][:10], []).append(fill)
            fills_by_cycle.setdefault(fill["cycle_id"], {})[fill["side"]] = fill
        active, previous = None, dec(100000)
        groups, year_open, year_close = {}, {}, {}
        for row in tables["account_daily"]:
            day, year = row["date"][:10], int(row["date"][:4])
            change = dec(row["equity"]) - previous
            year_open.setdefault(year, previous)
            year_close[year] = dec(row["equity"])
            fills = fills_by_day.get(day, [])
            assert len(fills) <= 1
            scope = active
            if fills and fills[0]["side"] == "BUY":
                assert active is None
                active = fills[0]["cycle_id"]
                scope = active
            elif fills:
                assert active == fills[0]["cycle_id"]
                scope, active = active, None
            if year in (2025, 2026):
                key = (year, scope or "FLAT")
                groups[key] = groups.get(key, Decimal(0)) + change
            previous = dec(row["equity"])
        cid = f"S014-C{9510 + index}"
        for year in (2025, 2026):
            total = sum((value for (y, _), value in groups.items() if y == year), Decimal(0))
            assert total == year_close[year] - year_open[year]
            record = official[(cid, year)]
            assert float(record["opening_equity"]) == float(year_open[year])
            assert float(record["closing_equity"]) == float(year_close[year])
            annual.append({"diagID": cid, "year": year, "own_year_opening": float(year_open[year]),
                           "closing": float(year_close[year]), "marked_pnl": float(total),
                           "sum_contribution": float(total / year_open[year]),
                           "official_return": float(record["return"]),
                           "float_representation_residual": float(record["return"]) - float(total / year_open[year]),
                           "decimal_telescoping_exact": True})
            for (scope_year, cycle_id), value in groups.items():
                if scope_year != year:
                    continue
                pair = fills_by_cycle.get(cycle_id, {})
                buy, sell = pair.get("BUY"), pair.get("SELL")
                net = ((dec(sell["price"]) * dec(sell["quantity"]) - dec(sell["fees"]))
                       - (dec(buy["price"]) * dec(buy["quantity"]) + dec(buy["fees"]))) if buy and sell else None
                cycles.append({"diagID": cid, "year": year, "cycle_id": cycle_id,
                               "actual_entry_E": buy["fill_time"][:10] if buy else None,
                               "actual_exit_E": sell["fill_time"][:10] if sell else None,
                               "actual_entry_price": buy["price"] if buy else None,
                               "actual_exit_price": sell["price"] if sell else None,
                               "actual_quantity": buy["quantity"] if buy else None,
                               "closed_whole_cycle_net_provenance": float(net) if net is not None else None,
                               "annual_marked_pnl": float(value), "own_year_opening": float(year_open[year]),
                               "annual_marked_contribution": float(value / year_open[year]),
                               "annual_marked_pnl_decimal": str(value)})
        dates = {r["warmup_sessions"]: r["signal_date"][:10] for r in tables["decisions"]}
        for row in tables["decisions"]:
            if int(row["signal_date"][:4]) in (2025, 2026) and row["pause_slot_consumed"]:
                pauses.append({"diagID": cid, "D": row["signal_date"][:10],
                               "planned_E": row["valid_session"][:10], "reservation_until": row["planned_slot_until"],
                               "eligible_again_D": dates.get(row["planned_slot_until"]),
                               "last_completed_sign": row["last_completed_sign"]})
    target = BASE / "review/anchor_actual_2025_2026_cycle_bridge.csv"
    with target.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cycles[0]))
        writer.writeheader()
        writer.writerows(cycles)
    bind(target)
    bind(Path(__file__).resolve())
    differences = []
    for index in (1, 2):
        cid = f"S014-C{9510 + index}"
        for year in (2025, 2026):
            matched = {}
            for row in cycles:
                if row["year"] == year and row["diagID"] in ("S014-C9510", cid):
                    matched.setdefault(row["actual_entry_E"], {})[row["diagID"]] = row
            for entry, rows in matched.items():
                control = rows.get("S014-C9510", {}).get("annual_marked_contribution", 0.0)
                treatment = rows.get(cid, {}).get("annual_marked_contribution", 0.0)
                differences.append({"diagID": cid, "year": year, "entry_E": entry,
                                    "control_contribution": control, "treatment_contribution": treatment,
                                    "treatment_minus_control_contribution": treatment - control,
                                    "control_actual_cycle_present": "S014-C9510" in rows,
                                    "treatment_actual_cycle_present": cid in rows})
    result = {
        "status": "PASS_ACTUAL_YEAR_MARK_ATTRIBUTION", "reviewer": "B", "blocking_findings": [],
        "reviewed_hashes": HASHES, "account_refs": account_refs,
        "annual_exact_decimal_bridges": annual,
        "actual_entry_date_contribution_difference_description": differences,
        "actual_2025_2026_pause_slots": pauses,
        "method": "Assign saved daily equity change to the actual funded cycle carried into, entered or sold on E. Own year-opening denominators. Decimal(str(saved equity)) differences telescope exactly. Retain float representation residual to published annual return; no new epsilon or acceptance rule.",
        "limits": ["Descriptive account accounting, not causal ablation or equal-Q experiment.",
                   "Missing-cycle zero is only zero actual ledger contribution; absent trade fields remain null, not zero-priced fills.",
                   "Cross-year annual marks differ from whole-trade net proceeds. Never sum cycle percentage returns as account return.",
                   "Real policy population and own completed-loss feedback differ after each exit; raw same-cycle threshold nesting does not imply nested full policy economics."],
        "new_funded_accounts": 0, "new_market_calls": 0, "new_prepared_fetches": 0, "new_fits": 0,
    }
    review = BASE / "review/anchor_actual_path_bridge_review.json"
    with review.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"review": review.relative_to(ROOT).as_posix(), "sha256": sha256(review.read_bytes()).hexdigest(),
                      "cycle_rows": len(cycles), "annual_bridges": len(annual),
                      "important_2026_differences": [r for r in differences if r["year"] == 2026 and r["entry_E"] in ("2026-01-26", "2026-02-10", "2026-03-05", "2026-08-27")],
                      "pause_slots": pauses}, ensure_ascii=False))


if __name__ == "__main__":
    main()
