"""Assess the two user-selected S019 configurations without changing their targets.

The native v4 comparison is used only to calculate the confirmed acceptance
checks. Both centers fail the retained Calmar gate, so no native ordering is
formed. The research's NAR-only ranking remains the governing policy.
"""
import argparse
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK / "others"
SCRATCH = ROOT / ".tmp/s019-stage4/assessment"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(TMP=str(SCRATCH), TEMP=str(SCRATCH), OMP_NUM_THREADS="1",
    OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")

import numpy as np  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import (  # noqa: E402
    RepositoryContext, create_research_context, publish_evidence,
    assemble_delivery, validate_experiment,
)
from czsc_trader.research_tools.equity_replay import build_equity_assessment  # noqa: E402
from czsc_trader.research_tools import equity_assessment as equity_adapter  # noqa: E402
from dataflows import ProviderConfig  # noqa: E402
from strategy_evaluator import assess_candidates, compare_candidates, performance_metrics  # noqa: E402
from strategy_evaluator import research_models as m  # noqa: E402
from strategy_evaluator import equity_assessment as equity_facts  # noqa: E402

BATCH = d.ResearchBatchRef("S019")
EXP = d.ExperimentRef("S019", WORK.name)
PROJECTOR_SHA = sha256(b"".join(Path(inspect.getsourcefile(value)).read_bytes()
    for value in (build_equity_assessment, equity_adapter, equity_facts))).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value, *, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, allow_nan=False,
        indent=None if compact else 2, separators=(",", ":") if compact else None) + "\n").encode())


def setup():
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, BATCH,
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    return repo, context


def bytes_for(reference):
    ref = d.EvidenceRef.from_dict(reference) if type(reference) is dict else reference
    content = ref.resolve(ROOT).read_bytes()
    assert sha256(content).hexdigest() == ref.sha256
    return ref, content


def fact(reference):
    ref, source = bytes_for(reference)
    header = json.loads(source)
    key = sha256((ref.sha256 + PROJECTOR_SHA).encode()).hexdigest()
    path = SCRATCH / f"{key}.json"
    receipt = SCRATCH / f"{key}.receipt.json"
    if path.exists() and receipt.exists():
        meta = read(receipt)
        raw = path.read_bytes()
        assert meta["source_sha256"] == ref.sha256 and meta["projector_sha256"] == PROJECTOR_SHA
        assert sha256(raw).hexdigest() == meta["projection_sha256"]
        value = m.AssessmentEvidence.from_dict(json.loads(raw))
    else:
        def resolve(item):
            raw = ref.resolve(ROOT).with_name(item["sha256"] + ".json").read_bytes()
            assert sha256(raw).hexdigest() == item["sha256"]
            return raw
        # This public entry resolves the immutable closure and projects recorded
        # observations directly, without additionally expanding the large payload.
        value, = build_equity_assessment(source, resolve)
        save(path, value.to_dict(), compact=True)
        save(receipt, {"source_sha256": ref.sha256, "projector_sha256": PROJECTOR_SHA,
            "projection_sha256": sha256(path.read_bytes()).hexdigest()})
    assert value.result_sha256 == ref.sha256
    assert value.candidate.candidate_id == "S019-" + header["request"]["candidate_id"]
    assert value.candidate.content_sha256 == header["request"]["content_sha256"]
    assert len(value.account) == 1212 and value.account[0].session == "2022-01-03" and value.account[-1].session == "2026-10-30"
    return value, header, ref


def target_set():
    source = read(ROOT / "research/S019/assets/deliveries/MANDATE/2/delivery.json")
    items = source["content"]["payload"]["items"]
    targets = next(x for x in items if x["item_id"] == "targets")["requirement"]["targets"]
    result = m.ResearchTargets.from_dict({"type": "ResearchTargets", "requirements": targets,
        "frequency_window_days": 60})
    assert len(result.requirements) == 12
    parameter, = [x for x in result.requirements if type(x) is m.ParameterNeighborhoodTarget]
    assert (parameter.minimum_numerator, parameter.minimum_denominator) == (4, 5)
    assert next(x for x in result.requirements if x.target_id == "center-calmar").lower.value == 5.0
    return result


def native_acceptance_policy():
    metrics = (*m.BENCHMARK_METRICS, *m.WITHIN_LAYER_METRICS, m.ResearchMetric.FREQUENCY_MEDIAN)
    return m.ComparisonPolicy("s019-native-acceptance-only-no-ranked-candidates-v1",
        tuple(m.MetricBinSpec(metric, 1.0 if metric is m.ResearchMetric.FREQUENCY_MEDIAN else .0001,
            0., m.BinRounding.NEAREST_HALF_EVEN) for metric in metrics),
        m.ParetoBasis.RAW, m.MissingEvidencePolicy.REQUIRE_COMPLETE)


def prepare():
    centers = read(WORK / "protocols/centers.json")
    facts = []
    for center in centers:
        value, header, _ = fact(center["account_ref"])
        assert value.candidate.content_sha256 == center["content_hash"]
        assert center["candidate"]["calmar"] < 5
        facts.append(value)
        print("CENTER_PROJECTED", center["id"], value.window_id, value.scenario_id, flush=True)
    assert {x.candidate.candidate_id for x in facts} == {"S019-C0135", "S019-C0224"}
    assert len({(x.window_id, x.scenario_id) for x in facts}) == 1
    designs = [m.ParameterNeighborhoodDesign.from_dict(read(WORK / f"protocols/{center['id']}_design.json")) for center in centers]
    assert designs[0].protocol == designs[1].protocol
    assert sorted(x.point_count for x in designs) == [8, 80]
    protocol = m.NeighborhoodSelfCheckProtocol("s019-c0135-c0224-stage4-v1",
        facts[0].window_id, facts[0].scenario_id, "STRESS", 252, 21,
        m.QuantileMethod.LINEAR, 1, 10000, 21, 20261110, 1e-8, designs[0].protocol,
        frequency_min_closed_cycles=3)
    value = {"protocol": protocol.to_dict(), "targets": target_set().to_dict(),
        "native_acceptance_policy": native_acceptance_policy().to_dict(),
        "research_ranking": "After all original targets pass, sort by unrounded standard NAR; exact ties remain tied.",
        "native_policy_scope": "Native v4 is used solely for all original target checks. Both original centers have Calmar<5; compare is guarded to return TARGET_NOT_MET and no ranks/pairs. This does not replace the authorized NAR-only ranking policy.",
        "parameter_comparability": "C0135 full two-continuous-axis 8-point neighborhood and C0224 full four-continuous-axis 80-point neighborhood are reported separately; no equal-geometry claim.",
        "family_diagnostics": "Full selected-history statistics are computed separately through public SE statistics/selection interfaces. No synthetic family values are injected into this panel.",
        "new_account_replays": 0, "center_sources": [x["account_ref"] for x in centers]}
    path = OUT / "assessment_protocol.json"
    if path.exists():
        assert read(path) == value
    else:
        save(path, value)
    print("ASSESSMENT_PREPARED", [x.point_count for x in designs], flush=True)


def summary(panel, comparison):
    rows = []
    for row, checked in zip(panel.rows, comparison.rows, strict=True):
        assert row.candidate == checked.candidate
        values = {x.metric.value: x.value for x in row.diagnostics}
        neighborhood, = [x for x in checked.target_checks if type(x) is m.ParameterNeighborhoodCheck]
        points = row.parameter_performances
        stress = row.stress_performance
        nar, dd = values["NET_ANNUAL_RETURN"], values["DRAWDOWN_MAGNITUDE"]
        point_nar = np.asarray([x.annual_return for x in points])
        point_dd = np.asarray([x.drawdown for x in points])
        point_calmar = np.asarray([x.annual_return/x.drawdown for x in points])
        rows.append({"candidate": row.candidate.to_dict(), "center": {"nar": nar, "mdd": dd, "calmar": nar/dd},
            "parameter": {"required_points": neighborhood.required_points, "valid_points": neighborhood.valid_points,
                "joint_passes": neighborhood.joint_passes, "required_passes": neighborhood.minimum_joint_passes,
                "pass_rate": neighborhood.joint_passes/neighborhood.required_points,
                "status": neighborhood.status.value, "nar_q10": float(np.quantile(point_nar, .1)),
                "mdd_q90": float(np.quantile(point_dd, .9)), "calmar_q10": float(np.quantile(point_calmar, .1)),
                "minimum_nar": float(point_nar.min()), "maximum_mdd": float(point_dd.max()),
                "minimum_calmar": float(point_calmar.min()), "maximum_calmar": float(point_calmar.max()),
                "all_points_absolute_risk_pass": bool(np.all(point_dd <= .25))},
            "stress": {"nar": stress.annual_return, "mdd": stress.drawdown,
                "calmar": stress.annual_return/stress.drawdown,
                "benchmark_nar": stress.benchmark_return, "benchmark_mdd": stress.benchmark_drawdown},
            "diagnostics": values, "uncertainty": row.uncertainty.to_dict(),
            "frequency_coverage": row.frequency_coverage.to_dict(), "coverage_gaps": list(row.coverage_gaps),
            "acceptance_status": checked.acceptance_status.value, "comparison_status": checked.status.value,
            "target_checks": [x.to_dict() for x in checked.target_checks]})
    return {"candidates": rows, "qualified_nar_ranking": [],
        "original_targets_retained": True, "native_ranks_formed": False,
        "parameter_geometries_equal": False,
        "family_diagnostics": [x.to_dict() for x in panel.family_diagnostics],
        "family_limitations": list(panel.family_limitations)}


def temporal():
    """Describe fixed centers' seen-history paths using public SE performance metrics."""
    protocol = m.NeighborhoodSelfCheckProtocol.from_dict(read(OUT / "assessment_protocol.json")["protocol"])

    def distribution(values):
        array = np.asarray(values, dtype=float)
        assert np.isfinite(array).all() and len(array)
        return {"count": len(array), "minimum": float(array.min()),
            "q10": float(np.quantile(array, .1)), "median": float(np.median(array)),
            "q90": float(np.quantile(array, .9)), "maximum": float(array.max()),
            "below_zero": int(np.sum(array < 0)), "equal_zero": int(np.sum(array == 0)),
            "above_zero": int(np.sum(array > 0))}

    def losing_runs(rows, metric):
        segments, current = [], []
        for row in rows:
            if row[metric] < 0:
                current.append(row)
            elif current:
                segments.append(current)
                current = []
        if current:
            segments.append(current)
        result = [{"count": len(segment), "first_window": segment[0]["window_id"],
            "last_window": segment[-1]["window_id"], "first_start": segment[0]["start"],
            "last_start": segment[-1]["start"], "last_end": segment[-1]["end"]}
            for segment in segments]
        return {"maximum_count": max((x["count"] for x in result), default=0), "segments": result}

    candidates = []
    for center in read(WORK / "protocols/centers.json"):
        value, _, ref = fact(center["account_ref"])
        sessions = [x.session for x in value.account]
        strategy = np.asarray([value.initial_cash, *[x.equity for x in value.account]])
        benchmark = np.asarray([value.initial_cash, *value.benchmark_equity])
        strategy_returns, benchmark_returns = strategy[1:]/strategy[:-1]-1, benchmark[1:]/benchmark[:-1]-1

        def window(name, start, stop):
            left, right = (performance_metrics(x[start:stop]) for x in (strategy_returns, benchmark_returns))
            assert np.isfinite([left.cagr, left.calmar, right.cagr, right.calmar]).all()
            return {"window_id": name, "start": sessions[start], "end": sessions[stop-1], "sessions": stop-start,
                "strategy": {"period_return": float(strategy[stop]/strategy[start]-1), "nar": left.cagr,
                    "mdd": -left.max_drawdown, "calmar": left.calmar},
                "benchmark": {"period_return": float(benchmark[stop]/benchmark[start]-1), "nar": right.cagr,
                    "mdd": -right.max_drawdown, "calmar": right.calmar},
                "nar_excess": left.cagr-right.cagr, "calmar_excess": left.calmar-right.calmar}

        full = window("FULL", 0, len(sessions))
        np.testing.assert_allclose([full["strategy"][key] for key in ("nar", "mdd", "calmar")],
            [center["candidate"][key] for key in ("nar", "drawdown", "calmar")], atol=1e-12, rtol=1e-12)
        years = []
        for year in sorted({x[:4] for x in sessions}):
            indices = [i for i, day in enumerate(sessions) if day.startswith(year)]
            years.append(window(year, indices[0], indices[-1]+1))
        rolling = [window(f"R{i:02}", start, start+protocol.rolling_window_days)
            for i, start in enumerate(range(0, len(sessions)-protocol.rolling_window_days+1, protocol.rolling_step_days))]
        assert len(rolling) == 46
        concentration = equity_facts.equity_concentration(value)
        assert value.equity.concentration_basis == "MAX_SINGLE"
        trades = json.loads(value.equity.candidate_ledger)["trades"]
        winners = sorted((x for x in trades if x["net_pnl"] > 0), key=lambda x: x["net_pnl"], reverse=True)
        profit_sum = sum(x["net_pnl"] for x in winners)
        assert concentration == winners[0]["net_pnl"]/profit_sum
        candidates.append({"candidate": value.candidate.to_dict(), "source": ref.to_dict(),
            "full": full, "years": years, "rolling": rolling,
            "rolling_distributions": {name: distribution([row[name] for row in rolling])
                for name in ("nar_excess", "calmar_excess")},
            "rolling_strategy_distributions": {name: distribution([row["strategy"][name] for row in rolling])
                for name in ("nar", "mdd", "calmar")},
            "rolling_benchmark_distributions": {name: distribution([row["benchmark"][name] for row in rolling])
                for name in ("nar", "mdd", "calmar")},
            "consecutive_lagging_rolling_windows": {name: losing_runs(rolling, name) for name in ("nar_excess", "calmar_excess")},
            "consecutive_lagging_calendar_years": {name: losing_runs(years, name) for name in ("nar_excess", "calmar_excess")},
            "profit_contribution": {"basis": "MAX_SINGLE", "largest_winner_share_of_positive_closed_pnl": concentration,
                "positive_closed_cycles": len(winners), "all_closed_cycles": len(trades),
                "positive_closed_pnl_sum": profit_sum, "closed_net_pnl_sum": sum(x["net_pnl"] for x in trades),
                "top_five_winners": [{**x, "share_of_positive_closed_pnl": x["net_pnl"]/profit_sum} for x in winners[:5]]}})
    output = {"status": "COMPLETE", "new_account_replays": 0,
        "source_scope": "Seen development history, fixed selected configurations, not independent validation.",
        "numeric_engine": "strategy_evaluator.performance_metrics over public V4 AssessmentEvidence session-close returns",
        "annualization_sessions": 252, "rolling_sessions": protocol.rolling_window_days,
        "rolling_step": protocol.rolling_step_days, "rolling_count": 46,
        "notes": ["Window opening equity is the previous session close; the first window opens at initial cash.",
            "2026 ends on 2026-10-30; period returns and annualized NAR are both reported.",
            "Overlapping rolling windows are dependent; lag-run count refers to successive window starts, not independent samples.",
            "NAR excess is the arithmetic difference of strategy and benchmark annualized returns; Calmar excess is their Calmar difference.",
            "MAX_SINGLE divides the largest positive closed-cycle net PnL by all positive closed-cycle net PnL; no extra hard gate is added."],
        "candidates": candidates}
    save(OUT / "assessment_temporal.json", output)
    print("TEMPORAL_DIAGNOSTICS_COMPLETE", [(x["candidate"]["candidate_id"], len(x["rolling"])) for x in candidates], flush=True)


def compute():
    started = perf_counter()
    assert not (OUT / "panel.json").exists(), "Retained assessment exists; inspect and reuse it before recomputing"
    setup_data = read(OUT / "assessment_protocol.json")
    inputs = read(OUT / "assessment_inputs.json")
    protocol = m.NeighborhoodSelfCheckProtocol.from_dict(setup_data["protocol"])
    targets = m.ResearchTargets.from_dict(setup_data["targets"])
    centers, evidence, links, designs, refs = [], [], [], [], []
    for entry in inputs["centers"]:
        baseline, _, base_ref = fact(entry["center_account"])
        pressure, _, stress_ref = fact(entry["stress_account"])
        plan_ref, plan_bytes = bytes_for(entry["parameter_plan"])
        plan = d.ParameterEvaluationPlan.from_dict(json.loads(plan_bytes))
        assert baseline.candidate == pressure.candidate == plan.design.center
        assert (baseline.scenario_context.one_way_cost, pressure.scenario_context.one_way_cost) == (.001, .002)
        assert pressure.scenario_id == protocol.stress_scenario
        centers.append(baseline.candidate)
        evidence.extend((baseline, pressure))
        refs.extend((base_ref, stress_ref))
        designs.append(plan.design)
        found = {}
        children = {child.candidate: child for child in plan.children}
        for reference in entry["parameter_accounts"]:
            point, header, ref = fact(reference)
            binding = d.ParameterEvaluationBinding.from_dict(header["request"]["lineage"]["parameter_binding"])
            assert binding.plan == plan_ref and point.parameter_point == binding.point
            assert point.parent == baseline.candidate and point.candidate in children
            assert point.parameter_point == plan.design.bind_point(point.parameter_point.point_index)
            assert point.parameter_point.point_index not in found
            found[point.parameter_point.point_index] = point
            evidence.append(point)
            refs.append(ref)
            links.append(m.PerturbationLink(point.parent, point.candidate, 1., point.derivation_sha256, point.parameter_point))
            print("POINT_PROJECTED", entry["id"], point.parameter_point.point_index, flush=True)
        assert set(found) == set(range(plan.design.point_count))
    assert len(evidence) == 92 and len(links) == 88
    request = m.CandidateAssessmentRequest(tuple(centers), protocol, tuple(links), tuple(evidence), parameter_designs=tuple(designs))
    repo, context = setup()
    request_bytes = (json.dumps(request.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n").encode()
    ref = publish_evidence(context, d.MaterialEvidenceWrite(EXP, "se-assessment-request", request_bytes, "application/json", "json"))
    save(OUT / "assessment_request_ref.json", ref.to_dict())
    save(OUT / "assessment_account_refs.json", [x.to_dict() for x in refs])
    print("ASSESSING", len(evidence), "facts", len(links), "points", flush=True)
    panel = assess_candidates(request)
    save(OUT / "panel.json", panel.to_dict())
    assert panel.formula_version == "research-assessment-v7"
    for row in panel.rows:
        values = {x.metric: x.value for x in row.diagnostics}
        assert values[m.ResearchMetric.NET_ANNUAL_RETURN] / values[m.ResearchMetric.DRAWDOWN_MAGNITUDE] < 5
        assert row.parameter_context.valid_points == row.parameter_context.prescribed_points
        assert not row.coverage_gaps, row.coverage_gaps
    comparison_request = m.CandidateComparisonRequest(tuple(centers), targets, panel,
        m.ComparisonPolicy.from_dict(setup_data["native_acceptance_policy"]))
    comparison = compare_candidates(comparison_request)
    for row in comparison.rows:
        gate = next(x for x in row.target_checks if x.target.target_id == "center-calmar")
        assert gate.status is m.TargetCheckStatus.FAILED
        assert row.status is m.ComparisonStatus.TARGET_NOT_MET and row.acceptance_status is m.TargetCheckStatus.FAILED
        assert all(getattr(row, name) is None for name in ("pareto_layer", "rank_in_layer", "rank_min", "rank_max"))
    assert not comparison.pairs and not comparison.sensitivities
    save(OUT / "comparison_request.json", comparison_request.to_dict())
    save(OUT / "comparison.json", comparison.to_dict())
    save(OUT / "assessment_summary.json", summary(panel, comparison))
    temporal()
    for row, path in zip(panel.rows, read(OUT / "assessment_temporal.json")["candidates"], strict=True):
        values = {x.metric: x.value for x in row.diagnostics}
        assert row.candidate.to_dict() == path["candidate"]
        np.testing.assert_allclose(values[m.ResearchMetric.ROLLING_EXCESS_Q10],
            path["rolling_distributions"]["nar_excess"]["q10"], atol=1e-12, rtol=1e-12)
        assert values[m.ResearchMetric.PROFIT_CONCENTRATION] == path["profit_contribution"]["largest_winner_share_of_positive_closed_pnl"]
    save(OUT / "assessment_execution.json", {"status": "COMPLETED", "seconds": perf_counter()-started,
        "centers": 2, "reused_account_evidence": len(evidence), "parameter_points": len(links),
        "new_account_replays": 0, "new_search_trials": 0, "request_sha256": request.sha256,
        "panel_sha256": panel.sha256, "comparison_sha256": comparison.sha256,
        "native_rank_formed": False, "research_ranking": "NAR_ONLY_AFTER_ALL_ORIGINAL_TARGETS_PASS",
        "family_statistics": "Separate public statistics evidence; not injected into SE family fields."})
    print("ASSESSMENT_COMPLETE", [row.status.value for row in comparison.rows], round(perf_counter()-started, 2), flush=True)


def publish():
    started = perf_counter()
    assert not (ROOT / "research/S019/deliveries/ASSESSMENT/1/receipt.json").exists(), "Inspect published state before retry"
    inputs = read(OUT / "assessment_inputs.json")
    request_ref, request_raw = bytes_for(read(OUT / "assessment_request_ref.json"))
    request = m.CandidateAssessmentRequest.from_dict(json.loads(request_raw))
    panel = m.AssessmentPanel.from_dict(read(OUT / "panel.json"))
    comparison_request = m.CandidateComparisonRequest.from_dict(read(OUT / "comparison_request.json"))
    comparison = m.CandidateComparison.from_dict(read(OUT / "comparison.json"))
    assert panel.request_sha256 == request.sha256 and comparison_request.panel == panel
    assert comparison.request_sha256 == comparison_request.sha256
    assert all(row.status is m.ComparisonStatus.TARGET_NOT_MET and row.rank_min is None for row in comparison.rows)
    assert not comparison.pairs
    source = d.DeliveryReference.from_dict(inputs["source_candidates"])
    mandate = d.DeliveryReference.from_dict(inputs["source_mandate"])
    candidate_set = d.CandidateSet.from_dict(read(ROOT / f"research/S019/assets/deliveries/CANDIDATES/{source.revision}/delivery.json")["content"]["payload"])
    actual = {f"{key.strategy_id}-{key.candidate_id}" for key in candidate_set.handoff}
    assert actual == {x.candidate_id for x in request.centers} == {"S019-C0135", "S019-C0224"}
    repo, context = setup()
    materials = []
    paths = [*sorted((WORK / "src").rglob("*.py")), *sorted((WORK / "protocols").glob("*")),
        *sorted(OUT.glob("*.json")), *sorted(OUT.glob("*.md"))]
    for index, path in enumerate(paths):
        if not path.is_file() or path.suffix not in {".py", ".json", ".md"} or path.name == "assessment_publication.json":
            continue
        ext = path.suffix[1:]
        materials.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP, f"stage4-material-{index:03}-{path.stem}",
            path.read_bytes(), {"py": "text/x-python", "json": "application/json", "md": "text/markdown"}[ext], ext)))
    account_refs = tuple(d.EvidenceRef.from_dict(x) for x in read(OUT / "assessment_account_refs.json"))
    plan_refs = tuple(d.EvidenceRef.from_dict(x["parameter_plan"]) for x in inputs["centers"])
    report = (WORK / "report.md").read_text(encoding="utf-8")
    assert "IN_PROGRESS" not in report
    recommendation = "两者完成指定稳健性检查，原中心Calmar门槛仍未通过，达标NAR推荐集合为空。逐项比较结果及剩余限制见报告；原生v4仅计算门槛且无排名，原NAR排序约定保持。"
    payload = d.CandidateAssessmentDelivery(source, mandate, request, panel, comparison_request, comparison,
        tuple(d.TargetMandateBinding(x.target_id, "targets") for x in comparison_request.targets.requirements),
        "frequency-days", "m30-benchmark", recommendation, tuple(materials), (), parameter_plans=plan_refs)
    # Prefix only local report links; preserve external URLs and fragment links.
    import re
    def stage_link(match):
        target = match.group(1)
        if "://" in target or target.startswith("#"):
            return match.group(0)
        return "](../../../experiments/EX039_20261110/" + target + ")"
    stage_report = re.sub(r"\]\(([^)]+)\)", stage_link, report)
    evidence = tuple(dict.fromkeys((request_ref, *materials, *account_refs, *plan_refs)))
    assembled = assemble_delivery(repo, d.DeliveryDefinition(BATCH, d.DeliveryStage.ASSESSMENT, 1,
        (source, mandate), schema_version=12),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=stage_report, evidence=evidence))
    assert assembled.validation.status is d.ValidationStatus.PASS
    assert assembled.validation.scope is d.DeliveryValidationScope.INTEGRITY
    save(OUT / "assessment_receipt.json", assembled.receipt.to_dict())
    save(OUT / "assessment_delivery_validation.json", assembled.validation.to_dict())
    receipt_ref = publish_evidence(context, d.MaterialEvidenceWrite(EXP, "assessment-receipt",
        (OUT / "assessment_receipt.json").read_bytes(), "application/json", "json"))
    pointer = WORK / "report_ref.json"
    assert not pointer.exists(), "Inspect existing experiment report before publishing another revision"
    published = publish_evidence(context, d.ExperimentReportWrite(EXP, sha256((WORK / "report.md").read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, (*evidence, receipt_ref)))
    checked = validate_experiment(repo, d.ExperimentValidationRequest(EXP, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status is d.ValidationStatus.PASS
    save(OUT / "assessment_publication.json", {"report": published.to_dict(), "report_validation": checked.to_dict(),
        "assessment": assembled.receipt.reference.to_dict(), "delivery_validation": assembled.validation.to_dict(),
        "seconds": perf_counter()-started, "new_account_replays": 0, "native_ranks_formed": False})
    print("ASSESSMENT_PUBLISHED", assembled.receipt.reference.content_sha256, published.sha256, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "temporal", "compute", "publish"))
    args = parser.parse_args()
    {"prepare": prepare, "temporal": temporal, "compute": compute, "publish": publish}[args.action]()
