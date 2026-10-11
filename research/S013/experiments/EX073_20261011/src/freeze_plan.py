"""Freeze source-only prospective method after final formatting and checks."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import entry_core as core
import entry_statistics as stats

HERE = Path(__file__).parent
ROOT = next(p for p in HERE.resolve().parents if (p / "pyproject.toml").exists())


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def main():
    sources = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))}
    focused = read(HERE / "focused_checks.json")
    assert focused["status"] == "PASS" and focused["source_hashes"] == sources
    refs66 = read(
        ROOT / "research/S013/experiments/EX066_20261011/protocols/final_evidence_references.json"
    )
    refs69 = read(
        ROOT / "research/S013/experiments/EX069_20261011/protocols/verification_references.json"
    )
    native = read(ROOT / "research/S013/experiments/EX069_20261011/protocols/plan.json")[
        "native_ref"
    ]
    refs71 = read(
        ROOT / "research/S013/experiments/EX071_20261011/protocols/verification_references.json"
    )
    refs72 = read(
        ROOT / "research/S013/experiments/EX072_20261011/protocols/result_references.json"
    )
    mandate = read(ROOT / "research/S013/deliveries/MANDATE/6/receipt.json")["reference"]
    availability = {
        "momentum20": "Close[T]/Close[T-20]-1",
        "range_position60": "(Close[T]-minLow60)/(maxHigh60-minLow60) through T; original range H/L limitations retained",
        "acf1": "original simple pct_change rolling20 mean-centered unbiased lag1 divided by population variance through T",
        "volatility20": "Close simple pct_change rolling20 sample standard deviation ddof1 through T",
        "intraday_return": "T Close/Open-1",
        "overnight_gap": "log(T Open/past session Close)",
        "intraday_energy20": "original trailing20 complete8bar intraday total squared-log-return energy root",
        "intraday_rms20": "sqrt(rolling20 mean(log(Close/Open)^2)) through T",
        "confirmation_score": "original C8880 T complete daily/intraday causal confirmation",
        "daily_close_location": "(2Close-High-Low)/(High-Low) on T; original HL limitations retained, not used for new risk labels",
        "feature_intraday_down_energy20": "rolling20 sum(within-day negative logreturn squared energy)/rolling20 sum(total within-day squared energy) through T; original first19 missing",
        "feature_overnight_down_energy20": "sqrt(rolling20 mean(min(log(Open/priorClose),0)^2)) through T",
        "turnover20": "T Amount/rolling20 mean Amount including T",
        "volume_ratio20": "T Volume/rolling20 mean Volume including T",
    }
    assert set(availability) == set(stats.CONTROLS)
    plan = {
        "role": "RSCH",
        "stage": 2,
        "prospective_frozen_utc": datetime.now(timezone.utc).isoformat(),
        "authorization": "root授权前瞻源码/声明EX073，实际统计须root下一明确启动；用户自主研究范围内S013-only",
        "question": "最后一次固定压力职责收口：真实原bear入场后第3-4日继续持有是否负收益/更大下行风险？",
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "component_method": core.METHOD,
        "statistics": stats.METHOD,
        "single_scope": "first actual C8880 bear BUY fills, align original signal_date T, include original early exits hypothetically; no future exit or outcome selection",
        "entry_selection_caveat": "actual fill realization occurs T+1, so this conditional realized-entry population is not a T-deployable filter; only flag/controls were known at T. Record unfilled/other route identities; no future old exit selector.",
        "hypothesis_signs": {
            "pressure_flag": "negative late_return, positive late_downside; never invert or rescue window/ratio/year"
        },
        "known_selected_information": {
            "EX069": "original positive recovery hypothesis failed despite negative return/positive risk association",
            "EX071": "actual-held lateweak continuation ineffective including2023 reversal; no exit change supported",
            "EX072": "fixed filter failed closed107<110; CAGR13.9851 vs17.1346 and fullDD15.0419 vs13.6187 worse; 2023 improvement alone not rescue",
            "old_signal_trigger_audit": "bear64, flagged15,2022flag4,2023flag3; actual fill-authenticated counts may differ and are not forced",
        },
        "control_availability_at_T": availability,
        "control_implementation_sources": [
            "research/S013/experiments/EX060_20261011/src/component_definitions.py",
            "research/S013/experiments/EX060_20261011/src/run_study_v4.py",
            "research/S013/experiments/EX061_20261011/src/run_opportunity_study.py",
            "research/S013/experiments/EX066_20261011/src/driver.py",
        ],
        "inputs": "EX058 authenticated original C8880 native cache exact public evidence; EX066 old14 features exact aligned withEX069; EX069 already public HFQ daily O/C warmup for pressure; native priced execution daily for labels. No provider/fetch.",
        "input_references": {
            "old_features.csv": refs66["features.csv"],
            "pressure_features.csv": refs69["features.csv"],
            "warm_prices.csv": refs69["daily_prices.csv"],
            "predecessor_verification.json": refs69["verification.json"],
        },
        "native_ref": native,
        "delivery_lineage": {
            "permitted_stage_predecessor": mandate,
            "purpose": "standalone single fixed pressure-responsibility component supplement, not replacement of original complete component panel",
            "excluded_unused_candidate_dependency": "No full CANDIDATES58 or COMPONENTS9 delivery ancestor; all actually used inputs and known counterevidence explicit EvidenceRefs",
        },
        "known_counterevidence_references": {
            "EX069_statistics": refs69["statistics.json"],
            "EX069_verification": refs69["verification.json"],
            "EX071_plan": refs71["plan.json"],
            "EX071_statistics": refs71["statistics.json"],
            "EX071_verification": refs71["verification.json"],
            "EX072_plan": refs72["plan"],
            "EX072_native_centre": refs72["centre"],
            "EX072_verification": refs72["verification"],
        },
        "source_files": sources,
        "common_sha256": sha256(
            (ROOT / "research/S013/experiments/EX058_20261011/src/common.py").read_bytes()
        ).hexdigest(),
        "limitations": [
            "same repeatedly seen development pool; bootstrap not selection corrected",
            "64/15 signal counts thin; annual3/4 flagged cannot establish independent confidence",
            "partial controls rank may explain flag or exhaust residualdf; retain null without control removal",
            "binary minority less20 means grouped evidence unreliable even if raw/partial overall calculable",
            "O/C risk ignores intraday extremes, no HL/path/account DD",
            "price counterfactual across native old exits, no current strategy economic claim",
            "fullaxis temporal blocks with sparse entries may produce unusable replicates; all statuses retained",
            "HFQ excludes dividend overlay; original historical revision/publication times not independently verified",
        ],
        "independent_check": "fill replay zero-to-positive and T action/valid date/quantity identity; pressure direct past4 arithmetic and unchangedEX069share; old14 allrows exact; fixed Open endpoints, maturity, samefee identity, O/C risk, multiplicative decomposition; every overall/year/phase and all500x4 replicate correlation/rank/df/status and CI recalc",
        "budget": {
            "workers": 1,
            "components": 1,
            "scopes": 1,
            "primary_labels": 2,
            "raw_partial_bootstrap_sets": 4,
            "bootstrap_per_set": 500,
            "block_sessions": 40,
            "seed": 13,
            "maximum_correlations": 2056,
            "predictive_models": 0,
            "parameter_trials": 0,
            "new_accounts": 0,
            "provider_requests": 0,
            "DEV_writes": 0,
        },
        "startup": "declare only now; actual input/statistics require separate root_statistics_authorization.json after source review",
        "stop": "One fixed run; weak/reversed/unavailable => preserve and stop pressure feature rescue. No strategy prototype, thresholds, ratio/lookback/horizon search, new economic gates or financial accounts.",
    }
    for name, value in (
        (
            "method.json",
            {"component": core.METHOD, "statistics": stats.METHOD, "source_files": sources},
        ),
        ("prospective_plan.json", plan),
    ):
        path = HERE / name
        assert not path.exists(), "no overwrite frozen method"
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
        )
    print(
        {"source_only_frozen": True, "sources": len(sources), "allocations": 0, "statistic_runs": 0}
    )


if __name__ == "__main__":
    main()
