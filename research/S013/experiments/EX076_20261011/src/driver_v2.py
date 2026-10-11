"""Two explicit read-only phases: authenticate old inputs, then one fixed study.

No provider/context/prepare/evaluate/publication API is used. Source preparation
does not authorize either real-input phase. Root binds a public prospective method.
"""

import argparse
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT = "S013_CURVATURE4_SINGLE_STATISTICS_FIXED"
REFERENCE_SCHEMA = {
    "old66_features": ("EX066_20261011", "text/csv", None),
    "old66_labels": ("EX066_20261011", "text/csv", None),
    "original_prices": ("EX066_20261011", "text/csv", None),
    "old61_features": ("EX061_20261011", "text/csv", None),
    "old69_features": ("EX069_20261011", "text/csv", None),
    "warm69_prices": ("EX069_20261011", "text/csv", None),
    "native_ref": ("EX058_20261011", "application/json", "account_evaluation"),
}


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def public(reference):
    from czsc_trader.research_tools.evidence import EvidenceRef

    ref = EvidenceRef.from_dict(reference)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("only S013 public evidence allowed")
    path = ref.resolve(ROOT)
    if digest(path) != reference["sha256"]:
        raise ValueError("immutable public evidence changed")
    return path


def reference_schema(references):
    if set(references) != set(REFERENCE_SCHEMA):
        raise ValueError("exact seven old immutable input references required")
    for key, (experiment, media, schema) in REFERENCE_SCHEMA.items():
        ref = references[key]
        if (ref.get("type") != "EvidenceRef" or ref.get("experiment") != {
                "type": "ExperimentRef", "strategy_id": "S013", "experiment_id": experiment}
                or ref.get("media_type") != media or ref.get("schema") != schema
                or ref.get("schema_version") != (6 if key == "native_ref" else None)):
            raise ValueError("fixed old input reference schema required: " + key)
        h = ref.get("sha256")
        if (not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
                or ref.get("evidence_id") != h + (".json" if key == "native_ref" else ".csv")):
            raise ValueError("canonical exact evidence identity required")


def continuation_schema(record, attempt, failure, original_method, method):
    """Original failed attempt is an immutable cause, never a fallback input."""
    if (attempt != record["original_attempt_content"]
            or failure != record["original_failure_content"]
            or attempt["method_reference"] != record["original_method_reference"]
            or failure["status"] != "FAILED_PRESERVED_NO_RETRY"
            or failure["error_type"] != "ValueError"
            or failure["error"] != "full original1636 N0 decision prefix required"
            or failure["provider_calls"] != 0 or failure["new_accounts"] != 0
            or original_method["source_freeze_sha256"] != record["original_execution_freeze_sha256"]
            or method["input_references"] != original_method["input_references"]
            or method["native_cache"] != original_method["native_cache"]):
        raise ValueError("exact original failed attempt/method/inputs required for technical continuation")


def authority(args):
    freeze_path = HERE / "execution_freeze_v2.json"
    if digest(freeze_path) != args.source_freeze_sha256:
        raise ValueError("root exact execution freeze binding required")
    freeze = read(freeze_path)
    for name, h in freeze["source_files"].items():
        if Path(name).name != name or digest(HERE / name) != h:
            raise ValueError("frozen source/prospective file drift")
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        if os.environ.get(name) != "1":
            raise ValueError("all four native numeric thread limits must equal1 before process launch")
    reference = read(args.method_reference)
    if reference.get("media_type") != "application/json":
        raise ValueError("public method JSON reference required")
    method = read(public(reference))
    if (method.get("status") != "PROSPECTIVE_DECLARED" or method.get("execution_contract") != CONTRACT
            or method.get("source_freeze_sha256") != args.source_freeze_sha256
            or method.get("source_files") != freeze["source_files"]):
        raise ValueError("exact public prospective method/source binding required")
    record = freeze["technical_continuation"]
    if method.get("technical_continuation") != record:
        raise ValueError("public explicit prospective technical correction binding required")
    for name in ("original_attempt", "original_failure"):
        item = record[name]
        expected_path = ".tmp/s013-cross-day-curvature/actual/authentication_" + ("attempt" if name == "original_attempt" else "failure") + ".json"
        if item["path"] != expected_path or digest(ROOT/item["path"]) != item["sha256"]:
            raise ValueError("original attempt/failure must remain exact and preserved")
    if digest(HERE/"execution_freeze.json") != record["original_execution_freeze_sha256"]:
        raise ValueError("original frozen source manifest changed")
    original_method = read(public(record["original_method_reference"]))
    continuation_schema(record, read(ROOT/record["original_attempt"]["path"]),
                        read(ROOT/record["original_failure"]["path"]), original_method, method)
    reference_schema(method["input_references"])
    cache = method["native_cache"]
    if (cache.get("path") != ".tmp/s013-mechanism-EX058/N0.pkl.gz"
            or cache.get("common_path") != "research/S013/experiments/EX058_20261011/src/common.py"
            or digest(ROOT / cache["path"]) != cache["sha256"]
            or digest(ROOT / cache["common_path"]) != cache["common_sha256"]):
        raise ValueError("original immutable N0 cache/common source required")
    work = Path(args.work).resolve()
    if not work.is_relative_to(ROOT / ".tmp"):
        raise ValueError("temporary work must stay inside repository .tmp")
    if work == (ROOT/".tmp/s013-cross-day-curvature/actual").resolve():
        raise ValueError("v2 technical continuation requires a new work directory; original failure remains")
    work.mkdir(parents=True, exist_ok=True)
    return method, reference, work


def frame(path, *, price=False, ends=False):
    import pandas as pd
    from input_authentication_v2 import exact_datetime, PRICE_COLUMNS

    result = pd.read_csv(path, index_col="signal_date", float_precision="round_trip",
                         dtype={n: "float64" for n in PRICE_COLUMNS} if price else None)
    result.index = exact_datetime(pd.to_datetime(result.index, errors="raise"))
    result.index.name = "signal_date"
    if ends:
        for name in result.columns:
            if name.startswith("label_end"):
                result[name] = pd.to_datetime(result[name], errors="raise").dt.as_unit("ns")
    return result


def authenticate(method, method_reference, work):
    if (work / "authentication_attempt.json").exists():
        raise ValueError("one authentication attempt only; preserve failures, no automatic retry")
    write_new(work / "authentication_attempt.json", {"status": "STARTED",
              "method_reference": method_reference, "new_accounts": 0, "provider_calls": 0})
    try:
        import input_authentication_v2 as adapter
        from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

        common_path = ROOT / method["native_cache"]["common_path"]
        if "common" in sys.modules and Path(sys.modules["common"].__file__).resolve() != common_path.resolve():
            raise ValueError("different original pickle reducer module already loaded")
        sys.path.insert(0, str(common_path.parent))
        common = importlib.import_module("common")
        bound, result = common.cache_read(ROOT / method["native_cache"]["path"])
        references = method["input_references"]
        paths = {name: public(ref) for name, ref in references.items()}
        if serialize_evaluation_evidence(bound, result) != read(paths["native_ref"]):
            raise ValueError("complete original cached request/result must equal original public evidence")
        if bound.strategy.candidate_id != "C8880" or bound.symbol != "510500.SH":
            raise ValueError("only exact original C8880/510500 permitted")
        ed = bound.execution_data
        features, labels, flat, sessions, proof = adapter.construct(
            frame(paths["old66_features"]), frame(paths["old61_features"]),
            frame(paths["old69_features"]), frame(paths["warm69_prices"]),
            frame(paths["original_prices"], price=True), frame(paths["old66_labels"], ends=True),
            ed.execution_daily, ed.evaluation_sessions, result.runs[0].execution.decisions, ed.pricing.to_dict())
        if common.SOURCE_CALLS:
            raise ValueError("source provider must never be invoked")
        outputs = {"features.csv": features, "labels.csv": labels,
                   "flat_eligible.csv": flat.to_frame(), "price_calendar.csv": features.iloc[:0, :0].reindex(sessions)}
        for name, value in outputs.items():
            with (work / name).open("x", encoding="utf-8", newline="\n") as stream:
                value.to_csv(stream, index_label="signal_date", float_format="%.17g")
        proof.update(method_reference=method_reference, input_references=references,
                     native_cache=method["native_cache"], source_files=method["source_files"],
                     output_sha256={name: digest(work/name) for name in outputs})
        write_new(work / "authentication.json", proof)
        return proof
    except Exception as exc:
        write_new(work / "authentication_failure.json", {"status": "FAILED_PRESERVED_NO_RETRY",
                  "error_type": type(exc).__name__, "error": str(exc), "new_accounts": 0, "provider_calls": 0})
        raise


def study(method, method_reference, work):
    proof = read(work / "authentication.json")
    if (proof["status"] != "PASS" or proof["method_reference"] != method_reference
            or proof["input_references"] != method["input_references"]
            or proof["native_cache"] != method["native_cache"]
            or proof["source_files"] != method["source_files"]):
        raise ValueError("complete exact prior authentication required")
    for name, h in proof["output_sha256"].items():
        if Path(name).name != name or digest(work / name) != h:
            raise ValueError("authenticated in-memory inputs changed")
    if (work / "study_attempt.json").exists():
        raise ValueError("one real statistics call only; preserve failure, no automatic retry")
    write_new(work / "study_attempt.json", {"status": "STARTED", "authentication_sha256": digest(work/"authentication.json"),
              "method_reference": method_reference, "new_accounts": 0, "provider_calls": 0})
    try:
        import curvature_statistics as statistics
        from reading import summarize
        features, labels = frame(work/"features.csv"), frame(work/"labels.csv", ends=True)
        scope = frame(work/"flat_eligible.csv").iloc[:, 0]
        calendar = frame(work/"price_calendar.csv").index
        outcome = statistics.analyze(features, labels, calendar, flat_eligible=scope)
        write_new(work/"statistics.json", outcome)
        write_new(work/"reading.json", summarize(outcome))
        write_new(work/"study_completed.json", {"status": "COMPLETE", "analyze_calls": 1,
                  "statistics_sha256": digest(work/"statistics.json"), "reading_sha256": digest(work/"reading.json"),
                  "new_accounts": 0, "provider_calls": 0})
    except Exception as exc:
        write_new(work/"study_failure.json", {"status": "FAILED_PRESERVED_NO_RETRY",
                  "error_type": type(exc).__name__, "error": str(exc), "new_accounts": 0, "provider_calls": 0})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("authenticate", "study"))
    parser.add_argument("--method-reference", required=True)
    parser.add_argument("--source-freeze-sha256", required=True)
    parser.add_argument("--work", required=True)
    args = parser.parse_args()
    method, reference, work = authority(args)
    if args.phase == "authenticate":
        authenticate(method, reference, work)
    else:
        study(method, reference, work)


if __name__ == "__main__":
    main()
