"""Separately authorized arithmetic verification only; import performs no I/O."""

from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def require_contract(authorization, actual_hashes):
    if (
        authorization.get("status") != "APPROVED"
        or authorization.get("phase") != "verification"
        or authorization.get("expected_experiment_id") != "EX075_20261011"
    ):
        raise PermissionError("new exact root EX075 verification authority required")
    for name in (
        "wrapper_freeze_sha256",
        "independent_freeze_sha256",
        "input_references_sha256",
        "result_references_sha256",
        "statistics_authority_sha256",
        "preflight_freeze_sha256",
    ):
        value = authorization.get(name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            or value != actual_hashes.get(name)
        ):
            raise PermissionError("verification exact binding mismatch: " + name)


def source_guard(work, filename):
    freeze = read(work / filename)
    for name, expected in freeze["source_files"].items():
        if Path(name).name != name or digest(work / name) != expected:
            raise ValueError("frozen verification/input source mismatch: " + name)
    return freeze


def authority():
    work = Path(__file__).resolve().parent
    authorization = read(work / "root_verification_authorization.json")
    hashes = dict(
        wrapper_freeze_sha256=digest(work / "actual_verification_source_freeze.json"),
        independent_freeze_sha256=digest(work / "independent_verification_source_freeze.json"),
        input_references_sha256=digest(work / "input_references.json"),
        result_references_sha256=digest(work / "result_references.json"),
        statistics_authority_sha256=digest(work / "root_statistics_authorization_v4.json"),
        preflight_freeze_sha256=digest(work / "source_freeze_v7.json"),
    )
    require_contract(authorization, hashes)
    source_guard(work, "actual_verification_source_freeze.json")
    independent = source_guard(work, "independent_verification_source_freeze.json")
    original = source_guard(work, "source_freeze_v4.json")
    active = source_guard(work, "source_freeze_v7.json")
    if (
        hashes["independent_freeze_sha256"]
        != "f9bd830c53725ac23a416c9eb0942b85d480e56a7022751144abd8270b1148a0"
        or independent["original_freeze_sha256"] != digest(work / "source_freeze_v4.json")
        or independent["statistics_source_sha256"]
        != original["source_files"]["statistics_draft_v2.py"]
    ):
        raise ValueError("original independent arithmetic source lineage changed")
    root = next(p for p in work.resolve().parents if (p / "pyproject.toml").exists())
    if digest(root / active["common_path"]) != active["common_sha256"]:
        raise ValueError("original cache/helper source changed")
    if read(work / "experiment.json")["experiment_id"] != "EX075_20261011":
        raise ValueError("exact declared experiment required")
    return work, root, hashes, active


def public(root, value):
    from czsc_trader.research_tools.evidence import EvidenceRef

    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013 evidence only")
    path = ref.resolve(root)
    if digest(path) != value["sha256"]:
        raise ValueError("public evidence byte hash mismatch")
    return path


def put(ctx, exp, path):
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite

    path = Path(path)
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp,
            path.stem.replace("_", "-"),
            path.read_bytes(),
            "text/x-python" if path.suffix == ".py" else "application/json",
            path.suffix[1:],
        ),
    ).to_dict()


def verify():
    work, root, hashes, active = authority()
    if (work / "verification_attempt.json").exists():
        raise ValueError("one authorized verification attempt; retain all failures")
    write_new(
        work / "verification_attempt.json",
        dict(
            utc=datetime.now(timezone.utc).isoformat(),
            accounts=0,
            authority_sha256=digest(work / "root_verification_authorization.json"),
            exact_bindings=hashes,
        ),
    )
    # No market input is loaded before independent authority and attempt record.
    from czsc_trader.research_tools.context import ExperimentRef
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
    import pandas as pd
    import independent_verification_draft_v2 as checker

    source = root / active["common_path"]
    if (
        "common" in sys.modules
        and Path(sys.modules["common"].__file__).resolve() != source.resolve()
    ):
        raise ValueError("different cache common module already imported")
    sys.path.insert(0, str(source.parent))
    common = importlib.import_module("common")
    inputs = read(work / "input_references.json")
    results = read(work / "result_references.json")
    for name, ref in inputs.items():
        if results.get(name) != ref:
            raise ValueError("statistics must retain exact authenticated input ref: " + name)
        public(root, ref)
    for ref in results.values():
        public(root, ref)
    checks = read(public(root, inputs["input_checks.json"]))
    if (
        checks.get("status") != "PASS"
        or checks.get("provider_calls") != 0
        or checks.get("accounts") != 0
    ):
        raise ValueError("successful zero-provider/zero-account public preflight required")
    if (
        results["root_statistics_authorization_v4.json"]["sha256"]
        != hashes["statistics_authority_sha256"]
    ):
        raise ValueError("public original statistics authority binding mismatch")
    bindings = read(work / "input_bindings_draft.json")
    if checks["input_bindings"] != bindings:
        raise ValueError("original input lineage changed")
    bound, cached = common.cache_read(common.CACHE / "N0.pkl.gz")
    if serialize_evaluation_evidence(bound, cached) != read(public(root, bindings["native_ref"])):
        raise ValueError("original native cache must equal public account serialization")
    if common.SOURCE_CALLS:
        raise ValueError("provider calls forbidden")

    def frame(name):
        value = pd.read_csv(
            public(root, inputs[name]), index_col="signal_date", float_precision="round_trip"
        )
        value.index = pd.to_datetime(value.index).as_unit("ns")
        return value

    features, labels = frame("features.csv"), frame("labels.csv")
    labels["label_end4"] = pd.to_datetime(labels["label_end4"])
    outcome = checker.verify_statistics(
        features,
        labels,
        frame("price_calendar.csv").index,
        read(public(root, results["statistics.json"])),
    )
    if common.SOURCE_CALLS:
        raise ValueError("provider calls forbidden")
    outcome.update(
        experiment=read(work / "experiment.json"),
        input_references=inputs,
        result_references=results,
        authority_sha256=digest(work / "root_verification_authorization.json"),
        exact_bindings=hashes,
        cache_serialized_public_native_exact=True,
        original_native_reference=bindings["native_ref"],
        provider_calls=0,
    )
    write_new(work / "verification.json", outcome)
    exp = ExperimentRef.from_dict(read(work / "experiment.json"))
    names = list(read(work / "independent_verification_source_freeze.json")["source_files"])
    names += list(read(work / "actual_verification_source_freeze.json")["source_files"])
    names += [
        "independent_verification_source_freeze.json",
        "actual_verification_source_freeze.json",
        "root_verification_authorization.json",
        "verification_attempt.json",
        "verification.json",
    ]
    refs = {}
    with (work / "verification_publication_progress.jsonl").open("x", encoding="utf-8"):
        pass
    for name in dict.fromkeys(names):
        refs[name] = put(common.context(1), exp, work / name)
        with (work / "verification_publication_progress.jsonl").open(
            "a", encoding="utf-8"
        ) as progress:
            progress.write(
                json.dumps(dict(name=name, reference=refs[name]), ensure_ascii=False) + "\n"
            )
        if name.endswith(".py"):
            with (exp.resolve(root) / "src" / name).open("xb") as f:
                f.write((work / name).read_bytes())
    write_new(work / "verification_references.json", refs)
    write_new(exp.resolve(root) / "protocols/verification_references.json", refs)


if __name__ == "__main__":
    verify()
