"""Verify public EX039 input lineage and assemble fixed offline model rows.

precheck is synthetic. assemble only fetches existing PreparedDataRef assets;
it never prepares data, calls a source, fits a model, or changes locked files.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
from io import StringIO
import json
from pathlib import Path
import socket
from uuid import UUID

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
ETF = ["etf_z", "etf_z_late", "etf_price_ret1", "etf_price_ret5", "etf_ready"]
OPTION = ["opt_ret1", "opt_rv20", "opt_vol_ratio", "opt_log_oi", "opt_log_volume", "opt_share_Q", "opt_dte", "opt_delta_put", "opt_ready", "opt_roll", "opt_active_pair"]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def relative(path):
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def local(name):
    value = Path(name)
    if value.is_absolute():
        raise ValueError("Lineage paths must be repository relative")
    result = (ROOT / value).resolve()
    if not result.is_relative_to(EX.resolve()):
        raise ValueError("EX039 lineage path outside authorized experiment")
    return result


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def offline():
    def blocked(*args, **kwargs):
        raise RuntimeError("EX039 input assembly forbids network/source calls")
    socket.socket.connect = blocked
    socket.create_connection = blocked


def verify_lock(path, required, unwrap_evidence=False):
    """Original and repair maps are additive graphs; never overlay originals."""
    from czsc_trader.research_tools import EvidenceRef

    lock = read(path)
    if unwrap_evidence:
        lock = lock["evidence"]
    if not isinstance(lock, dict) or not lock or required not in lock:
        raise ValueError("Published lock must be nonempty and contain required source")
    checked = {}
    for name, value in lock.items():
        current = local(name)
        ref = EvidenceRef.from_dict(value)
        if ref.experiment.strategy_id != "S014" or ref.experiment.experiment_id != "EX039_20261019":
            raise ValueError("Published lock reference belongs to another experiment")
        evidence = ref.resolve(ROOT)
        if digest(evidence) != ref.sha256 or current.read_bytes() != evidence.read_bytes():
            raise ValueError("Published current/evidence bytes mismatch: " + name)
        checked[name] = {"reference": value, "sha256": ref.sha256, "bytes": current.stat().st_size}
    return {"path": relative(path), "sha256": digest(path), "checked": checked}


def original_source(name):
    from czsc_trader.research_tools import EvidenceRef

    old = ROOT / "research/S014/experiments/EX032_20261018"
    value = read(old / "others/result.json")["evidence"]["others/" + name]
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S014" or ref.experiment.experiment_id != "EX032_20261018":
        raise ValueError("Original input reference identity mismatch")
    evidence = ref.resolve(ROOT)
    source = old / "others" / name
    if digest(evidence) != ref.sha256 or source.read_bytes() != evidence.read_bytes():
        raise ValueError("Immutable original/evidence bytes mismatch: " + name)
    return source, value


def normalized(frame):
    result = frame.copy()
    if "Date" in result:
        if "date" in result:
            raise ValueError("Ambiguous Date/date columns")
        result = result.rename(columns={"Date": "date"})
    if "date" not in result:
        raise ValueError("Missing date key")
    result["date"] = pd.to_datetime(result.date, errors="raise").dt.normalize()
    if result.date.isna().any() or result.date.duplicated().any():
        raise ValueError("Missing or duplicate feature date")
    return result.sort_values("date", kind="stable").reset_index(drop=True)


def csv_representation(frame):
    return pd.read_csv(StringIO(frame.to_csv(index=False)))


def same_frame(actual, expected, label):
    a, b = normalized(csv_representation(actual)), normalized(csv_representation(expected))
    if set(a.columns) != set(b.columns):
        raise ValueError(label + ": column set mismatch")
    pd.testing.assert_frame_equal(a[b.columns], b, check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12, obj=label)


def bool_values(series, label):
    out = series.astype("string").str.lower().map({"true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False})
    if (series.notna() & out.isna()).any():
        raise ValueError(label + ": invalid boolean")
    return out.astype("boolean")


def merge_frames(original, etf, option):
    base, e, o = normalized(original), normalized(etf), normalized(option)
    parent = base[bool_values(base.A, "A").fillna(False)].reset_index(drop=True)
    for label, other, expected in (("ETF", e, base), ("OPTION", o, parent)):
        if not other.date.equals(expected.date):
            raise ValueError(label + " features must contain exactly its inherited full/A-only date grid")
        shared = [name for name in base if name in other]
        same_frame(other[shared], expected[shared], label + " inherited fields")
    if not set(ETF).issubset(e) or not set(OPTION).issubset(o):
        raise ValueError("Missing fixed analysis feature/quality columns")
    if set(e).intersection(o).difference(base.columns):
        raise ValueError("Unexpected overlapping external feature columns")
    output = base.merge(e[["date"] + [c for c in e if c not in base]], on="date", how="left", validate="one_to_one")
    output = output.merge(o[["date"] + [c for c in o if c not in base]], on="date", how="left", validate="one_to_one")
    pd.testing.assert_frame_equal(output[list(base.columns)], base, check_dtype=False, check_exact=True, obj="exact original merged values")
    same_frame(output[list(base.columns)], base, "all original columns after merge")
    # No fill, selection, imputation, or readiness rewrite is performed.
    parent_mask = bool_values(output.A, "A").fillna(False)
    same_frame(output.loc[parent_mask, ["date", *OPTION]], o[["date", *OPTION]], "all parent option values and missingness after merge")
    if output.loc[~parent_mask, [c for c in o if c not in base]].notna().any().any():
        raise ValueError("Non-A option fields must stay missing after left join")
    for c in ["A", "entry_filled", "etf_ready", "opt_ready", "opt_roll", "opt_active_pair"]:
        bool_values(output[c], c)
    return output


def verify_pointer_item(item):
    path = local(item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError("Pointer item hash mismatch: " + item["path"])
    return {"path": item["path"], "sha256": item["sha256"]}


def prepared_ref(value):
    from dataflows import PreparedDataRef
    return PreparedDataRef(UUID(value["space_id"]), UUID(value["preparation_id"]), value["manifest_sha256"])


def fetch_ready(ctx, request, reference, expected_identity=None):
    result = ctx.data.fetch(request, prepared=prepared_ref(reference))
    if not result.ready or result.identity.dataset != request.dataset or result.identity.symbol != request.symbol:
        raise ValueError("Formal public fetch failed or returned different dataset/symbol")
    identity = result.identity
    if expected_identity:
        if identity.content_sha256 != expected_identity["content_sha256"] or identity.symbol != expected_identity["symbol"] or getattr(identity.dataset, "value", identity.dataset) != expected_identity["dataset"]:
            raise ValueError("Formal fetch identity differs from feature lineage")
    return result, {"dataset": getattr(identity.dataset, "value", identity.dataset), "symbol": identity.symbol, "content_sha256": identity.content_sha256, "prepared": reference}


def verify_features(original, calendar, out, repair):
    from czsc_trader.application import RepositoryContext, create_research_context
    from czsc_trader.research_tools import ResearchBatchRef
    from dataflows import DataRequest, Dataset, EvidenceParameters

    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"))
    ep = read(out / "etf_successful_preparation.json")
    em = read(out / "etf_features.json")
    if ep["status"] != "READY_CONDITIONAL_RAW_PROXY" or ep["reference"] != ep["prepared"] or ep["reference"] != em["prepared"]:
        raise ValueError("ETF successful preparation reference mismatch")
    if ep["repair_lock"]["sha256"] != repair["sha256"] or ep["repair_lock"]["references"] != read(local(repair["path"])):
        raise ValueError("ETF successful preparation repair graph mismatch")
    pointer_checks = {name: verify_pointer_item(ep[name]) for name in ("preparation", "source_receipt", "implementation", "repair_lock")}
    prep = read(local(ep["preparation"]["path"]))
    if prep["status"] != "READY" or prep["reference"] != ep["reference"] or ep["requests"] != em["requests"]:
        raise ValueError("ETF READY preparation/feature requests mismatch")
    for item in ep["verified_canonical_copies"]:
        source, target = local(item["source"]), local(item["target"])
        if source.read_bytes() != target.read_bytes() or digest(target) != item["sha256"] or target.stat().st_size != item["bytes"]:
            raise ValueError("ETF repaired canonical copy mismatch")
    for name, expected in ep["original_attempt_preserved"].items():
        if digest(out / name) != expected:
            raise ValueError("ETF original failed attempt changed")
    etf_source, etf_lineage = {}, {}
    requests = [DataRequest(Dataset.ETF_SHARE_SIZE, "510300.SH", "2020-01-01", "2026-10-15", "2026-10-15"), DataRequest(Dataset.ETF_UNADJUSTED_DAILY, "510300.SH", "2020-01-01", "2026-10-15", "2026-10-15")]
    for name, request in zip(("share", "price"), requests, strict=True):
        fetched, etf_lineage[name] = fetch_ready(ctx, request, ep["reference"], em["source_identities"][name])
        path = out / f"etf_{name}_source.csv"
        if digest(path) != em["source_csv_sha256"][name]:
            raise ValueError("ETF source CSV hash mismatch")
        same_frame(pd.read_csv(path), fetched.dataframe, "ETF public " + name)
        etf_source[name] = fetched
    feature_path = out / "etf_features.csv"
    if digest(feature_path) != em["features_csv_sha256"] or digest(out / "etf_combined_source.csv") != em["combined_source_csv_sha256"]:
        raise ValueError("ETF feature/combined source hash mismatch")
    spec = importlib.util.spec_from_file_location("ex039_verified_etf", EX / "src/prepare_etf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    combined, assumptions = module.combine_sources(etf_source["share"].dataframe, etf_source["price"].dataframe, calendar, etf_source["share"].identity.metadata, etf_source["price"].identity.metadata)
    combined["AvailableDate"] = combined.ShareAvailableDate
    same_frame(pd.read_csv(out / "etf_combined_source.csv"), combined, "ETF combined public sources")
    events = read(out / "etf_events.json")
    if digest(out / "etf_events.json") != em["event_identity"]["sha256"] or events != em["event_content"] or assumptions != em["availability_assumptions"]:
        raise ValueError("ETF event/availability lineage mismatch")
    rebuilt, _ = module.build_features(original, calendar, combined, events, read(EX / "protocols/design.json")["etf_columns"])
    etf = pd.read_csv(feature_path)
    same_frame(etf, rebuilt, "ETF rebuilt features")
    om, op = read(out / "option_inputs.json"), read(out / "option_prepared.json")
    option_path = out / "option_features.csv"
    option_hash = digest(option_path)
    if op["status"] != "READY" or option_hash != om["feature_sha256"] or option_hash != op["source_sha256"]:
        raise ValueError("Option feature/preparation source hash mismatch")
    if om["inherited_inputs_sha256"] != digest(ROOT / "research/S014/experiments/EX032_20261018/others/inputs.csv"):
        raise ValueError("Option inherited input hash mismatch")
    sourcehashes = read(out / "option_sourcehashes.json")
    verify_pointer_item(sourcehashes["implementation"])
    for item in sourcehashes["inherited"]:
        name = Path(item["path"])
        path = (ROOT / name).resolve()
        allowed = ROOT / "research/S014"
        if name.is_absolute() or not path.is_relative_to(allowed.resolve()) or digest(path) != item["sha256"]:
            raise ValueError("Option inherited source lineage mismatch")
    for item in sourcehashes["raw_files"]:
        verify_pointer_item(item)
    rawrefs_path = local(om["rawrefs_path"])
    if digest(rawrefs_path) != om["rawrefs_sha256"] or digest(out / "option_quality.csv") != om["quality_sha256"]:
        raise ValueError("Option raw graph/quality hash mismatch")
    rawcontainer = read(rawrefs_path)
    wrapped = "evidence" in rawcontainer
    rawmap = rawcontainer["evidence"] if wrapped else rawcontainer
    if not isinstance(rawmap, dict) or not rawmap:
        raise ValueError("Option raw EvidenceRef graph is empty")
    rawcheck = verify_lock(rawrefs_path, next(iter(rawmap)), unwrap_evidence=wrapped)
    request = DataRequest(Dataset.STRATEGY_FEATURE_EVIDENCE, "S014:EX039:MA_OI_MATCHED_V1", "2020-01-01", "2026-10-15", None, "daily", EvidenceParameters(ROOT, relative(option_path), option_hash))
    fetched, option_lineage = fetch_ready(ctx, request, op["reference"])
    if fetched.identity.content_sha256 != op["content_sha256"] or len(fetched.dataframe) != op["rows"]:
        raise ValueError("Option fetched identity/row count mismatch")
    option = pd.read_csv(option_path)
    same_frame(option, fetched.dataframe, "Option formal public feature fetch")
    return etf, option, {"ETF": {"pointer": relative(out / "etf_successful_preparation.json"), "pointer_sha256": digest(out / "etf_successful_preparation.json"), "feature_sha256": digest(feature_path), "pointer_checks": pointer_checks, "public_fetches": etf_lineage, "reconstruction": "MATCH"}, "OPTION": {"prepared_receipt": relative(out / "option_prepared.json"), "prepared_receipt_sha256": digest(out / "option_prepared.json"), "feature_sha256": option_hash, "public_fetch": option_lineage, "raw_graph": {"path": rawcheck["path"], "sha256": rawcheck["sha256"], "verified_entries": len(rawcheck["checked"])}, "sourcehashes_sha256": digest(out / "option_sourcehashes.json")}}


def precheck():
    """Synthetic merge boundaries; no source reads, public fetches or fits."""
    dates = pd.date_range("2024-01-01", periods=3)
    base = pd.DataFrame({"date": dates, "signal": [0, 1, 2], "A": [False, True, True], "year": [2024] * 3, "contract": ["K0", "K1", "K1"], "Y3": [np.nan, .1, -.2], "entry_filled": [None, True, False]})
    etf = base[["date", "signal", "A", "year"]].copy()
    for name in ETF:
        etf[name] = [False, True, False] if name.endswith("ready") else [np.nan, 0., 1.]
    option = base.loc[base.A].copy()
    for name in OPTION:
        option[name] = [True, False] if name in ("opt_ready", "opt_roll", "opt_active_pair") else [0., 2.]
    result = merge_frames(base, etf, option)
    assert pd.isna(result.loc[0, "opt_delta_put"]) and result.loc[1, "opt_delta_put"] == 0
    assert result.loc[1, "Y3"] == .1 and result.loc[2, "Y3"] == -.2
    for bad in (pd.concat([option, option.iloc[[0]]]), option.assign(Y3=[.2, -.2]), option.iloc[:-1]):
        try:
            merge_frames(base, etf, bad)
        except (ValueError, AssertionError):
            pass
        else:
            raise AssertionError("Invalid duplicate/mutated/incomplete feature grid accepted")
    return {"status": "PASS", "checks": ["one-to-one dates", "all original fields preserved", "non-A missing option stays missing", "valid zero retained", "duplicate rejected", "shared target mutation rejected", "missing date rejected"], "public_fetches": 0, "source_calls": 0, "real_fits": 0}


def assemble():
    offline()
    out = EX / "others"
    names = ("model_inputs.csv", "model_input_merge.json", "model_input_lineage.json", "model_input_preflight.json", "model_input_hashes.json")
    if any((out / name).exists() for name in names):
        raise FileExistsError("Model assembly already has outputs; preserve existing attempt")
    locks = {"original": verify_lock(EX / "protocols/published_design.json", relative(EX / "protocols/design.json")), "ETF_repair_additive": verify_lock(EX / "protocols/published_etf_repair.json", relative(EX / "src/resume_etf.py"))}
    original_paths, refs = {}, {}
    for name in ("inputs.csv", "labels.csv", "calendar.csv"):
        original_paths[name], refs[name] = original_source(name)
    original = pd.read_csv(original_paths["inputs.csv"])
    calendar = pd.read_csv(original_paths["calendar.csv"])
    etf, option, lineage = verify_features(original, calendar, out, locks["ETF_repair_additive"])
    merged = merge_frames(original, etf, option)
    if not np.array_equal(merged.signal, calendar.signal) or not pd.to_datetime(merged.date).equals(pd.to_datetime(calendar.date)):
        raise ValueError("Merged signal/calendar identity mismatch")
    # Copy immutable source companions byte-for-byte for analyze_fixed.py.
    companions = {}
    for name in ("labels.csv", "calendar.csv"):
        destination = out / name
        if destination.exists():
            if destination.read_bytes() != original_paths[name].read_bytes():
                raise ValueError("Existing companion differs from immutable original")
        else:
            with destination.open("xb") as stream:
                stream.write(original_paths[name].read_bytes())
        companions[name] = {"sha256": digest(destination), "bytes": destination.stat().st_size}
    with (out / "model_inputs.csv").open("x", encoding="utf-8", newline="") as stream:
        merged.to_csv(stream, index=False, lineterminator="\n")
    # Run the locked analyzer's preparation-only function: no fit/statistical use.
    spec = importlib.util.spec_from_file_location("ex039_assembly_preflight", EX / "src/analyze_fixed.py")
    analyzer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analyzer)
    b65 = read(ROOT / "research/S014/experiments/EX032_20261018/protocols/design.json")["baseline_columns"]
    _, tasks, coverage = analyzer.prepare(EX, b65)
    write(out / "model_input_lineage.json", {"status": "VERIFIED_PUBLIC_FETCH_AND_IMMUTABLE_LINEAGE", "locks": locks, "EX032": refs, "external_features": lineage, "companions": companions, "assembler_sha256": digest(__file__)})
    a = bool_values(merged.A, "A").fillna(False)
    non_a = merged.loc[~a]
    write(out / "model_input_merge.json", {"status": "PASS", "rows": len(merged), "A_rows": int(a.sum()), "all_original_columns_unchanged": list(original.columns), "merge": "exact-date one-to-one left joins; no fill/imputation", "non_A_option_numeric_finite_counts": {c: int(np.isfinite(non_a[c].to_numpy(float)).sum()) for c in OPTION if c not in ("opt_ready", "opt_roll", "opt_active_pair")}, "model_inputs_sha256": digest(out / "model_inputs.csv"), "ETF_features_sha256": digest(out / "etf_features.csv"), "OPTION_features_sha256": digest(out / "option_features.csv"), "new_fits": 0, "new_source_calls": 0})
    write(out / "model_input_preflight.json", {"status": "PASS_INPUT_ONLY_NOT_FIT_AUTHORIZATION", "analysis_expected_fields": ETF + OPTION, "fixed_model_slots": len(tasks), "model_input_sha256": digest(out / "model_inputs.csv"), "lineage_sha256": digest(out / "model_input_lineage.json"), "merge_sha256": digest(out / "model_input_merge.json"), "coverage": coverage, "new_fits": 0, "new_source_calls": 0, "next_step": "Publicly publish merged inputs, prepare local feature evidence and establish run lock before model execution."})
    hash_names = ("model_inputs.csv", "model_input_merge.json", "model_input_lineage.json", "model_input_preflight.json", "labels.csv", "calendar.csv", "etf_features.csv", "option_features.csv")
    write(out / "model_input_hashes.json", {"status": "PASS", "files": {relative(out / name): {"sha256": digest(out / name), "bytes": (out / name).stat().st_size} for name in hash_names}, "assembler_sha256": digest(__file__)})
    return {"status": "PASS", "rows": len(merged), "fixed_slots_planned_not_run": len(tasks), "model_inputs_sha256": digest(out / "model_inputs.csv"), "new_fits": 0, "new_source_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("precheck", "assemble"))
    args = parser.parse_args()
    offline()
    print(json.dumps(precheck() if args.mode == "precheck" else assemble(), ensure_ascii=False, allow_nan=False))
