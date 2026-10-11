"""Prospective original13 declaration; execute only after root identity approval."""

from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def build_geometry(previous):
    geometry = {
        name: previous[name]
        for name in ("version", "protocol", "coordinates", "origins", "mapping", "feasibility")
    }
    legacy_path = "research/S013/experiments/EX043_20261011/src/direction_oracle.py"
    geometry.update(
        fixed_or_categorical=[
            "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY combines exact20 rawbull-boundary BODY AND restriction with exact55 rawbear local ACF eligibility OR recovery",
            "Bear eligibility=range_pass AND momentum_pass AND (original rawACFpass OR flatrawbear priorfinalbearTIME strictBELOW currentClose>currentOpen); then originalconfirmation. No fixedscore0 or new support cutoff; originalACFpass bear opportunities remain unaffected by BODY",
            "Bull flat enhancedeligible entry: only currentrawbull and previous complete daily rawbear requires currentClose>Open; strict equality rejects before originalconfirmation. Stablebull originalentry unaffected, nextstablebull not latched or delayed. Holding has no exception, no new gate and no exit/same-day behavior changes",
            "Only final reason=time and exit-before active_route=bear classifies BELOW/EQUAL/ABOVE with strict signalClose versus own episode signal-entry anchor. All other exits category=None; no epsilon, fill-PnL labels or new exit-price anchor",
            "Beforedecision last_exit_reason/route/category initially None; flat failures, score refusals and rawroute changes preserve context, any route signalentry clears all three. EQUAL/ABOVE/NONE never acquire recovery exception",
            "Original rawACFpass eligible bear entries are fully preserved at identical beforestate regardless BODY. Actual recovery flag requires originalacf failure plus range/momentum/selectedcontext/body and excludes score; originalconfirmation still required. No direction veto or direction refusal on bear; only explicit bull boundary direction refusal precedes score",
            "Original rawACF20 statistic/confirmation, bull rules except stated boundarygate, range/time/regime/loss/trail priority, held-session H and all13 numerical coordinates remain active and unchanged; L only in original confirmation score; undefined originalacf refuses",
            "Original parent warmup unchanged exactly at center and canonical32; complete previousrawmomentum shifted before reindex requires max(parent,W+2). Full-domain W60/L40/ranges21 minimum61 becomes62; domain retained and missing public prepared history FAILED without provider/fallback. Existing complete daily shift1 price diagnostic remains causal",
            "All13 original numerical domains/centers and original32 coordinates retained; no statistic replacement, threshold/unit remapping, narrowing, new numeric dimensions or point reselection. Fixed route/category/BODY structures have selection risk not covered by numericgeometry",
            "Local OR can mask ACF cutoff on recovery as55, bullboundary BODY can veto otherwiseeligible bull entries as20; original parameters remain meaningful globally, not asserted influential at every actual point. No artificial coordinate contraction or masking as proof",
            "Original positive2023 BELOW-category cash contribution+2.3049pp and failed broader ACF removal are counterevidence; old groups cannot be added/deleted to predict newprofit. Repeated seen development pool and two selected old mechanisms do not provide independent validation",
        ],
        comparison="Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.",
        candidate_reservation={"first": 8840, "last": 8871},
        prospective_identity_note="Prospective center C8880 and parameters C8840..8871 selected by root; root still must verify registry/assets collisions before formal declaration. Pure tests authenticate strong ID/type/geometry contracts and do not write registry/assets or certify future collision freedom.",
        helper_source_files={
            name: file_hash(SRC / name)
            for name in (
                "run_parameters.py",
                "parameter_analysis.py",
                "pair_parameters.py",
                "declare_geometry.py",
                "common.py",
                "account_reference.py",
                "ledger_reference.py",
                "analysis_reference.py",
            )
        },
        boundary_recovery_oracle_sha256=file_hash(SRC / "boundary_recovery_oracle.py"),
        legacy_direction_oracle={"path": legacy_path, "sha256": file_hash(ROOT / legacy_path)},
        selection_history="Exact20 RAW boundaryBODY C9102 passed return/annualDD/negativeyears but109closed failed110frequency; exact55 localBODYrecovery C7980 had118closed but2023-0.0252056%. Combining complementary route information is a structural hypothesis after observed outcomes, not arithmetic compensation or cutoff tuning. Root57 fixedscore0 support worsened2023 to-1.116198%; exclude that floor. Old29 centeredMEAN+boundaryBODY failedannualDD, strong near counter. No promise of fixing loss or frequency; adaptive exposed development pool, no independent validation or new58 actual opportunity projection.",
        counts="If qualified:64 old controls reused,32 newbusiness/33actual including one technical serial/spawn duplicate. If unqualified:zero parameter preparation/evaluation/reuse.",
        identity="control_key aliases preserve native labels/IDs/source/plans/lineage/account references. Registered original C2132 is IMPLEMENTATION parent; own new center is PARAMETERS parent. Coupled C4900 is historical control only.",
        diagnostic_controls="C7980 B0-RAW-RECOVERY and C9102 B0-BULL-BOUNDARY are exactexisting center-only diagnostics, not controls, selected center, reused parameter cohort or SE/pair panel. No extra economic condition or veto. Mechanism2x2 is2132/9102/7980/newN0; C4900 B0-COUPLED separate multi-structure historicalparameter control, not mixed into this2x2. Four old centers plusnewN0, only3parametercohorts.",
        economic_policy="Only four original economic gates qualify center; all neighbor gates remain diagnostics, no additional veto. AbsoluteQ10/Q90 and relative degradation jointly inform improvement.",
    )
    assert len(geometry["coordinates"]) == 13 and geometry["protocol"] == {
        "radius": 0.05,
        "point_count": 32,
        "seed": 13,
    }
    return geometry


def main():
    assert not (PROTOCOLS / "geometry.json").exists()
    previous = read(ROOT / "research/S013/experiments/EX043_20261011/protocols/geometry.json")
    geometry = build_geometry(previous)
    write(PROTOCOLS / "geometry.json", geometry)
    ref = publish_evidence(
        context(1),
        MaterialEvidenceWrite(
            EXPERIMENT,
            "prospective-common-parameter-geometry",
            (PROTOCOLS / "geometry.json").read_bytes(),
            "application/json",
            "json",
        ),
    )
    write(PROTOCOLS / "geometry_reference.json", ref.to_dict())
    print({"geometry": "PUBLISHED", "dimensions": 13, "points": 32, "centers_if_qualified": 3})


if __name__ == "__main__":
    main()
