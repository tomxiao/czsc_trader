"""Standby execution source only. Import does not read files or market inputs.

Each actual phase requires a NEW root phase authorization bound to final freeze.
No authorization is supplied by source preparation or by prior EX074 approval.
"""

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


def authority(phase, here=None):
    if phase != "preflight":
        raise ValueError("v5 is only the separately authorized technical preflight continuation")
    work = Path(__file__).resolve().parent if here is None else Path(here)
    authorization = read(work / "root_preflight_authorization_v5.json")
    freeze_path = work / "source_freeze_v5.json"
    if (
        authorization.get("status") != "APPROVED"
        or authorization.get("phase") != phase
        or authorization.get("freeze_sha256") != digest(freeze_path)
        or authorization.get("expected_experiment_id") != "EX075_20261011"
    ):
        raise PermissionError("NEW root exact phase/freeze/EX075 authorization required")
    freeze = read(freeze_path)
    for name, expected in freeze["source_files"].items():
        if Path(name).name != name or digest(work / name) != expected:
            raise ValueError("frozen file changed or illegal path: " + name)
    root = next(p for p in work.resolve().parents if (p / "pyproject.toml").exists())
    common_path = root / freeze["common_path"]
    if digest(common_path) != freeze["common_sha256"]:
        raise ValueError("original native helper source changed")
    return work, root, freeze


def original_common(root, freeze):
    source = root / freeze["common_path"]
    if (
        "common" in sys.modules
        and Path(sys.modules["common"].__file__).resolve() != source.resolve()
    ):
        raise ValueError("different common module already imported")
    sys.path.insert(0, str(source.parent))
    return importlib.import_module("common")


def binding_schema(bindings):
    """Reference metadata only, no evidence resolving or reading."""
    expected = {
        "native_ref": ("EX058_20261011", "application/json", "account_evaluation"),
        "old66_features": ("EX066_20261011", "text/csv", None),
        "old66_labels": ("EX066_20261011", "text/csv", None),
        "old69_features": ("EX069_20261011", "text/csv", None),
        "warm69_prices": ("EX069_20261011", "text/csv", None),
        "native73_prices": ("EX073_20261011", "text/csv", None),
    }
    for key, (experiment, media, schema) in expected.items():
        ref = bindings[key]
        digest_value = ref.get("sha256")
        if (
            ref.get("type") != "EvidenceRef"
            or ref.get("experiment")
            != {"type": "ExperimentRef", "strategy_id": "S013", "experiment_id": experiment}
            or ref.get("media_type") != media
            or ref.get("schema") != schema
            or not isinstance(digest_value, str)
            or len(digest_value) != 64
            or any(c not in "0123456789abcdef" for c in digest_value)
            or ref.get("evidence_id") != digest_value + (".json" if key == "native_ref" else ".csv")
        ):
            raise ValueError("exact existing source reference schema required: " + key)
        if key == "native_ref" and ref.get("schema_version") != 6:
            raise ValueError("original native schema version6 required")
    return True


def public(root, value):
    from czsc_trader.research_tools.evidence import EvidenceRef

    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("only original S013 evidence allowed")
    path = ref.resolve(root)
    if digest(path) != value["sha256"]:
        raise ValueError("immutable evidence hash mismatch")
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
            {".py": "text/x-python", ".csv": "text/csv"}.get(path.suffix, "application/json"),
            path.suffix[1:],
        ),
    ).to_dict()


def declared(work, root):
    from czsc_trader.research_tools.context import ExperimentRef

    exp = ExperimentRef.from_dict(read(work / "experiment.json"))
    if exp.experiment_id != "EX075_20261011":
        raise ValueError("unexpected experiment")
    refs = read(work / "method_references.json")
    if read(public(root, refs["plan.json"])) != read(work / "plan.json"):
        raise ValueError("public prospective plan must match exact local bytes content")
    return exp, refs


def preflight():
    work, root, freeze = authority("preflight")
    exp, refs = declared(work, root)
    if (
        not (work / "input_attempt.json").exists()
        or read(work / "preflight_failure_v4.json")["status"] != "FAILED_PRESERVED_NO_RETRY"
    ):
        raise ValueError("original input failure chain must remain explicit")
    if (work / "input_attempt_v5.json").exists():
        raise ValueError("one authorized technical continuation only; retain failure")
    common = original_common(root, freeze)
    write_new(
        work / "input_attempt_v5.json",
        {
            "utc": datetime.now(timezone.utc).isoformat(),
            "accounts": 0,
            "original_failed_attempt_sha256": digest(work / "input_attempt.json"),
            "technical_freeze_sha256": digest(work / "source_freeze_v5.json"),
            "technical_authorization_sha256": digest(work / "root_preflight_authorization_v5.json"),
            "technical_progress": "technical_publication_progress_v5.jsonl",
        },
    )
    with (work / "technical_publication_progress_v5.jsonl").open("x", encoding="utf-8"):
        pass
    technical_refs = {}
    original = read(work / "source_freeze_v4.json")["source_files"]
    for name in (
        *(n for n in freeze["source_files"] if n not in original),
        "source_freeze_v5.json",
        "root_preflight_authorization_v5.json",
        "root_preflight_authorization_v4.json",
        "input_attempt.json",
    ):
        technical_refs[name] = put(common.context(1), exp, work / name)
        with (work / "technical_publication_progress_v5.jsonl").open(
            "a", encoding="utf-8"
        ) as progress:
            progress.write(
                json.dumps({"name": name, "reference": technical_refs[name]}, ensure_ascii=False)
                + "\n"
            )
        if name.endswith(".py"):
            with (exp.resolve(root) / "src" / name).open("xb") as f:
                f.write((work / name).read_bytes())
    write_new(work / "technical_references_v5.json", technical_refs)
    write_new(exp.resolve(root) / "protocols/technical_references_v5.json", technical_refs)
    import pandas as pd
    import input_adapter_draft_v2 as adapter
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

    from prepared_schema_v5 import numerical

    bindings = read(work / "input_bindings_draft.json")
    binding_schema(bindings)
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    if serialize_evaluation_evidence(bound, result) != read(public(root, bindings["native_ref"])):
        raise ValueError("cached original native must equal exact public account evidence")
    ed = bound.execution_data
    # Same prepared immutable requests as the authenticated original cache only.
    # common.context installs a raising provider callback: missing assets refuse.
    ctx = common.context(1)
    fetched, identities = {}, {}
    for key in ("adjusted_daily", "execution_daily", "execution_30m"):
        got = ctx.data.fetch(ed.requests[key], prepared=ed.prepared)
        if not got.ready:
            raise ValueError("existing prepared original asset unavailable: " + key)
        f = numerical(got.dataframe)
        fetched[key] = f
        identities[key] = {
            "content_sha256": got.identity.content_sha256,
            "request": str(ed.requests[key]),
        }
    priced = ed.pricing.apply(
        fetched["execution_30m"],
        raw_daily=fetched["execution_daily"],
        adjusted_daily=fetched["adjusted_daily"],
    )
    left, right = (
        priced.reset_index(drop=True).copy(),
        ed.execution_intraday.reset_index(drop=True).copy(),
    )
    left.attrs, right.attrs = {}, {}
    pd.testing.assert_frame_equal(left, right, check_exact=True)

    def frame(ref):
        f = pd.read_csv(public(root, ref), index_col="signal_date", float_precision="round_trip")
        f.index = pd.to_datetime(f.index).as_unit("ns")
        return f

    bars = (
        ed.execution_intraday.rename(columns={"open": "Open", "close": "Close", "vol": "Volume"})
        .set_index("dt")[["Open", "Close", "Volume"]]
        .copy()
    )
    bars.index = pd.to_datetime(bars.index).as_unit("ns")
    prices = (
        ed.execution_daily.rename(columns={"open": "Open", "close": "Close"})
        .set_index("dt")[["Open", "Close"]]
        .copy()
    )
    prices.index = pd.to_datetime(prices.index).as_unit("ns")
    bars.attrs, prices.attrs = {}, {}
    sessions = pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).normalize().as_unit("ns")
    built = adapter.construct(
        frame(bindings["old66_features"]),
        frame(bindings["old69_features"]),
        frame(bindings["native73_prices"]),
        frame(bindings["warm69_prices"]),
        bars,
        prices,
        sessions,
        ed.pricing.to_dict(),
        bound.strategy.candidate_id,
        "510500.SH",
    )
    features, labels, observations, profile, checks = built
    oldlabels = frame(bindings["old66_labels"])
    if not oldlabels.index.equals(labels.index):
        raise ValueError("original net-label signal grid must remain identical")
    import numpy as np

    np.testing.assert_allclose(
        labels.return4_net, oldlabels.return_4, rtol=0, atol=5e-15, equal_nan=True
    )
    pd.testing.assert_series_equal(
        labels.label_end4,
        pd.to_datetime(oldlabels.label_end_return_4),
        check_exact=True,
        check_names=False,
    )
    if common.SOURCE_CALLS:
        raise ValueError("provider use forbidden")
    for name, value in (
        ("features.csv", features),
        ("labels.csv", labels),
        ("observations.csv", observations),
        ("profile.csv", profile),
        ("price_calendar.csv", pd.DataFrame(index=sessions)),
        ("full_native_prices.csv", prices),
        ("prices.csv", prices.loc[sessions]),
    ):
        with (work / name).open("x", encoding="utf-8", newline="") as f:
            value.to_csv(f, index_label="signal_date", float_format="%.17g")
        refs[name] = put(common.context(1), exp, work / name)
    checks["input_bindings"] = bindings
    checks["original_prepared_asset_identities"] = identities
    checks["priced_intraday_recomputed_exact"] = True
    checks["EX066_return4_fee_labels_and_maturity_exact_contract"] = True
    checks["preflight_authorization_sha256"] = digest(work / "root_preflight_authorization_v4.json")
    checks["technical_preflight_authorization_sha256"] = digest(
        work / "root_preflight_authorization_v5.json"
    )
    checks["technical_references"] = technical_refs
    checks["original_failed_preflight_preserved"] = True
    write_new(work / "input_checks.json", checks)
    refs["input_checks.json"] = put(common.context(1), exp, work / "input_checks.json")
    refs.update(technical_refs)
    write_new(work / "input_references.json", refs)
    write_new(exp.resolve(root) / "protocols/input_references.json", refs)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "preflight":
        raise ValueError("v5 only resumes authorized preflight; no allocation/statistics")
    preflight()
