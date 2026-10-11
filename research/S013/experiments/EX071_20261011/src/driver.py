"""Frozen S013 actual-held information study; no new accounts or execution rules."""

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
import continuation_core as core
import opportunity_statistics as stats
from independent_inputs import verify_inputs
from independent_statistics import verify_statistics
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = Path(__file__).parent
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


def check_sources(plan):
    for name, expected in plan["source_files"].items():
        assert digest(WORK / name) == expected, name
    assert (
        digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py")
        == plan["common_sha256"]
    )


def declare():
    plan = read(WORK / "prospective_plan.json")
    check_sources(plan)
    assert read(WORK / "focused_checks.json")["status"] == "PASS"
    for name, expected in plan["source_files"].items():
        assert read(WORK / "focused_checks.json")["source_hashes"][name] == expected
    for ref in plan["input_references"].values():
        public(ref)
    public(plan["native_ref"])
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "实际持仓中的尾盘弱势与继续持有信息",
            "固定late_weakness能否在实际持仓及已知持仓状态控制后，区分明早卖出与继续4日的价格收益/观察下行风险？",
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
    print({"declared": exp.experiment_id, "accounts": 0}, flush=True)


def native(plan):
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    assert serialize_evaluation_evidence(bound, result) == read(public(plan["native_ref"]))
    assert bound.strategy.candidate_id == "C8880"
    assert bound.execution_data.pricing.to_dict()["basis"] == "HFQ_RESEARCH"
    return bound, result


def parse_dates(f):
    for name in f:
        if name.startswith("label_end_"):
            f[name] = pd.to_datetime(f[name])
    return f


def study():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    check_sources(plan)
    assert not (WORK / "input_checks.json").exists(), "No automatic rerun"
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    ctx = common.context(1)
    bound, result = native(plan)
    old = frame(public(plan["input_references"]["features.csv"]))
    old_labels = parse_dates(frame(public(plan["input_references"]["old_labels.csv"])))
    assert len(old) == 1635 and old.index.equals(old_labels.index)
    execution = result.runs[0].execution
    state = core.build_known_state(
        execution.account_daily, execution.fills, execution.decisions, old.index
    )
    base = [
        n for n in stats.CONTROLS if n not in ("holding_age", "entry_mark_pnl", "known_falling")
    ]
    assert len(base) == 19 and "late_recovery" not in base
    features = old[base].copy()
    features["holding_age"], features["entry_mark_pnl"] = state.holding_age, state.entry_mark_pnl
    features["known_falling"] = old.momentum20.lt(0).astype(float)
    features["late_weakness"] = -old.late_recovery
    features = features.loc[:, [*stats.CONTROLS, *stats.COMPONENTS]]
    prices = bound.execution_data.execution_daily.set_index("dt")[["open", "close"]].rename(
        columns={"open": "Open", "close": "Close"}
    )
    prices.index = pd.to_datetime(prices.index).as_unit("ns")
    prices.attrs = {}
    labels = core.build_labels(prices, old.index)
    scopes = pd.DataFrame(
        {
            "actual_held": state.actual_held,
            "declining_actual_held": state.actual_held & old.momentum20.lt(0),
            "actual_signal_continue": state.actual_held & state.signal_held_after,
            "actual_signal_exit": state.actual_held & ~state.signal_held_after,
        },
        index=old.index,
    )
    verified = verify_inputs(
        execution.account_daily,
        execution.fills,
        execution.decisions,
        state,
        prices,
        labels,
        old_labels,
    )
    before_disagreement = state.actual_held.ne(state.signal_held_before)
    assert not common.SOURCE_CALLS
    info = {
        "status": "PASS",
        "native_exact": True,
        "native_candidate": "C8880",
        "price_basis": bound.execution_data.pricing.to_dict(),
        "old19controls_exact": True,
        "component_exact_negative_ex061": True,
        "signal_n": len(features),
        "scope_counts": {n: int(scopes[n].sum()) for n in scopes},
        "actual_before_disagreement_n": int(before_disagreement.sum()),
        "state_audit_by_year": {},
        "feature_missing": features.isna().sum().to_dict(),
        "independent_pre_statistics_inputs": verified,
        "provider_calls": common.SOURCE_CALLS,
        "new_accounts": 0,
        "input_authenticated_utc": datetime.now(timezone.utc).isoformat(),
    }
    for year in sorted(old.index.year.unique()):
        mask = old.index.year == year
        info["state_audit_by_year"][str(year)] = {
            "actual_held": int(state.actual_held[mask].sum()),
            "before_mismatch": int(before_disagreement[mask].sum()),
            "before_true_actual_flat": int(
                (state.signal_held_before[mask] & ~state.actual_held[mask]).sum()
            ),
            "before_false_actual_held": int(
                (~state.signal_held_before[mask] & state.actual_held[mask]).sum()
            ),
            "actual_signal_continue": int(scopes.actual_signal_continue[mask].sum()),
            "actual_signal_exit": int(scopes.actual_signal_exit[mask].sum()),
            "distinct_entry_sessions": int(state.entry_session[mask].nunique()),
        }
    write(WORK / "input_checks.json", info)
    for name, value in (
        ("features", features),
        ("state", state),
        ("labels", labels),
        ("scopes", scopes),
        ("daily_prices", prices),
    ):
        value.to_csv(WORK / (name + ".csv"), index_label="signal_date", float_format="%.17g")
    for name in (
        "input_checks.json",
        "features.csv",
        "state.csv",
        "labels.csv",
        "scopes.csv",
        "daily_prices.csv",
    ):
        refs[name] = put(ctx, exp, WORK / name)
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    print(
        {"inputs_authenticated": True, "scope_counts": info["scope_counts"], "checks": verified},
        flush=True,
    )
    outcome = stats.analyze(features, labels, scopes)
    outcome["statistics_started_after_public_input_and_source"] = True
    outcome["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write(WORK / "statistics.json", outcome)
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print({"statistics_complete": exp.experiment_id, "accounts": 0}, flush=True)


def verify():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    check_sources(plan)
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    features, scopes, prices = (
        frame(public(refs[n])) for n in ("features.csv", "scopes.csv", "daily_prices.csv")
    )
    labels = parse_dates(frame(public(refs["labels.csv"])))
    state = frame(public(refs["state.csv"]))
    state["entry_session"] = pd.to_datetime(state.entry_session)
    old = frame(public(plan["input_references"]["features.csv"]))
    old_labels = parse_dates(frame(public(plan["input_references"]["old_labels.csv"])))
    _, result = native(plan)
    e = result.runs[0].execution
    input_result = verify_inputs(
        e.account_daily, e.fills, e.decisions, state, prices, labels, old_labels
    )
    np.testing.assert_array_equal(features.late_weakness, -old.late_recovery)
    for name in stats.CONTROLS:
        expected = (
            state[name]
            if name in ("holding_age", "entry_mark_pnl")
            else old.momentum20.lt(0).astype(float)
            if name == "known_falling"
            else old[name]
        )
        np.testing.assert_allclose(features[name], expected, rtol=0, atol=0, equal_nan=True)
    assert scopes.actual_held.equals(state.actual_held)
    assert scopes.declining_actual_held.equals(state.actual_held & old.momentum20.lt(0))
    assert scopes.actual_signal_continue.equals(state.actual_held & state.signal_held_after)
    assert scopes.actual_signal_exit.equals(state.actual_held & ~state.signal_held_after)
    checks = verify_statistics(features, labels, scopes, read(public(refs["statistics.json"])))
    verdict = {
        "status": "PASS",
        "input_checks": input_result,
        "statistical_checks": checks,
        "checks": checks + input_result["checks"] + 27,
        "scope": "independent chronological actual fill replay incl same-day fills, ledger-date state, signal intent scopes, exact old controls/component, every paired fee-affine and marked-close accounting identity, OPEN/CLOSE horizon endpoints, ranks/DF for all years/phases, mature shared train/test rows and prediction truth/MSE; no bootstrap or account repeat",
        "new_accounts": 0,
        "provider_calls": common.SOURCE_CALLS,
        "scientific_judgment": "not made",
    }
    assert not common.SOURCE_CALLS
    write(WORK / "verification.json", verdict)
    refs["verification.json"] = put(common.context(1), exp, WORK / "verification.json")
    write(exp.resolve(ROOT) / "protocols/verification_references.json", refs)
    print({"verification": "PASS", "checks": verdict["checks"]}, flush=True)


if __name__ == "__main__":
    {"declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
