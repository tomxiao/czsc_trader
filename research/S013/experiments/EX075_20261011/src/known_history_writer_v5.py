"""Source-only history update: exactly three authorized public summaries."""

from hashlib import sha256
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    from czsc_trader.research_tools.evidence import EvidenceRef

    here = Path(__file__).resolve().parent
    root = next(p for p in here.parents if (p / "pyproject.toml").exists())
    oldfreeze = read(here / "source_freeze.json")
    for name, digest in oldfreeze["source_files"].items():
        assert sha256((here / name).read_bytes()).hexdigest() == digest
    specs = {
        "EX074_analysis": (
            "research/S013/experiments/EX074_20261011/protocols/analysis_reference.json",
            None,
            "3442fe27127a19d92b8bc10c45d2e73df781688fa56a1a810a2f64ea9b079d57",
        ),
        "EX074_root_review": (
            "research/S013/experiments/EX074_20261011/protocols/root_scientific_review_references.json",
            "root_scientific_review.json",
            "bc1c924843ca050812570c685d894649120facf7cd9f80d61ee2ed2f85348d7c",
        ),
        "EX073_root_review": (
            "research/S013/experiments/EX073_20261011/protocols/root_review_references.json",
            "root_review.json",
            "c6f13f90eb4801a163b875c5adf487bb554db470c2743f1c08cfbb2519c28498",
        ),
    }
    refs, summaries = {}, {}
    for name, (relative, key, digest) in specs.items():
        metadata = read(root / relative)
        ref = metadata if key is None else metadata[key]
        assert ref["sha256"] == digest
        path = EvidenceRef.from_dict(ref).resolve(root)
        assert sha256(path.read_bytes()).hexdigest() == digest
        refs[name], summaries[name] = ref, read(path)
    analysis, review, previous = (
        summaries[n] for n in ("EX074_analysis", "EX074_root_review", "EX073_root_review")
    )
    rows = {}
    for name in ("B0", "N_PRESSURE_EARLY_EXIT"):
        r = analysis["rows"][name]
        rows[name] = {
            "center": {
                n: r["center"][n]
                for n in ("net_cagr", "full_drawdown", "closed_trades", "gates", "qualified")
            },
            "q10_cagr": r["q10_cagr"],
            "q90_full_drawdown": r["q90_full_drawdown"],
            "gate_pass_counts": r["gate_pass_counts"],
            "joint_count": r["joint_count"],
            "point_count": r["point_count"],
            "double_fee": {
                n: r["stress"][n] for n in ("net_cagr", "full_drawdown", "gates", "qualified")
            },
            "double_fee_2023_return": r["stress"]["annual"]["2023"]["return"],
        }
    history = {
        "status": "SOURCE_ONLY_KNOWN_ADAPTIVE_HISTORY_NO_NEW_FINANCIAL_OR_STATISTICAL_RUN",
        "public_summary_references": refs,
        "rows": rows,
        "EX074_root_classification": review["scientific_classification"],
        "objective_achieved": review["objective_achieved"],
        "center_qualification_preserved": review["centre_original_four_gate_qualified"],
        "not_preferred_as_robust_improvement": not review["preferred_as_robust_improvement"],
        "comparison": analysis["comparison"],
        "integer_coverage": analysis["integer_coverage"],
        "EX073_previous_limited_judgment": {
            n: previous[n] for n in ("component_status", "judgment", "objective_achieved")
        },
        "selection_counterevidence": [
            "EX073 finite whole-pool holding-horizon evidence supported only one fixed native countertest, not strategy profit/robustness. EX074 actual paths provide stronger negative evidence for that responsibility.",
            "EX074 center passes original four gates but CAGR14.3985% below17.1346% and fullDD16.3764% above13.6187%; center qualification cannot be described as robustness improvement.",
            "Own standard32 sets are15D vs13D nonpaired geometry: returnQ10 5.4750% below6.3981%, DDQ90 30.6360% above28.3508%. Relative-center degradation is not absolute robustness.",
            "New counts5/24/30/4 joint1/32 vsold7/32/27/2 joint0/32; frequency/negative-year gains do not compensate absolute return/DD deterioration. No selecting P21 or rescuing holdcap/window.",
            "Pressurewindow remains4 in all32 standardpoints, integer sensitivity not covered; holdcap1/2/3/4 counts11/12/7/2 retained without choosing best.",
            "New independent doublefee CAGR10.3050%, fullDD20.2657%, 2023−3.9731%; fails overall-return and negative-buyhold-year profit gates. Old doublefee2023 also negative. Fees remain an economic concern.",
            "Volume/body is a previously fixed untested interaction hypothesis prepared before finalEX074 results. Independent algebra does not imply predictive independence. It does not reverse failed overnight-pressure recovery sign or rescue its trading mechanism.",
            "Repeated adaptively selected research on the same development pool remains selection-biased; chronological mature OOS and descriptive CI do not create sealed validation or eliminate selection bias.",
        ],
        "scope": "Only these three authorized public summaries read; no raw/forward market data, underlying account assets, new provider or adjacent batch read",
        "next_ceiling": "Separate root approval for one fixed stage-two full-pool information test first; any support only allows later actual decision-state validation, not account or strategy deployment",
        "budget": {
            "authorized_public_summaries": 3,
            "real_input_reads": 0,
            "new_statistics": 0,
            "signals": 0,
            "accounts": 0,
            "allocate": 0,
            "publish": 0,
            "DEV": 0,
        },
    }
    with (here / "known_history_v5.json").open("x", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, allow_nan=False)
    plan = read(here / "draft_plan_v4.json")
    plan.update(
        draft_version=5,
        source_only_progress="EX074 completed public summary and root negative review now known; volume feature/18controls/labels/500x40/ridge10/classification unchanged; actualphase still unauthorized",
        v4_plan_sha256=sha256((here / "draft_plan_v4.json").read_bytes()).hexdigest(),
        known_history_reference={
            "path": "known_history_v5.json",
            "sha256": sha256((here / "known_history_v5.json").read_bytes()).hexdigest(),
        },
        known_public_references=refs,
        input_phase_protocol="Separate NEW root_*_authorization_v2.json phases bound to source_freeze_v2.json. One EX075 allocation or stop retaining allocated ref; no actualphase authorized by source preparation or EX074approval",
    )
    with (here / "draft_plan_v5.json").open("x", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, allow_nan=False)
    source = (here / "authorized_driver_draft.py").read_text(encoding="utf-8")
    source = (
        source.replace("source_freeze.json", "source_freeze_v2.json")
        .replace("draft_plan_v4.json", "draft_plan_v5.json")
        .replace("_authorization.json", "_authorization_v2.json")
    )
    with (here / "authorized_driver_draft_v2.py").open("x", encoding="utf-8") as f:
        f.write(source)
    print({"source_only_history_written": True, "old26_unchanged": True, "actual_phases": 0})


if __name__ == "__main__":
    main()
