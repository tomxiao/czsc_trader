"""Fixed opportunity-density diagnostic; no fitting, new labels or accounts.

Normal execution requires four publicly published EvidenceRefs in --lock.
--synthetic-check never reads research outcomes or local research evidence.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
METRICS = ("A9", "L9", "O9")
ESTIMATORS = ("node_mean", "fixed_common_strata", "within_group_cluster_equal")
DRAWS = 2000
SEED = 13
STATE_SHA256 = "0380657b078564aae4a84ba5d7e9acfd92ef89cb50d16481e350c47c2bfdf2f5"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_published(value, experiment=None):
    from czsc_trader.research_tools import EvidenceRef

    ref = EvidenceRef.from_dict(value)
    require(ref.experiment.strategy_id == "S014", "Non-S014 evidence rejected")
    if experiment is not None:
        require(ref.experiment.experiment_id == experiment, "Wrong source experiment")
    raw = ref.resolve(ROOT).read_bytes()
    require(sha256(raw).hexdigest() == ref.sha256, "Published content hash differs")
    return raw, ref.to_dict()


def strict_bool(series):
    # CSV supplies native booleans or literal True/False; never truth-cast strings.
    require(series.notna().all(), "Missing state boolean")
    require(series.astype(str).isin(["True", "False"]).all(), "Invalid state boolean")
    return series.astype(str).eq("True")


def assemble(feature, events, states, expected_n=145, expected_clusters=59):
    require(len(feature) == expected_n, "Unexpected verified feature population")
    for frame in (feature, events, states):
        require(not frame.cycle_id.duplicated().any(), "Duplicate cycle identity")
    keys = ["cycle_id", "entry_date", "decision_date"]
    require(set(feature.cycle_id) == set(events.cycle_id), "Feature/event cycles differ")
    frame = feature.merge(events, on=keys, how="inner", validate="one_to_one")
    frame = frame.merge(states, on=keys, how="left", validate="one_to_one", indicator=True)
    require(len(frame) == expected_n and frame._merge.eq("both").all(), "State identity missing")
    frame = frame.drop(columns="_merge")
    for column in ("entry_date", "decision_date", "terminal_date", "previous_close_date",
                   "latest_feature_session", "verified_original_trigger_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise")
        require(frame[column].notna().all(), "Missing required date")
    require((frame.entry_date <= frame.previous_close_date).all(), "State predates entry")
    require((frame.previous_close_date < frame.decision_date).all(), "Future previous close")
    require((frame.latest_feature_session < frame.decision_date).all(), "Future opportunity input")
    require((frame.verified_original_trigger_date < frame.entry_date).all(), "Invalid entry trigger")
    require((frame.decision_date < frame.terminal_date).all(), "Invalid fixed endpoint")
    frame["P"] = strict_bool(frame.P)
    frame["D"] = strict_bool(frame.D)
    numeric = [*METRICS, "P_value", "D_value", "entry_price", "decision_close", "previous_close"]
    require(np.isfinite(frame[numeric].to_numpy(float)).all(), "Nonfinite observation")
    require((frame[["entry_price", "decision_close", "previous_close"]] > 0).all().all(),
            "Invalid state prices")
    p = frame.decision_close / (frame.entry_price * 1.001) - 1
    d = frame.decision_close / frame.previous_close - 1
    require(np.allclose(p, frame.P_value, rtol=0, atol=1e-12), "P value cannot be reproduced")
    require(np.allclose(d, frame.D_value, rtol=0, atol=1e-12), "D value cannot be reproduced")
    require(frame.P.eq(p.gt(0)).all() and frame.D.eq(d.gt(0)).all(), "P/D sign differs")
    extra = frame.additional_prior_opportunities
    require(np.isfinite(extra).all() and extra.ge(0).all() and extra.eq(np.floor(extra)).all(),
            "Invalid prior opportunity count")
    require(frame.compulsory_original_trigger_in_window.eq(1).all(), "Missing own trigger")
    require((frame.prior_six_potential_opportunities - 1).eq(extra).all(), "Own trigger subtraction differs")
    require(frame.cluster_id.notna().all() and frame.cluster_id.nunique() == expected_clusters,
            "Original event cluster identity differs")
    require(np.allclose(frame.A9, frame.L9 - frame.O9, rtol=0, atol=1e-10), "A9 != L9 - O9")
    frame["X"] = extra.ge(1)
    frame["year"] = frame.decision_date.dt.year
    require(frame.decision_year.eq(frame.year).all(), "Decision-year identity differs")
    frame["without2026"] = frame.decision_date.le("2025-12-31") & frame.terminal_date.le("2025-12-31")
    return frame.sort_values(["decision_date", "cycle_id"]).reset_index(drop=True)


class Scope:
    """All strata and their weights are fixed before bootstrap/leave-one-cluster-out."""

    def __init__(self, frame, cluster_codes, total_clusters):
        self.y = frame[list(METRICS)].to_numpy(float)
        self.x = frame.X.to_numpy(bool)
        self.codes = np.asarray(cluster_codes)
        self.ncluster = total_clusters
        self.strata = []
        self.strata_rows = []
        for key, part in frame.groupby(["year", "P", "D"], sort=True):
            ids = np.flatnonzero(frame.index.isin(part.index))
            n0, n1 = int((~self.x[ids]).sum()), int(self.x[ids].sum())
            self.strata_rows.append({"year": int(key[0]), "P": bool(key[1]), "D": bool(key[2]),
                                     "none_n": n0, "extra_n": n1, "weight": min(n0, n1),
                                     "common_support": bool(n0 and n1)})
            if n0 and n1:
                self.strata.append((ids, min(n0, n1)))
        self.cluster_means = np.full((total_clusters, 2, 3), np.nan)
        for c in range(total_clusters):
            for x in (0, 1):
                ids = (self.codes == c) & (self.x == x)
                if ids.any():
                    self.cluster_means[c, x] = self.y[ids].mean(axis=0)

    def means(self, ids, node_weights):
        result = []
        for x in (0, 1):
            selected = ids[self.x[ids] == x]
            weights = node_weights[selected]
            if weights.sum() <= 0:
                return None
            result.append(np.average(self.y[selected], axis=0, weights=weights))
        return np.asarray(result)

    def estimate(self, multiplicities):
        node_weights = multiplicities[self.codes]
        means = self.means(np.arange(len(self.x)), node_weights)
        raw = None if means is None else means[1] - means[0]
        adjusted = np.zeros(3)
        total = sum(weight for _, weight in self.strata)
        if not total:
            adjusted = None
        else:
            for ids, weight in self.strata:
                part = self.means(ids, node_weights)
                if part is None:
                    adjusted = None
                    break
                adjusted += (part[1] - part[0]) * weight / total
        cluster_values = []
        for x in (0, 1):
            available = np.isfinite(self.cluster_means[:, x, 0]) & (multiplicities > 0)
            if not available.any():
                cluster_values = []
                break
            cluster_values.append(np.average(self.cluster_means[available, x], axis=0,
                                             weights=multiplicities[available]))
        equal = None if not cluster_values else cluster_values[1] - cluster_values[0]
        return {name: value for name, value in zip(ESTIMATORS, (raw, adjusted, equal), strict=True)}

    def describe(self):
        def group(x):
            ids = self.x == x
            return {"nodes": int(ids.sum()), "clusters": int(np.unique(self.codes[ids]).size),
                    "means": {m: (float(self.y[ids, j].mean()) if ids.any() else None)
                              for j, m in enumerate(METRICS)}}
        return {"none": group(False), "extra": group(True), "strata": self.strata_rows,
                "common_support_nodes": sum(int(len(ids)) for ids, _ in self.strata),
                "fixed_common_weight": sum(weight for _, weight in self.strata)}


def vectors(values):
    return {name: {metric: (None if vector is None else float(vector[j]))
                   for j, metric in enumerate(METRICS)} for name, vector in values.items()}


def calculate(frame, draws=DRAWS):
    cluster_ids = sorted(frame.cluster_id.unique().tolist())
    code_map = {value: i for i, value in enumerate(cluster_ids)}
    codes = frame.cluster_id.map(code_map).to_numpy(int)
    ncluster = len(cluster_ids)
    masks = {"ALL": np.ones(len(frame), dtype=bool), "WITHOUT2026": frame.without2026.to_numpy(bool)}
    masks.update({str(year): frame.year.eq(year).to_numpy(bool) for year in sorted(frame.year.unique())})
    scopes = {name: Scope(frame.loc[mask], codes[mask], ncluster) for name, mask in masks.items()}
    original = np.ones(ncluster, dtype=int)
    results = {name: {"population": scope.describe(), "differences_extra_minus_none": vectors(scope.estimate(original))}
               for name, scope in scopes.items()}
    boot = {name: {kind: [] for kind in ESTIMATORS} for name in scopes}
    rng = np.random.default_rng(SEED)
    # Each draw samples the SAME original clusters jointly across outcomes/scopes.
    for _ in range(draws):
        multiplicities = np.bincount(rng.integers(0, ncluster, size=ncluster), minlength=ncluster)
        for name, scope in scopes.items():
            for kind, value in scope.estimate(multiplicities).items():
                boot[name][kind].append([np.nan] * 3 if value is None else value)
    for name in scopes:
        results[name]["joint_cluster_bootstrap"] = {}
        for kind, values in boot[name].items():
            array = np.asarray(values)
            valid = np.isfinite(array).all(axis=1)
            results[name]["joint_cluster_bootstrap"][kind] = {
                "valid_draws": int(valid.sum()), "null_draws": int((~valid).sum()),
                "ordinary_descriptive_95_interval": {
                    metric: (np.quantile(array[valid, j], [.025, .975]).tolist() if valid.any() else None)
                    for j, metric in enumerate(METRICS)}}
    loo = []
    for c, cluster_id in enumerate(cluster_ids):
        weights = original.copy()
        weights[c] = 0
        loo.append({"omitted_original_cluster": cluster_id,
                    "scopes": {name: vectors(scope.estimate(weights)) for name, scope in scopes.items()}})
    return {"scopes": results, "leave_one_original_cluster_out": loo,
            "bootstrap": {"draws": draws, "seed": SEED, "original_clusters": ncluster,
                          "joint_across_scopes_and_labels": True, "redraw_empty_groups": False}}


def load_inputs(lock_path):
    lock = json.loads(lock_path.read_bytes())
    published = {}
    raw = {}
    for name in ("source", "design", "feasibility_rows", "feasibility_summary"):
        raw[name], published[name] = load_published(lock[name])
    require(raw["source"] == Path(__file__).read_bytes(), "Running source differs from published lock")
    for name, filename in (("feasibility_rows", "opportunity_feasibility_verified_rows.csv"),
                           ("feasibility_summary", "opportunity_feasibility_verified.json")):
        require(raw[name] == (OUT / filename).read_bytes(), "Verified feasibility bytes differ")
    summary = json.loads(raw["feasibility_summary"])
    require(summary["calendar_and_actual_order_trigger_checks"] == "PASS_ALL_145", "Unverified inputs")
    require(summary["events"] == 145 and not summary["outcome_columns_loaded_or_compared"],
            "Expected outcome-free feasibility")
    # Revalidate every declared upstream reference, including no-op receipt/calendar.
    for i, ref in enumerate(summary["source_references"]):
        _, published[f"verified_input_{i}"] = load_published(ref)
    ex35 = ROOT / "research/S014/experiments/EX035_20261018/others/result.json"
    result35 = json.loads(ex35.read_bytes())
    event_raw, published["events"] = load_published(result35["evidence"]["others/events.csv"], "EX035_20261018")
    require(event_raw == (ex35.parent / "events.csv").read_bytes(), "EX035 local/public events differ")
    require(published["events"] in summary["source_references"], "Feature/event publication differs")
    ex19 = ROOT / "research/S014/experiments/EX019_20261017/others/result.json"
    result19 = json.loads(ex19.read_bytes())
    # Two published names may identify the same bytes. Select the exact reviewed
    # v2 business name, then enforce the unchanged content identity.
    state_ref = result19["evidence"]["ex019-others-state_diagnostics_v2_members-csv"]
    require(state_ref["sha256"] == STATE_SHA256, "EX019 exact v2 state SHA differs")
    state_raw, published["states"] = load_published(state_ref, "EX019_20261017")
    state_columns = ["cycle_id", "entry_date", "decision_date", "P", "D", "P_value", "D_value",
                     "entry_price", "decision_close", "previous_close", "previous_close_date"]
    # No EX019 future-return columns are consumed.
    states = pd.read_csv(BytesIO(state_raw), usecols=state_columns)
    events = pd.read_csv(BytesIO(event_raw), usecols=["cycle_id", "entry_date", "decision_date",
                                                        "terminal_date", "cluster_id", *METRICS])
    feature = pd.read_csv(BytesIO(raw["feasibility_rows"]))
    frame = assemble(feature, events, states)
    require(frame.X.value_counts().to_dict() == {True: 85, False: 60}, "Locked input groups differ")
    return frame, published


def synthetic_check():
    # Hand-computable heterogeneous clusters also exercise state standardization.
    frame = pd.DataFrame({"cluster_id": [0, 0, 1, 1, 2, 2], "X": [0, 1, 0, 1, 0, 1],
                          "year": [2025] * 4 + [2026] * 2, "P": [False] * 6, "D": [False] * 6,
                          "L9": [0., 1., 2., 3., 4., 5.], "O9": [0., 3., 1., 4., 2., 5.],
                          "without2026": [True] * 4 + [False] * 2})
    frame["A9"] = frame.L9 - frame.O9
    result = calculate(frame, draws=80)
    require(len(result["leave_one_original_cluster_out"]) == 3, "LOO must cover every original cluster")
    for scope in result["scopes"].values():
        for values in scope["differences_extra_minus_none"].values():
            require(np.allclose([values[m] for m in METRICS], [-2., 1., 3.]), "Synthetic contrast differs")
    only = frame.loc[frame.X.eq(0)].copy()
    none = calculate(only, draws=20)
    require(none["scopes"]["ALL"]["differences_extra_minus_none"]["node_mean"]["A9"] is None,
            "Missing group must be null")
    require(none["scopes"]["ALL"]["joint_cluster_bootstrap"]["node_mean"]["null_draws"] == 20,
            "Null draws must not be resampled")
    sparse = frame.copy()
    sparse["D"] = sparse.X.astype(bool)
    no_support = calculate(sparse, draws=20)
    require(no_support["scopes"]["ALL"]["population"]["fixed_common_weight"] == 0,
            "Disjoint strata must have zero common support")
    require(no_support["scopes"]["ALL"]["differences_extra_minus_none"]["fixed_common_strata"]["A9"] is None,
            "Disjoint strata must stay null")
    require(strict_bool(pd.Series([True, False])).tolist() == [True, False], "Strict boolean failed")
    try:
        strict_bool(pd.Series(["False", "unknown"]))
    except ValueError:
        pass
    else:
        raise ValueError("Invalid boolean was accepted")
    require(result == calculate(frame, draws=80), "Seeded synthetic output not deterministic")
    dates = pd.date_range("2025-01-10", periods=6)
    feature = pd.DataFrame({"cycle_id": [f"synthetic-{i}" for i in range(6)],
                            "entry_date": (dates - pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
                            "decision_date": dates.strftime("%Y-%m-%d"), "decision_year": 2025,
                            "prior_six_potential_opportunities": [1, 2] * 3,
                            "compulsory_original_trigger_in_window": 1,
                            "additional_prior_opportunities": [0, 1] * 3,
                            "latest_feature_session": (dates - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                            "verified_original_trigger_date": (dates - pd.Timedelta(days=3)).strftime("%Y-%m-%d")})
    keys = ["cycle_id", "entry_date", "decision_date"]
    events = feature[keys].copy()
    events["terminal_date"] = (dates + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    events["cluster_id"] = frame.cluster_id.to_numpy()
    events[list(METRICS)] = frame[list(METRICS)]
    states = feature[keys].copy()
    states["previous_close_date"] = feature.latest_feature_session
    states["entry_price"] = 10.
    states["decision_close"] = 10.01
    states["previous_close"] = 10.01
    states["P_value"] = states.decision_close / (states.entry_price * 1.001) - 1
    states["D_value"] = 0.
    states["P"] = states.P_value.gt(0)
    states["D"] = False
    joined = assemble(feature, events, states, expected_n=6, expected_clusters=3)
    require(len(joined) == 6 and joined.X.sum() == 3, "Synthetic causal join differs")
    invalid = events.copy()
    invalid.loc[0, "A9"] += .1
    try:
        assemble(feature, invalid, states, expected_n=6, expected_clusters=3)
    except ValueError:
        pass
    else:
        raise ValueError("Broken accounting identity was accepted")
    invalid_state = states.copy()
    invalid_state.loc[0, "previous_close_date"] = dates[0].strftime("%Y-%m-%d")
    try:
        assemble(feature, events, invalid_state, expected_n=6, expected_clusters=3)
    except ValueError:
        pass
    else:
        raise ValueError("Future state observation was accepted")
    print(json.dumps({"status": "PASS", "synthetic_only": True,
                      "checks": ["known three-metric contrast", "fixed state support", "empty group null",
                                 "null draws retained", "disjoint strata null", "strict booleans",
                                 "deterministic joint resampling", "all clusters left out once",
                                 "causal state join", "broken accounting identity rejected",
                                 "future state rejected"],
                      "real_outcomes_loaded": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-check", action="store_true")
    parser.add_argument("--lock", type=Path)
    args = parser.parse_args()
    if args.synthetic_check:
        require(args.lock is None, "Synthetic check must not load a real lock")
        synthetic_check()
        return
    require(args.lock is not None, "Published design/source lock is mandatory")
    json_path = OUT / "opportunity_diagnostic.json"
    rows_path = OUT / "opportunity_diagnostic_rows.csv"
    require(not json_path.exists() and not rows_path.exists(), "Existing results are immutable; do not rerun")
    frame, refs = load_inputs(args.lock)
    result = {"status": "COMPLETE_FIXED_DIAGNOSTIC_ONLY", "source_references": refs,
              "technical_revision": "v2 selects exact published EX019 v2 state name and verifies unchanged SHA; identical-content aliases are not ambiguity; no statistical definition changed",
              "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "definition": "X=at least one eligible opportunity in strictly prior six sessions after removing own entry trigger",
              "window_interpretation": "Six sessions span two H3 holding lengths, not complete trading cycles",
              "extra_interpretation": "Includes pre-entry past opportunities; not actual missed orders",
              "primary": "Delta A9=mean(extra)-mean(none), prespecified direction negative",
              "attribution": "Delta O9 prespecified positive; L9 unrestricted; A9=L9-O9",
              "units": "Original EX035 local wealth contrast divided by decision-node wealth W_D; decimal ratios, not annual strategy returns",
              "strata_policy": "Fixed year x P x D original common strata; fixed min(n0,n1) weights; absent required group yields null, never drops a stratum",
              "cluster_policy": "Original 59 clusters; within each X group average nodes within cluster then average observed clusters equally",
              "without2026_policy": "Both decision date and original terminal date <= 2025-12-31",
              "resources": {"new_fits": 0, "new_return_labels": 0, "new_accounts": 0, "new_source_calls": 0},
              "limitations": ["All evidence and selection history are already seen; no independent alpha claim",
                              "C0011 original policy only; not an explanation of C0056",
                              "Intervals are descriptive diagnostics, not new economic gates",
                              "No threshold, window, endpoint, direction, state-layer selection or policy search"],
              **calculate(frame)}
    csv_bytes = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    result["rows_sha256"] = sha256(csv_bytes).hexdigest()
    json_bytes = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with rows_path.open("xb") as stream:
        stream.write(csv_bytes)
    with json_path.open("xb") as stream:
        stream.write(json_bytes)
    print(json.dumps({"status": result["status"], "nodes": len(frame), "clusters": frame.cluster_id.nunique(),
                      "result_sha256": sha256(json_bytes).hexdigest(), "rows_sha256": result["rows_sha256"]}))


if __name__ == "__main__":
    def blocked(*args, **kwargs):
        raise RuntimeError("Source/network calls prohibited")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    main()
