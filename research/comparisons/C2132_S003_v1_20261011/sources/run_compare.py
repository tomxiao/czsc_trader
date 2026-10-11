"""Approved original-strategy comparison; prospective designs, native accounts only."""

# ruff: noqa: E402
import os

for variable in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[variable] = "1"
import argparse
from dataclasses import replace
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys

import pandas as pd
from strategy_runtime import StrategyCandidate, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
)
from strategy_evaluator import (
    AssessmentCandidate,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterDesignRequest,
    ParameterPerturbationProtocol,
    ParameterSpace,
    build_parameter_perturbation_design,
)
from czsc_trader.application import (
    create_experiment,
    load_candidate,
    publish_evidence,
    publish_evidence_many,
    ExperimentRequest,
)
from czsc_trader.research_tools import (
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationBenchmark,
    LimitBuyHold,
    ExecutionPriceBasis,
    MaterialEvidenceWrite,
    EvaluationEvidenceWrite,
    ParameterEvaluationPlan,
    EvaluationLineage,
    build_assessment_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp/c2132-s003-compare"
OUT = ROOT / "research/comparisons/C2132_S003_v1_20261011"
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
from common import cache_read, cache_write

sys.path.insert(0, str(WORK))
DEPENDENCIES = tuple(
    ImplementationDependency(x, version(x)) for x in ("numpy", "pandas", "czsc-strategy-runtime")
)
PROTOCOL = ParameterPerturbationProtocol()
START, END = date(2021, 4, 23), date(2026, 9, 8)


def plain(value):
    return json.loads(json.dumps(value, default=dict, allow_nan=False))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def ctx(family, workers=1):
    from local_data import context

    return context(family, workers)


def material(context, experiment, name, value):
    return publish_evidence(
        context,
        MaterialEvidenceWrite(
            experiment,
            name,
            (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(),
            "application/json",
            "json",
        ),
    )


def get_path(value, name):
    for part in name.split("."):
        value = value[part]
    return value


def set_path(value, name, number, kind):
    parts = name.split(".")
    for part in parts[:-1]:
        value = value[part]
    value[parts[-1]] = int(number) if kind == "INTEGER" else float(number)


def feasible_c2132(values):
    return bool(values[1] < values[2] and values[5] < values[6])


def feasible_s003(values):
    return bool(1 <= values[0] <= 252 and float(values[0]).is_integer() and 0 <= values[1] <= 1)


def request(candidate, experiment):
    return EvaluationRequest(
        ROOT,
        experiment.experiment_id,
        candidate,
        {
            "candidate_id": candidate.reference_id,
            "source_files": list(candidate.payload["runtime"]["source_files"]),
            "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
        },
        "510500.SH",
        "etf",
        (EvaluationWindow("common", START, END),),
        END,
        1_000_000,
        (EvaluationCost("baseline", 0.001, "FORMAL"),),
        benchmark=EvaluationBenchmark(
            LimitBuyHold(
                lot_size=100,
                premium=0.01,
                price_tick=0.001,
                price_limit_ratio=0.1,
                maximum_order_quantity=1_000_000,
            )
        ),
        workers=1,
        frequency_window_days=60,
        dependencies=DEPENDENCIES,
        price_basis=ExecutionPriceBasis.HFQ_RESEARCH,
    )


def seed_precheck(lengths):
    # All signal thresholds must be finite, including the first signal day.
    seed = pd.read_csv(
        ROOT / "strategies/S003/releases/v1/runtime/strategy_runtime/resources/s003_v1_seed.csv.gz"
    )
    seed["Date"] = pd.to_datetime(seed["Date"])
    seed = seed.set_index("Date").sort_index()
    old, _ = cache_read(ROOT / ".tmp/s013-mechanism-EX058/N0.pkl.gz")
    calendar = pd.DatetimeIndex(old.input_bindings["full"].plan.calendar_dates)
    executions = calendar[(calendar >= pd.Timestamp(START)) & (calendar <= pd.Timestamp(END))]
    signals = calendar[calendar.get_indexer(executions) - 1]
    assert signals[0] == pd.Timestamp("2021-04-22")
    for length in lengths:
        threshold = (
            seed["MoneyflowBreadth"].shift(1).rolling(length, min_periods=length).quantile(0.8)
        )
        assert threshold.reindex(signals).notna().all()
        assert seed.reindex(signals)["MoneyflowBreadth"].notna().all()
    return {
        "status": "PASS",
        "first_signal": str(signals[0].date()),
        "sessions": len(executions),
        "lengths": sorted(set(lengths)),
        "all_requested_thresholds_finite": True,
        "seed_sha256": digest(
            ROOT
            / "strategies/S003/releases/v1/runtime/strategy_runtime/resources/s003_v1_seed.csv.gz"
        ),
    }


def declare():
    assert not (OUT / "declaration.json").exists(), "Declaration already fixed; use run/resume"
    OUT.mkdir(parents=True, exist_ok=True)
    contexts = {f: ctx(f) for f in ("S013", "S003")}
    experiments = {
        f: create_experiment(
            contexts[f],
            ExperimentRequest(
                "C2132与S003-v1原策略统一口径对照",
                "获批共同区间、百万资金、费用和后复权；原规则不优化；五项自检；完成后暂停",
                date(2026, 10, 11),
            ),
        )
        for f in contexts
    }
    write(OUT / "experiments.json", {f: x.to_dict() for f, x in experiments.items()})
    centers = {"S013": load_candidate(contexts["S013"].repository, CandidateKey("S013", "C2132"))}
    payload = read(ROOT / "strategies/S003/versions/v1.json")["strategy_payload"]
    centers["S003"] = StrategyCandidate(
        "S003", "C9900", payload, ROOT / "strategies/S003/releases/v1/runtime/strategy_runtime"
    )
    ccoords = read(ROOT / "research/S013/experiments/EX058_20261011/protocols/geometry.json")[
        "coordinates"
    ]
    coordinates = {
        "S013": ccoords,
        "S003": [
            ["rule.feature.threshold_lookback_sessions", 1.0, 252.0, "INTEGER"],
            ["rule.feature.threshold_quantile", 0.0, 1.0, "CONTINUOUS"],
        ],
    }
    states = []
    declarations = []
    for family, center in centers.items():
        context = contexts[family]
        experiment = experiments[family]
        identity = context.runtime.identify(center, dependencies=DEPENDENCIES)
        mapping = material(
            context,
            experiment,
            "parameter-mapping",
            {
                "coordinates": coordinates[family],
                "source_sha256": digest(__file__),
                "mapping": "payload.parameters dotted path, exact int/float, all other fields unchanged",
                "domain_origin": "Original C2132 domains"
                if family == "S013"
                else "Prospective finite diagnostic L[1,252], q[0,1]; not original historical search domain",
                "fixed_execution": "original rules unchanged; common explicit costs override strategy fee",
            },
        )
        feasibility = material(
            context,
            experiment,
            "parameter-feasibility",
            {
                "source_sha256": digest(__file__),
                "constraints": "bull.entry < bull.exit and bear.entry < bear.exit"
                if family == "S013"
                else "positive integer L<=252; q within[0,1]",
                "economic_filter": False,
            },
        )
        space = ParameterSpace(
            tuple(
                ParameterCoordinate(
                    name,
                    float(get_path(center.payload["parameters"], name)),
                    low,
                    high,
                    ParameterCoordinateKind(kind),
                )
                for name, low, high, kind in coordinates[family]
            ),
            mapping.sha256,
            feasibility.sha256,
        )
        generated = build_parameter_perturbation_design(
            ParameterDesignRequest(
                AssessmentCandidate(center.reference_id, identity.content_sha256), PROTOCOL, space
            ),
            feasibility=feasible_c2132 if family == "S013" else feasible_s003,
        )
        assert generated.status.value == "COMPLETE", generated.to_dict()
        design = generated.design
        base = context.evaluation.prepare(request(center, experiment))
        if family == "S003":
            seed_check = seed_precheck([60, *[int(p.coordinates[0]) for p in design.points]])
            write(OUT / "seed_precheck.json", seed_check)
        children = []
        for point in design.points:
            child_id = f"C{(8900 if family == 'S013' else 9901) + point.index:04}"
            assert not (ROOT / f"research/{family}/assets/candidates/{child_id}").exists()
            assert not (
                ROOT / f"research/registrations/{family}/candidates/{child_id}.json"
            ).exists()
            payload = plain(center.payload)
            for (name, _, _, kind), number in zip(
                coordinates[family], point.coordinates, strict=True
            ):
                set_path(payload["parameters"], name, number, kind)
            child = StrategyCandidate(family, child_id, payload, center.source_root)
            children.append(context.evaluation.prepare(request(child, experiment)))
        plan = ParameterEvaluationPlan.create(
            design,
            base,
            tuple(children),
            mapping_evidence=mapping,
            feasibility_evidence=feasibility,
            dataflows=context.data,
        )
        plan_ref = material(context, experiment, "prospective-parameter-plan", plan.to_dict())
        states.append((family, experiment, base, tuple(children), plan, plan_ref))
        declarations.append(
            {
                "family": family,
                "original_label": "C2132" if family == "S013" else "S003-v1",
                "center": {
                    "candidate_id": center.reference_id,
                    "content_sha256": identity.content_sha256,
                    "source_sha256": identity.source_sha256,
                    "original_release": "S003-v1" if family == "S003" else None,
                    "transport_identity_note": "S003 historical C001 is incompatible with modern C+four-digit typed key; C9900 is unregistered frozen-release transport only"
                    if family == "S003"
                    else "Original registered identity retained",
                },
                "source_root": str(center.source_root.relative_to(ROOT)).replace("\\", "/"),
                "parameter_plan": plan_ref.to_dict(),
                "design": design.to_dict(),
                "pricing": base.execution_data.pricing.to_dict(),
                "daily_fingerprint": base.execution_data.fingerprint,
            }
        )
        print("DECLARED", family, len(children), flush=True)
    cache_write(WORK / "prepared.pkl.gz", tuple(states))
    pricing = [s[2].execution_data.pricing.to_dict() for s in states]
    assert pricing[0] == pricing[1], "HFQ anchor/factors differ"
    for field in ("adjusted_daily", "execution_daily"):
        a, b = [getattr(s[2].execution_data, field) for s in states]
        pd.testing.assert_frame_equal(a, b, check_exact=True)
    declaration = {
        "status": "PROSPECTIVE_DECLARED",
        "start": START.isoformat(),
        "end": END.isoformat(),
        "initial_cash": 1_000_000,
        "standard_one_way_cost": 0.001,
        "stress_one_way_cost": 0.002,
        "price_basis": "HFQ_RESEARCH",
        "no_extra_cash_dividend": True,
        "benchmark": states[0][2].benchmark.to_dict(),
        "five_self_checks": "research-assessment-v3;126sessions/step21 LINEAR;topceil10percentwinningcycles;2000pairedstationarybootstrap/meanblock20/seed13",
        "business_accounts": 68,
        "technical_duplicates": 2,
        "selection": "None; both originals and all32 points independent of performance",
        "family_bias": "No comparable full historical-family matrix under unified conditions; explicitly unavailable, not zero",
        "sources": declarations,
        "runner_sha256": digest(__file__),
        "data_helper_sha256": digest(WORK / "local_data.py"),
        "geometry_review": read(WORK / "geometry-review/review.json"),
        "limitations": [
            "Seen development data; no independent validation",
            "Different original execution structure and parameter dimension/domain",
            "S003 core remains invested and unclosed; closed trades count intraday overlay cycles only",
        ],
    }
    references = {
        f: material(
            contexts[f], experiments[f], "unified-comparison-declaration", declaration
        ).to_dict()
        for f in contexts
    }
    write(OUT / "declaration.json", declaration)
    write(OUT / "declaration_references.json", references)
    print("READY_ALL_68_ACCOUNTS_NO_FINANCIAL_EVALUATIONS", flush=True)


def evaluate_cached(context, request, label):
    path = WORK / (label + ".pkl.gz")
    if path.exists():
        expected, result = cache_read(path)
        assert expected.strategy.runtime_identity_sha256 == request.strategy.runtime_identity_sha256
        assert expected.execution_data.fingerprint == request.execution_data.fingerprint
        assert expected.costs == request.costs and expected.windows == request.windows
        assert expected.lineage == request.lineage
        build_assessment_evidence(request, result)
    else:
        result = context.evaluation.evaluate(request)
        cache_write(path, (request, result))
    return result


def run():
    declaration = read(OUT / "declaration.json")
    assert declaration["runner_sha256"] == digest(__file__)
    states = cache_read(WORK / "prepared.pkl.gz")
    receipts = []
    for family, experiment, base, children, plan, plan_ref in states:
        context = ctx(family, 4)
        result = evaluate_cached(context, base, family + "-center")
        center_ref = publish_evidence(
            context, EvaluationEvidenceWrite(experiment, "original-center", base, result)
        )
        stress = replace(base, costs=(EvaluationCost("stress_20bp_per_side", 0.002, "STRESS"),))
        stressed = evaluate_cached(context, stress, family + "-stress")
        stress_ref = publish_evidence(
            context, EvaluationEvidenceWrite(experiment, "original-center-stress", stress, stressed)
        )
        bound = []
        for point, child, item in zip(plan.design.points, children, plan.children, strict=True):
            before = plain(base.strategy.payload["parameters"])
            after = plain(child.strategy.payload["parameters"])
            changes = {
                coord.name: {
                    "before": get_path(before, coord.name),
                    "after": get_path(after, coord.name),
                }
                for coord in plan.design.space.coordinates
                if get_path(before, coord.name) != get_path(after, coord.name)
            }
            derivation = CandidateDerivation(
                CandidateKey(family, base.strategy.candidate_id),
                plan.design.center.content_sha256,
                CandidateKey(family, child.strategy.candidate_id),
                item.candidate.content_sha256,
                CandidateDerivationKind.PARAMETERS,
                changes,
                PROTOCOL.sha256,
                CandidateEvidence(center_ref.repository_path, center_ref.sha256),
            )
            bound.append(
                replace(
                    child,
                    lineage=EvaluationLineage(
                        derivation, plan.bind_point(plan_ref, point.index, repository_root=ROOT)
                    ),
                )
            )
        # One technical spawn reproduction per strategy, before remaining business points.
        serial = evaluate_cached(ctx(family, 1), bound[0], family + "-P00")
        proof_path = WORK / (family + "-spawn-proof.json")
        if not proof_path.exists():
            outcome = context.evaluation.evaluate_many((bound[0],))[0]
            assert outcome.status.value == "SUCCEEDED", outcome.error
            assert serial.result_hash == outcome.result.result_hash
            for a, b in (
                (serial.runs[0].execution, outcome.result.runs[0].execution),
                (serial.runs[0].buyhold.execution, outcome.result.runs[0].buyhold.execution),
            ):
                for field in ("decisions", "orders", "fills", "account_daily", "trades"):
                    pd.testing.assert_frame_equal(
                        getattr(a, field), getattr(b, field), check_exact=True
                    )
            proof = {
                "status": "PASS",
                "serial_spawn": "Exact result and all5 strategy/benchmark ledgers",
                "result_hash": serial.result_hash,
                "actual_technical_duplicates": 1,
            }
            proof["reference"] = material(
                context, experiment, "serial-spawn-proof", proof
            ).to_dict()
            write(proof_path, proof)
        rows = []
        for offset in range(0, 32, 4):
            group = list(enumerate(bound[offset : offset + 4], start=offset))
            pending = [(i, r) for i, r in group if not (WORK / f"{family}-P{i:02}.pkl.gz").exists()]
            outcomes = (
                context.evaluation.evaluate_many(tuple(r for _, r in pending)) if pending else ()
            )
            for (i, r), outcome in zip(pending, outcomes, strict=True):
                assert outcome.status.value == "SUCCEEDED", outcome.error
                cache_write(WORK / f"{family}-P{i:02}.pkl.gz", (r, outcome.result))
            pairs = [cache_read(WORK / f"{family}-P{i:02}.pkl.gz") for i, _ in group]
            for (_, expected), (_, cached_result) in zip(group, pairs, strict=True):
                build_assessment_evidence(expected, cached_result)
            pairs = [
                (expected, cached_result)
                for (_, expected), (_, cached_result) in zip(group, pairs, strict=True)
            ]
            published = publish_evidence_many(
                context,
                tuple(
                    EvaluationEvidenceWrite(experiment, f"parameter-{i:02}", r, y)
                    for (i, _), (r, y) in zip(group, pairs, strict=True)
                ),
            )
            for (i, _), (r, y), outcome in zip(group, pairs, published, strict=True):
                assert outcome.status.value == "PUBLISHED", outcome.error
                rows.append(
                    {
                        "index": i,
                        "candidate": r.strategy.reference_id,
                        "result_hash": y.result_hash,
                        "reference": outcome.reference.to_dict(),
                    }
                )
            write(
                OUT / (family + "-checkpoint.json"),
                {"status": "COMPLETE" if len(rows) == 32 else "PARTIAL", "rows": rows},
            )
            print("PARAMETERS", family, len(rows), flush=True)
        receipts.append(
            {
                "family": family,
                "experiment": experiment.to_dict(),
                "center": center_ref.to_dict(),
                "stress": stress_ref.to_dict(),
                "parameters": rows,
                "serial_spawn": read(proof_path),
            }
        )
        write(OUT / "account_receipts.json", receipts)
    # The executable buy-and-hold reference must be identical between families.
    left, right = [cache_read(WORK / (f + "-center.pkl.gz"))[1].runs[0] for f in ("S013", "S003")]
    pd.testing.assert_frame_equal(
        left.buyhold.account_daily, right.buyhold.account_daily, check_exact=True
    )
    print("68_BUSINESS_ACCOUNTS_COMPLETE_COMMON_BENCHMARK_EXACT", flush=True)


def analyze():
    from assessment_helper import assess_unified

    states = cache_read(WORK / "prepared.pkl.gz")
    panels = {}
    for family, experiment, base, children, plan, plan_ref in states:
        central = cache_read(WORK / (family + "-center.pkl.gz"))
        stress = cache_read(WORK / (family + "-stress.pkl.gz"))
        points = tuple(cache_read(WORK / f"{family}-P{i:02}.pkl.gz") for i in range(32))
        panel = assess_unified(central, stress, points, plan.design)
        value = panel.to_dict() if hasattr(panel, "to_dict") else panel
        value["reference"] = material(
            ctx(family), experiment, "latest-five-self-checks", value
        ).to_dict()
        panels[family] = value
        for label, (req, res) in [("baseline", central), ("stress", stress)]:
            run = res.runs[0]
            run.execution.account_daily.to_csv(OUT / f"{family}-{label}-account.csv", index=False)
            run.execution.trades.to_csv(OUT / f"{family}-{label}-trades.csv", index=False)
        write(OUT / (family + "-assessment.json"), value)
    write(OUT / "assessment_panels.json", panels)
    print("LATEST_FIVE_SELF_CHECKS_COMPLETE", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("declare", "run", "analyze"))
    {"declare": declare, "run": run, "analyze": analyze}[parser.parse_args().phase]()
