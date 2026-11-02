"""RSCH final numerical review and explicit schema-15 delivery; no account replay.

Run after the complete 269-account current-implementation manifest is published.
Without --publish only analysis and a report draft are written. Independent
account audits are never invoked. Historical evidence is retained unchanged.
"""
# ruff: noqa: E402
from __future__ import annotations

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUTPUT = WORK / "others/bounded_v1"
SCRATCH = ROOT / ".tmp/s017-bounded-stage4-finalize-v1"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math
from statistics import median
from time import perf_counter

from dataflows import ProviderConfig
from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, assemble_delivery, create_research_context, load_candidate,
    publish_evidence, validate_experiment,
)
from czsc_trader.research_tools.equity_replay import build_equity_assessment, materialize_equity
from strategy_evaluator import (
    CandidatePerformanceAssessmentRequest, DeclaredParameterPointSet,
    DeclaredPointSetComparisonContract, ParameterPerformanceEvidence,
    assessment_benchmark_fingerprint, assess_candidates, compare_candidates,
)
from strategy_evaluator import research_models as m
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources, canonical_sha256
from strategy_runtime.equity import equity_hash

from finalize_calmar_v2_analysis import calmar, combine, numeric_metrics, quantile, scalar

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
CONSTRUCTION = "d7d8ce3141d97f7502bef9a7df5213e320c8388e037ac718c10fa682f9471534"
NONPARAMETER_FIELDS = (
    "window", "history_start", "instrument", "specification", "specification_hash",
    "initial_cash", "input_binding", "data_manifest", "sources", "warmup_bars",
    "benchmark", "benchmark_sha256", "frequency_window_days", "drawdown_basis",
    "concentration_basis", "engine_sources",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes(), parse_constant=lambda value: (
        _ for _ in ()).throw(ValueError(f"Nonfinite JSON value: {value}")))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def close(left, right, label):
    require(left is not None and right is not None and math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-11),
            f"RSCH numerical verification differs: {label}: {left}, {right}")


def published(record):
    reference = d.EvidenceRef.from_dict(record["evidence"])
    require(reference.experiment.strategy_id == "S017" and reference.schema == "equity_research"
            and reference.schema_version == 4, "Only explicit S017 V4 publications are accepted")
    path = reference.resolve(ROOT)
    content = path.read_bytes()
    require(sha256(content).hexdigest() == reference.sha256, "Published account bytes differ")
    envelope = json.loads(content)
    request = envelope["request"]
    require(envelope["request_hash"] == record["request_hash"] == equity_hash(request)
            and envelope["evaluation_id"] == record["evaluation_id"], "Published result identity differs")
    require(request["content_sha256"] == record["identity"]
            and request["candidate_id"] == record["candidate"], "Published candidate differs from manifest")
    require(request["window_id"] == "TRAIN_2024_2025" and request["history_start"] == "2023-11-01"
            and request["window"] == {"start": "2024-01-02T14:30:00+00:00", "end": "2025-12-31T21:00:00+00:00"}
            and request["initial_cash"] == 100000. and request["drawdown_basis"] == "BAR_CLOSE"
            and request["concentration_basis"] == "MAX_SINGLE" and request["frequency_window_days"] == 60,
            "Account has a different sample or metric contract")
    return reference, path, envelope


def center_fact(record, key, scenario, cost):
    reference, path, envelope = published(record)
    request = envelope["request"]
    require(request["candidate_id"] == key and request["scenario_id"] == scenario
            and request["fee_rate"] == cost, "Center scenario/cost differs")
    owned = {(envelope[name]["kind"], envelope[name]["sha256"])
             for name in ("input_ref", "candidate_ref", "benchmark_ref")}

    def resolve(item):
        require((item["kind"], item["sha256"]) in owned, "Unowned ledger dependency")
        content = (path.parent / (item["sha256"] + ".json")).read_bytes()
        require(sha256(content).hexdigest() == item["sha256"], "Ledger dependency bytes differ")
        return content

    fact, = build_equity_assessment(materialize_equity(path.read_bytes(), resolve))
    require(fact.candidate == m.AssessmentCandidate("S017-" + key, record["identity"]), "Center identity differs")
    metrics = numeric_metrics(record["candidate_metrics"])
    baseline = numeric_metrics(record["benchmark_metrics"])
    from strategy_evaluator.equity_assessment import equity_performance
    for actual, expected in zip(equity_performance(fact),
                               (metrics["NET_ANNUAL_RETURN"], metrics["DRAWDOWN_MAGNITUDE"]), strict=True):
        close(actual, expected, key + " center metrics")
    for actual, expected in zip(equity_performance(fact, benchmark=True),
                               (baseline["NET_ANNUAL_RETURN"], baseline["DRAWDOWN_MAGNITUDE"]), strict=True):
        close(actual, expected, key + " benchmark metrics")
    return fact, envelope, reference


def load_inputs():
    manifest = read(OUTPUT / "manifest.json")
    require(manifest["status"] == "COMPLETED", "Full current-implementation execution is not complete")
    require(manifest["construction_sha256"] == CONSTRUCTION and manifest["planned_strategy_accounts"] == 269
            and manifest["old_accounts_mixed"] is False and manifest["independent_account_audits"] == 0,
            "Declared execution scope or implementation policy differs")
    require(set(manifest["standards"]) == set(manifest["pressures"]) == set(manifest["parameters"]) == set(KEYS),
            "The six-candidate scope is incomplete")
    proposal = read(WORK / "others/bounded_parameter_check_proposal.json")
    require(canonical_sha256(proposal["construction"]) == CONSTRUCTION, "Fixed construction changed")
    confirmed = read(WORK / "protocols/confirmed_bounded_stage4_v3.json")
    require(confirmed["construction_sha256"] == CONSTRUCTION, "Current protocol construction differs")
    protocol = m.CalmarSelfCheckProtocol.from_dict(confirmed["protocol"])
    policy = m.ComparisonPolicy.from_dict(confirmed["policy"])
    targets = m.ResearchTargets.from_dict(confirmed["targets"])
    atoms = tuple(atom for target in targets.requirements for atom in (
        (*target.joint_targets, *target.all_point_targets)
        if isinstance(target, m.ParameterNeighborhoodTarget) else (target,)))
    require(not any(isinstance(target, m.ResearchTarget) and target.metric is m.ResearchMetric.NET_ANNUAL_RETURN
                    for target in atoms), "An independent net-annual-return hard gate was introduced")
    plans, plan_refs, selections = {}, {}, []
    for key in KEYS:
        source = proposal["centers"][key]
        indices = tuple(point["source_full_plan_point_index"] for point in source["proposed_points"])
        require(indices == tuple(confirmed["point_sets"][key]["source_point_indices"])
                and len(indices) == confirmed["point_sets"][key]["N"], "Protocol point set changed")
        records = manifest["parameters"][key]
        require(len(records) == source["proposed_N"] == len(indices)
                and len({row["index"] for row in records}) == len(indices)
                and {row["index"] for row in records} == set(indices), "Missing/duplicate/unexpected parameter points: " + key)
        path = OUTPUT / "plans" / (key + ".json")
        description = read(OUTPUT / "plans" / (key + "-reference.json"))
        reference = d.EvidenceRef.from_dict(description["reference"])
        require(reference.resolve(ROOT).read_bytes() == path.read_bytes(), "Published plan changed")
        plan = d.ParameterEvaluationPlan.from_dict(read(path))
        require(plan.design.center.candidate_id == "S017-" + key, "Wrong plan center")
        for point in source["proposed_points"]:
            actual = {item.name: item.value for item in plan.design.points[point["source_full_plan_point_index"]].values}
            require(actual == point["values"], "Current design changed declared coordinates")
        plans[key], plan_refs[key] = plan, reference
        selections.append(DeclaredParameterPointSet(plan.design, indices, CONSTRUCTION))
    require(sum(len(manifest["parameters"][key]) for key in KEYS) == 257, "The full 257-point set is incomplete")
    return manifest, proposal, protocol, policy, targets, plans, plan_refs, tuple(selections)


def parameter_projection(record, key, plan, plan_ref, base, standard, benchmark_fingerprint):
    reference, _, envelope = published(record)
    request, origin = envelope["request"], standard["request"]
    require(all(request[name] == origin[name] for name in NONPARAMETER_FIELDS),
            "Parameter account changes implementation/data/execution context: " + key)
    require(envelope["data"] == standard["data"] and envelope["benchmark_ref"] == standard["benchmark_ref"]
            and envelope["benchmark_identity"] == standard["benchmark_identity"], "Parameter benchmark/input differs")
    index = record["index"]
    child = plan.children[index]
    require(child.candidate.candidate_id == "S017-" + record["candidate"]
            and child.candidate.content_sha256 == record["identity"]
            and request["candidate_definition"] == json.loads(child.payload_json)["equity_definition"],
            "Parameter payload differs from original planned point")
    binding = d.ParameterEvaluationBinding.from_dict(request["lineage"]["parameter_binding"])
    require(binding.plan == plan_ref and binding.point == plan.design.bind_point(index)
            and request["lineage"]["parameter_binding"] == record["parameter_binding"], "Original point binding differs")
    value = ParameterPerformanceEvidence.from_dict(record["performance_projection"])
    require(value.candidate == child.candidate and value.parent == base.candidate
            and value.parameter_point == binding.point and value.request_sha256 == record["request_hash"]
            and value.result_sha256 == reference.sha256 and value.evaluation_id == record["evaluation_id"]
            and value.context_sha256 == base.context_sha256 and value.metric_version == base.metric_version
            and value.benchmark_equity_sha256 == benchmark_fingerprint
            and value.scenario_context == base.scenario_context and value.initial_cash == base.initial_cash
            and value.frequency_window_days == 60, "Published numeric projection context or identity differs")
    require(value.derivation_sha256 == canonical_sha256(request["lineage"]["derivation"])
            and request["scenario_id"] == "STANDARD" and request["fee_rate"] == .001,
            "Parameter derivation/scenario differs")
    actual, benchmark = numeric_metrics(record["candidate_metrics"]), numeric_metrics(record["benchmark_metrics"])
    for left, right in zip((value.performance.annual_return, value.performance.drawdown,
                           value.performance.benchmark_return, value.performance.benchmark_drawdown),
                          (actual["NET_ANNUAL_RETURN"], actual["DRAWDOWN_MAGNITUDE"],
                           benchmark["NET_ANNUAL_RETURN"], benchmark["DRAWDOWN_MAGNITUDE"]), strict=True):
        close(left, right, "parameter numeric projection")
    return value, reference


def curve_metrics(points, opening, observations):
    peak, maximum = opening, 0.
    for point in points:
        peak = max(peak, point["equity"])
        maximum = max(maximum, 1 - point["equity"] / peak)
    annual = (points[-1]["equity"] / opening) ** (252 / observations) - 1
    return {"NET_ANNUAL_RETURN": annual, "DRAWDOWN_MAGNITUDE": maximum,
            "NET_CALMAR": calmar(annual, maximum)}


def time_analysis(fact, protocol):
    candidate, benchmark = (json.loads(content) for content in (fact.equity.candidate_ledger, fact.equity.benchmark_ledger))
    by_session = [{}, {}]
    for mapping, ledger in zip(by_session, (candidate, benchmark), strict=True):
        for point in ledger["account_points"]:
            mapping.setdefault(point["session"], []).append(point)
    sessions = tuple(item.session for item in fact.account)
    require(len(sessions) == 502 and sessions[0] == "2024-01-02" and sessions[-1] == "2025-12-31",
            "Actual 2024-2025 trading calendar differs")

    def sliced(start, count):
        result = []
        for mapping in by_session:
            opening = fact.initial_cash if start == 0 else mapping[sessions[start - 1]][-1]["equity"]
            points = [point for session in sessions[start:start + count] for point in mapping[session]]
            result.append(curve_metrics(points, opening, count))
        return {"start": sessions[start], "end": sessions[start + count - 1], "sessions": count,
                "candidate": result[0], "benchmark": result[1],
                "excess_calmar": None if result[0]["NET_CALMAR"] is None or result[1]["NET_CALMAR"] is None
                else result[0]["NET_CALMAR"] - result[1]["NET_CALMAR"]}

    years = []
    for year in ("2024", "2025"):
        positions = [index for index, session in enumerate(sessions) if session.startswith(year)]
        years.append(sliced(positions[0], len(positions)))
    windows = [sliced(start, protocol.rolling_window_days)
               for start in range(0, len(sessions) - protocol.rolling_window_days + 1, protocol.rolling_step_days)]
    require(len(windows) == 12, "Rolling window coverage differs")
    excess = [item["excess_calmar"] for item in windows]
    streak = longest = 0
    for value in excess:
        streak = streak + 1 if value is not None and value < 0 else 0
        longest = max(longest, streak)
    winners = sorted((item["net_pnl"] for item in candidate["trades"] if item["net_pnl"] > 0), reverse=True)
    concentration = None if not winners else winners[0] / sum(winners)
    return {"years": years, "rolling_windows": windows, "rolling_excess_calmar_q10": quantile(excess, .1),
            "negative_rolling_windows": sum(value is not None and value < 0 for value in excess),
            "longest_negative_rolling_run": longest, "max_single_profit_concentration": concentration}


def verify_hard_gates(panel, compared, targets, manifest, facts, pressures, protocol):
    rows, results, summaries = {row.candidate.candidate_id: row for row in panel.rows}, {}, {}
    group, = (target for target in targets.requirements if isinstance(target, m.ParameterNeighborhoodTarget))
    for ranked in compared.rows:
        key = ranked.candidate.candidate_id.removeprefix("S017-")
        row, fact = rows[ranked.candidate.candidate_id], facts[key]
        metrics = {item.metric.value: item.value for item in row.diagnostics}
        standard, baseline = (numeric_metrics(manifest["standards"][key][name])
                              for name in ("candidate_metrics", "benchmark_metrics"))
        stress, stress_bh = (numeric_metrics(manifest["pressures"][key][name])
                             for name in ("candidate_metrics", "benchmark_metrics"))
        counts = Counter(item.exit_session for item in fact.closed_cycles)
        sessions = [item.session for item in fact.account]
        windows = [sum(counts[session] for session in sessions[index:index + 60]) for index in range(len(sessions) - 59)]
        close(metrics["FREQUENCY_MEDIAN"], float(median(windows)), key + " actual-session frequency")
        coverage = sum(count >= 3 for count in windows)
        require((row.frequency_coverage.total_windows, row.frequency_coverage.covered_windows) == (len(windows), coverage),
                "Independent frequency-window coverage differs")
        checked, point_checks = [], []
        standard["FREQUENCY_MEDIAN"] = float(median(windows))
        for target in targets.requirements:
            if isinstance(target, m.FrequencyCoverageTarget):
                passed = coverage * target.minimum_denominator >= len(windows) * target.minimum_numerator
                checked.append({"target_id": target.target_id, "status": "PASSED" if passed else "FAILED"})
            elif isinstance(target, m.ParameterNeighborhoodTarget):
                for record in manifest["parameters"][key]:
                    value, bh = numeric_metrics(record["candidate_metrics"]), numeric_metrics(record["benchmark_metrics"])
                    joint = [scalar(atom, value, bh, .001) for atom in target.joint_targets]
                    all_points = [scalar(atom, value, bh, .001) for atom in target.all_point_targets]
                    point_checks.append({"index": record["index"], "joint": joint, "all": all_points})
                total = len(point_checks)
                minimum = (13 * total + 15) // 16
                joint_count = sum(combine(point["joint"]) == "PASSED" for point in point_checks)
                status = ("FAILED" if any(combine(point["all"]) == "FAILED" for point in point_checks)
                          else "INDETERMINATE" if any(combine(point["joint"]) == "INDETERMINATE"
                              or combine(point["all"]) == "INDETERMINATE" for point in point_checks)
                          else "PASSED" if joint_count >= minimum else "FAILED")
                checked.append({"target_id": target.target_id, "status": status})
                calculated = next(item for item in ranked.target_checks if item.target.target_id == group.target_id)
                require((calculated.required_points, calculated.minimum_joint_passes, calculated.valid_points,
                         calculated.joint_passes) == (total, minimum, total, joint_count), "Independent parameter counts differ")
            else:
                require(type(target) is m.ResearchTarget, "Unsupported hard target")
                pressure = target.scope is m.TargetScope.STRESS
                checked.append(scalar(target, stress if pressure else standard, stress_bh if pressure else baseline,
                                      .002 if pressure else .001))
        require({item["target_id"]: item["status"] for item in checked}
                == {item.target.target_id: item.status.value for item in ranked.target_checks}, "Independent hard gates differ")
        require(combine(checked) == ranked.acceptance_status.value, "Independent aggregate acceptance differs")
        times = time_analysis(fact, protocol)
        close(times["rolling_excess_calmar_q10"], row.rolling_calmar_excess_q10.value, key + " rolling Calmar Q10")
        close(times["max_single_profit_concentration"], metrics["PROFIT_CONCENTRATION"], key + " concentration")
        points = [numeric_metrics(record["candidate_metrics"]) for record in manifest["parameters"][key]]
        q10, q90 = quantile([point["NET_CALMAR"] for point in points], .1), quantile([point["DRAWDOWN_MAGNITUDE"] for point in points], .9)
        close(q90, metrics["PARAMETER_DRAWDOWN_Q90"], key + " declared DD Q90")
        ranking_inputs = {"NET_CALMAR": standard["NET_CALMAR"], "DRAWDOWN_MAGNITUDE": standard["DRAWDOWN_MAGNITUDE"],
            "PARAMETER_CALMAR_Q10": q10, "PARAMETER_DRAWDOWN_Q90": q90,
            "ROLLING_EXCESS_CALMAR_Q10": times["rolling_excess_calmar_q10"],
            "STRESS_CALMAR_LOSS": standard["NET_CALMAR"] - stress["NET_CALMAR"],
            "PROFIT_CONCENTRATION": metrics["PROFIT_CONCENTRATION"], "FREQUENCY_MEDIAN": metrics["FREQUENCY_MEDIAN"]}
        summaries[key] = {"standard": standard, "standard_benchmark": baseline, "pressure": stress,
            "pressure_benchmark": stress_bh, "target_checks": checked, "parameter_point_checks": point_checks,
            "parameter_joint_passes": sum(combine(point["joint"]) == "PASSED" for point in point_checks),
            "parameter_minimum_joint_passes": (13 * len(points) + 15) // 16, "N": len(points),
            "frequency_windows": len(windows), "frequency_covered": coverage,
            "frequency_coverage": coverage / len(windows), "ranking_inputs": ranking_inputs,
            "time": times, "uncertainty": row.uncertainty.to_dict(), "coverage_gaps": list(row.coverage_gaps),
            "acceptance": ranked.acceptance_status.value, "comparison_status": ranked.status.value,
            "pareto_layer": ranked.pareto_layer, "rank_min": ranked.rank_min, "rank_max": ranked.rank_max}
        results[key] = ranked
    return summaries, results


def verify_ranking(summaries, results, policy):
    eligible = {key for key, row in summaries.items() if row["acceptance"] == "PASSED"
                and all(value is not None and math.isfinite(value) for value in row["ranking_inputs"].values())}
    require(eligible == {key for key, row in results.items() if row.pareto_layer is not None},
            "Eligible and actually ranked candidates differ")
    remaining, layer = set(eligible), 1
    maximize = {m.ResearchMetric.PARAMETER_CALMAR_Q10, m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
                m.ResearchMetric.FREQUENCY_MEDIAN}
    specifications = {item.metric: item for item in policy.bins}
    while remaining:
        def dominates(a, b):
            left, right = summaries[a]["ranking_inputs"], summaries[b]["ranking_inputs"]
            return (left["NET_CALMAR"] >= right["NET_CALMAR"] and left["DRAWDOWN_MAGNITUDE"] <= right["DRAWDOWN_MAGNITUDE"]
                    and (left["NET_CALMAR"] > right["NET_CALMAR"] or left["DRAWDOWN_MAGNITUDE"] < right["DRAWDOWN_MAGNITUDE"]))
        front = {key for key in remaining if not any(dominates(other, key) for other in remaining - {key})}
        require(front, "Independent Pareto layering failed")
        vectors = {}
        for key in front:
            bins = []
            for metric in policy.ranking_metrics:
                value, spec = summaries[key]["ranking_inputs"][metric.value], specifications[metric]
                bucket = int(((Decimal(str(value)) - Decimal(str(spec.origin))) / Decimal(str(spec.resolution)))
                             .to_integral_value(rounding=ROUND_FLOOR))
                bins.append(bucket)
            require(tuple(bins) == results[key].bin_values, "Independent ranking bins differ")
            vectors[key] = tuple(-bucket if metric in maximize else bucket
                                 for metric, bucket in zip(policy.ranking_metrics, bins, strict=True))
        for key in front:
            rank = 1 + sum(vectors[other] < vectors[key] for other in front)
            last = rank + sum(vectors[other] == vectors[key] for other in front) - 1
            require((results[key].pareto_layer, results[key].rank_min, results[key].rank_max) == (layer, rank, last),
                    "Independent Pareto/lexicographic order differs")
        remaining -= front
        layer += 1
    return sorted(eligible, key=lambda key: (results[key].pareto_layer, results[key].rank_min, key))


def historical_counterevidence():
    """Review old adverse numeric observations without changing historical eligibility."""
    adverse, seen, sources, annual_labels = [], set(), [], []
    for directory in (WORK / "others/neighborhood_batches", WORK / "others/neighborhood_batches_v2"):
        for path in sorted(directory.glob("*.json")):
            value = read(path)
            for record in value.get("records", []):
                if "candidate_metrics" not in record or "benchmark_metrics" not in record:
                    continue
                reference = record.get("evidence")
                if reference is None or reference["sha256"] in seen:
                    continue
                seen.add(reference["sha256"])
                metrics, baseline = numeric_metrics(record["candidate_metrics"]), numeric_metrics(record["benchmark_metrics"])
                if record.get("joint_pass") is False:
                    annual_labels.append({"source": path.relative_to(WORK).as_posix(), "center": value.get("center"),
                        "index": record.get("index"), "evidence": reference,
                        "historical_rule_label": "OLD_ANNUAL_RETURN_JOINT_FAIL",
                        "interpretation": "Retained original label; not used as a current Calmar gate"})
                failed = (metrics["DRAWDOWN_MAGNITUDE"] > .25
                          or metrics["DRAWDOWN_MAGNITUDE"] > .9 * baseline["DRAWDOWN_MAGNITUDE"]
                          or metrics["NET_CALMAR"] is None or baseline["NET_CALMAR"] is None
                          or metrics["NET_CALMAR"] < float(Decimal(str(baseline["NET_CALMAR"])) * Decimal('1.25')))
                if failed:
                    adverse.append({"source": path.relative_to(WORK).as_posix(), "center": value.get("center"), "index": record.get("index"),
                        "candidate": record.get("candidate"), "metrics": metrics, "benchmark": baseline,
                        "evidence": reference, "interpretation": "Historical adverse observation; not reassigned to the new declaration"})
                    sources.append(d.EvidenceRef.from_dict(reference))
    return {"historical_unique_published_points_reviewed": len(seen), "adverse_observations": adverse,
            "old_annual_rule_fail_labels_preserved": annual_labels,
            "historical_eligibility_rewritten": False}, tuple(dict.fromkeys(sources))


def report_text(summary):
    rows, rankable = summary["centers"], summary["rankable_candidates"]
    recommended = [key for key in rankable if (rows[key]["pareto_layer"], rows[key]["rank_min"])
                   == (rows[rankable[0]]["pareto_layer"], rows[rankable[0]]["rank_min"])] if rankable else []
    narrative = (f"推荐优先审阅{'、'.join(recommended)}，金融排名并列时一并保留；其余入围配置及代价见附录。进入阶段五仍需用户选定具体候选。"
                 if recommended else "当前没有同时满足全部硬门且可比的配置，建议暂缓进入阶段五，先依据失败项决定补证或回到研究。")
    rank_labels = {key: ("未入榜" if rows[key]["pareto_layer"] is None else
        f"{rows[key]['pareto_layer']} / {rows[key]['rank_min']}—{rows[key]['rank_max']}") for key in KEYS}
    table = "\n".join(f"|{key}|{rows[key]['standard']['NET_ANNUAL_RETURN']:.2%}|{rows[key]['standard']['DRAWDOWN_MAGNITUDE']:.2%}|"
        f"{rows[key]['standard']['NET_CALMAR']:.6f}|{rows[key]['parameter_joint_passes']}/{rows[key]['N']}（需{rows[key]['parameter_minimum_joint_passes']}）|"
        f"{rows[key]['acceptance']}|{rank_labels[key]}|" for key in KEYS)
    diagnostic = "\n".join(f"|{key}|{rows[key]['ranking_inputs']['PARAMETER_CALMAR_Q10']:.6f}|"
        f"{rows[key]['ranking_inputs']['PARAMETER_DRAWDOWN_Q90']:.2%}|{rows[key]['ranking_inputs']['ROLLING_EXCESS_CALMAR_Q10']:.6f}|"
        f"{rows[key]['ranking_inputs']['STRESS_CALMAR_LOSS']:.6f}|{rows[key]['ranking_inputs']['PROFIT_CONCENTRATION']:.2%}|"
        f"{rows[key]['ranking_inputs']['FREQUENCY_MEDIAN']:.1f}|{rows[key]['frequency_covered']}/{rows[key]['frequency_windows']}|" for key in KEYS)
    years = "\n".join(f"|{key}|{year['start'][:4]}|{year['candidate']['NET_ANNUAL_RETURN']:.2%}|"
        f"{year['candidate']['DRAWDOWN_MAGNITUDE']:.2%}|{year['benchmark']['NET_ANNUAL_RETURN']:.2%}|"
        f"{year['benchmark']['DRAWDOWN_MAGNITUDE']:.2%}|" for key in KEYS for year in rows[key]["time"]["years"])
    pressures = "\n".join(f"|{key}|{rows[key]['pressure']['NET_ANNUAL_RETURN']:.2%}|{rows[key]['pressure']['DRAWDOWN_MAGNITUDE']:.2%}|"
        f"{rows[key]['pressure']['NET_CALMAR']:.6f}|{rows[key]['pressure_benchmark']['NET_CALMAR']:.6f}|" for key in KEYS)
    def interval_label(value):
        if (value["status"] == m.DiagnosticStatus.AVAILABLE.value
                and value["lower_95"] is not None and value["upper_95"] is not None):
            return f"{value['lower_95']:.6f}—{value['upper_95']:.6f}"
        return value["status"] + "：" + (value["reason"] or "区间不可用")

    intervals = "\n".join(f"|{key}|{interval_label(rows[key]['uncertainty'])}|"
        f"{rows[key]['time']['negative_rolling_windows']}/12|{rows[key]['time']['longest_negative_rolling_run']}|" for key in KEYS)
    failed = "\n".join(f"- {key}：" + "；".join(f"{item['target_id']}={item['status']}" for item in rows[key]["target_checks"]
        if item["status"] in ("FAILED", "INDETERMINATE")) for key in KEYS if rows[key]["acceptance"] != "PASSED") or "全部适用硬门均通过。"
    risk_table = "\n".join(f"|{key}|{rows[key]['parameter_max_drawdown']:.4%}|"
        f"{rows[key]['parameter_dd_cap_failure_count']}/{rows[key]['N']}|" for key in KEYS)
    single_axis_risks = "\n".join(
        f"- {key}：单独将{item['parameter']}由{item['center_value']:.8f}改为{item['point_value']:.8f}，"
        f"原点编号{item['point_index']}的回撤为{item['drawdown']:.4%}。"
        for key in KEYS for item in rows[key]["single_axis_dd_cap_failures"])
    parameter_names = ("alpha", "initial_fraction", "accepted_fraction", "g_when_u", "g_when_other", "g_when_mf")
    parameters = "\n".join("|" + key + "|" + "|".join(f"{rows[key]['parameters'][name]:.8f}"
                                                      for name in parameter_names) + "|" for key in KEYS)
    execution = summary["execution_observation"]
    return f"""# EX076：固定257点自检完成，RSCH完成目标核验及Calmar排序

本轮阶段四计算与数值自检已完成：六标准、六压力和257个固定邻点，共269个策略账户使用同一当前实现重新计算并显式发布；不自动混用旧65点。RSCH已核验完整N、原点绑定、全部硬门及v8/v6排序。数值通过候选：{', '.join(key for key in KEYS if rows[key]['acceptance'] == 'PASSED') or '无'}。这不等于独立样本验证、冻结或生产准入。

## 做了哪些尝试

沿用2024—2025开发样本、2023-11-01起预热、100000美元初始资金、逐柱回撤及既定成交合同。固定65个单参数方向点与192个联合点；非零参数相对±5%，零g绝对0.05，真实合法边界不裁剪。每配置32个联合点按F=A×B×C×D×E固定半份构造，方向先于本轮绩效确定。TDR公共执行会话最多12个工作进程、每进程1线程，共享同合同买持；TDR保留可审计事实，默认不重做独立账户审计。

中心Calmar严格大于同合同买持1.5倍、DD不高于买持0.8倍且不高于25%；参数至少ceil(13N/16)点联合满足Calmar≥买持1.25倍及DD≤买持0.9倍，全部点DD≤25%。压力每侧0.2%按同压力买持核验Calmar及回撤。60实际交易日闭合中位≥6，至少90%完整窗口≥3。没有独立净年化收益门，缺失不缩N、不补值。

本轮账户准备、回放及显式发布合计{execution['elapsed_seconds'] / 60:.2f}分钟，采样进程树RSS峰值{execution['memory']['peak_tree_rss'] / 2**30:.2f}GiB、最低可用内存{execution['memory']['minimum_available'] / 2**30:.2f}GiB；该计时不含后续RSCH聚合及正式交付。原生并行累计时间不当作墙钟提速倍数，45分钟是估算节点。

## 有哪些收获

五项自检均已处理：参数采用本次完整声明点集；时间按连续原账切片年度及12个滚动252交易日窗口；集中性检查最大盈利周期贡献；执行按独立费用压力；统计不确定性报告成对stationary bootstrap年化收益差区间及研究族选择证据缺口。报告诊断不新增硬门；滚动超额Calmar、压力损失及集中度等仍按已确认政策参与排序。

{failed}

|配置|本次参数点最大回撤|超过25%上限的点数|
|---|---:|---:|
{risk_table}

{single_axis_risks}

联合通过比例与全点绝对风险上限分别核验；较高Calmar不能抵消任何已声明点的回撤超限。

这次固定点集不等于原2829点完整笛卡尔邻域。另32个联合角点、多数部分参数中心/端点组合、连续区域及高阶交互未穷尽；Q10/Q90仅描述本次离散检验集。方法修改发生在已知部分阶段四结果之后，不能倒称事前独立验证。旧结果不删除、不改资格，本次审阅旧已发布点{summary['historical_counterevidence']['historical_unique_published_points_reviewed']}个，其中按当前Calmar/DD观察到{len(summary['historical_counterevidence']['adverse_observations'])}个不利点，逐项记录；保留的{len(summary['historical_counterevidence']['old_annual_rule_fail_labels_preserved'])}个旧净年化联合门FAIL标签不自动成为新Calmar否决。旧未完成流程及事后改变方法的限制仍存在，新点集通过不能倒称旧全邻域通过。

只有2024—2025两年，反复开发和候选筛选共用样本；重叠滚动窗口不是12个独立市场样本。PBO、完整试验次数及有效次数的全研究族材料仍不足，不用六个入围中心冒充完整选择历史；收益区间未校正全部搜索偏差，不表示未来成功概率。未读取2026封存价格或策略绩效。

## 下一步建议

{narrative} 排序为已确认硬门通过后的中心Calmar/DD原始值帕累托分层，同层依次比较参数Calmar Q10、DD Q90、滚动超额Calmar Q10、压力Calmar下降量、最大盈利周期贡献及频率中位；比率分箱0.0001、频率0.5，全部同档保留并列，不以候选ID打破金融并列。

## 依据与结果附录

[本轮协议](../../protocols/confirmed_bounded_stage4_v3.json)、[完整计算清单](manifest.json)、[SE面板](panel.json)、[SE比较](comparison.json)、[RSCH独立数值核验](rsch_verification.json)、[完整分析](analysis.json)、[旧反证](historical_counterevidence.json)。正式发布状态及FULL核验回执见publication.json；本草稿在发布前不宣称正式交付已完成。

### 金融逻辑与精确参数

六配置共用“下跌柱被后续价格有效收复后入场、接受新支撑后逐步抬升保护线”的机制。alpha约束收复距离，initial_fraction决定初始结构失效线，accepted_fraction决定新接受结构的基础保护。三个g按入场时冻结的趋势/收复背景控制推进保护：g越大，上涨后保护线抬得越快，能保留更多已得利润，也更容易被正常回撤提前退出。持仓中不因新背景改路由，不用事后信息改写原入场。

C0338—C0342只改变MF背景（连续至少两根下跌柱被完整收复）的g，提供同机制的退出取舍；g为0仍保留基础结构保护，不表示完全没有止损。C0352同时改变六参数，alpha较高使入场要求更严格，不能把它与另五点的差异归因于单一MF保护。较低历史回撤不保证未来风险，任何局部收益差均不能证明独立的保护效果。

|配置|alpha|initial_fraction|accepted_fraction|g_when_u|g_when_other|g_when_mf|
|---|---:|---:|---:|---:|---:|---:|
{parameters}

### 中心与目标核对

|配置|净年化|逐柱DD|净Calmar|参数联合通过|全部硬门|层 / 层内名次区间|
|---|---:|---:|---:|---|---|---|
{table}

层级按原始Calmar与回撤值计算，表中舍入值不用于重新分层；同层才按既定分箱比较稳健性指标。

### 稳健性排序输入

|配置|参数Calmar Q10|参数DD Q90|滚动超额Calmar Q10|压力Calmar下降|最大盈利贡献|60日闭合中位|≥3笔窗口|
|---|---:|---:|---:|---:|---:|---:|---:|
{diagnostic}

### 费用压力

|配置|压力净年化|压力逐柱DD|压力Calmar|同压力买持Calmar|
|---|---:|---:|---:|---:|
{pressures}

### 年度切片（继承连续账户的资金和持仓）

|配置|年份|净年化|逐柱DD|买持净年化|买持逐柱DD|
|---|---:|---:|---:|---:|---:|
{years}

年度起点使用前一交易日末净值，逐柱DD包含该起点；不是重新投入本金的独立回测。12滚动窗逐项数值及连续落后详情保留在analysis.json。

### 成对统计区间与连续落后

|配置|净年化差95%区间|滚动Calmar差<0窗口|最长连续落后窗口数|
|---|---:|---:|---:|
{intervals}

区间为同历日成对stationary bootstrap、1000次、平均块长20、seed17；不是Calmar置信区间。原账、依赖数据和代码须与Git材料共同保留，单独Git无法恢复全部研究事实。
"""


def publish(request, panel, comparison_request, compared, summary, references, plan_refs):
    repository = RepositoryContext.discover(ROOT)
    batch, experiment = d.ResearchBatchRef("S017"), d.ExperimentRef("S017", WORK.name)
    candidate = load_candidate(repository, CandidateKey("S017", KEYS[0]))
    research = create_research_context(repository, batch, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(12, 1, 17))
    mandate = d.DeliveryReference.from_dict(read(OUTPUT / "mandate_reference.json"))
    require(mandate.stage is d.DeliveryStage.MANDATE and mandate.revision == 9, "New mandate reference differs")
    candidates = d.DeliveryReceipt.from_dict(read(ROOT / "research/S017/deliveries/CANDIDATES/3/receipt.json")).reference
    current_mandate = d.DeliveryContent.from_dict(read(ROOT / "research/S017/assets/deliveries/MANDATE/9/delivery.json")["content"])
    owners = {target.target_id: item.item_id for item in current_mandate.payload.items
              if isinstance(item.requirement, d.PerformanceRequirement) for target in item.requirement.targets}
    materials, material_paths = [], {}
    for name in ("analysis.json", "rsch_verification.json", "historical_counterevidence.json", "manifest.json",
                 "panel.json", "comparison.json", "comparison_request.json"):
        path = OUTPUT / name
        material = publish_evidence(research, d.MaterialEvidenceWrite(experiment, "bounded-v1-" + path.stem,
            path.read_bytes(), "application/json", "json"))
        materials.append(material)
        material_paths[name] = material.path
    for path in (Path(__file__), WORK / "protocols/confirmed_bounded_stage4_v3.json"):
        material = publish_evidence(research, d.MaterialEvidenceWrite(experiment, "bounded-v1-" + path.stem,
            path.read_bytes(), "text/x-python" if path.suffix == ".py" else "application/json", path.suffix[1:]))
        materials.append(material)
        material_paths[path.name] = material.path
    contrary = tuple(d.EvidenceRef.from_dict(row["evidence"])
                     for row in summary["historical_counterevidence"]["adverse_observations"])
    top = [key for key in summary["rankable_candidates"] if (
        summary["centers"][key]["pareto_layer"], summary["centers"][key]["rank_min"])
        == (summary["centers"][summary["rankable_candidates"][0]]["pareto_layer"],
            summary["centers"][summary["rankable_candidates"][0]]["rank_min"])] if summary["rankable_candidates"] else []
    recommendation = ("RSCH推荐优先审阅" + "、".join(top)
                      if summary["rankable_candidates"] else "全部候选暂不进入阶段五；依据失败或不足项决定后续研究")
    payload = d.CandidateAssessmentDelivery(candidates, mandate, request, panel, comparison_request, compared,
        tuple(d.TargetMandateBinding(target.target_id, owners[target.target_id])
              for target in comparison_request.targets.requirements), "frequency_days", "benchmark", recommendation,
        contrary, ("用户选择进入阶段五的具体候选、补证或暂缓",), parameter_plans=tuple(plan_refs[key] for key in KEYS))
    report = (OUTPUT / "report.md").read_text(encoding="utf-8")
    package_report = report.replace("../../protocols/confirmed_bounded_stage4_v3.json",
                                    material_paths["confirmed_bounded_stage4_v3.json"])
    publication_statement = ("本报告通过schema15公共assemble_delivery的FULL校验后发布；复用该次调用已完成的"
        "证据核对、SE复核及发布字节复核结果，不再额外冷读269份原账重做一次FULL。")
    package_report = package_report.replace("本草稿在发布前不宣称正式交付已完成。", publication_statement)
    for name, path in material_paths.items():
        package_report = package_report.replace("](" + name + ")", "](" + path + ")")
    evidence = tuple(dict.fromkeys((*references, *plan_refs.values(), *materials, *contrary)))
    definition = d.DeliveryDefinition(batch, d.DeliveryStage.ASSESSMENT, 1, (candidates, mandate), schema_version=15)
    assembled = assemble_delivery(repository, definition,
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=package_report, evidence=evidence),
        resources=ExecutionResources(12, 1, 17), on_progress=lambda event: print(
            "STAGE4_DELIVERY", event.phase.value, event.completed, event.total, flush=True))
    require(assembled.validation.status is d.ValidationStatus.PASS, "ASSESSMENT assembly failed")
    # Root report replacement is explicit and is only performed in publish mode.
    root_report = report.replace("../../protocols/", "protocols/").replace(
        "本草稿在发布前不宣称正式交付已完成。", publication_statement)
    for name in ("manifest.json", "panel.json", "comparison.json", "rsch_verification.json", "analysis.json",
                 "historical_counterevidence.json"):
        root_report = root_report.replace("](" + name + ")", "](others/bounded_v1/" + name + ")")
    (WORK / "report.md").write_text(root_report, encoding="utf-8", newline="\n")
    previous = d.EvidenceRef.from_dict(read(WORK / "report_ref.json")["report"])
    report_ref = publish_evidence(research, d.ExperimentReportWrite(experiment, sha256(root_report.encode()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, evidence, previous=previous))
    validated = validate_experiment(repository, d.ExperimentValidationRequest(experiment,
        d.ExperimentValidationScope.REPORT_PUBLICATION))
    require(validated.status is d.ValidationStatus.PASS, "Experiment report publication failed validation")
    save(OUTPUT / "publication.json", {"status": "STAGE4_COMPLETE_SCHEMA15_FULL_PASS",
        "assessment": assembled.receipt.to_dict(), "assembly_full_validation": assembled.validation.to_dict(),
        "additional_cold_full_validation_performed": False,
        "validation_evidence_reuse": "same assemble_delivery invocation FULL, publication and final byte checks",
        "report": report_ref.to_dict(),
        "experiment_validation": validated.to_dict(), "new_account_replays_by_finalization": 0,
        "independent_account_audit_performed": False, "sealed_2026_prices_accessed": False,
        "stage_five_authorized": False, "materials": [value.to_dict() for value in materials]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="Explicitly assemble schema15 and publish the root report")
    args = parser.parse_args()
    started = perf_counter()
    manifest, _, protocol, policy, targets, plans, plan_refs, selections = load_inputs()
    standards, pressures, metadata, references = {}, {}, {}, []
    implementation = None
    for key in KEYS:
        standard, envelope, reference = center_fact(manifest["standards"][key], key, "STANDARD", .001)
        pressure, pressure_envelope, pressure_ref = center_fact(manifest["pressures"][key], key, "PRESSURE", .002)
        require(implementation is None or envelope["request"]["engine_sources"] == implementation,
                "Centers use different implementations")
        implementation = envelope["request"]["engine_sources"]
        require(pressure_envelope["request"]["engine_sources"] == implementation, "Pressure uses a different implementation")
        standards[key], pressures[key], metadata[key] = standard, pressure, envelope
        references.extend((reference, pressure_ref))
    projections = []
    for key in KEYS:
        fingerprint = assessment_benchmark_fingerprint(standards[key])
        for record in manifest["parameters"][key]:
            projection, reference = parameter_projection(record, key, plans[key], plan_refs[key], standards[key], metadata[key], fingerprint)
            projections.append(projection)
            references.append(reference)
    links = tuple(m.PerturbationLink(item.parent, item.candidate, 1., item.derivation_sha256, item.parameter_point)
                  for item in projections)
    base = m.CandidateAssessmentRequest(tuple(standards[key].candidate for key in KEYS), protocol, links,
        (*standards.values(), *pressures.values()), parameter_designs=selections)
    request = CandidatePerformanceAssessmentRequest(base, tuple(projections))
    panel = assess_candidates(request)
    comparison_request = m.CalmarComparisonRequest(base.centers, targets, panel, policy, selections,
        DeclaredPointSetComparisonContract.from_dict(read(WORK / "protocols/confirmed_bounded_stage4_v3.json")["comparison"]))
    compared = compare_candidates(comparison_request)
    summaries, results = verify_hard_gates(panel, compared, targets, manifest, standards, pressures, protocol)
    for key in KEYS:
        records = manifest["parameters"][key]
        summaries[key]["parameter_max_drawdown"] = max(record["candidate_metrics"]["drawdown"] for record in records)
        failures = [record for record in records if record["candidate_metrics"]["drawdown"] > .25]
        summaries[key]["parameter_dd_cap_failure_count"] = len(failures)
        axes = {axis.name: axis.center for axis in plans[key].design.space.axes}
        single_axis = []
        for record in failures:
            changes = [value for value in plans[key].design.points[record["index"]].values if value.value != axes[value.name]]
            if len(changes) == 1:
                value = changes[0]
                single_axis.append({"point_index": record["index"], "parameter": value.name,
                    "center_value": axes[value.name], "point_value": value.value,
                    "drawdown": record["candidate_metrics"]["drawdown"], "evidence": record["evidence"]})
        summaries[key]["single_axis_dd_cap_failures"] = single_axis
    eligible = verify_ranking(summaries, results, policy)
    historical, _ = historical_counterevidence()
    groups = defaultdict(list)
    for row in panel.rows:
        groups[row.behavior_sha256].append(row.candidate.candidate_id)
    summary = {"status": "COMPLETE_RSCH_NUMERICALLY_VERIFIED", "centers": summaries,
        "rankable_candidates": eligible, "fixed_parameter_points": 257, "current_implementation_strategy_accounts": 269,
        "new_account_replays_by_finalization": 0, "independent_account_audit_performed": False,
        "historical_counterevidence": historical, "behavior_groups": list(groups.values()),
        "family_diagnostics": [item.to_dict() for item in panel.family_diagnostics],
        "family_limitations": list(panel.family_limitations), "sealed_2026_prices_accessed": False,
        "source_manifest_sha256": sha256((OUTPUT / "manifest.json").read_bytes()).hexdigest(),
        "source_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "execution_observation": {name: manifest[name] for name in ("elapsed_seconds", "memory", "equity_statistics")},
        "elapsed_seconds": perf_counter() - started}
    for key in KEYS:
        summaries[key]["parameters"] = {axis.name: axis.center for axis in plans[key].design.space.axes}
    save(OUTPUT / "analysis.json", summary)
    save(OUTPUT / "historical_counterevidence.json", historical)
    save(OUTPUT / "panel.json", panel.to_dict())
    save(OUTPUT / "comparison.json", compared.to_dict())
    # The formal delivery already embeds the typed request and its raw center
    # facts. Keep the extra working copy out of research materials and Git.
    save(SCRATCH / "request.json", request.to_dict())
    save(OUTPUT / "comparison_request.json", comparison_request.to_dict())
    save(OUTPUT / "rsch_verification.json", {"status": "PASS_RSCH_HARD_GATE_QUANTILE_AND_RANKING_VERIFICATION",
        "parameter_points": 257, "complete_declared_N": {key: summaries[key]["N"] for key in KEYS},
        "hard_target_statuses_equal": True, "parameter_counts_equal": True, "frequency_coverage_equal": True,
        "parameter_and_rolling_quantiles_equal": True, "raw_pareto_and_bins_equal": True,
        "missing_or_failed_points_dropped": False, "net_annual_return_independent_gate_added": False,
        "independent_account_audit_performed": False, "sealed_2026_prices_accessed": False})
    (OUTPUT / "report.md").write_text(report_text(summary), encoding="utf-8", newline="\n")
    print("BOUNDED_STAGE4_RSCH_VERIFIED", eligible, "elapsed_seconds", perf_counter() - started, flush=True)
    if args.publish:
        publish(request, panel, comparison_request, compared, summary, tuple(references), plan_refs)


if __name__ == "__main__":
    main()
