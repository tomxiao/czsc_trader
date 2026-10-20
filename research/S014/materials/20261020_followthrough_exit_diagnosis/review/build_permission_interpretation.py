"""Bounded EX052 actual economic readout; no new account, label or market data."""

import csv
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "research/S014/materials/20261020_followthrough_exit_diagnosis"
HASHES = {}


def read_bytes(path, expected=None):
    content = path.read_bytes()
    digest = sha256(content).hexdigest()
    if expected is not None:
        assert digest == expected
    HASHES[path.relative_to(ROOT).as_posix()] = digest
    return content


def read(path, expected=None):
    return json.loads(read_bytes(path, expected))


def table(name, expected=None):
    return list(csv.DictReader(read_bytes(BASE / "accounting" / name, expected).decode().splitlines()))


def main():
    yearly = table("permission_policy_yearly_summary.csv", "620f3833566fd7ecd58cf4ae08bb610cc9d13daaa9569f92d0eaac7bce1e5b34")
    summary = table("permission_policy_summary.csv", "75b16443b5e9191700a87d6c60e9d4fc5a12afd6bbefc1e0684d854de4623449")
    events = table("permission_actual_events.csv")
    audit = read(BASE / "accounting/independent_permission_audit_summary.json", "9d3d6fdb8d93bf716035e6be09b617e9665b2ae1d8222675325967cac814edc7")
    reports = [read(ROOT / ref["path"], ref["sha256"]) for ref in audit["account_reports"]]
    for row in yearly:
        required = max(0.0, 1.5 * float(row["buyhold_return"]))
        assert required == float(row["required_return"])
        assert (float(row["return"]) >= required) == (row["return_pass"] == "True")
        assert (float(row["max_drawdown"]) < float(row["buyhold_drawdown"])) == (row["drawdown_pass"] == "True")
    treatment = next(r for r in summary if r["diagID"] == "S014-C9521")
    assert treatment["all_original_economic_goals_pass"] == "True"
    assert float(treatment["frequency_full_contract"]) == 60 * int(treatment["closed_trades_full_contract"]) / int(treatment["sessions_full_contract"])
    assert float(treatment["frequency_full_contract"]) >= 3
    own_events = [r for r in events if r["diagID"] == "S014-C9521"]
    assessed = [r for r in own_events if r["S1_evaluated"] == "True"]
    allowed = [r for r in assessed if r["S1_true"] == "True"]
    refused = [r for r in assessed if r["S1_true"] == "False"]
    assert len(assessed) == 16 and len(allowed) == 7 and len(refused) == 9
    bridge = read(BASE / "review/permission_actual_path_bridge_review.json", "3d662bfe95efcd94da9f5c9462cae53342ecec959b769646a241078ed2ac9545")
    read_bytes(BASE / "review/permission_actual_2025_2026_cycle_bridge.csv")
    report = next(r for r in reports if r["parameters"] == {"permission_profile": "AGE_PRIOR_TREND_PERMISSION"})
    ref = report["account_ref"]
    account_path = ROOT / "research/S014/assets/evidence/EX052_20261020" / ref["evidence_id"]
    account = read(account_path, ref["sha256"])
    assert account["result_hash"] == report["result_hash"]
    decisions = {r["signal_date"][:10]: r for r in account["runs"][0]["ledgers"]["decisions"]["data"]}
    d = decisions["2025-04-09"]
    assert not d["pause_slot_consumed"] and d["entry_signal"] and d["last_completed_sign"] == 1
    april_state = {key: d[key] for key in ("signal_date", "valid_session", "entry_signal", "pause_armed", "pause_slot_consumed", "last_completed_sign", "reservation_index", "target_position")}
    trades = account["runs"][0]["ledgers"]["trades"]["data"]
    april = next(r for r in trades if r["entry_date"].startswith("2025-04-10"))
    selected_cases = [r for r in events if r["D"] in ("2021-02-09", "2023-02-01", "2024-01-03", "2025-03-27", "2025-06-19", "2026-01-06", "2026-01-09", "2026-01-29", "2026-02-11", "2026-03-06", "2026-09-01")]
    differences = [r for r in bridge["actual_entry_date_contribution_difference_description"] if r["year"] == 2025]
    march = next(r["treatment_minus_control_contribution"] for r in differences if r["entry_E"] == "2025-03-21")
    april_difference = next(r["treatment_minus_control_contribution"] for r in differences if r["entry_E"] == "2025-04-10")
    annual_delta = next(float(r["return_difference_vs_C9502"]) for r in yearly if r["diagID"] == "S014-C9521" and r["year"] == "2025")
    read_bytes(Path(__file__).resolve())
    result = {
        "status": "PASS_ORIGINAL_ALL_SEVEN_ECONOMIC_GOALS_HISTORICAL_DIAGNOSTIC_ONLY",
        "reviewer": "B", "blocking_findings": [], "reviewed_hashes": HASHES,
        "original_economic_goal_judgment": {"C9521_all_original_economic_goals_pass": True, "annual_returns_pass": "7/7", "annual_strict_drawdowns_pass": "7/7", "frequency_closed_per60": float(treatment["frequency_full_contract"]), "closed_trades": 92, "sessions": 1642, "new_economic_vetoes": 0, "formal_registration": False, "phase_advance": False},
        "yearly_results": yearly, "policy_summaries": summary,
        "own_first_SHOCK_permission_population": {"all_first_SHOCK_cycles": len(own_events), "held_age_qualified_S1_evaluated": len(assessed), "S1_true_hold": len(allowed), "S1_false_original_exit": len(refused), "age0_original_exit_without_S1_dependency": len(own_events) - len(assessed)},
        "selected_actual_cases_with_opposing_evidence": selected_cases,
        "actual_Apr9_state": april_state, "actual_Apr10_trade": april,
        "2025_description_bridge": {"annual_return_delta": annual_delta, "March21_cycle_contribution_delta": march, "Apr10_actual_cycle_contribution_delta": april_difference, "other_actual_funding_participation_residual": annual_delta - march - april_difference, "causal_ablation": False},
        "main_conclusion": "C9521 is a concrete historical economic breakthrough: all original seven return and strictDD goals plus original full-window frequency pass together. Acknowledge this without adding terminalwealth, confidence-interval, margin or independent-sample vetoes. It remains a sharedseen adaptively chosen diagnostic, not automatically formally registered or advanced.",
        "2025_chain": "At own firstSHOCK March27(age4), original priorMA slope fails, so permission refuseshold and originalSELL fills March28 at5.97 from March21entry5.66: net+5.2663%, actualQ61600/net18379.592. It avoids originalC9502April1netloss. On April9 ownlastcompletion is positive and pause notconsumed; actualBUY April10Q78700@4.69, SELL April24@5.09 net30710.314. May30H10andJune19age0exit remain. This is a genuine full-policy chain rather than a sum of local counterfactual labels.",
        "2026_chain": "Jan6 heldS1FALSE uses Jan7SELL6.46 instead of controlJan8at6.30. Jan9age0 still sellsJan12at6.80. Jan29/Feb11/Mar6/Sep1 heldS1TRUE preserve originalcontinuations to Feb9at9.01/Mar4at11.50/Mar19at18.50/Sep10at20.58. Unlike EX051, no Feb13anchorloss and no Mar4pause from that inventedexit. Different own quantities/funding and laterlosscycles mean four profits must not be summed as causal annual benefit.",
        "2021_strong_counterexample": "Feb9S1FALSE exitsFeb10at5.16 (+39.9372% cycle) versus controlFeb25at7.07 (+91.7357%). Annual2021 falls199.3857%to150.7390%, still exceeds original71.9038% goal. This is real foregone upside, not an economic rejection gate or proof all S1FALSE states are unsafe.",
        "other_counterevidence": "2020return4.2511% belowcontrol15.6416%;2024return13.1550% below15.9960%; TRUE2023Feb/2024Jan still have previously negative local continuation labels. Fullcutoffwealth1522765.495 belowC9502 1638378.751, and2020-24end332362.749 below456974.037. Therefore not general dominance or a perfect continuation classifier, while originalgoal pass remains true.",
        "selection_limits": "Old pooledS1 negative direction and old no-combination decision are retained. AGE-domain permission was explicitly reopened after labels and EX051 failures; all2020..26seen. Passing this finite history does not establish independent generalization/new information, nor does that limitation erase achievement of the user-specified economic criteria.",
        "next_step": "Stop account expansion in this round; present the exact pass and costs. Any formal candidate registration, stage transition or later validation must be separately scoped using existing governance rather than automatically invoked.",
        "resource_accounting": audit["resource_accounting"],
        "new_reviewer_accounts": 0, "new_market_calls": 0, "new_prepared_fetches": 0, "new_fits": 0,
    }
    path = BASE / "review/permission_interpretation_results.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest(), "goal_pass": True, "bridge2025": result["2025_description_bridge"]}))


if __name__ == "__main__":
    main()
