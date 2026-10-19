"""Public pinned-input preparations and sequential fixed-node account diagnostics."""

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import socket

import requests
from czsc_trader.application import publish_evidence, create_research_context, RepositoryContext
from dataflows import ProviderConfig
from czsc_trader.research_tools import (
    ResearchBatchRef,
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
METHOD = ROOT / "research/S014/materials/20261020_2026_diagnosis"
FILES = ("strategies/loss_interaction_review.py",)
UPSTREAM = ('authorization', 'method', 'baseline_integrity', 'method_inventory', 'source_bindings', 'independent_method_review', 'method_evidence_gate', 'evaluation_protocol', 'observability_review', 'independent_source_review', 'account_attribution', 'exit_attribution', 'diagnosis_delivery', 'previous_source', 'previous_lock', 'previous_control_receipt', 'previous_final_verification', 'corrected_audit_source', 'fixture_source', 'helper_source', 'shared_account_audit', 'input_provider_source')

sys.path.append(str(EX.parent / "EX017_20261017/src"))
from pinned_inputs import get_context  # noqa: E402


def no_network(*args, **kwargs):
    raise RuntimeError("EX048 uses authenticated S014 pinned offline data only")


requests.sessions.Session.request = no_network
socket.socket.connect = no_network
socket.create_connection = no_network


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


def publication_context():
    return create_research_context(
        RepositoryContext.discover(ROOT), ResearchBatchRef("S014"),
        resources=EvaluationResources(max_workers=2, native_threads_per_worker=1, random_seed=17),
        providers=ProviderConfig(bindings={}),
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
    for field in UPSTREAM:
        assert digest(ROOT / design[field]["path"]) == design[field]["sha256"]
    precheck = read(EX / "others/synthetic_precheck.json")
    assert precheck["status"] == "PASS_PURE_SYNTHETIC_ONLY" and precheck["checks_count"] == 87
    assert precheck["actual_SRT_observation_materializations"] == 666
    prefix_precheck = read(EX / "others/audit_prefix_precheck.json")
    assert prefix_precheck["status"] == "PASS_PURE_SYNTHETIC_ONLY"
    assert prefix_precheck["checks_count"] == 7
    assert digest(EX / "src/audit_accounts.py") == prefix_precheck["audit_source_sha256"]
    assert digest(PACKAGE / FILES[0]) == precheck["source_sha256"]
    assert digest(EX / "src/precheck.py") == precheck["precheck_source_sha256"]
    assert (
        digest(
            ROOT
            / "research/S014/experiments/EX047_20261020/src/strategy_runtime/strategies/shock_action_review.py"
        )
        == precheck["previous_source_sha256"]
    )
    ctx = publication_context()
    source_hash = implementation_sha256(FILES, source_root=PACKAGE)
    rows = []
    for i, params in enumerate(design["fixed_parameters"]):
        cid = f"C{9480 + i:04}"
        assert not (ROOT / "research/S014/assets/candidates" / cid).exists()
        payload = {
            "runtime": {
                "module": "strategy_runtime.strategies.loss_interaction_review",
                "qualname": "LossInteractionStrategy",
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
                "mode": params["pause_profile"],
                "parameters": params,
                "candidate": candidate.reference_id,
                "runtime_sha256": description.runtime_sha256,
                "payload_sha256": digest(path),
                "payload_ref": publish_file(ctx, path, f"ex048-payload-{i:03}"),
            }
        )
    paths = [
        EX / "protocols/design.json",
        EX / "others/synthetic_precheck.json",
        EX / "others/audit_prefix_precheck.json",
        *sorted((EX / "src").rglob("*.py")),
    ]
    published = {
        p.relative_to(EX).as_posix(): publish_file(
            ctx, p, "ex048-locked-" + p.relative_to(EX).as_posix().replace("/", "-")
        )
        for p in paths
    }
    for name in UPSTREAM:
        path = ROOT / design[name]["path"]
        published[name] = publish_file(ctx, path, "ex048-upstream-" + name)
    write(EX / "protocols/published_sources.json", published)
    lock = {
        "status": "LOCKED_BEFORE_ACCOUNTS",
        "revision": 1,
        "planned_account_count": 2,
        "user_account_numeric_cap": None,
        "no_automatic_blind_retries": True,
        "runtime_implementation_sha256": source_hash,
        "source_hashes": {p.relative_to(EX).as_posix(): digest(p) for p in paths},
        "external_source_hashes": {design[k]["path"]: design[k]["sha256"] for k in UPSTREAM},
        "runs": rows,
        "published_sources_sha256": digest(EX / "protocols/published_sources.json"),
        "economic_complete_years": list(range(2020, 2026)),
        "2026_role": "Original partial-year economic acceptance through 2026-10-15, not annualized; all seven original annual goals retained",
    }
    write(EX / "protocols/execution_lock.json", lock)
    write(
        EX / "protocols/published_lock.json",
        publish_file(ctx, EX / "protocols/execution_lock.json", "ex048-execution-lock-v1"),
    )
    print("LOCKED_AND_PUBLIC 2 fixed diagnostic identities", flush=True)


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
    source_review = read(EX / "others/gate_source_review.json")
    assert source_review["status"] == "PASS"
    assert source_review["source_lock_sha256"] == digest(EX / "protocols/execution_lock.json")
    source_ref = EvidenceRef.from_dict(source_review["review_ref"])
    assert digest(source_ref.resolve(ROOT)) == source_ref.sha256
    if index:
        assert read(EX / "others/gate_control.json")["status"] == "PASS"
        independent = read(EX / "others/gate_control_independent.json")
        assert independent["status"] == "PASS"
        assert independent["source_lock_sha256"] == digest(EX / "protocols/execution_lock.json")
        assert independent["account_ref"] == read(EX / "others/accounts/run-000.json")["evidence"]
        review_ref = EvidenceRef.from_dict(independent["review_ref"])
        assert digest(review_ref.resolve(ROOT)) == review_ref.sha256
        for previous in range(1, index):
            assert read(EX / f"others/gates/arm-{previous:03}.json")["status"] == "PASS"
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
        binding_ref = publish_file(ctx, binding_path, f"ex048-binding-{index:03}")
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
        preflight_ref = publish_file(ctx, preflight_path, f"ex048-preflight-{index:03}")
        print("PREPARED_AND_PREFLIGHT", index, row["mode"], flush=True)
    except Exception as exc:
        failure_path = EX / f"others/prepare_failures/{index:03}.json"
        write(
            failure_path,
            {"index": index, "mode": row["mode"], "error": repr(exc), "account_dispatched": False},
        )
        publish_file(ctx, failure_path, f"ex048-prepare-failure-{index:03}")
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
        "execution_source_lock_ref": read(EX / "protocols/published_lock.json"),
        "execution_source_lock_sha256": digest(EX / "protocols/execution_lock.json"),
        "runtime_sha256": row["runtime_sha256"],
        "published_source_ref": read(EX / "protocols/published_sources.json")[
            "src/strategy_runtime/strategies/loss_interaction_review.py"
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
                    f"loss-interaction-{index:03}-{row['mode'].lower().replace('/', '-')}",
                    bound,
                    outcome.result,
                ),
            )
            receipt["evidence"] = ref.to_dict()
            receipt["result_hash"] = outcome.result.result_hash
            account = read(ref.resolve(ROOT))
            receipt["request_content_sha256"] = account["request_identity"]["content_sha256"]
            receipt["runtime_binding_hash"] = account["runtime_binding_hash"]
            receipt["audit"] = audit(account, row["parameters"])
    except Exception as exc:
        receipt["exception"] = repr(exc)
    receipt_path = EX / f"others/accounts/run-{index:03}.json"
    write(receipt_path, receipt)
    publish_file(ctx, receipt_path, f"ex048-receipt-{index:03}")
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
    snapshot_ref = publish_file(ctx, snapshot, f"ex048-accounts-index-{index:03}")
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
        "others/gate_control.json" if index == 0 else f"others/gates/arm-{index:03}.json"
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
    publish_file(ctx, gate_path, f"ex048-gate-{index:03}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("build", "control", "batch"))
    args = parser.parse_args()
    if args.phase == "build":
        build()
    elif args.phase == "control":
        execute(0)
    else:
        for index in range(1, 2):
            execute(index)
