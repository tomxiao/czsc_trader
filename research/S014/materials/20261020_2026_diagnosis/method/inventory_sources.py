"""Read frozen S014 contracts/results only; no market preparation, replay or fit."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_bytes())


def identity(path):
    p = ROOT / path
    return {"path": path, "sha256": sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}


def locate(path, anchor):
    item = identity(path)
    lines = (ROOT / path).read_bytes().split(b"\n")
    i, line = next((i + 1, line.decode("utf-8").rstrip("\r")) for i, line in enumerate(lines) if anchor in line.decode("utf-8"))
    return {**item, "line": i, "anchor": anchor, "excerpt": line, "line_basis": "LF-delimited bytes"}


def main():
    source = "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py"
    receipt = read("research/S014/experiments/EX046_20261020/others/accounts/run-001.json")
    assert receipt["candidate"] == "S014-C9461" and receipt["parameters"] == {"pause_profile": "AFTER_NET_LOSS_SKIP1"}
    report = read("research/S014/materials/20261020_preentry_diagnosis/accounting/pause_account_001_independent_review.json")
    assert report["account_ref"] == receipt["evidence"] and report["result_hash"] == receipt["result_hash"]
    old_grid = []
    for i in range(9):
        path = f"research/S014/materials/20261019_exante_hold_exit/accounting/account_{i:03}_independent_review.json"
        r = read(path)
        old_grid.append({"index": i, "parameters": r["parameters"], "original_2026_goal_audit": next(row for row in r["original_annual_goal_audit"] if row["year"] == 2026), "source": identity(path), "json_locator": "original_annual_goal_audit[year=2026]"})
    locators = [locate(source, text) for text in (
        "deadline = i + 9", "reservation = i + 10", "completed_net = float(fill.price) * .999 - entry_fill_price * 1.001",
        "shock = bool(eligible and feature.shock_known and (net_profit > 0) and (feature.z5 > 2))",
        "cost_loss_price = entry_fill_price * (1 + 0.001) - close * (1 - 0.001)",
        "if inherited or expired or risk_exit or ordinary_support:", "if armed:", "reservation = i + 11",
        '"entry": {"order_type": "LIMIT", "limit_parameter": 0.01}',
    )]
    old = []

    def prior(label, path, anchor, exact_rule, result, relevance):
        old.append({"family": label, "evidence": locate(path, anchor), "rule": exact_rule, "already_answered": result, "difference_vs_current_question": relevance})

    prior("EX006 profit-and-weakness probes", "research/S014/experiments/EX006_20261016/others/report.md", "2026年20日持有中点", "Eight once-only midpoint early exits using unrealized profit plus price weakness, next executable sale versus fixed original endpoint.", "All8 pooled comparisons negative;2026 H20 middle31 selected attempts early sale21.019% versus fixed41.022%, roughly20.003pp sacrificed. Not continuous annual account returns.", "Old warning that taking profit can forfeit strong rises. Conditions differ from positiveP+Z5>2, population/endpoints differ from C9461; do not transfer old local values to its account.")
    prior("EX024 first supportbreak currentP", "research/S014/experiments/EX024_20261018/protocols/account_report.md", "| 2026 |", "At first strictly early supportbreak freeze current buy-fee-adjusted P once; P>0 or P<=0 permits exit, otherwise wait originalH10; original reservation.", "2026 P113.66% fails196.46%; N218.02% passes but fails otheryears; originalR230.71% passes2026 but overall originalgoals fail. Noallgoals route.", "Neither positiveP+highZ without supportbreak nor actual completed-loss memory; cannot rebrand P/N as the new shock interaction.")
    prior("EX025 candle entry confirmation", "research/S014/experiments/EX025_20261018/protocols/account_report.md", "| 2026 |", "Original support candidate additionally C_D>O_D; same originalB/R/P exit and fees.", "New2026 returns62.51%,2.46%,68.61% allbelow196.46%; all originalgoals0/6.2024localrepair loses many other-year opportunities.", "Not a new2026 remedy; gating future entry is different from holding exit necessity.")
    prior("EX026 H3/H5 full-cycle clocks", "research/S014/experiments/EX026_20261018/protocols/account_report.md", "| 2026 |", "Both actual holding deadline and reservation clock shorten toH3/H5, crossed originalB/R/P.", "All six new2026 returns81.22..99.48% below196.46%; all originalgoals0/9. H3P/H3B economicrepeat retained.", "UniformshorterH is already negative and outside present requirement to retain actualH10; no neighboring horizon scan.")
    prior("EX027 H1/H2 natural short boundary", "research/S014/experiments/EX027_20261018/protocols/account_report.md", "| 2026 |", "H1 onlyB, H2 B/R/P; realT+1 no sameD buy/sell. Deadline and post-exit opportunity clock both change.", "2026H1-18.87%;H2 55.64..79.60% allfail; newfullaccounts allnegative and originalgoals0/10.", "Cannot claim more frequent participation or shorter holding is a new fix; it changed whole opportunity paths.")
    prior("EX028 H15 extension", "research/S014/experiments/EX028_20261018/protocols/account_report.md", "| 2026 |", "Hold/reservationH15 with B/R/P, not conditional local continuation.", "2026 128.56%,155.88%,112.42% allbelow196.46%; originalgoals0/6, lowerthanH10 completewealth. Same-entry profitable labels failed to carry to new full paths.", "Alreadynegative and outside retainedH10 requirement; longer holding labels cannot justify horizon expansion.")
    prior("EX029 conditional reservation currentP", "research/S014/experiments/EX029_20261018/protocols/account_report.md", "| 2026 |", "Firstearly supportbreak freezes P sign to retain or drop actual-entry reservation, while support earlySELL stays.", "2026 positive-reserve72.04%, nonpositive169.89%, immediate77.80% allfail; originalall-reserveR230.71% passes2026 but otheryearsgaps. Alloriginalgoals0/4.", "OldP belongs to still-held firstbreak, not completed loss or updated flat recovery; conditional clocks are not automatically new information.")
    prior("EX043 holding/exit3x3", "research/S014/materials/20261019_exante_hold_exit/accounting/policy_summary.csv", "ENTRY_GRACE/SHOCK_PROFIT", "HoldBASE/GRACE/TREND crossed exitBASE/SHOCK/GIVEBACK, costBASE and no completion pause.", "Saved2026 audit: GRACE/BASE196.9781% passes196.4644%; GRACE/SHOCK89.0484%, GRACE/GIVEBACK110.0430% fail. GRACE/BASE only4/6 returns in2020-25 and oneDDfail; noall-originalgoals policy.", "Strong existing competitor for earlyprofitexit harm, but not samepopulation as currentcost+loss feedback. OFF comparison now is interaction/necessity ablation, not a newindicator or proved2026gain.")
    prior("EX044 Z entry/ANY-P/cost5", "research/S014/materials/20261019_2024_diagnosis/accounting/policy_summary.csv", "BASE/POSITIVE_P/NET_LOSS_1ATR", "HighZ candidate filter2x2 with positiveP vsanyP exits; plus originalcost-stop-only arm. SameGRACE andH10.", "Noall-goals route; cost arm5/6completeyearreturns and5/7original including2026fail, while all7DDpass. Old2024 gains cannot be called2026repair.", "Current C9461 retains cost arm and adds ownclosed-loss pause. Removing its pause is already EX046BASE, not a new mechanism or sufficient explanation for the2026gap.")
    prior("EX045 highZ blocked-slot clock", "research/S014/materials/20261019_2024_diagnosis/official/clock_interpretation_notes.json", "Planned-slot clock does not jointly retain2024", "Same highZ candidate filter with retryeveryD orconsumeplannedH10slot; no actual closing loss and costBASE.", "Wholepathclock matters but neither solvesallgoals. KEEP2024-13.4581%/2025+34.2681% stillgaps; source blocks no2025 directRETRYcandidate, prior phasepropagation remains.", "Planned slot alreadytested as clock action; using C9461loss memory is different state, but arbitraryslotlength oryearreset would be repeated phase fitting.")
    result = {
        "status": "READONLY_MECHANISM_AND_INTERFACE_REVIEW_NO_NEW_EXPERIMENT_OR_ACCOUNT",
        "verified_branch": "codex/s014-jinniu-research", "verified_clean_HEAD": "cbdce86125241807b2d1e57c7ebde7fb2757f587", "role": "RSCH",
        "baseline": {"candidate_label": receipt["candidate"], "formal_candidate_registered": False, "source": identity(source), "source_ref": receipt["published_source_ref"], "parameters": receipt["parameters"], "account_ref": receipt["evidence"], "result_hash": receipt["result_hash"], "actual_execution_lock_ref": receipt["execution_source_lock_ref"], "same_source_original_parent_lock_ref": read("research/S014/experiments/EX046_20261020/protocols/published_lock.json"), "annual_2026_existing_audit": next(row for row in report["original_annual_goal_audit"] if row["year"] == 2026), "annual2020_25_original_joint_pass": "6/6 returns and6/6DD plus original frequency; allpreviouslyseen; must retain all complete-year checks in any new full-path comparison"},
        "baseline_duties": {
            "entry": "After original60session startup: actuallyflat, original S5 supportOK, oldreservation reached and not realfailedBUYreset; plan nextE original1%limit fullcash wholelots.",
            "hold_exit_priority": "Inherited prior SELLpending or actualH10deadline first; positivecurrent-netP and knownZ5>2 selectedSHOCK or originalNETcurrent1ATR selectedCOST next; otherwise strictS5break except actualBUY-D GRACE. A disabledSHOCK never disables cost/support/deadline/pending.",
            "deadline": "ActualBUY indexi sets deadlinei+9 decisionclose and reservationi+10; failedSELL remains pending until actuallyfilled, withoutmovinganchors.",
            "feedback": "ActualfullSELL completes own positive-funded BUY cycle. Strict exitfill*.999-entryfill*1.001<0 arms once; after actualSELL sameD may consume if originaleligibility holds. Originalreservation may defer. First eligibleflatD consumesi+11, noorder/entry/deadline/cost/fee and clearsarmed immediately. Persistent lastloss does not indefinitely rearm.",
            "crossyear": "NoJanreset of held/pending/reservation/armed orcash; start originalfull2020window, not2026-only reset. AnnualPnl and anyunfinishedendposition use originalledger, no forced10/15sale.",
            "observability": "Current history has fixed100unit reconstructed fill state, not live authoritative portfolio callback. Existing realC9461 audited perD against actualfunded fills. Any newsource must freshly recertify actualfunded flags and strict fee-adjusted complete-sign, never feed frozen futureC9461trades to a changed path."
        },
        "source_locators": locators, "prior_mechanisms_and_negative_evidence": old, "EX043_saved_2026_grid": old_grid,
        "current_minimal_priority_question": {
            "status": "METHOD_FEASIBILITY_ONLY_ROOT_WAITING_CURRENT_ACCOUNT_ATTRIBUTION_TO_LOCK",
            "question": "With actual C9461 COST+GRACE+ownclosed-loss feedback fixed, is positiveP highZ SHOCK still necessary, or does it sacrifice sustained advances and alter later opportunities enough to explain the2026gap?",
            "comparison": "New-source exact originalSHOCK-ON C9461 control plus only SHOCK-OFF; no other factor. It is a component necessity/interaction test, not a newalpha or threshold discovery.",
            "no_new_parameters_selected": "Keep original Z5,2boundary,P>0,ATR20prior1cost,S5,fees,actualH10 andskip1 unchanged. Proposed mode ON/OFF is not an implementation or dispatch authorization here.",
            "nonoverlap_logic": "Within originalfinite/positiveATR eligibleSHOCKdomain, netP>0 implies cost_loss_price<0 so COST cannot trigger; Z5>2 implies C_D>C_D-5>=S5, so strictsupportbreak cannot coincide; eligible already excludes inheritedpending/deadline. This is an algebraic domain statement, not a measured future effect. Changed later paths still obey allother exits.",
            "not_force_H10": "OFF removes onlyselectedSHOCK from newSELLintent; current/future cost orsupport/deadline/pending still causes sale. Do not erase rawSHOCKcondition, manipulateZ/knownflags orpriceinputs, and do not cancel an inheritedactualpending SELL.",
            "own_path": "A changedexit changes actualsellprice,completedprofit/loss,armed,slot,quantity andfutureentry population; recompute its own entirefundedpath. No adding oldmissedtradePnL or freezing oldcompletion feedback.",
            "why_not_exact_repeat": "EX043 measured SHOCK inside older costBASE/noownclosedfeedback; EX044 heldSHOCKfixed when addingcost; EX046 heldSHOCKfixed when addingownfeedback. Its currentconditionalnecessity remainsunanswered; oldsupport isnot a promise about itsnewgap.",
            "strongest_counterevidence": "SHOCK helped2022/2025 in priorGRACE routes and currentC9461alreadypasses2020-25. Removing it might restore2026butfail2025orotherpriorpassingyears. OldGRACE/BASE2026barelypasses, farfromproving currentC9461OFF; noyear-specificchoice.",
            "route_if_later_authorized": "Newpublicexperiment andnewsource/payloadidentity, sameauthenticatedpinnedinputs/fingerprint andclock exceptnewruntime; A/Bsource+synthetic/actualSRTreview thenpublicfreeze; freshONaccount exact allC9461old economic/observationfields andAactualfundedcontrolPASS beforeOFF. Full2020..partial2026originalacceptance and originalfreq; sixprioryears checkedthroughowncontinuouspaths. Noformalregistration,stageadvance,platform/data/prod change.",
            "current_noop_ref_is_not_new_source_control": "ExistingC9461 oroldEX046BASE audits cannot replace freshnewsourceONequivalence. Use corrected auditD/E mapping andpreserve anytechnicalfailures/additivesupplement chain."
        },
        "unlocked_alternative_questions_not_parallel": [
            {"question": "Does loss origin, rather than any completed loss, justify a later skip?", "state": "Freeze first newSELL-intent cause from originalcost/support/shock/deadline, preserve whilepending, associate with ownactuallyclosednetloss; do not infer cause from falseflags on delayedactualSELLD.", "difference": "Acrosscompletedcycle cause memory instead of currentcostthreshold. Existingcostformula/threshold unchanged.", "status": "Retain only if currentattribution doesnot support theSHOCKnecessity question; no chosenclass,parameter,populationorpolicy run."},
            {"question": "Is the prior loss already price-repaired when the first new original opportunity arrives?", "state": "D-known flatcandidate price versus ownpreviousactualentrycost/exit reference; classify recovery before deciding whether to consumearmedonce. A recovery price doesnot undo theactualrealizedcashloss.", "difference": "Updated flat-state applicability of pastloss, not EX029 frozen currentheldP or EX030 movingS5recovery. Keeps actualholdingH10 and1%execution.", "status": "Unspecifiednotlocked; do not select recoverybenchmark/window to hit observed2026slots. No support meansinapplicable, not reason to tuneto2026."}
        ],
        "corrected_calling_contract": {"authoritative_old_v2_runner": identity("research/S014/experiments/EX046_20261020/src/run_accounts_v2.py"), "corrected_internal_audit": identity("research/S014/experiments/EX046_20261020/src/audit_accounts_v2.py"), "mapping": "decision.signaldateD isnextE daily.signaldate; decision.valid_session equalsdaily.dateE. Dheld/cash useactualdaily_by_date[D], firstprewindowD2019-12-31 explicitinitial100000cash/0qty. NeverzipDheldtoEquantity.", "dates": "First completed-memory observation, first selectedarmed, first oldstateincludingreservation divergence, firsttargetdivergence andfirstactualfundedE are separate; metadata isnot economicdifference.", "publication": "Onlyauthorized localpublicAPI Material/EvaluationEvidenceWrite into repository research/S014/assets/evidence/<EX>/<SHA>, noexternalupload; previousrejection/proof/same-operationreapproval retained. Do notmodifyoldsource/refs orbypassreview."},
        "resources": {"new_experiments": 0, "new_market_input_loads": 0, "new_strategy_replays": 0, "new_accounts": 0, "new_fits": 0, "new_state_PnL_calculations": 0, "new_parameters_chosen": 0},
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()
    }
    destination = OUT / "c9461_mechanism_inventory.json"
    with destination.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"status": result["status"], "sha256": sha256(destination.read_bytes()).hexdigest(), "source_locator_count": len(locators), "old_mechanism_families": len(old)}))


if __name__ == "__main__":
    main()
