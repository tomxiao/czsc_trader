"""Freeze concise EX051 economic counterevidence from saved audited outputs."""

import csv
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "research/S014/materials/20261020_followthrough_exit_diagnosis"
HASHES = {}


def bind(path, expected=None):
    content = path.read_bytes()
    digest = sha256(content).hexdigest()
    if expected is not None:
        assert digest == expected
    HASHES[path.relative_to(ROOT).as_posix()] = digest
    return content


def read(path, expected=None):
    return json.loads(bind(path, expected))


def table(name, expected=None):
    return list(csv.DictReader(bind(BASE / "accounting" / name, expected).decode().splitlines()))


def output(name, result):
    path = BASE / "review" / name
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}))


def main():
    yearly = table("anchor_policy_yearly_summary.csv", "fc6f8825e1fd600f8190ae9e90d355d4e226f82dae5f21c54eba3212e9c096a4")
    summaries = table("anchor_policy_summary.csv", "0d8bda1133f05b89dda3ac3c3f05749c1f321050d00d88c602c96806dc097e82")
    events = table("anchor_actual_events.csv")
    first = table("anchor_policy_first_SHOCK_actual_cycles.csv")
    audit = read(BASE / "accounting/independent_anchor_audit_summary.json", "610a11a4217d093dd853097ebf8b7f783c316b57ed37330b70070dff5fb58aae")
    for ref in audit["account_reports"]:
        bind(ROOT / ref["path"], ref["sha256"])
    bridge = read(BASE / "review/anchor_actual_path_bridge_review.json", "c420e27fc4820b24bb7f5dc296010513cf4c319e8e59384a33aa10b3f5a8af03")
    bridge_path = BASE / "review/anchor_actual_2025_2026_cycle_bridge.csv"
    cycle_rows = list(csv.DictReader(bind(bridge_path).decode().splitlines()))
    assert len(yearly) == 21 and len(summaries) == 3
    assert all(row["all_original_economic_goals_pass"] == "False" for row in summaries)
    assert len(bridge["annual_exact_decimal_bridges"]) == 6
    assert audit["resource_accounting"]["actual_dispatched"] == 3
    assert audit["resource_accounting"]["FAILED"] == 0
    relevant = [r for r in cycle_rows if (r["year"] == "2026" and r["actual_entry_E"] in ("2026-01-26", "2026-02-10", "2026-03-05", "2026-08-27")) or (r["year"] == "2025" and r["actual_entry_E"] == "2025-03-21")]
    counts = {}
    for summary in summaries:
        profile = summary["anchor_profile"]
        selected = [r for r in events if r["anchor_profile"] == profile and r["selected_anchor_exit"] == "True"]
        counts[profile] = {
            "selected_D": len(selected), "selected_distinct_actual_cycles": len({r["cycle_id"] for r in selected}),
            "new_exit_added_D": sum(r["new_exit_added"] == "True" for r in selected),
            "cost_or_support_overlap_D": sum(r["cost_overlap"] == "True" or r["support_overlap"] == "True" for r in selected),
            "selected_2026_D": [r["D"] for r in selected if r["D"].startswith("2026")],
        }
    assert counts["SHOCK_ANCHOR_ZERO"]["selected_distinct_actual_cycles"] == 9
    assert counts["SHOCK_ANCHOR_FROZEN_1ATR"]["selected_distinct_actual_cycles"] == 5
    bind(Path(__file__).resolve())
    output("anchor_interpretation_results.json", {
        "status": "PASS_FIXED_THREE_POLICY_READOUT", "reviewer": "B", "blocking_findings": [],
        "reviewed_hashes": dict(HASHES), "policy_summaries": summaries,
        "all_seven_year_rows": yearly, "actual_anchor_counts": counts,
        "actual_first_SHOCK_population_rows": len(first), "important_actual_cycle_records": relevant,
        "actual_pause_slots": bridge["actual_2025_2026_pause_slots"],
        "conclusion": "Both fixed followthrough exits reduce2025 loss but do not repair the2025 return goal and destroy the control2026 return pass. Neither replaces C9502. All3 fail at least one original annual return goal; DD7/7 and original frequency pass are retained, not sufficient substitutes.",
        "2025_mechanism": "March28 D has netP+0.5055%, but new nextE March31 actualfill5.58 from entry5.66 is netloss1.6104%. Both reduce original April1 netloss8.6634%, yet own strictnetloss still arms pause and April9 consumes plannedApril10 slot. Neither restores that opportunity; actualdecisionclose profit is not a guaranteed executable profit.",
        "2026_mechanism": "Both sell Jan26 cycle on Feb3 at7.53 instead of controlFeb9 at9.01; both sell Feb10 cycle on Feb13 at9.31 netloss1.8860% instead of controlMar4 at11.50 profit21.1935%. Their own Mar4 loss-pause then skips plannedMar5 entry until eligibility returnsMar19. They therefore have no controlMar5..Mar19 cycle. This is an actual endogenous feedback chain, not merely a local premature-exit comparison.",
        "buffer_counterevidence": "Frozen1ATR also triggers Feb2 andFeb12: source declines4.419 versusATR02.291988, and6.06876 versusATR03.909342. Thus treating only tiny ZERO noise is insufficient; more-than-one-frozen-day-range pullbacks can precede large recovery. This does not justify scanning larger buffer thresholds.",
        "zero_vs_buffer": "1ATR preserves2020July continuation and2026September exitSep10 at20.58; ZERO exits2020July8 and2026Sep4 at17.33. The buffer has a real tolerance effect, but both lose2026 and1ATR2026 annualDD34.4457% is higher than control25.6179%, although still below original BH59.7736%.",
        "cross_year_counterevidence": "2021May17 and2024Jan5 new exits improve particular actual cycles; not every added exit is harmful. Both2024 annual returns about21.24% exceed control15.9960%. Yet originalgoal fit must use all years; positive local cases do not cancel2025/26 failures.",
        "accounting_not_causality": "82 actualcycle-year rows and6 exact Decimal telescoping bridges. Jan26/Feb10/Mar5/Sep cycle marks use each account own quantity and own yearopening equity. Contribution differences reconcile annual paths descriptively; do not call them recoverable causal money or sum closedcycle percentreturns. Same-cycle raw1ATR trigger impliesZERO but wholepolicy populations/funding/pauses are not nested.",
        "technical_resources": audit["resource_accounting"],
        "original_inline_audit_note": "Three engineSUCCEEDED,0FAILED/UNKNOWN/retry. One separate KeyError inline audit expression failure remains in original control receipt. Corrected v2 audits the same original account; no control reevaluation or trading-source change.",
        "next_question": "At firstSHOCK D0, can preexisting trend permission avoid one extra day of deterioration without sacrificing valuable continuation? This is explicitly adaptive sharedseen development and requires a separate fixed successor. Preserve old S1 negative direction and2021False large winner/2023-24True losers. No thresholdscan, date/year switch, or automatic signal claim.",
        "new_funded_accounts": 0, "new_market_calls": 0, "new_prepared_fetches": 0, "new_fits": 0,
    })
    proposal = read(BASE / "permission_proposal.json", "9fd1604f0a9d4b6172912ed9fcfd9f72f59d4841a395d71713f3f612a4cf73d4")
    for rel, expected in proposal["bindings"].items():
        bind(ROOT / rel, expected)
    output("permission_method_review.json", {
        "status": "PASS_METHOD_FOR_SEPARATE_ROOT_LOCK_ONLY", "reviewer": "B", "blocking_findings": [],
        "reviewed_hashes": dict(HASHES),
        "decision_value": "One fixed firstSHOCK permission interaction is a different decision time/responsibility from the failed later anchor exits. Original firstSHOCK-age>=1 domain and original priorMAtrend direction are frozen. It can test actual policy realization and own loss-pause consequence, not establish a new signal.",
        "frozen_action": "Only first own eligiblepositiveP SHOCK assesses permission. Treatment holds iffage>=1 ANDS1TRUE, with separate cycleSHOCK-disable latch. S1FALSE executes original nextE SHOCK exit. Preserve cost/support/GRACE/H10/pending/fees/lots/owncompletedloss pause. No051anchor, daily reassessment or same-dayclose liquidation.",
        "observability": "S1 uses old priorMA20, priorMA20lag5 andsourceD-1Close in originalHFQ. Control andage0 exit need no newS1 dependency. Treatmenteligibleheld firstSHOCK operands unknown explicitly fail, not FALSE/fill0. New numericdiagnostics declare observed fields; unprojectedraw independently reconstruct.",
        "strongest_competitors": ["Prior S1pooled direction was unsupported and oldEX050 explicitly excluded this combination. Newchoice reopens that decision after viewing outcomes; preserve originals.", "2021Feb9 S1FALSE largepositive continuation will be sacrificed; cannot attribute oldpooled negative result only toage0 mixing.", "2023Feb1 and2024Jan3 S1TRUE negativecontinuations refute a generaltrendguarantee.", "Different own fund/quantity/pause paths can drive annualresults even with similar permissioncounts; report all7 annualgates/frequency andactualrefused/allowedcycles."],
        "resources_if_separately_locked": {"actual_accounts": 2, "fresh_C9502_controls": 1, "fixed_treatments": 1, "new_fits": 0, "new_supplier_calls": 0, "grid": 0},
        "scope": "Method only. No newjoint population count, return calculation, componentlabel or actualaccount. Root explicit successorlock and focused source/control gates remain necessary.",
    })


if __name__ == "__main__":
    main()
