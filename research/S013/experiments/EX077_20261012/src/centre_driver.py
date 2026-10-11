"""Fixed single-centre staged runner. SOURCE ONLY until exact root phase authority.

No action on import; no parameter search, alternate policy or automatic retry.
"""

import argparse
from dataclasses import replace
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import canonical_frame_sha256
from strategy_runtime import StrategyCandidate, implementation_sha256
from czsc_trader.application import ExperimentRequest, create_experiment, publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-price-event-policy"
OLD = ROOT / "research/S013/experiments/EX058_20261011"
GENERAL = ROOT / "research/S013/experiments/EX074_20261011/src"
CANDIDATE = "C9077"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load(name, path):
    if name in sys.modules:
        if Path(sys.modules[name].__file__).resolve() != path.resolve():
            raise RuntimeError("module identity collision")
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def common():
    return load("common", OLD / "src/common.py")


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013-only reference required")
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError("public evidence SHA mismatch")
    return path


def authorize(phase, path):
    authority = read(path)
    freeze = read(WORK / "centre_source_freeze.json")
    if (
        authority.get("phase") != phase
        or authority.get("source_freeze_sha256") != digest(WORK / "centre_source_freeze.json")
        or authority.get("candidate_id") != CANDIDATE
    ):
        raise PermissionError("new exact root phase/source/candidate authority required")
    for rel, expected in freeze["files"].items():
        if digest(ROOT / rel) != expected:
            raise ValueError("frozen source drift: " + rel)
    if phase != "declare":
        if authority.get("plan_reference") != read(stage()[2] / "protocols/plan_reference.json"):
            raise PermissionError("actual public plan must be bound by phase authority")
    write(
        WORK / (phase + "_attempt.json"),
        {
            "phase": phase,
            "authority": authority,
            "authority_sha256": digest(path),
            "status": "STARTED_NO_AUTOMATIC_RETRY",
        },
    )
    return authority


def native():
    c = common()
    cache = c.CACHE / "N0.pkl.gz"
    pair = c.cache_read(cache)
    reference = read(c.RUNS / "account_references.json")["N0"]
    if pair[0].strategy.candidate_id != "C8880" or serialize_evaluation_evidence(*pair) != read(
        public(reference)
    ):
        raise ValueError("original baseline native pair authentication failed")
    return pair, reference, cache


def put(ctx, exp, path):
    path = Path(path)
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp,
            "price-event-" + path.stem.replace("_", "-"),
            path.read_bytes(),
            "text/x-python" if path.suffix == ".py" else "application/json",
            path.suffix[1:],
        ),
    ).to_dict()


def stage():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    path = exp.resolve(ROOT)
    plan = read(path / "protocols/plan.json")
    if read(public(read(path / "protocols/plan_reference.json"))) != plan:
        raise ValueError("actual plan/public bytes mismatch")
    return exp, plan, path


def payload(source):
    files = ["strategies/policy.py", "strategies/price_event.py"]
    return {
        "parameters": {"lookback": 20, "distance": 1.0},
        "runtime": {
            "contract_version": 1,
            "module": "strategy_runtime.strategies.price_event",
            "qualname": "PriceEvent",
            "source_files": files,
            "source_sha256": implementation_sha256(files, source_root=source),
        },
    }


def declare(authority_path):
    authority = authorize("declare", authority_path)
    run_date = date.fromisoformat(authority["run_date"])
    expected = "EX077_" + run_date.strftime("%Y%m%d")
    if authority.get("expected_experiment_id") != expected:
        raise ValueError("root must bind actual CST date and expected EX077 identifier")
    for path in (
        ROOT / "research/S013/assets/candidates" / CANDIDATE,
        ROOT / "research/registrations/S013/candidates" / (CANDIDATE + ".json"),
    ):
        if path.exists():
            raise ValueError("C9077 already occupied")
    (old, _), baseline_ref, cache = native()
    c = common()
    ctx = c.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "独立价格事件周期固定中心反证",
            "只简化完整状态表达；不声称新增alpha；原四门任一失败停止。",
            run_date,
        ),
    )
    write(WORK / "allocated_experiment.json", exp.to_dict())
    if exp.experiment_id != expected:
        raise RuntimeError("Allocation mismatch preserved; never allocate again")
    src = exp.resolve(ROOT) / "src"
    for name, source in (
        ("strategy_runtime/strategies/policy.py", WORK / "policy.py"),
        ("strategy_runtime/strategies/price_event.py", WORK / "integration_adapter_draft.py"),
        ("centre_driver.py", Path(__file__)),
        ("centre_audit.py", WORK / "centre_audit.py"),
    ):
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
    strategy = StrategyCandidate(
        "S013", CANDIDATE, payload(src / "strategy_runtime"), src / "strategy_runtime"
    )
    identity = ctx.runtime.identify(strategy, dependencies=old.dependencies)
    plan = {
        "status": "PROSPECTIVELY_DECLARED_ZERO_ACCOUNTS_AWAITING_PREPARE",
        "experiment": exp.to_dict(),
        "candidate_id": CANDIDATE,
        "content_sha256": identity.content_sha256,
        "payload": json.loads(json.dumps(dict(strategy.payload), default=dict)),
        "design": read(WORK / "integration_plan_draft.json"),
        "prospective_policy": read(WORK / "prospective_plan.json"),
        "baseline_native": baseline_ref,
        "baseline_cache": cache.relative_to(ROOT).as_posix(),
        "baseline_cache_sha256": digest(cache),
        "baseline_execution_fingerprint": old.execution_data.fingerprint,
        "baseline_input_bindings": {k: v.to_dict() for k, v in old.input_bindings.items()},
        "pricing": old.execution_data.pricing.to_dict(),
        "benchmark": old.benchmark.to_dict(),
        "baseline_contract": {
            "initial_cash": old.initial_cash,
            "costs": [
                {
                    "scenario_id": x.scenario_id,
                    "one_way_cost": x.one_way_cost,
                    "measurement_tier": x.measurement_tier,
                }
                for x in old.costs
            ],
            "windows": [
                {"window_id": x.window_id, "start": x.start.isoformat(), "end": x.end.isoformat()}
                for x in old.windows
            ],
            "price_basis": old.price_basis.value,
        },
        "independent_policy_lineage": None,
        "source_freeze": read(WORK / "centre_source_freeze.json"),
        "synthetic_precheck": read(WORK / "centre_source_proof.json"),
        "budget": {
            "centre_current": 1,
            "conditional32": 32,
            "conditional_fee": 1,
            "maximum_business_accounts": 34,
            "technical_repeats": 0,
        },
        "stop": "ANY_ORIGINAL_FOUR_GATE_FAIL_STOP_NO32_NOFEE_NOPARAMETER_RESCUE",
        "root_authority": authority,
        "root_route_decision": read(WORK / "root_route_decision.json"),
    }
    plan_path = exp.resolve(ROOT) / "protocols/plan.json"
    write(plan_path, plan)
    refs = {"plan": put(ctx, exp, plan_path), "baseline_native": baseline_ref}
    for source in src.rglob("*.py"):
        refs[source.relative_to(src).as_posix()] = put(ctx, exp, source)
    for source in (
        WORK / "centre_source_freeze.json",
        WORK / "centre_source_proof.json",
        Path(authority_path),
        WORK / "source_freeze.json",
        WORK / "prospective_plan.json",
        WORK / "root_route_decision.json",
        WORK / "independent_policy_freeze.json",
        WORK / "independent_policy_audit.py",
        WORK / "independent_policy_proof.json",
        WORK / "centre_source_checks.py",
        OLD / "src/common.py",
        GENERAL / "economics_reference.py",
        GENERAL / "account_reference.py",
        GENERAL / "execution_links.py",
    ):
        refs[source.name] = put(ctx, exp, source)
    write(exp.resolve(ROOT) / "protocols/plan_reference.json", refs["plan"])
    write(exp.resolve(ROOT) / "protocols/prospective_references.json", refs)
    write(WORK / "experiment.json", exp.to_dict())
    if c.SOURCE_CALLS:
        raise RuntimeError("forbidden provider was attempted")
    return {
        "status": "DECLARED",
        "experiment": exp.experiment_id,
        "plan_reference": refs["plan"],
        "accounts": 0,
    }


def fetched_daily(ctx, binding):
    request = binding.plan.requests["daily"]
    value = ctx.data.fetch(request, prepared=binding.prepared)
    if (
        not value.ready
        or value.identity.dataset != str(request.dataset)
        or value.identity.symbol != request.symbol
        or value.identity.metadata.get("adjustment") != "hfq"
        or canonical_frame_sha256(value.dataframe) != value.identity.content_sha256
    ):
        raise ValueError("existing HFQ daily asset authentication failed")
    daily = value.dataframe
    axis = pd.DatetimeIndex(pd.to_datetime(daily.Date)).normalize()
    if (
        not axis.is_unique
        or not axis.is_monotonic_increasing
        or not np.isfinite(daily.Close.to_numpy(float)).all()
        or not (daily.Close > 0).all()
    ):
        raise ValueError("existing HFQ daily axis/Close invalid")
    first = pd.Timestamp("2019-12-31")
    if (
        len(axis[axis <= first]) < 121
        or not (axis == first).any()
        or axis[-1] != pd.Timestamp("2026-09-29")
    ):
        raise ValueError(
            "original existing asset does not cover121 history and native prefix; no provider/domain fallback"
        )
    ident = value.identity
    return daily, {
        name: getattr(ident, name)
        for name in ("dataset", "source", "symbol", "data_start", "data_cutoff", "content_sha256")
    } | {"metadata": dict(ident.metadata)}


def prepare(authority_path):
    authorize("prepare", authority_path)
    exp, plan, path = stage()
    c = common()
    ctx = c.context(1)
    (old, _), _, cache = native()
    if digest(cache) != plan["baseline_cache_sha256"]:
        raise ValueError("baseline cache drift")
    original_daily, original_identity = fetched_daily(ctx, old.input_bindings["full"])
    strategy = StrategyCandidate("S013", CANDIDATE, plan["payload"], path / "src/strategy_runtime")
    request = replace(
        old,
        experiment_id=exp.experiment_id,
        strategy=strategy,
        runtime_binding={
            "candidate_id": strategy.reference_id,
            "source_files": list(strategy.payload["runtime"]["source_files"]),
            "implementation_sha256": strategy.payload["runtime"]["source_sha256"],
        },
        input_bindings={},
        lineage=None,
    )
    bound = ctx.evaluation.prepare(request)
    if (
        bound.execution_data is not old.execution_data
        or bound.execution_data.fingerprint != plan["baseline_execution_fingerprint"]
    ):
        raise ValueError("native execution identity changed")
    daily, identity = fetched_daily(ctx, bound.input_bindings["full"])
    original = original_daily.set_index(
        pd.DatetimeIndex(pd.to_datetime(original_daily.Date)).normalize()
    )
    new = daily.set_index(pd.DatetimeIndex(pd.to_datetime(daily.Date)).normalize())
    pd.testing.assert_frame_equal(new, original.loc[new.index], check_exact=True)
    signals = pd.DatetimeIndex(
        pd.to_datetime(tuple(bound.input_bindings["full"].plan.signal_dates.values()))
    ).normalize()
    if (
        len(signals) != 1636
        or signals[0] != pd.Timestamp("2019-12-31")
        or signals[-1] != pd.Timestamp("2026-09-29")
    ):
        raise ValueError("native anchor decision prefix changed")
    if (
        ctx.runtime.identify(strategy, dependencies=bound.dependencies).content_sha256
        != plan["content_sha256"]
        or c.SOURCE_CALLS
    ):
        raise ValueError("runtime drift or forbidden provider attempt")
    c.cache_write(WORK / "centre_prepared.pkl.gz", bound)
    proof = {
        "status": "PASS",
        "accounts": 0,
        "existing121warm_ready": True,
        "baseline_daily_identity": original_identity,
        "daily_identity": identity,
        "original_subset_prices_exact": True,
        "input_bindings": {k: v.to_dict() for k, v in bound.input_bindings.items()},
        "prepared_cache_sha256": digest(WORK / "centre_prepared.pkl.gz"),
        "execution_fingerprint": bound.execution_data.fingerprint,
        "provider_calls": c.SOURCE_CALLS,
    }
    write(WORK / "centre_prepare.json", proof)
    ref = put(ctx, exp, WORK / "centre_prepare.json")
    write(path / "protocols/prepare_reference.json", ref)
    return {"status": "PREPARED_ZERO_ACCOUNTS", "reference": ref}


def execute(authority_path):
    authority = authorize("execute", authority_path)
    exp, _, path = stage()
    if authority.get("account_budget") != 1 or authority.get("prepare_reference") != read(
        path / "protocols/prepare_reference.json"
    ):
        raise PermissionError("exact one-account and actual prepare authority required")
    proof = read(public(authority["prepare_reference"]))
    if (
        proof["status"] != "PASS"
        or digest(WORK / "centre_prepared.pkl.gz") != proof["prepared_cache_sha256"]
    ):
        raise ValueError("prepared cache authentication failed")
    c = common()
    ctx = c.context(1)
    bound = c.cache_read(WORK / "centre_prepared.pkl.gz")
    result = ctx.evaluation.evaluate(bound)
    c.cache_write(WORK / "centre_account.pkl.gz", (bound, result))
    ref = publish_evidence(
        ctx, EvaluationEvidenceWrite(exp, "fixed-price-event-centre-native", bound, result)
    ).to_dict()
    if read(public(ref)) != serialize_evaluation_evidence(bound, result) or c.SOURCE_CALLS:
        raise ValueError("native publication/provider authentication failed")
    receipt = {
        "status": "COMPLETE",
        "new_accounts": 1,
        "reference": ref,
        "request_hash": result.request_hash,
        "result_hash": result.result_hash,
        "cache_sha256": digest(WORK / "centre_account.pkl.gz"),
        "plan_reference": read(path / "protocols/plan_reference.json"),
        "prepare_reference": authority["prepare_reference"],
    }
    write(WORK / "centre_execution.json", receipt)
    write(path / "protocols/centre_reference.json", ref)
    return receipt


def verify(authority_path):
    authority = authorize("verify", authority_path)
    exp, plan, path = stage()
    receipt = read(WORK / "centre_execution.json")
    if (
        authority.get("centre_reference") != receipt["reference"]
        or digest(WORK / "centre_account.pkl.gz") != receipt["cache_sha256"]
    ):
        raise PermissionError("exact completed-account evidence and cache authority required")
    c = common()
    ctx = c.context(1)
    bound, result = c.cache_read(WORK / "centre_account.pkl.gz")
    if (
        bound.execution_data.fingerprint != plan["baseline_execution_fingerprint"]
        or bound.benchmark.to_dict() != plan["benchmark"]
        or bound.execution_data.pricing.to_dict() != plan["pricing"]
    ):
        raise ValueError("whole original benchmark/pricing/native execution contract changed")
    daily, _ = fetched_daily(ctx, bound.input_bindings["full"])
    helpers = {
        name: load("price_event_" + name, GENERAL / (name + ".py"))
        for name in ("economics_reference", "account_reference", "execution_links")
    }
    checker = load("price_event_centre_audit", path / "src/centre_audit.py")
    report = checker.audit(ctx, bound, result, read(public(receipt["reference"])), daily, helpers)
    if c.SOURCE_CALLS:
        raise RuntimeError("forbidden provider attempt")
    report["references"] = {
        "centre": receipt["reference"],
        "prepare": read(path / "protocols/prepare_reference.json"),
        "plan": read(path / "protocols/plan_reference.json"),
    }
    write(WORK / "centre_verification.json", report)
    ref = put(ctx, exp, WORK / "centre_verification.json")
    write(path / "protocols/verification_reference.json", ref)
    return {
        "status": "VERIFIED",
        "reference": ref,
        "economics": report["economics"],
        "stop": report["stop"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("declare", "prepare", "execute", "verify"))
    parser.add_argument("--authority", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            globals()[args.phase](Path(args.authority)),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )
