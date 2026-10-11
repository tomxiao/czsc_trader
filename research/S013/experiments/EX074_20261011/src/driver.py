"""EX074 fixed pressure-latched deadline test; explicit root authorization required."""

from __future__ import annotations
from dataclasses import replace
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import shutil
import argparse
import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate, implementation_sha256, ParameterSet
from strategy_manager import (
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
    CandidateKey,
)
from czsc_trader.application import (
    create_experiment,
    ExperimentRequest,
    publish_evidence,
    validate_delivery,
)
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools import (
    MaterialEvidenceWrite,
    EvaluationEvidenceWrite,
    EvaluationLineage,
)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-pressure-early-exit"
OLD = ROOT / "research/S013/experiments/EX058_20261011"
NEW_ID = "C9074"
EXPECTED = "EX074_20261011"
ORIGINAL = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def digest(p):
    return sha256(Path(p).read_bytes()).hexdigest()


def write(p, value):
    p = Path(p)
    if p.exists():
        raise RuntimeError("Immutable output exists: " + str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


def load(name, path):
    if name in sys.modules:
        assert Path(sys.modules[name].__file__).resolve() == path.resolve()
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def oldcommon():
    return load("common", OLD / "src/common.py")


def public(q):
    ref = EvidenceRef.from_dict(q)
    assert ref.experiment.strategy_id == "S013"
    path = ref.resolve(ROOT)
    assert digest(path) == ref.sha256
    return path


def delivery_integrity(ctx, value):
    reference = d.DeliveryReference.from_dict(value)
    validation = validate_delivery(
        ctx.repository, reference, scope=d.DeliveryValidationScope.INTEGRITY
    )
    assert validation.status is d.ValidationStatus.PASS, validation.to_dict()
    return reference, validation


def put(ctx, exp, path, name=None):
    path = Path(path)
    media = {".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown"}.get(
        path.suffix, "application/json"
    )
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp, name or path.stem.replace("_", "-"), path.read_bytes(), media, path.suffix[1:]
        ),
    ).to_dict()


def runtime_config(source, p):
    files = ["strategies/" + q.name for q in sorted((source / "strategies").glob("*.py"))]
    return {
        "parameters": p,
        "runtime": {
            "contract_version": 1,
            "module": "strategy_runtime.strategies.pressure_early_exit_range",
            "qualname": "PressureEarlyExitRange",
            "source_files": files,
            "source_sha256": implementation_sha256(files, source_root=source),
        },
    }


def native():
    common = oldcommon()
    pair = common.cache_read(common.CACHE / "N0.pkl.gz")
    ref = common.read(common.RUNS / "account_references.json")["N0"]
    assert serialize_evaluation_evidence(*pair) == read(public(ref))
    assert pair[0].strategy.candidate_id == "C8880"
    return pair, ref


def stage():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    name = next(
        (
            n
            for n in ("effective_plan3", "effective_plan2", "effective_plan", "plan")
            if (exp.resolve(ROOT) / "protocols" / (n + ".json")).exists()
        )
    )
    plan = read(exp.resolve(ROOT) / "protocols" / (name + ".json"))
    for path, value in plan["source_files"].items():
        assert digest(ROOT / path) == value, path
    assert read(public(read(exp.resolve(ROOT) / "protocols" / (name + "_reference.json")))) == plan
    return exp, plan, exp.resolve(ROOT)


def declare():
    assert not (WORK / "experiment.json").exists()
    feasible = read(WORK / "feasibility_plan.json")
    proof = read(WORK / "exit_checks.json")
    freeze = read(WORK / "freeze_v2.json")
    authorization = read(WORK / "root_execution_authorization.json")
    assert authorization["status"] == "APPROVED_EX074_CENTRE"
    assert authorization["freeze_sha256"] == digest(WORK / "freeze_v2.json")
    assert (
        proof["status"] == "PASS"
        and proof["account_runs"] == 0
        and proof["original_six_sources_byte_exact"]
    )
    for rel, h in freeze["files"].items():
        assert digest(ROOT / rel) == h, rel
    for rel, h in feasible["source_file_hashes"].items():
        assert digest(WORK / rel) == h, rel
    base = read(OLD / "protocols/plan.json")["configurations"][0]["payload"]["parameters"]
    p = feasible["payload"]["parameters"]
    assert {k: v for k, v in p.items() if k != "pressure_exit"} == base
    assert p["pressure_exit"] == {"enabled": True, "lookback": 4, "early_hold_cap": 2}
    assert (
        feasible["geometry"]["coordinates"][:13]
        == read(OLD / "protocols/geometry.json")["coordinates"]
    )
    assert len(feasible["geometry"]["coordinates"]) == 15
    assert not (ROOT / "research/S013/assets/candidates" / NEW_ID).exists()
    assert not (ROOT / "research/registrations/S013/candidates" / (NEW_ID + ".json")).exists()
    (old, _), oldref = native()
    common = oldcommon()
    ctx = common.context(1)
    design_source = WORK / "exit_source/strategy_runtime"
    assert (
        implementation_sha256(feasible["source_files"], source_root=design_source)
        == feasible["source_sha256"]
    )
    for q in (OLD / "src/strategy_runtime").rglob("*.py"):
        assert (
            q.read_bytes()
            == (design_source / q.relative_to(OLD / "src/strategy_runtime")).read_bytes()
        )
    review_ref = feasible["basis"]["public_EX073_root_review"]
    public(review_ref)
    delivery, delivery_validation = delivery_integrity(
        ctx, feasible["basis"]["public_EX073_delivery"]
    )
    assert read(public(review_ref)) == read(public(authorization["scientific_review_ref"]))
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "原熊市入场锁存隔夜下跌压力并缩短TIME上限的固定账户反证",
            "仅原熊市买入信号锁存此前4日隔夜负收益压力大于日内压力的标记；标记episode的TIME上限min(原H,2)，其他退出及买入规则保持，signal age对齐EX073后半段。",
            date(2026, 10, 11),
        ),
    )
    write(WORK / "allocated_experiment.json", exp.to_dict())
    assert exp.experiment_id == EXPECTED, "Keep allocation on mismatch; do not reallocate"
    target = exp.resolve(ROOT) / "src"
    target.mkdir(exist_ok=True)
    shutil.copytree(design_source, target / "strategy_runtime", dirs_exist_ok=True)
    for name in (
        "driver.py",
        "native_audit.py",
        "feature_certificate.py",
        "oracle.py",
        "economics_reference.py",
        "account_reference.py",
        "execution_links.py",
    ):
        shutil.copyfile(WORK / name, target / name)
    source = target / "strategy_runtime"
    candidate = StrategyCandidate("S013", NEW_ID, runtime_config(source, p), source)
    identity = ctx.runtime.identify(candidate, dependencies=old.dependencies)
    plan = {
        "experiment": exp.to_dict(),
        "role": "RSCH",
        "stage": 3,
        "policies": ["B0", "N_PRESSURE_EARLY_EXIT"],
        "authorization": authorization,
        "scope": feasible["scope"],
        "objective": feasible["objective"],
        "original_four_gates": [
            "return",
            "annual_drawdown",
            "frequency",
            "negative_buyhold_year_profit",
        ],
        "new_hard_gates": False,
        "rule": feasible["mechanism"],
        "strong_counterevidence": feasible["basis"],
        "feasibility_snapshot": feasible,
        "synthetic_precheck": proof,
        "freeze": freeze,
        "predecessor_delivery_integrity": {
            "reference": delivery.to_dict(),
            "validation": delivery_validation.to_dict(),
        },
        "effective_numeric_parameter_count": 15,
        "geometry": feasible["geometry"],
        "if_centre_passes": "Root confirmation before freezing exact15D32/.05/seed13/HALF_EVEN and fee; no new neighbours or point replacement; not paired13D comparison",
        "stop": feasible["experiment_execution_not_authorized_here"]["stop"],
        "budget": {
            "maximum_new_financial": 34,
            "centre_current": 1,
            "conditional_standard32": 32,
            "conditional_independent_fee": 1,
            "technical_financial_repeats": 0,
            "neighbours_authorized": 0,
            "baseline_centre_reuse": 1,
            "old34_accounts_authenticated_diagnostic_reuse_only": True,
        },
        "latest_fivechecks": "S013-EX062-five-independent-checks-v1; rolling126/step21; block20 bootstrap2000 seed13; PBO/DSR unavailable not0; no new economic veto",
        "candidate_id": NEW_ID,
        "content_sha256": identity.content_sha256,
        "payload": json.loads(json.dumps(dict(candidate.payload), default=dict)),
        "baseline_parameters": base,
        "baseline_reuse": oldref,
        "baseline_native_cache": (common.CACHE / "N0.pkl.gz").relative_to(ROOT).as_posix(),
        "baseline_cache_sha256": digest(common.CACHE / "N0.pkl.gz"),
        "input_bindings": {k: v.to_dict() for k, v in old.input_bindings.items()},
        "execution_data_fingerprint": old.execution_data.fingerprint,
        "price_basis": "HFQ_RESEARCH",
        "initial_cash": 1000000,
        "one_way_fee": 0.001,
        "pricing": old.execution_data.pricing.to_dict(),
        "benchmark": old.benchmark.to_dict(),
        "source_files": {q.relative_to(ROOT).as_posix(): digest(q) for q in target.rglob("*.py")},
        "external_source_files": {
            (OLD / "src/common.py").relative_to(ROOT).as_posix(): digest(OLD / "src/common.py")
        },
        "data_provider_revision": "S013-EX058-existing-only",
        "preflight": "maxworkers1 disabled1636exact plus EX073 all available pressure/old-entry comparison; independent ownpath beforefinancial",
    }
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    ref = put(
        ctx,
        exp,
        exp.resolve(ROOT) / "protocols/plan.json",
        "prospective-fixed-pressure-early-exit-centre",
    )
    refs = {"plan": ref, "baseline_native": oldref, "root_scientific_review": review_ref}
    for q in target.rglob("*.py"):
        refs[q.relative_to(target).as_posix()] = put(ctx, exp, q)
    for name in (
        "feasibility_plan.json",
        "exit_checks.json",
        "execution_checks.json",
        "freeze_v2.json",
        "root_execution_authorization.json",
    ):
        refs[name] = put(
            ctx, exp, WORK / name, "preaccount-design-" + name.replace("_", "-").replace(".", "-")
        )
    for name in (
        "build_source.py",
        "build_execution.py",
        "exit_checks.py",
        "prepare_plan.py",
        "execution_checks.py",
        "freeze_source.py",
    ):
        refs[name] = put(
            ctx, exp, WORK / name, "preaccount-source-" + name.replace("_", "-").replace(".", "-")
        )
    write(exp.resolve(ROOT) / "protocols/plan_reference.json", ref)
    write(exp.resolve(ROOT) / "protocols/prospective_references.json", refs)
    write(WORK / "experiment.json", exp.to_dict())
    assert not common.SOURCE_CALLS
    return {
        "status": "DECLARED",
        "experiment": exp.experiment_id,
        "content_sha256": identity.content_sha256,
        "accounts": 0,
    }


def audits():
    # Use immutable formal helper code; cache common reducer remains original.
    exp, plan, path = stage()
    sys.path.insert(0, str(path / "src"))
    for n in (
        "feature_certificate",
        "oracle",
        "economics_reference",
        "account_reference",
        "execution_links",
    ):
        load(n, path / "src" / f"{n}.py")
    return load("pressure_early_native_audit", path / "src/native_audit.py")


def prepared():
    exp, plan, path = stage()
    common = oldcommon()
    ctx = common.context(1)
    oldpair, ref = native()
    old = oldpair[0]
    assert digest(ROOT / plan["baseline_native_cache"]) == plan["baseline_cache_sha256"]
    source = path / "src/strategy_runtime"
    candidate = StrategyCandidate("S013", plan["candidate_id"], plan["payload"], source)
    identity = ctx.runtime.identify(candidate, dependencies=old.dependencies)
    assert identity.content_sha256 == plan["content_sha256"]
    parent = ctx.runtime.identify(old.strategy, dependencies=old.dependencies)
    lineage = CandidateDerivation(
        CandidateKey("S013", "C8880"),
        parent.content_sha256,
        CandidateKey("S013", NEW_ID),
        identity.content_sha256,
        CandidateDerivationKind.IMPLEMENTATION,
        {
            "pressure_exit": {
                "before": None,
                "after": {"enabled": True, "lookback": 4, "early_hold_cap": 2},
            }
        },
        read(path / "protocols/plan_reference.json")["sha256"],
        CandidateEvidence(EvidenceRef.from_dict(ref).repository_path, ref["sha256"]),
    )
    request = replace(
        old,
        experiment_id=exp.experiment_id,
        strategy=candidate,
        runtime_binding={
            "candidate_id": candidate.reference_id,
            "source_files": list(candidate.payload["runtime"]["source_files"]),
            "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
        },
        input_bindings={},
        lineage=EvaluationLineage(lineage),
    )
    request = ctx.evaluation.prepare(request)
    assert request.execution_data is old.execution_data
    actual = {k: v.to_dict() for k, v in request.input_bindings.items()}
    for k, v in actual.items():
        original = plan["input_bindings"][k]
        assert {n: q for n, q in v.items() if n != "plan"} == {
            n: q for n, q in original.items() if n != "plan"
        }
        assert {n: q for n, q in v["plan"].items() if n != "strategy"} == {
            n: q for n, q in original["plan"].items() if n != "strategy"
        }
        assert v["plan"]["strategy"]["reference_id"] == candidate.reference_id
        definition = ctx.runtime.describe(candidate)
        assert v["plan"]["strategy"]["runtime_sha256"] == definition.runtime_sha256
        assert v["plan"]["strategy"]["release_hash"] == definition.release_hash
    assert not common.SOURCE_CALLS
    return ctx, exp, plan, path, request, oldpair


def preflight():
    ctx, exp, plan, path, request, oldpair = prepared()
    common = oldcommon()
    audit = audits()
    assert not (WORK / "preflight.json").exists()
    baseline = audit.audit(ctx, *oldpair, read(public(plan["baseline_reuse"])), new=False)
    import types
    import importlib

    namespace = types.ModuleType("s013_early_exit_preflight")
    namespace.__path__ = [str(path / "src/strategy_runtime")]
    sys.modules[namespace.__name__] = namespace
    mod = importlib.import_module(namespace.__name__ + ".strategies.pressure_early_exit_range")
    oldmod = importlib.import_module(
        namespace.__name__ + ".strategies.boundary_bear_recovery_range"
    )
    binding = request.input_bindings["full"]
    fetched = ctx.data.fetch(binding.plan.requests["daily"], prepared=binding.prepared)
    assert fetched.ready
    daily = fetched.dataframe.copy()
    sessions = pd.DatetimeIndex(
        pd.to_datetime(oldpair[1].runs[0].execution.decisions.signal_date)
    ).normalize()
    p = plan["payload"]["parameters"]
    disabled = mod.PressureEarlyExitRange(
        ParameterSet(p | {"pressure_exit": {"enabled": False, "lookback": 4, "early_hold_cap": 2}})
    )
    hist = disabled.calculate_history({"daily": daily}, sessions)
    oldhist = oldmod.BoundaryBearRecoveryRange(
        ParameterSet(plan["baseline_parameters"])
    ).calculate_history({"daily": daily}, sessions)
    pd.testing.assert_frame_equal(hist[oldhist.columns], oldhist, check_exact=True)
    olddec = oldpair[1].runs[0].execution.decisions.copy()
    olddec.index = sessions
    comparable = [n for n in oldhist.columns if n in olddec]
    for n in comparable:
        left, right = oldhist[n], olddec[n]
        if pd.api.types.is_numeric_dtype(left):
            assert np.array_equal(left.to_numpy(), right.to_numpy(), equal_nan=True), n
        else:
            assert all((a == b) or (pd.isna(a) and pd.isna(b)) for a, b in zip(left, right)), n
    model = mod.PressureEarlyExitRange(ParameterSet(p))
    newhist = model.calculate_history({"daily": daily}, sessions)
    prefix = model.calculate_history(
        {"daily": daily.iloc[:-10]}, sessions[sessions <= pd.Timestamp(daily.Date.iloc[-11])]
    )
    pd.testing.assert_frame_equal(prefix, newhist.loc[prefix.index], check_exact=True)
    # Frozen public EX073 warm prices and historical B0 entries; no statistics recomputation.
    method_refs = plan["feasibility_snapshot"]["driver_preflight"]["public_EX073_identity_refs"]
    warmref = method_refs["warm_prices.csv"]
    warm = pd.read_csv(public(warmref), index_col=0, parse_dates=True, float_precision="round_trip")
    core_ref = method_refs["entry_core.py"]
    core = load("s013_frozen_entry_core74", public(core_ref))
    pressure = core.pressure(warm)
    values = newhist.loc[pressure.index.intersection(newhist.index)]
    pressure = pressure.reindex(values.index)
    assert pressure.pressure_available.all() and len(values) == len(newhist)
    numeric_tolerance = {"rtol": 1e-11, "atol": 1e-12}
    max_abs_diff = {}
    for n, q in (
        ("pressure_overnight_down", "overnight_down4"),
        ("pressure_intraday_down", "intraday_down4"),
        ("pressure_share", "pressure_share4"),
    ):
        max_abs_diff[n] = float(np.max(np.abs(values[n].to_numpy() - pressure[q].to_numpy())))
        assert np.allclose(values[n].to_numpy(), pressure[q].to_numpy(), **numeric_tolerance), (
            n,
            "EX073_pressure_numeric",
        )
    assert np.array_equal(
        values.pressure_dominant.to_numpy(), pressure.pressure_flag.to_numpy(bool)
    )
    aligned = daily.copy()
    aligned.index = pd.DatetimeIndex(pd.to_datetime(aligned.Date)).normalize()
    common_dates = aligned.index.intersection(warm.index)
    price_diff = float(
        np.max(
            np.abs(
                aligned.loc[common_dates, ["Open", "Close"]].to_numpy()
                - warm.loc[common_dates, ["Open", "Close"]].to_numpy()
            )
        )
    )
    assert np.allclose(
        aligned.loc[common_dates, ["Open", "Close"]],
        warm.loc[common_dates, ["Open", "Close"]],
        rtol=0,
        atol=5e-15,
    )
    scope_ref = method_refs["scope.csv"]
    prior_scope = pd.read_csv(
        public(scope_ref), index_col=0, parse_dates=True, float_precision="round_trip"
    )
    account = oldpair[1].runs[0].execution.account_daily
    fills = oldpair[1].runs[0].execution.fills
    reproduced_entries = core.actual_entries(account, fills, oldpair[1].runs[0].execution.decisions)
    original_bear_dates = sorted(reproduced_entries.loc[reproduced_entries.regime.eq("bear")].index)
    historical_bear_dates = sorted(prior_scope.index[prior_scope.iloc[:, 0].to_numpy(bool)])
    assert original_bear_dates == historical_bear_dates
    ex073_identity = {
        "all_available_pressure_dates": len(values),
        "old_bear_entry_dates_exact": len(original_bear_dates),
        "warm_ref": warmref,
        "core_ref": core_ref,
        "scope_ref": scope_ref,
        "numeric_within_declared_tolerance": True,
        "strict_flags_exact": True,
        "numeric_tolerance": numeric_tolerance,
        "actual_max_abs_diff": max_abs_diff,
        "aligned_price_dates": len(common_dates),
        "actual_max_price_abs_diff": price_diff,
        "price_tolerance": {"rtol": 0, "atol": 5e-15},
        "explanation": "Observed differences recorded; CSV precision/rolling starts are possible causes, not independently established causal explanations.",
    }
    doc = {
        "status": "PASS",
        "financial_accounts": 0,
        "max_workers": 1,
        "baseline_complete_native_audit": baseline,
        "disabled_historical_signal_count": len(hist),
        "disabled_original_source_old_columns_exact": True,
        "disabled_native_old_columns_exact": comparable,
        "enabled_real_prefix_exact": True,
        "enabled_ownpath_entry_latches": int(newhist.pressure_entry_latched.sum()),
        "enabled_ownpath_early_time_exits": int(newhist.pressure_early_time_exit.sum()),
        "new_signal_target_difference_n": int(
            (newhist.target_position != oldhist.target_position).sum()
        ),
        "input_bindings": {k: v.to_dict() for k, v in request.input_bindings.items()},
        "provider_calls": common.SOURCE_CALLS,
        "EX073_exact_identity": ex073_identity,
    }
    write(WORK / "preflight.json", doc)
    common.cache_write(WORK / "prepared.pkl.gz", (request, oldpair))
    ref = put(ctx, exp, WORK / "preflight.json")
    write(path / "protocols/preflight_reference.json", ref)
    assert not common.SOURCE_CALLS
    return {
        "status": "PREFLIGHT_PASS",
        "financial_accounts": 0,
        "disabled_original_signal_count": len(hist),
        "enabled_latches": doc["enabled_ownpath_entry_latches"],
        "enabled_early_time_exits": doc["enabled_ownpath_early_time_exits"],
    }


def execute():
    exp, plan, path = stage()
    common = oldcommon()
    ctx = common.context(1)
    assert read(public(read(path / "protocols/preflight_reference.json")))["status"] == "PASS"
    assert not (WORK / "execution_started.json").exists()
    request, _ = common.cache_read(WORK / "prepared.pkl.gz")
    assert (
        ctx.runtime.identify(request.strategy, dependencies=request.dependencies).content_sha256
        == plan["content_sha256"]
    )
    write(
        WORK / "execution_started.json",
        {
            "status": "INFLIGHT",
            "account_budget": 1,
            "plan_reference": read(path / "protocols/plan_reference.json"),
        },
    )
    result = ctx.evaluation.evaluate(request)
    common.cache_write(WORK / "centre.pkl.gz", (request, result))
    ref = publish_evidence(
        ctx, EvaluationEvidenceWrite(exp, "pressure-early-exit-full-centre-native", request, result)
    ).to_dict()
    assert serialize_evaluation_evidence(request, result) == read(public(ref))
    write(path / "protocols/centre_reference.json", ref)
    write(
        WORK / "execution_complete.json",
        {
            "status": "COMPLETE",
            "actual_new_accounts": 1,
            "new_32": 0,
            "new_fee": 0,
            "reference": ref,
            "request_hash": result.request_hash,
            "result_hash": result.result_hash,
            "cache_sha256": digest(WORK / "centre.pkl.gz"),
        },
    )
    assert not common.SOURCE_CALLS
    return {
        "status": "NATIVE_FULL_COMPLETE",
        "actual_new_accounts": 1,
        "request_hash": result.request_hash,
        "result_hash": result.result_hash,
    }


def verify():
    exp, plan, path = stage()
    common = oldcommon()
    ctx = common.context(1)
    complete = read(WORK / "execution_complete.json")
    assert digest(WORK / "centre.pkl.gz") == complete["cache_sha256"]
    pair = common.cache_read(WORK / "centre.pkl.gz")
    report = audits().audit(ctx, *pair, read(public(complete["reference"])), new=True)
    baseline = read(WORK / "preflight.json")["baseline_complete_native_audit"]
    report["baseline"] = baseline
    run = pair[1].runs[0].execution
    d = run.decisions
    report["raw_counts"] = {
        "signal_days": len(d),
        "pressure_dominant_all_days": int(d.pressure_dominant.sum()),
        "own_bear_entry_latches": int(d.pressure_entry_latched.sum()),
        "early_time_exits": int(d.pressure_early_time_exit.sum()),
        "signal_buy_entries": int(d.signal_reason.eq("entry").sum()),
        "actual_buy_fills": int(run.fills.side.eq("BUY").sum()),
        "actual_sell_fills": int(run.fills.side.eq("SELL").sum()),
        "raw_trade_rows": len(run.trades),
        "closed_trades": report["economics"]["closed_trades"],
        "open_cycles": int(run.trades.exit_date.isna().sum()),
    }
    report["raw_early_exit_dates"] = [
        str(x) for x in d.loc[d.pressure_early_time_exit, "signal_date"]
    ]
    report["interpretation"] = (
        "Early TIME changes recovery memory, subsequent entries and cash paths. Old15 entry pressure flags do not predetermine new own-state latches/trade profits. Signal age cap does not guarantee actual2-day holdings. No hypothetical future group-profit selection."
    )
    report["stop_policy"] = (
        "ANY_ORIGINAL4_FAIL_STOP_NO32_NOFEE_NONEIGHBOUR"
        if not report["economics"]["qualified"]
        else "CENTRE_PASS_WAIT_ROOT_CONFIRMATION_BEFORE32_FEE"
    )
    report["counts"] = {
        "new_financial": 1,
        "new_standard32": 0,
        "new_fee": 0,
        "new_neighbours": 0,
        "baseline_reuse": 1,
        "technical_financial_repeats": 0,
    }
    report["provider_calls"] = common.SOURCE_CALLS
    refs = {
        "centre": complete["reference"],
        "preflight": read(path / "protocols/preflight_reference.json"),
        "plan": read(path / "protocols/plan_reference.json"),
    }
    for name in ("decisions", "orders", "fills", "account_daily", "trades"):
        getattr(run, name).to_csv(WORK / (name + ".csv"), index=False, float_format="%.17g")
        refs[name + ".csv"] = put(ctx, exp, WORK / (name + ".csv"))
    write(WORK / "verification.json", report)
    refs["verification"] = put(ctx, exp, WORK / "verification.json")
    write(path / "protocols/result_references.json", refs)
    assert not common.SOURCE_CALLS
    return {
        "status": "NATIVE_INDEPENDENT_AUDIT_PASS",
        "economics": report["economics"],
        "baseline_economics": baseline["economics"],
        "raw_counts": report["raw_counts"],
        "stop_policy": report["stop_policy"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("declare", "preflight", "execute", "verify"))
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
