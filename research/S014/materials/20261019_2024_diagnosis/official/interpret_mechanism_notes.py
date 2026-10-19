"""Supplement fixed five-path interpretation with counterexamples and actual cycles."""

from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def day(value):
    return str(value)[:10]


def main():
    target = HERE / "interpretation_adversarial_notes.json"
    if target.exists():
        raise FileExistsError(target)
    data_path = HERE / "interpretation_results.json"
    data = read(data_path)
    assert data["all_five_pass"]
    reports = [
        HERE.parent / "accounting" / f"account_{i:03d}_independent_review.json" for i in range(5)
    ]
    audited = [read(p) for p in reports]
    assert all(r["status"] == "PASS" for r in audited)
    ledgers = []
    for r in audited:
        ref = EvidenceRef.from_dict(r["account_ref"])
        content = ref.resolve(ROOT).read_bytes()
        assert sha256(content).hexdigest() == ref.sha256
        ledgers.append({k: v["data"] for k, v in json.loads(content)["runs"][0]["ledgers"].items()})
    additions = {}
    boundary = {}
    for i in [1, 2, 3, 4]:
        ledger = ledgers[i]
        dates = {int(d["warmup_sessions"]): day(d["signal_date"]) for d in ledger["decisions"]}
        added = []
        flag = "cost_exit_added_vs_baseline" if i == 4 else "shock_exit_added_vs_positive"
        for d in ledger["decisions"]:
            if day(d["signal_date"]) > "2025-12-31" or not d[flag]:
                continue
            entry_day = dates[int(d["entry_index"])]
            new = next(t for t in ledger["trades"] if day(t["entry_date"]) == entry_day)
            prior = [t for t in ledgers[0]["trades"] if day(t["entry_date"]) == entry_day]
            added.append(
                dict(
                    D=day(d["signal_date"]),
                    intended_E=day(d["valid_session"]),
                    entry_day=entry_day,
                    actual_policy_trade=new,
                    baseline_same_entry_day_trade=prior,
                    price_return_difference_pp_if_same_entry=100
                    * (new["net_return"] - prior[0]["net_return"])
                    if len(prior) == 1
                    else None,
                    inference_limit="Same entry date trade-price comparison only; actual quantities/cash differ. Not independent local effect additive to terminal wealth.",
                )
            )
        additions[str(i)] = added
    for i, ledger in enumerate(ledgers):
        account = next(r for r in ledger["account_daily"] if day(r["date"]) == "2024-12-31")
        decision = next(r for r in ledger["decisions"] if day(r["signal_date"]) == "2024-12-31")
        boundary[str(i)] = dict(
            account=account,
            D_state={
                k: decision[k]
                for k in [
                    "held_at_close",
                    "entry_index",
                    "reservation_index",
                    "entry_signal",
                    "exit_pending",
                    "warmup_sessions",
                ]
            },
        )
    assertions = [
        {
            "finding": "No five-arm solution meets all original annual goals",
            "evidence": "BASE,ANY_P,cost pass5/6 annual return goals; gate and joint pass3/6. All5 pass6/6 complete-year drawdowns and original frequency. No diagnostic CI/count/no-harm rule was added.",
            "status": "SUPPORTED",
        },
        {
            "finding": "Entry guard repairs2024 but does not preserve the earlier cross-year target result",
            "evidence": "2024+11.3074396881%,2021+69.5179540142% below71.9037674743%,2022-17.7493265395%,2025+4.0042500691% below40.1878639521%.",
            "status": "SUPPORTED",
        },
        {
            "finding": "2025 loss of performance is not a count of contemporaneous gate vetoes",
            "evidence": "Actual gate and joint2025 have0 entry_guard_blocked and0 candidate_shock. Prior-year entry changes have already changed cycle timing and reservation: May30/June19 flat, actualJune11 entry andJune27 later entry. Old baseline high-Z candidate dates cannot be copied into a new path's opportunity population.",
            "status": "SUPPORTED_PATH_DEPENDENCE_NOT_ISOLATED_CAUSATION",
        },
        {
            "finding": "Joint gate+ANY_P gives no incremental economic evidence beyond gate on these inputs",
            "evidence": "1 and3 exact2020-25 daily wealth/cash/position and actual fills; ANY_P adds0 selected exits on gate path. Five configurations give four economic paths. Endpoint interaction-18355.410 reflects path prevention of the standaloneANY_P benefit, not additive causal cancellation.",
            "status": "SUPPORTED",
        },
        {
            "finding": "ANY_P detects a small observed domain defect, not the majority2024 loss mechanism",
            "evidence": "Prior baseline3 excludedD/2cycles become2 new actual exitD/2cycles:2022Sep9 and2024Oct9. Annual2022 improves3.650456pp;2024 improves0.929190pp but remains-20.228145%. No new trigger2023/2025; small annual return differences there reflect prior wealth/lot arithmetic, not fresh signals.",
            "status": "SUPPORTED_SPARSE_LOCAL_RESPONSIBILITY",
        },
        {
            "finding": "NET cost stop is a partial improvement with a cross-year counterexample",
            "evidence": "2024-12.372455% versus-21.157335% frozen;2020-24 wealth312130.034 versus275765.241 frozen and278758.908 original. 2022/2025 remain passing.2023 return17.288355% versus19.957720% frozen, still above3.365347% goal. This cost is disclosed, not a new annualnoharm veto.",
            "status": "SUPPORTED_PARTIAL_NOT_ACCEPTED_STRATEGY",
        },
        {
            "finding": "Selected cost states substantially overlap original support actions",
            "evidence": "26 cost-selectedD in26cycles;20 already ordinary support exits and6 additional exits.2024 9 selected/6 overlapping/3 additional:Jan30,Jul15,Oct9.0graceoverride.2022 and2025 new cost exits0, so their small return differences are not contemporaneous extra risk identifications.",
            "status": "SUPPORTED",
        },
        {
            "finding": "Rolling ATR shrink is a valid competing explanation but not observed as a price-flat trigger here",
            "evidence": "Strict samecycle,previouseligible,costfalse->true,currentClose>=previousClose,currentATR<previousATR,currentloss<previousATR gives0 cases over selected2020-25 actual cost path. Does not prove fixedATR/otherinputs would be equivalent.",
            "status": "NOT_OBSERVED_IN_THIS_PATH",
        },
        {
            "finding": "Current cost stop can precede a new S5 break but cannot undo entryday damage",
            "evidence": "Jan29 costratio.7512<1 and already-3.678674% net;Jan30 ratio1.38639,supportfalse->EJan31actual4.30sale vsBASEFeb1 4.07. October9entry net-8.244696%,costratio3.11778->EOct10actual4.17; still cycle-9.331845%,no guaranteed1ATR cap.",
            "status": "SUPPORTED_CLOCK_BOUNDARY",
        },
        {
            "finding": "Future research scope is unresolved; no year gate or rescue-threshold inference follows",
            "evidence": "Shared seen2020-25 motivating state/population and these outcomes are development information. Financial annual reports published2025 cannot become2024 entry inputs; warning titles have limited coverage. The remaining entryday loss responsibility is supported by the original attribution, but no tested current rule solves it across years.",
            "status": "UNRESOLVED",
        },
    ]
    result = dict(
        status="COMPLETE_ADVERSARIAL_INTERPRETATION",
        assertions=assertions,
        actual_new_exit_cycles=additions,
        calendar2024_yearend_actual_states=boundary,
        recommended_readout="Keep the fixed five outcomes and report cost-stop as the strongest partial mechanism refinement, not a qualified candidate; entryguard is rejected under original goals on this history;ANY_P is narrowly supportive but insufficient. No further account or threshold proposed without a distinct remaining question.",
        no_new_accounts=True,
        no_new_labels_or_fit=True,
        no_external_data=True,
        scope="2020-25 only; prior-year state transfer explicitly retained",
        reviewed_hashes={
            p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in [
                data_path,
                *reports,
                Path(__file__),
                HERE.parent / "accounting/independent_ex044_audit_summary.json",
            ]
        },
    )
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "sha256": sha256(target.read_bytes()).hexdigest(),
                "new_exit_cycles": additions,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
