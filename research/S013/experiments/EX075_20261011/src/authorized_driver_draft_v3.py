"""Standby execution source only. Import does not read files or market inputs.

Each actual phase requires a NEW root phase authorization bound to final freeze.
No authorization is supplied by source preparation or by prior EX074 approval.
"""

from datetime import date, datetime, timezone
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
    if phase not in ("declare", "preflight", "statistics"):
        raise ValueError("three separate fixed phases required")
    work = Path(__file__).resolve().parent if here is None else Path(here)
    authorization = read(work / ("root_" + phase + "_authorization_v3.json"))
    freeze_path = work / "source_freeze_v3.json"
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


def declare():
    work, root, freeze = authority("declare")
    if (work / "allocation_attempt.json").exists() or (work / "experiment.json").exists():
        raise ValueError("one allocation only; retain failure and root handles recovery")
    common = original_common(root, freeze)
    from czsc_trader.application import create_experiment, ExperimentRequest

    write_new(
        work / "allocation_attempt.json",
        {
            "expected": "EX075_20261011",
            "freeze_sha256": digest(work / "source_freeze_v3.json"),
            "utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    exp = create_experiment(
        common.context(1),
        ExperimentRequest(
            "当天下跌bar成交量集中度的独立收益与风险信息",
            "固定单组件能否超出原18控制和成熟过去均值预测下一开盘后四日扣费收益及OPEN/CLOSE风险？",
            date(2026, 10, 11),
        ),
    )
    write_new(work / "experiment.json", exp.to_dict())
    if exp.experiment_id != "EX075_20261011":
        raise ValueError("unexpected allocated experiment retained; STOP, no reallocation")
    plan = {
        **read(work / "draft_plan_v5.json"),
        "prior_draft_status": read(work / "draft_plan_v5.json")["status"],
        "status": "PROSPECTIVELY_DECLARED_ZERO_ACCOUNTS_AWAITING_INPUT_AUTHENTICATION",
        "experiment": exp.to_dict(),
        "source_files": freeze["source_files"],
        "declared_utc": datetime.now(timezone.utc).isoformat(),
        "source_freeze_sha256": digest(work / "source_freeze_v3.json"),
        "statistics_authorized": False,
    }
    write_new(work / "plan.json", plan)
    refs = {}
    for name in (
        *freeze["source_files"],
        "source_freeze_v3.json",
        "plan.json",
        "root_declare_authorization_v3.json",
    ):
        refs[name] = put(common.context(1), exp, work / name)
        if name.endswith(".py"):
            (exp.resolve(root) / "src").mkdir(exist_ok=True)
            with (exp.resolve(root) / "src" / name).open("xb") as f:
                f.write((work / name).read_bytes())
    write_new(exp.resolve(root) / "protocols/plan.json", plan)
    write_new(exp.resolve(root) / "protocols/method_references.json", refs)
    write_new(work / "method_references.json", refs)


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
    if (work / "input_attempt.json").exists():
        raise ValueError("one input authentication only; retain failure")
    write_new(
        work / "input_attempt.json", {"utc": datetime.now(timezone.utc).isoformat(), "accounts": 0}
    )
    import pandas as pd
    import input_adapter_draft as adapter
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

    common = original_common(root, freeze)
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
        f = got.dataframe.copy()
        f["dt"] = pd.to_datetime(f["dt"]).as_unit("ns")
        for column in f:
            if column not in ("dt", "symbol", "freq"):
                f[column] = pd.to_numeric(f[column], errors="raise")
        f.attrs = {}
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
        ("prices.csv", prices),
    ):
        with (work / name).open("x", encoding="utf-8", newline="") as f:
            value.to_csv(f, index_label="signal_date", float_format="%.17g")
        refs[name] = put(common.context(1), exp, work / name)
    checks["input_bindings"] = bindings
    checks["original_prepared_asset_identities"] = identities
    checks["priced_intraday_recomputed_exact"] = True
    checks["EX066_return4_fee_labels_and_maturity_exact_contract"] = True
    checks["preflight_authorization_sha256"] = digest(work / "root_preflight_authorization_v3.json")
    write_new(work / "input_checks.json", checks)
    refs["input_checks.json"] = put(common.context(1), exp, work / "input_checks.json")
    refs["root_preflight_authorization_v3.json"] = put(
        common.context(1), exp, work / "root_preflight_authorization_v3.json"
    )
    write_new(work / "input_references.json", refs)
    write_new(exp.resolve(root) / "protocols/input_references.json", refs)


def statistics():
    work, root, freeze = authority("statistics")
    exp, _ = declared(work, root)
    if (work / "statistics_attempt.json").exists():
        raise ValueError("one fixed statistical run only; retain failure")
    refs = read(work / "input_references.json")
    if read(public(root, refs["input_checks.json"]))["status"] != "PASS":
        raise ValueError("input authentication required before statistics")
    write_new(
        work / "statistics_attempt.json",
        {"utc": datetime.now(timezone.utc).isoformat(), "accounts": 0},
    )
    import pandas as pd
    import statistics_draft_v2 as stats

    def frame(name):
        f = pd.read_csv(
            public(root, refs[name]), index_col="signal_date", float_precision="round_trip"
        )
        f.index = pd.to_datetime(f.index).as_unit("ns")
        return f

    labels = frame("labels.csv")
    labels["label_end4"] = pd.to_datetime(labels["label_end4"])
    output = stats.analyze(frame("features.csv"), labels, frame("price_calendar.csv").index)
    write_new(work / "statistics.json", output)
    common = original_common(root, freeze)
    refs["statistics.json"] = put(common.context(1), exp, work / "statistics.json")
    refs["root_statistics_authorization_v3.json"] = put(
        common.context(1), exp, work / "root_statistics_authorization_v3.json"
    )
    write_new(work / "result_references.json", refs)
    write_new(exp.resolve(root) / "protocols/result_references.json", refs)


if __name__ == "__main__":
    {"declare": declare, "preflight": preflight, "statistics": statistics}[sys.argv[1]]()
