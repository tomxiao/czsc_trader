"""Public pinned-input preparations and sequential fixed-node account diagnostics."""

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import requests
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationBenchmark,
    EvaluationCost,
    EvaluationEvidenceWrite,
    EvaluationRequest,
    EvaluationResources,
    EvaluationWindow,
    EvidenceRef,
    ExperimentRef,
    LimitBuyHold,
    MaterialEvidenceWrite,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
PACKAGE = EX / "src/strategy_runtime"
METHOD = ROOT / "research/S014/materials/20261019_2025_action_execution/joint_method"
FILES = ("strategies/joint_action_review.py",)
sys.path.append(str(EX.parent / "EX017_20261017/src"))
from pinned_inputs import get_context  # noqa: E402


def no_network(*args, **kwargs):
    raise RuntimeError("EX042 uses authenticated S014 pinned offline data only")


requests.sessions.Session.request = no_network


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write("\n")


def context():
    return get_context(
        EvaluationResources(max_workers=2, native_threads_per_worker=1, random_seed=17)
    )


def publish_file(ctx, path, name):
    media = {
        ".py": "text/x-python",
        ".json": "application/json",
        ".csv": "text/csv",
        ".md": "text/markdown",
    }
    ref = publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            ExperimentRef("S014", EX.name),
            name,
            path.read_bytes(),
            media[path.suffix],
            path.suffix[1:],
        ),
    )
    assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
    return ref.to_dict()


def build():
    design = read(EX / "protocols/design.json")
    assert design["execution_authorized"]
    for field in (
        "authorization",
        "method",
        "source_bindings",
        "independent_method_review",
        "shared_account_audit",
        "H10_reference_receipt",
        "EX041_independent_account_audit",
        "conditional_joint_plan",
    ):
        assert digest(ROOT / design[field]["path"]) == design[field]["sha256"]
    assert (PACKAGE / FILES[0]).read_bytes() == (
        METHOD / "prototype_runtime" / FILES[0]
    ).read_bytes()
    precheck = read(EX / "others/synthetic_precheck.json")
    assert precheck["status"] == "PASS_PURE_SYNTHETIC_ONLY" and precheck["checks_count"] == 73
    assert precheck["actual_SRT_observation_materializations"] == 264
    assert digest(PACKAGE / FILES[0]) == precheck["source_sha256"]
    assert digest(EX / "src/precheck.py") == precheck["precheck_source_sha256"]
    assert (
        digest(
            ROOT
            / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"
        )
        == precheck["original_source_sha256"]
    )
    assert (
        digest(
            ROOT
            / "research/S014/experiments/EX041_20261019/src/strategy_runtime/strategies/early_cycle_review.py"
        )
        == precheck["predecessor_source_sha256"]
    )
    from audit_accounts import h10_reference

    existing_h10 = h10_reference()["runs"][0]
    known_D = next(
        r
        for r in existing_h10["ledgers"]["decisions"]["data"]
        if r["signal_date"][:10] == "2025-06-19"
    )
    known_inventory = next(
        r
        for r in existing_h10["ledgers"]["account_daily"]["data"]
        if r["date"][:10] == "2025-06-19"
    )
    assert (
        known_D["buy_filled_today"]
        and known_D["held_at_close"]
        and not known_D["exit_pending"]
        and known_D["target_position"] == 1
        and known_D["target_cycle_completed"]
        and known_D["entry_index"] == known_D["warmup_sessions"]
        and known_inventory["quantity"] > 0
    ), "Joint fixed node unsupported on authenticated actual H10 path"
    ctx = context()
    source_hash = implementation_sha256(FILES, source_root=PACKAGE)
    rows = []
    for i, params in enumerate(design["fixed_parameters"]):
        cid = f"C{9900 + i:04}"
        assert not (ROOT / "research/S014/assets/candidates" / cid).exists()
        payload = {
            "runtime": {
                "module": "strategy_runtime.strategies.joint_action_review",
                "qualname": "JointActionStrategy",
                "contract_version": 1,
                "source_files": list(FILES),
                "source_sha256": source_hash,
            },
            "parameters": params,
        }
        candidate = StrategyCandidate("S014", cid, payload, PACKAGE)
        description = StrategyRuntime().describe(candidate)
        path = EX / f"protocols/payloads/{i:03}.json"
        write(path, payload)
        rows.append(
            {
                "index": i,
                "mode": params["mode"],
                "parameters": params,
                "candidate": candidate.reference_id,
                "runtime_sha256": description.runtime_sha256,
                "payload_sha256": digest(path),
                "payload_ref": publish_file(ctx, path, f"ex042-payload-{i:03}"),
            }
        )
    paths = [
        EX / "protocols/design.json",
        EX / "others/synthetic_precheck.json",
        *sorted((EX / "src").rglob("*.py")),
    ]
    published = {
        p.relative_to(EX).as_posix(): publish_file(
            ctx, p, "ex042-locked-" + p.relative_to(EX).as_posix().replace("/", "-")
        )
        for p in paths
    }
    for name in (
        "authorization",
        "method",
        "source_bindings",
        "independent_method_review",
        "shared_account_audit",
        "H10_reference_receipt",
        "EX041_independent_account_audit",
        "conditional_joint_plan",
    ):
        path = ROOT / design[name]["path"]
        published[name] = publish_file(ctx, path, "ex042-upstream-" + name)
    write(EX / "protocols/published_sources.json", published)
    lock = {
        "status": "LOCKED_BEFORE_ACCOUNTS",
        "revision": 1,
        "planned_account_count": 2,
        "user_account_numeric_cap": None,
        "no_automatic_blind_retries": True,
        "runtime_implementation_sha256": source_hash,
        "source_hashes": {p.relative_to(EX).as_posix(): digest(p) for p in paths},
        "external_source_hashes": {
            design[k]["path"]: design[k]["sha256"]
            for k in (
                "independent_method_review",
                "shared_account_audit",
                "H10_reference_receipt",
                "EX041_independent_account_audit",
                "conditional_joint_plan",
            )
        },
        "runs": rows,
        "published_sources_sha256": digest(EX / "protocols/published_sources.json"),
        "unique_economic_endpoint": "2025-12-31 SESSION_CLOSE",
    }
    write(EX / "protocols/execution_lock.json", lock)
    write(
        EX / "protocols/published_lock.json",
        publish_file(ctx, EX / "protocols/execution_lock.json", "ex042-execution-lock-v1"),
    )
    print("LOCKED_AND_PUBLIC 2 independent diagnostic identities", flush=True)


def validate_lock():
    lock = read(EX / "protocols/execution_lock.json")
    for rel, expected in lock["external_source_hashes"].items():
        assert digest(ROOT / rel) == expected, rel
    for rel, expected in lock["source_hashes"].items():
        assert digest(EX / rel) == expected, rel
    assert digest(EX / "protocols/published_sources.json") == lock["published_sources_sha256"]
    ref = EvidenceRef.from_dict(read(EX / "protocols/published_lock.json"))
    assert ref.resolve(ROOT).read_bytes() == (EX / "protocols/execution_lock.json").read_bytes()
    return lock


def execute(index):
    from audit_accounts import audit

    lock = validate_lock()
    if index:
        assert read(EX / "others/gate_control.json")["status"] == "PASS"
    row = lock["runs"][index]
    assert row["index"] == index
    assert not (EX / f"others/dispatches/{index:03}.json").exists(), "No blind retry after dispatch"
    payload_path = EX / f"protocols/payloads/{index:03}.json"
    assert digest(payload_path) == row["payload_sha256"]
    payload = read(payload_path)
    candidate = StrategyCandidate("S014", row["candidate"].split("-")[1], payload, PACKAGE)
    request = EvaluationRequest(
        repository_root=ROOT,
        experiment_id=EX.name,
        strategy=candidate,
        runtime_binding={
            "candidate_id": candidate.reference_id,
            "source_files": list(FILES),
            "implementation_sha256": lock["runtime_implementation_sha256"],
        },
        symbol="600722.SH",
        asset_type="stock",
        windows=(EvaluationWindow("full", date(2020, 1, 2), date(2026, 10, 15)),),
        data_cutoff=date(2026, 10, 15),
        initial_cash=100000,
        costs=(EvaluationCost("baseline", 0.001),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.01, 0.01, 0.1, 1000000)),
        workers=1,
    )
    ctx = context()
    try:
        bound = ctx.evaluation.prepare(request)
        binding = {
            "candidate": candidate.reference_id,
            "payload": payload,
            "window": ["2020-01-02", "2026-10-15"],
            "initial_cash": 100000,
            "one_way_cost": 0.001,
            "benchmark": bound.benchmark.to_dict(),
            "execution_requests": {k: asdict(v) for k, v in bound.execution_data.requests.items()},
            "execution_prepared": asdict(bound.execution_data.prepared),
            "execution_identities": bound.execution_data.input_identities,
            "execution_fingerprint": bound.execution_data.fingerprint,
            "input_bindings": {k: v.to_dict() for k, v in bound.input_bindings.items()},
        }
        old = read(
            ROOT
            / "research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json"
        )
        assert binding["execution_identities"] == old["original_execution_identities"], (
            "original execution contents differ"
        )
        assert binding["execution_fingerprint"] == old["original_execution_fingerprint"], (
            "original execution fingerprint differs"
        )
        original_binding = read(
            ROOT
            / old["formal_source_refs"]["ex023-others-binding_support_exit_reserve_H10-json"][
                "path"
            ]
        )
        a, b = (
            binding["input_bindings"]["full"]["plan"],
            original_binding["input_bindings"]["full"]["plan"],
        )
        assert {k: v for k, v in a.items() if k != "strategy"} == {
            k: v for k, v in b.items() if k != "strategy"
        }, "original strategy input/clock content differs"
        assert a["strategy"]["reference_id"] == candidate.reference_id
        binding_path = EX / f"others/bindings/{index:03}.json"
        write(binding_path, binding)
        binding_ref = publish_file(ctx, binding_path, f"ex042-binding-{index:03}")
        preflight = {
            "status": "PASS",
            "index": index,
            "public_prepare": "SUCCEEDED",
            "original_execution_identity_exact": True,
            "original_strategy_input_clock_plan_exact_except_runtime_identity": True,
            "source_lock": digest(EX / "protocols/execution_lock.json"),
            "binding_ref": binding_ref,
            "real_account_dispatched": False,
        }
        preflight_path = EX / f"others/preflight/{index:03}.json"
        write(preflight_path, preflight)
        preflight_ref = publish_file(ctx, preflight_path, f"ex042-preflight-{index:03}")
        print("PREPARED_AND_PREFLIGHT", index, row["mode"], flush=True)
    except Exception as exc:
        failure_path = EX / f"others/prepare_failures/{index:03}.json"
        write(
            failure_path,
            {"index": index, "mode": row["mode"], "error": repr(exc), "account_dispatched": False},
        )
        publish_file(ctx, failure_path, f"ex042-prepare-failure-{index:03}")
        raise
    dispatch_path = EX / f"others/dispatches/{index:03}.json"
    write(
        dispatch_path,
        {
            "index": index,
            "mode": row["mode"],
            "state": "DISPATCHED_COUNTS_EVEN_IF_UNKNOWN",
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "blind_retry_allowed": False,
        },
    )
    print("DISPATCH", index, row["mode"], flush=True)
    receipt = {
        "index": index,
        "mode": row["mode"],
        "parameters": row["parameters"],
        "candidate": candidate.reference_id,
        "payload_sha256": row["payload_sha256"],
        "published_payload_ref": row["payload_ref"],
        "runtime_implementation_sha256": lock["runtime_implementation_sha256"],
        "runtime_sha256": row["runtime_sha256"],
        "published_source_ref": read(EX / "protocols/published_sources.json")[
            "src/strategy_runtime/strategies/joint_action_review.py"
        ],
        "binding_ref": binding_ref,
        "preflight_ref": preflight_ref,
        "status": "UNKNOWN",
        "evidence": None,
        "result_hash": None,
        "audit": None,
    }
    try:
        outcomes = ctx.evaluation.evaluate_many((bound,))
        assert len(outcomes) == 1
        outcome = outcomes[0]
        receipt["status"] = outcome.status.value
        receipt["error"] = asdict(outcome.error) if outcome.error else None
        if outcome.result is not None:
            ref = publish_evidence(
                ctx,
                EvaluationEvidenceWrite(
                    ExperimentRef("S014", EX.name),
                    f"2025-action-{index:03}-{row['mode'].lower()}",
                    bound,
                    outcome.result,
                ),
            )
            receipt["evidence"] = ref.to_dict()
            receipt["result_hash"] = outcome.result.result_hash
            account = read(ref.resolve(ROOT))
            receipt["request_content_sha256"] = account["request_identity"]["content_sha256"]
            receipt["runtime_binding_hash"] = account["runtime_binding_hash"]
            receipt["audit"] = audit(
                account, row["mode"], row["parameters"]["entry_execution_date"]
            )
    except Exception as exc:
        receipt["exception"] = repr(exc)
    receipt_path = EX / f"others/accounts/run-{index:03}.json"
    write(receipt_path, receipt)
    publish_file(ctx, receipt_path, f"ex042-receipt-{index:03}")
    records = [read(p) for p in sorted((EX / "others/accounts").glob("run-*.json"))]
    snapshot = EX / f"others/accounts_index-{index:03}.json"
    write(
        snapshot,
        {
            "records": records,
            "dispatched_count": len(records),
            "external_calls": 0,
            "formal_registered_candidates": 0,
        },
    )
    snapshot_ref = publish_file(ctx, snapshot, f"ex042-accounts-index-{index:03}")
    # Editable aggregation points only to immutable per-run receipts/snapshots.
    (EX / "others/accounts_index.json").write_bytes(snapshot.read_bytes())
    (EX / "others/accounts_index_ref.json").write_text(
        json.dumps(snapshot_ref, indent=2) + "\n", encoding="utf-8"
    )
    print("ACCOUNT", index, receipt["status"], receipt["audit"], flush=True)
    assert (
        receipt["status"] == "SUCCEEDED"
        and receipt["audit"]
        and receipt["audit"]["status"] == "PASS"
    ), "Stop all dependent evaluations on technical/control failure"
    gate_path = EX / (
        "others/gate_control.json"
        if index == 0
        else "others/gate_joint.json"
        if index == 1
        else "others/gate_unused.json"
    )
    write(
        gate_path,
        {
            "status": "PASS",
            "index": index,
            "account_ref": receipt["evidence"],
            "source_lock_sha256": digest(EX / "protocols/execution_lock.json"),
        },
    )
    publish_file(ctx, gate_path, f"ex042-gate-{index:03}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("build", "control", "joint"))
    args = parser.parse_args()
    if args.phase == "build":
        build()
    else:
        execute({"control": 0, "joint": 1}[args.phase])
