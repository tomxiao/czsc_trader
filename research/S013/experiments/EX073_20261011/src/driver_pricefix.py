"""Declare fixed EX073 then await root before actual input/statistics; zero accounts."""

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
import entry_core as core
import entry_statistics as stats
from independent_checks import verify_inputs, verify_statistics
from price_authentication import authenticate_price_units
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

WORK = Path(__file__).parent
ROOT = next(p for p in WORK.resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
import common  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError("Immutable output already exists: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013 only")
    return ref.resolve(ROOT)


def put(ctx, exp, path):
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


def frame(path):
    f = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    f.index = pd.to_datetime(f.index).as_unit("ns")
    return f


def check(plan):
    amendment = read(WORK / "price_technical_amendment.json")
    for name, expected in amendment["new_source_files"].items():
        assert digest(WORK / name) == expected, name
    for name, expected in plan["source_files"].items():
        assert digest(WORK / name) == expected, name
    assert (
        digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py")
        == plan["common_sha256"]
    )


def declare():
    plan = read(WORK / "prospective_plan.json")
    check(plan)
    focused = read(WORK / "focused_checks.json")
    assert focused["status"] == "PASS" and focused["source_hashes"] == plan["source_files"]
    for ref in plan["input_references"].values():
        public(ref)
    for ref in plan["known_counterevidence_references"].values():
        public(ref)
    public(plan["native_ref"])
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "原真实下跌入场的后两日继续持有增量",
            "固定四日隔夜压力主导标记，能否区分原实际bear买入后的第3-4日可控继续收益与观察下行风险？",
            date(2026, 10, 11),
        ),
    )
    write(WORK / "experiment.json", exp.to_dict())
    plan = {
        **plan,
        "experiment": exp.to_dict(),
        "declared_utc": datetime.now(timezone.utc).isoformat(),
    }
    write(WORK / "plan.json", plan)
    refs = {}
    for name in (
        *plan["source_files"],
        "focused_checks.json",
        "method.json",
        "prospective_plan.json",
        "plan.json",
    ):
        refs[name] = put(ctx, exp, WORK / name)
        if name.endswith(".py"):
            (exp.resolve(ROOT) / "src").mkdir(exist_ok=True)
            (exp.resolve(ROOT) / "src" / name).write_bytes((WORK / name).read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", refs)
    print(
        {"declared": exp.experiment_id, "statistics": "WAIT_ROOT_REVIEW", "accounts": 0}, flush=True
    )


def study():
    # Authorization is written only after explicit root post-review startup instruction.
    authorization = read(WORK / "root_statistics_authorization.json")
    assert (
        authorization["authorized"] is True
        and authorization["question_version"] == core.METHOD["version"]
    )
    plan = read(WORK / "plan.json")
    check(plan)
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    assert not (WORK / "input_checks.json").exists(), "No automatic rerun"
    ctx = common.context(1)
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    assert bound.strategy.candidate_id == "C8880"
    assert serialize_evaluation_evidence(bound, result) == read(public(plan["native_ref"]))
    assert bound.execution_data.pricing.to_dict()["basis"] == "HFQ_RESEARCH"
    old = frame(public(plan["input_references"]["old_features.csv"]))
    old69 = frame(public(plan["input_references"]["pressure_features.csv"]))
    warm = frame(public(plan["input_references"]["warm_prices.csv"]))
    assert len(old) == 1635 and old.index.equals(old69.index)
    old14 = old.loc[:, stats.CONTROLS].copy()
    pd.testing.assert_frame_equal(old14, old69.loc[:, stats.CONTROLS], check_exact=True)
    p = core.pressure(warm)
    np.testing.assert_allclose(
        p.pressure_share4.reindex(old.index), old69.overnight_down_share4, rtol=0, atol=1e-13
    )
    features = old14.join(
        p[["pressure_flag", "overnight_down4", "intraday_down4", "pressure_share4"]]
    )
    assert p.pressure_available.reindex(old.index).all()
    execution = result.runs[0].execution
    entries = core.actual_entries(execution.account_daily, execution.fills, execution.decisions)
    bear = entries.loc[entries.regime.eq("bear")]
    assert bear.index.isin(old.index).all()
    scope = pd.Series(old.index.isin(bear.index), index=old.index, name="actual_bear_entry")
    prices = bound.execution_data.execution_daily.set_index("dt")[["open", "close"]].rename(
        columns={"open": "Open", "close": "Close"}
    )
    prices.index = pd.to_datetime(prices.index).as_unit("ns")
    prices.attrs = {}
    assert prices.index[-1] == pd.Timestamp("2026-09-30")
    price_authentication = authenticate_price_units(
        prices, warm, bound.execution_data.pricing.to_dict()["anchor_factor"], old.index
    )
    targets = core.labels(prices, old.index)
    verified = verify_inputs(
        execution.account_daily,
        execution.fills,
        execution.decisions,
        entries,
        prices,
        features,
        targets,
        scope,
        old14,
        warm,
    )
    assert not common.SOURCE_CALLS
    info = {
        "status": "PASS",
        "native_candidate": "C8880",
        "native_exact": True,
        "price_basis": bound.execution_data.pricing.to_dict(),
        "actual_all_entry_n": len(entries),
        "actual_bear_entry_n": len(bear),
        "bear_flag_n": int(features.loc[scope, "pressure_flag"].sum()),
        "known_previous_signal_counts_only": {"bear": 64, "flag": 15},
        "counts_not_forced_to_match": True,
        "source_controls_exact": True,
        "price_unit_technical_authentication": price_authentication,
        "control_missing_counts": old14.isna().sum().to_dict(),
        "independent_input_checks": verified,
        "provider_calls": common.SOURCE_CALLS,
        "new_accounts": 0,
        "authenticated_utc": datetime.now(timezone.utc).isoformat(),
    }
    write(WORK / "input_checks.json", info)
    for name, f in (
        ("features", features),
        ("labels", targets),
        ("entries", entries),
        ("scope", scope.to_frame()),
        ("prices", prices),
    ):
        f.to_csv(WORK / (name + ".csv"), index_label="signal_date", float_format="%.17g")
        refs[name + ".csv"] = put(ctx, exp, WORK / (name + ".csv"))
    refs["input_checks.json"] = put(ctx, exp, WORK / "input_checks.json")
    refs["root_statistics_authorization.json"] = put(
        ctx, exp, WORK / "root_statistics_authorization.json"
    )
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    outcome = stats.analyze(features, targets, scope)
    outcome["public_prospective_declaration_before_statistics"] = True
    outcome["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write(WORK / "statistics.json", outcome)
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print(
        {"statistics_complete": exp.experiment_id, "accounts": 0, "entries": len(bear)}, flush=True
    )


def verify():
    plan = read(WORK / "plan.json")
    check(plan)
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    features, targets, entries, scope, prices = [
        frame(public(refs[n + ".csv"]))
        for n in ("features", "labels", "entries", "scope", "prices")
    ]
    for col in targets:
        if col.startswith("label_end_"):
            targets[col] = pd.to_datetime(targets[col])
    for col in ("entry_session", "entry_fill_time"):
        entries[col] = pd.to_datetime(entries[col])
    old = frame(public(plan["input_references"]["old_features.csv"]))
    warm = frame(public(plan["input_references"]["warm_prices.csv"]))
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    assert serialize_evaluation_evidence(bound, result) == read(public(plan["native_ref"]))
    e = result.runs[0].execution
    a = verify_inputs(
        e.account_daily,
        e.fills,
        e.decisions,
        entries,
        prices,
        features,
        targets,
        scope.iloc[:, 0],
        old.loc[:, stats.CONTROLS],
        warm,
    )
    b = verify_statistics(
        features, targets, scope.iloc[:, 0], read(public(refs["statistics.json"])), stats.CONTROLS
    )
    out = {
        "status": "PASS",
        "independent_inputs": a,
        "independent_statistics": b,
        "checks": a["checks"] + b["checks"],
        "new_accounts": 0,
        "provider_calls": common.SOURCE_CALLS,
    }
    assert not common.SOURCE_CALLS
    write(WORK / "verification.json", out)
    refs["verification.json"] = put(common.context(1), exp, WORK / "verification.json")
    write(exp.resolve(ROOT) / "protocols/verification_references.json", refs)
    print(out, flush=True)


if __name__ == "__main__":
    {"declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
