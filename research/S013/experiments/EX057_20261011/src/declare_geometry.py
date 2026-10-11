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
            "RAW_BEAR_TIME_BELOW_BODY_SUPPORTED_ACF_RECOVERY on original C2132 rawACF20: range_pass AND momentum_pass AND (original rawACFpass OR selected flatrawbear priorfinalbearTIME strictBELOW BODY-positive and originalscore>=0 supported recovery), followed by original confirmation score",
            "Only final reason=time and exit-before active_route=bear classifies BELOW/EQUAL/ABOVE with strict signalClose versus own episode signal-entry anchor. All other exits category=None; no epsilon, threshold/day search or fill-PnL labels",
            "Beforedecision last_exit_reason/route/category initially None; flat failures, score refusals and rawroute changes preserve context, any route signalentry clears all three. EQUAL/ABOVE/NONE never acquire recovery exception",
            "Original rawACFpass eligible entries are fully preserved at identical beforestate regardless BODY/support. Actual recovery flag requires originalacf failure plus range/momentum/selectedcontext/body/support, includes fixed originalscore>=0 support, not originaltheta; enhanced opportunity equals flat AND enhancedeligible. No direction veto or direction refusal; originalconfirmation still required. Holding has no exception and no exit/same-day behavior changes",
            "Original rawACF20 statistic/confirmation, bull rules, range/time/regime/loss/trail priority, held-session H and all13 numerical coordinates remain active and unchanged; L only in original confirmation score; undefined originalacf still refuses",
            "Fixed0 support is structural, outside13 numeric domains; original confirmation.threshold remains active and distinct. OriginalACFpass negative scores are not vetoed; score0 equality supports only exception; theta>0 may still reject support. No claim of support-constant stability or independent validation",
            "All13 original numerical domains/centers and original32 coordinates retained; no statistic replacement, threshold/unit remapping, narrowing, new numeric dimensions or point reselection",
            "Original parent warmup unchanged exactly, including W60/L40/ranges21 minimum61 and center180; Supported BODY recovery uses current signalClose/Open and original composite score>=0 without extra warmup; complete daily shift1 diagnostic remains causal, no previous_regime/momentum diagnostic or W+2 requirement",
            "Original positive2023 BELOW-category cash contribution+2.3049pp and failed broader ACF removal are counterevidence; locally adding ACF-failing supported BODY-positive entries may introduce losses/stale-context churn. Contributions describe old path, never deletion-profit predictions",
        ],
        comparison="Original EX01532 and coupled EX043N0 32 exact native reuse; only qualified newN0 gets32 new full points at original C2132 numeric centers/full13domains/coordinates. Coupled cohort is historical counterevidence with multiple structural differences.",
        candidate_reservation={"first": 8540, "last": 8571},
        prospective_identity_note="Prospective center C8580 and parameters C8540..8571 selected by root; root still must verify registry/assets collisions before formal declaration. Pure tests authenticate strong ID/type/geometry contracts and do not write registry/assets or certify future collision freedom.",
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
        supported_recovery_oracle_sha256=file_hash(SRC / "supported_recovery_oracle.py"),
        legacy_direction_oracle={"path": legacy_path, "sha256": file_hash(ROOT / legacy_path)},
        selection_history="Prior RAW BELOW CLOSE/BODY gates restricted alreadyeligible entries and failed frequency. Root-supplied EX055 BODY-only recovery passed return/DD/frequency but failed2023 (-0.0252056%). Fixed57 zero-score support is the mathematical neutral point of original EQUAL_BLOCKS rank score, not a fitted cutoff or extra numeric coordinate. It changes only local ACF-failing BODY recovery; originalACFpass opportunities retain originaltheta, even negative score. A supported exception must still pass originaltheta (which may exceed0). Stricter support can miss good entries or reduce frequency; no promise of fixing loss, no per-year rule. Only historical55 opportunities referenced, no57 actual opportunity projection. Adaptive exposed development pool, no independent validation or category/window optimization.",
        counts="If qualified:64 old controls reused,32 newbusiness/33actual including one technical serial/spawn duplicate. If unqualified:zero parameter preparation/evaluation/reuse.",
        identity="control_key aliases preserve native labels/IDs/source/plans/lineage/account references. Registered original C2132 is IMPLEMENTATION parent; own new center is PARAMETERS parent. Coupled C4900 is historical control only.",
        diagnostic_controls="Prior RAW BODY-only ACF recovery C7980 appears only as B0-RAW-RECOVERY in plan.diagnostic_controls/analysis.rows; not controls, selected center, reused parameter cohort or SE/pair panel. No extra economic condition or veto; three old centers plus newN0 form four center-only comparisons; old recovery remains unqualified historical diagnostic, not parameter cohort.",
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
