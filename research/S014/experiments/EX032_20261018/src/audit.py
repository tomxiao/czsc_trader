"""Independent fixed-interaction audit using stored coefficients, never refits."""

from hashlib import sha256
import json
from pathlib import Path
import socket
from uuid import UUID

import numpy as np
import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    def prohibited(*args, **kwargs):
        raise RuntimeError("Independent audit forbids network and fitting")

    socket.socket.connect = prohibited
    socket.create_connection = prohibited
    np.linalg.solve = prohibited
    np.linalg.lstsq = prohibited
    target = OUT / "independent_audit.json"
    assert not target.exists(), "Preserve independent evidence"
    checks, hashes = [], {}

    def check(name, value):
        assert bool(value), name
        checks.append(name)

    def hashed(path):
        value = sha256(path.read_bytes()).hexdigest()
        hashes[path.relative_to(ROOT).as_posix()] = value
        return value

    def close(name, actual, expected, atol=2e-12):
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=atol, equal_nan=True)
        checks.append(name)

    def published(experiment, key):
        index = ROOT / f"research/S014/experiments/{experiment}/others/result.json"
        reference = read(index)["evidence"][key]
        path = EvidenceRef.from_dict(reference).resolve(ROOT)
        check("published_" + experiment + "_" + key, hashed(path) == reference["sha256"])
        return path, reference

    plan = read(EX / "protocols/design.json")
    check("authorized_budget", plan["execution_authorized"] and plan["proposed_fits_cap"] == 12)
    for lock in ["published_design", "run_lock"]:
        for name, reference in read(EX / f"protocols/{lock}.json").items():
            check("lock_" + name, hashed(ROOT / name) == reference["sha256"])
            check("resolved_lock_" + name,
                  EvidenceRef.from_dict(reference).resolve(ROOT).read_bytes() == (ROOT / name).read_bytes())
    info = read(OUT / "inputs.json")
    input_hash = hashed(OUT / "inputs.csv")
    check("input_hash", input_hash == info["input_sha256"])
    for filename, key in [("stock_hfq_close.csv", "stock_close_sha256"),
                          ("labels.csv", "label_sha256"), ("calendar.csv", "calendar_sha256")]:
        check("prepared_" + filename, hashed(OUT / filename) == info[key])
    f = pd.read_csv(OUT / "inputs.csv").set_index("signal")
    original_path, original_ref = published("EX031_20261018", "others/inputs.csv")
    original = pd.read_csv(original_path).set_index("signal")
    check("input_reference", original_ref == info["source_evidence"]["EX031_inputs"])
    check("signal_order", f.index.tolist() == original.index.tolist() == list(range(1642)))
    oldmeta_path, oldmeta_ref = published("EX031_20261018", "others/inputs.json")
    oldmeta = read(oldmeta_path)
    check("metadata_reference", oldmeta_ref == info["source_evidence"]["EX031_metadata"])
    check("data_reference", plan["data_reference"] == info["data_reference"] == oldmeta["data_reference"])
    check("inherited_evidence", info["inherited_evidence"] == oldmeta["source_evidence"])
    for name in ["labels", "calendar"]:
        path, reference = published("EX031_20261018", f"others/{name}.csv")
        check("immutable_" + name, path.read_bytes() == (OUT / f"{name}.csv").read_bytes())
        check("reference_" + name, reference == info["source_evidence"]["EX031_" + name])
    cols = plan["baseline_columns"]
    check("baseline65", len(cols) == len(set(cols)) == 65)
    for column in original.columns:
        if column in ["feature_ready", "label_ready"]:
            continue
        if pd.api.types.is_numeric_dtype(original[column]):
            close("inherited_" + column, f[column], original[column])
        else:
            check("inherited_" + column, f[column].fillna("MISSING").equals(original[column].fillna("MISSING")))

    ready_path, ready_ref = published("EX004_20261016", "input-readiness")
    check("stock_readiness_ref", ready_ref == info["source_evidence"]["stock_readiness"])
    records = [r for r in read(ready_path)["records"] if r["request"]["dataset"] == "stock.ohlcv"]
    check("single_stock_source", len(records) == 1)
    record = records[0]
    check("stock_binding", record == info["stock_binding"])
    request, binding = record["request"], record["reference"]
    check("stock_identity", request["symbol"] == "600722.SH" and record["rows"] == 1642)
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"),
                                      providers=ProviderConfig(bindings={}))
    fetched = context.data.fetch(
        DataRequest(Dataset(request["dataset"]), request["symbol"], request["start"],
                    request["end"], request["required_cutoff"]),
        prepared=PreparedDataRef(UUID(binding["space_id"]), UUID(binding["preparation_id"]),
                                 binding["manifest_sha256"]))
    check("bound_offline_stock", fetched.ready and fetched.identity.content_sha256 == record["content_sha256"])
    stock = fetched.dataframe.copy()
    stock["Date"] = pd.to_datetime(stock.Date)
    stock = stock.sort_values("Date").reset_index(drop=True)
    dates = pd.DatetimeIndex(pd.to_datetime(f.date))
    check("stock_dates", pd.DatetimeIndex(stock.Date).equals(dates) and not stock.Date.duplicated().any())
    saved_stock = pd.read_csv(OUT / "stock_hfq_close.csv")
    check("stock_saved_dates", pd.DatetimeIndex(pd.to_datetime(saved_stock.Date)).equals(dates))
    close("stock_saved_close", saved_stock.Close, stock.Close)
    check("stock_finite_positive", np.isfinite(stock.Close).all() and stock.Close.gt(0).all())
    prices = stock.set_index("Date").Close
    q_dates = pd.to_datetime(f.q)
    q_close = pd.Series(q_dates.map(prices), index=f.index)
    t_close = pd.Series(dates.map(prices), index=f.index)
    valid = t_close.notna() & q_close.notna() & t_close.gt(0) & q_close.gt(0)
    cumulative = (t_close / q_close - 1).where(valid)
    state = cumulative.le(0).astype(float).where(valid)
    close("exact_Q_close", f.hfq_close_Q, q_close)
    close("exact_T_close", f.hfq_close_T, t_close)
    close("cumulative_change", f.stock_cumulative_return, cumulative)
    close("state_S", f.S, state, atol=0)
    close("interaction_zS", f.zs, f.z * state, atol=0)
    ready_q = f.q.notna()
    check("Q_before_P", (q_dates[ready_q] < pd.to_datetime(f.loc[ready_q, "p"])).all())
    check("P_before_T", (pd.to_datetime(f.loc[ready_q, "p"]) < pd.to_datetime(f.loc[ready_q, "date"])).all())
    check("missing_Q_count", info["missing_exact_q"] == int((ready_q & q_close.isna()).sum()))
    close("old5_diagnostic", f.z_old5, f.z.shift(5), atol=0)
    expected_ready = np.isfinite(f[cols + ["S", "z"]].to_numpy(float)).all(axis=1)
    check("common_feature_ready", np.array_equal(f.feature_ready, expected_ready))
    check("common_label_ready", f.label_ready.equals(f.Y3.notna() & f.maturity.ge(0)))
    check("parent_A", f.A.equals(f.gap.lt(0) & f.intraday.gt(0)))
    labels = pd.read_csv(OUT / "labels.csv")
    closed = labels.loc[labels.status.eq("CLOSED")]
    close("existing_cash_identity", closed.net_return,
          closed.quantity * (closed.exit_price - closed.entry_price - .001 * (closed.entry_price + closed.exit_price)) / 100000)
    check("quantity_lot100", closed.quantity.mod(100).eq(0).all())
    check("unfilled_zero", labels.loc[~labels.entry_filled, "net_return"].dropna().eq(0).all())
    h3 = labels.loc[labels.horizon.eq(3)].set_index("signal")
    h1 = labels.loc[labels.horizon.eq(1)].set_index("signal")
    close("same_H3_label", f.Y3, h3.net_return.reindex(f.index))
    close("same_H3_maturity", f.maturity, h3.maturity.reindex(f.index), atol=0)
    close("same_H1_label", f.Y1, h1.net_return.where(h1.maturity.ge(0)).reindex(f.index))
    common = f.Y1.notna() & f.Y3.notna() & f.maturity.ge(0)
    close("same_entry_h1_h3", f.loc[common, "entry"], h1.entry.reindex(f.index[common]), atol=0)
    close("same_quantity_h1_h3", f.loc[common, "quantity"], h1.quantity.reindex(f.index[common]), atol=0)

    variants = {"M0": cols + ["S"], "M1": cols + ["S", "z"], "M2": cols + ["S", "z", "zs"]}
    receipt = read(OUT / "fit_receipt.json")
    check("budget_receipt", receipt["status"] == "COMPLETE" and receipt["fits_reserved"] == 12
          and receipt["fits_completed"] == 12 and receipt["failed_fits"] == 0 and receipt["fits_remaining"] == 0)
    check("reserved_count", len(list((OUT / "fits").glob("reserved_*.json"))) == 12)
    check("fit_count", len(list((OUT / "fits").glob("fit_*.json"))) == 12)
    check("failure_count", not list((OUT / "fits").glob("failed_*.json")))
    prediction_hash = hashed(OUT / "predictions.csv")
    check("prediction_hash", prediction_hash == receipt["prediction_sha256"])
    prediction = pd.read_csv(OUT / "predictions.csv").set_index("signal")
    slot, all_tests, residuals, prediction_errors = 0, [], [], []
    for year in plan["evaluation_years"]:
        full = f.loc[f.year.eq(year) & expected_ready]
        cutoff = int(full.index.min())
        test_ids = full.index[full.label_ready].tolist()
        train_ids = f.index[expected_ready & f.label_ready & f.maturity.lt(cutoff)].tolist()
        all_tests.extend(test_ids)
        for name, columns in variants.items():
            slot += 1
            reserved = read(OUT / f"fits/reserved_{slot:02d}.json")
            path = OUT / f"fits/fit_{slot:02d}.json"
            hashed(path)
            fit = read(path)
            prefix = f"fit_{slot:02d}_"
            check(prefix + "reservation", reserved["slot"] == slot and reserved["year"] == year
                  and reserved["model"] == name and reserved["failure_counts"])
            check(prefix + "identity", fit["slot"] == slot and fit["year"] == year and fit["model"] == name)
            check(prefix + "columns", fit["columns"] == columns)
            check(prefix + "training", fit["train_signals"] == train_ids)
            check(prefix + "test", fit["test_signals"] == test_ids)
            check(prefix + "cutoff", fit["cutoff"] == cutoff and f.loc[train_ids, "maturity"].max() < cutoff)
            check(prefix + "maturity", fit["max_training_maturity"] == f.loc[train_ids, "maturity"].max())
            check(prefix + "input_hash", fit["input_sha256"] == input_hash)
            x = f.loc[train_ids, columns].to_numpy(float)
            y = f.loc[train_ids, "Y3"].to_numpy(float)
            mu, scale = x.mean(0), x.std(0)
            scale[scale < 1e-12] = 1
            close(prefix + "mean", fit["mean"], mu)
            close(prefix + "scale", fit["scale"], scale)
            close(prefix + "y_mean", fit["y_mean"], y.mean())
            standardized = (x - mu) / scale
            coef = np.asarray(fit["coef"])
            lhs = (standardized.T @ standardized + 10 * np.eye(len(columns))) @ coef
            rhs = standardized.T @ (y - y.mean())
            residual = float(np.max(np.abs(lhs - rhs)))
            residuals.append(residual)
            close(prefix + "normal_equation", lhs, rhs, atol=1e-9)
            train_scores = standardized @ coef + y.mean()
            threshold = float(np.quantile(train_scores, .75))
            close(prefix + "threshold", fit["threshold"], threshold)
            scores = (f.loc[test_ids, columns].to_numpy(float) - mu) / scale @ coef + y.mean()
            close(prefix + "saved_prediction", fit["predictions"], scores)
            close(prefix + "published_prediction", prediction.loc[test_ids, "score_" + name], scores)
            check(prefix + "selection", np.array_equal(prediction.loc[test_ids, "sel_" + name], scores >= threshold))
            prediction_errors.append(float(np.max(np.abs(np.asarray(fit["predictions"]) - scores))))
    check("evaluation_order", prediction.index.tolist() == all_tests)
    check("receipt_rows", len(prediction) == receipt["evaluation_rows"] and int(prediction.A.sum()) == receipt["parent_rows"])
    for column in f.columns:
        expected = f.loc[all_tests, column]
        if pd.api.types.is_numeric_dtype(expected):
            close("evaluation_inherited_" + column, prediction[column], expected)
        else:
            check("evaluation_inherited_" + column,
                  np.array_equal(prediction[column].fillna("MISSING").to_numpy(),
                                 expected.fillna("MISSING").to_numpy()))
    hashed(Path(__file__))
    result = {
        "status": "PASS", "checks": len(checks), "check_names": checks,
        "fits_audited": slot, "evaluation_rows": len(prediction), "parent_rows": int(prediction.A.sum()),
        "closed_cash_identities": len(closed), "max_normal_equation_residual": max(residuals),
        "max_prediction_reconstruction_error": max(prediction_errors),
        "new_fits": 0, "new_labels": 0, "new_accounts": 0, "new_upstream_calls": 0,
        "method": "Pinned source identity, exact-date stock close mapping, unchanged cash labels, stored-coefficient normal-equation and prediction checks. np.linalg.solve/lstsq and network prohibited.",
        "limitations": ["Does not establish positive economic utility.", "Outcome statistics beyond stored predictions require their own verification."],
        "source_sha256": hashes,
    }
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ["status", "checks", "fits_audited", "evaluation_rows", "parent_rows", "max_normal_equation_residual"]}))


if __name__ == "__main__":
    main()
