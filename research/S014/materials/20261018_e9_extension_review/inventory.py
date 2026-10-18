"""E9 date and potential-entry inventory; no new wealth labels or matching."""
import io
import json
from hashlib import sha256
from pathlib import Path

import pandas as pd

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def main():
    assert not (OUT / "inventory.json").exists()
    old_path = ROOT / "research/S014/materials/20261018_action_value_method_review/inventory.json"
    old = json.loads(old_path.read_bytes())
    account_ref = EvidenceRef.from_dict(old["sources"]["public_account_C0011"]["public_ref"])
    raw = account_ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == account_ref.sha256
    account = json.loads(raw)
    assert account["result_hash"] == old["sources"]["public_account_C0011"]["result_hash"]
    # Only dates, policy inputs and already-verified exit dates are used.
    decisions = pd.DataFrame(account["runs"][0]["ledgers"]["decisions"]["data"])[
        ["signal_date", "ready", "parent", "high"]]
    decisions.signal_date = pd.to_datetime(decisions.signal_date).dt.strftime("%Y-%m-%d")
    decisions = decisions.set_index("signal_date")
    cal_ref = EvidenceRef.from_dict(old["sources"]["research/S014/experiments/EX033_20261018/others/calendar.csv"]["public_ref"])
    cal_raw = cal_ref.resolve(ROOT).read_bytes()
    assert sha256(cal_raw).hexdigest() == cal_ref.sha256
    dates = pd.read_csv(io.BytesIO(cal_raw)).date.tolist()
    events = []
    for node in old["events"]:
        ix = dates.index(node["entry_date"])
        ds = {f"E{k}": dates[ix+k] if ix+k < len(dates) else None for k in (2,6,7,8,9)}
        assert ds["E2"] == node["E2"] and ds["E9"] == node["E9"]
        eligible = ds["E2"] is not None and ds["E9"] is not None
        row = {"cycle_id": node["cycle_id"], "entry_date": node["entry_date"],
               "entry_year": node["entry_year"], "decision_year": node["decision_year"],
               **ds, "eligible": eligible, "route": "CENSORED", "potential_buy_decisions": []}
        if eligible:
            assert node["same_quantity_H6_actual_exit"] == ds["E6"]
            assert node["original_actual_exit"] <= ds["E6"]
            for day in (ds["E6"], ds["E7"], ds["E8"]):
                state = decisions.loc[day]
                assert state.notna().all()
                assert all(v in (0,1,False,True) for v in state)
                qualified = bool(state.ready and state.parent and state.high)
                row["potential_buy_decisions"].append({"day": day, "ready": bool(state.ready),
                    "parent": bool(state.parent), "high": bool(state.high), "potential_entry": qualified})
            row["route"] = "PUBLIC_H_REPLAY_REQUIRED" if any(x["potential_entry"] for x in row["potential_buy_decisions"]) else "EXACT_H_CASH_REUSE"
        events.append(row)
    eligible = [x for x in events if x["eligible"]]
    replay = [x for x in eligible if x["route"] == "PUBLIC_H_REPLAY_REQUIRED"]
    cash = [x for x in eligible if x["route"] == "EXACT_H_CASH_REUSE"]
    assert len(eligible) == 145 and len(events) == 147
    result = {"status": "PASS_METADATA_ONLY", "events": events,
        "counts": {"original_entries": len(events), "E9_eligible": len(eligible),
                   "H_replay": len(replay), "H_cash_reuse": len(cash), "censored": len(events)-len(eligible),
                   "proposed_accounts_including_one_noop_control": len(replay)+1},
        "by_decision_year": {str(y): {"eligible": sum(x["decision_year"]==y for x in eligible),
                                      "replay": sum(x["decision_year"]==y for x in replay),
                                      "cash_reuse": sum(x["decision_year"]==y for x in cash)} for y in range(2020,2027)},
        "sources": {"C0011": account_ref.to_dict(), "calendar": cal_ref.to_dict(),
                    "prior_inventory_sha256": sha256(old_path.read_bytes()).hexdigest(),
                    "C0011_result_hash": account["result_hash"]},
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "proof_obligation": "C0011 ready,parent,high independent of portfolio and intervention; no qualifying close at E6/E7/E8 implies no H order at E7/E8/E9 after verified E6 sale. Keep these nodes in full population.",
        "not_a_signal": "Future opportunity flags only choose exact computation route; never used at D as predictive feature or sample screen",
        "new_calls": 0, "new_wealth_labels": 0, "new_accounts": 0, "new_matching": 0, "new_fits": 0}
    with (OUT / "inventory.json").open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"counts":result["counts"],"by_decision_year":result["by_decision_year"]}))


if __name__ == "__main__":
    main()
