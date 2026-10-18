"""Independent EX031 audit: pinned inputs and stored coefficients; zero refits."""

from hashlib import sha256
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    def prohibited(*args, **kwargs):
        raise RuntimeError("Independent audit forbids network and model fitting")

    socket.socket.connect = prohibited
    socket.create_connection = prohibited
    np.linalg.solve = prohibited
    np.linalg.lstsq = prohibited
    target = OUT / "independent_audit.json"
    assert not target.exists(), "Preserve independent audit"
    checks = []
    inputs_used = {}

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def hashed(path):
        value = sha256(path.read_bytes()).hexdigest()
        inputs_used[path.relative_to(ROOT).as_posix()] = value
        return value

    def published(experiment, key, csv=True):
        ref = read(ROOT / f"research/S014/experiments/{experiment}/others/result.json")["evidence"][key]
        path = ROOT / f"research/S014/assets/evidence/{experiment}/{ref['evidence_id']}"
        check("published_" + key, hashed(path) == ref["sha256"])
        return pd.read_csv(path) if csv else read(path)

    plan = read(EX / "protocols/design.json")
    for relative, ref in read(EX / "protocols/published_design.json").items():
        check("locked_" + relative, hashed(ROOT / relative) == ref["sha256"])
    info = read(OUT / "inputs.json")
    input_hash = hashed(OUT / "inputs.csv")
    check("input_manifest", input_hash == info["input_sha256"])
    f = pd.read_csv(OUT / "inputs.csv").set_index("signal")
    m = pd.read_csv(OUT / "methanol.csv").set_index("signal")
    labels = pd.read_csv(OUT / "labels.csv")
    original = published("EX010_20261017", "run-stock-lag-features").set_index("signal")
    cols = plan["baseline_columns"]
    check("baseline65", len(cols) == len(set(cols)) == 65)
    pd.testing.assert_frame_equal(f[cols], original[cols], check_exact=False, rtol=0, atol=1e-13)
    check("baseline_values", True)
    old_labels = published("EX008_20261017", "run-labels")
    pd.testing.assert_frame_equal(labels, old_labels, check_exact=False, rtol=0, atol=1e-13)
    check("labels_unchanged", True)
    observations = published("EX016_20261017", "ex016-annual_observations-csv").set_index("signal")
    splits = published("EX016_20261017", "ex016-others-annual_followup-json", False)["splits"]
    check("environment_splits", info["environment_splits"] == splits)
    check("environment_all_published_parent_rows", np.array_equal(
        f.loc[observations.index, "environment"], np.where(observations.high, "high", "low")))
    check("environment_initial_ready", int(f.index[f.environment.ne("unready")].min()) == 185)
    check("parent_definition", (f.A == (f.gap.lt(0) & f.intraday.gt(0))).all())
    np.testing.assert_allclose(f.z_old5, f.z.shift(5), rtol=0, atol=0, equal_nan=True)
    check("old5_causal_shift", True)
    check("methanol_source_rows", m.index.tolist() == list(range(2, 1642)))
    check("methanol_prefix_unready", f.z.iloc[:2].isna().all())

    prior = ROOT / "research/S014/materials/20261018_methanol_feasibility"
    completion = ROOT / "research/S014/materials/20261018_methanol_completion"
    def table(path):
        hashed(path)
        data = read(path)
        return pd.DataFrame(data["items"], columns=data["fields"])

    mapping = table(prior / "responses/call_02.json").set_index("trade_date")
    calendar = table(prior / "responses/call_04.json")
    opens = sorted(calendar.loc[calendar.is_open.eq(1), "cal_date"])
    raw = {}
    paths = [prior / f"responses/call_{n:02d}.json" for n in (5, 6, 7, 8)]
    for path in sorted((completion / "attempts").glob("call_*.json")):
        receipt = read(path)
        if receipt["status"] == "RECEIVED":
            response = ROOT / receipt["response_path"]
            check("source_receipt_" + path.stem, hashed(response) == receipt["response_sha256"])
            paths.append(response)
    for path in paths:
        rows = table(path)
        raw[rows.ts_code.iloc[0]] = rows.set_index("trade_date")
    check("raw22", len(raw) == 22)
    for row in m.itertuples():
        i = int(row.Index)
        p, q = opens[i - 1], opens[i - 2]
        k = mapping.loc[p, "mapping_ts_code"]
        rate = float(raw[k].loc[p, "close"] / raw[k].loc[q, "close"] - 1)
        check(f"methanol_{i}", row.contract == k and row.p.replace("-", "") == p
              and row.q.replace("-", "") == q and abs(row.r - rate) < 2e-15
              and row.z == float(rate > 0)
              and row.roll == (k != mapping.loc[q, "mapping_ts_code"]))
    closed = labels.loc[labels.status.eq("CLOSED")]
    expected = closed.quantity * (closed.exit_price * .999 - closed.entry_price * 1.001) / 100000
    np.testing.assert_allclose(closed.net_return, expected, rtol=0, atol=2e-14)
    check("cash_identity_all6334", len(closed) == 6334)
    check("lot_cash_limits", (closed.quantity.mod(100).eq(0)
          & (closed.quantity * closed.entry_price * 1.001 <= 100000 + 1e-7)).all())
    check("unfilled_zero", labels.loc[labels.status.eq("UNFILLED"), "net_return"].eq(0).all())
    check("censored_not_liquidated", labels.loc[labels.status.eq("RIGHT_CENSORED"), "net_return"].isna().all())
    for horizon, name in ((3, "Y3"), (1, "Y1")):
        rows = labels.loc[labels.horizon.eq(horizon)].set_index("signal")
        expected = rows.net_return.where(rows.maturity.ge(0)).reindex(f.index)
        np.testing.assert_allclose(f[name], expected, rtol=0, atol=1e-14, equal_nan=True)
        check(name + "_identity", True)
    valid = np.isfinite(f[cols + ["z", "z_old5"]].to_numpy(float)).all(1)
    check("feature_ready", (f.feature_ready == valid).all())
    check("label_ready", (f.label_ready == (f.Y3.notna() & f.maturity.ge(0))).all())
    predictions = pd.read_csv(OUT / "predictions.csv").set_index("signal")
    fit_receipt = read(OUT / "fit_receipt.json")
    check("prediction_hash", hashed(OUT / "predictions.csv") == fit_receipt["prediction_sha256"])
    fit_paths = sorted((OUT / "fits").glob("fit_*.json"))
    reservations = sorted((OUT / "fits").glob("reserved_*.json"))
    check("exact12slots", len(fit_paths) == len(reservations) == 12)
    expected_models = {"B": cols, "Bz": cols + ["z"], "Bold": cols + ["z_old5"]}
    seen = set()
    residuals = []
    all_test = set()
    for path in fit_paths:
        hashed(path)
        fit = read(path)
        year, model = fit["year"], fit["model"]
        check(path.stem + "_unique", (year, model) not in seen)
        seen.add((year, model))
        reservation = read(OUT / f"fits/reserved_{fit['slot']:02d}.json")
        check(path.stem + "_reserved", (reservation["year"], reservation["model"]) == (year, model))
        check(path.stem + "_identity", fit["input_sha256"] == input_hash
              and fit["status"] == "COMPLETE" and fit["columns"] == expected_models[model])
        full = f.loc[f.year.eq(year) & f.feature_ready]
        cut = int(full.index.min())
        train = f.loc[f.feature_ready & f.label_ready & f.maturity.lt(cut)]
        test = full.loc[full.label_ready]
        check(path.stem + "_time_rows", fit["cutoff"] == cut
              and fit["train_signals"] == train.index.tolist()
              and fit["test_signals"] == test.index.tolist()
              and fit["max_training_maturity"] == int(train.maturity.max()) < cut)
        all_test.update(test.index)
        x, xt = train[fit["columns"]].to_numpy(float), test[fit["columns"]].to_numpy(float)
        y = train.Y3.to_numpy(float)
        mean, scale = x.mean(0), x.std(0)
        scale[scale < 1e-12] = 1.0
        np.testing.assert_allclose(mean, fit["mean"], rtol=0, atol=1e-13)
        np.testing.assert_allclose(scale, fit["scale"], rtol=0, atol=1e-13)
        check(path.stem + "_preprocessing", abs(y.mean() - fit["y_mean"]) < 1e-14)
        xx = (x - mean) / scale
        coef = np.array(fit["coef"])
        # Verify the unique ridge optimum using stored coefficients. Never solve/refit.
        lhs = (xx.T @ xx + 10 * np.eye(len(coef))) @ coef
        rhs = xx.T @ (y - y.mean())
        error = float(np.max(np.abs(lhs - rhs)))
        residuals.append(error)
        check(path.stem + "_normal_equation", error < 1e-9)
        fitted = xx @ coef + y.mean()
        expected = (xt - mean) / scale @ coef + y.mean()
        np.testing.assert_allclose(expected, fit["predictions"], rtol=0, atol=1e-12)
        np.testing.assert_allclose(expected, predictions.loc[test.index, "score_" + model], rtol=0, atol=1e-12)
        check(path.stem + "_q75", abs(float(np.quantile(fitted, .75)) - fit["threshold"]) < 1e-12)
        check(path.stem + "_selection", np.array_equal(
            predictions.loc[test.index, "sel_" + model], np.array(fit["predictions"]) >= fit["threshold"]))
    check("four_years_three_models", seen == {(y, m) for y in (2023, 2024, 2025, 2026) for m in expected_models})
    check("complete_evaluation_rows", predictions.index.tolist() == sorted(all_test))
    check("fit_receipt", fit_receipt["fits_reserved"] == fit_receipt["fits_completed"] == 12
          and fit_receipt["failed_fits"] == 0 and fit_receipt["new_source_calls"] == 0
          and fit_receipt["new_accounts"] == 0)
    result = {
        "status": "PASS", "checks_count": len(checks), "checks": checks,
        "existing_fit_results_checked": 12, "new_model_fits": 0,
        "coefficient_validation": "stored coefficients satisfy ridge normal equations; predictions reconstructed by matrix multiplication only",
        "maximum_normal_equation_absolute_residual": max(residuals),
        "annual_environment_published_rows_matched": len(observations),
        "feature_first_ready_signal": int(f.index[f.feature_ready].min()),
        "evaluation_rows": len(predictions), "parent_rows": int(predictions.A.sum()),
        "new_source_calls": 0, "new_account_runs": 0,
        "inputs_sha256": inputs_used, "audit_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "input provenance, causal source identities, execution labels, sample splits and stored coefficient correctness; no claim of mechanism support",
    }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "checks_count", "existing_fit_results_checked", "new_model_fits", "parent_rows", "maximum_normal_equation_absolute_residual")}))


if __name__ == "__main__":
    main()
