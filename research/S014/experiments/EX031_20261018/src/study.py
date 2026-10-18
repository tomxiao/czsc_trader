"""Authorized EX031 offline inputs and exactly twelve fixed ridge fits."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
import json
import socket
import sys
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write(p, obj):
    p.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def csv(p, df):
    df.to_csv(p, index=False, lineterminator="\n")


def block_network(*a, **k):
    raise RuntimeError("EX031 forbids all network access")


def offline():
    socket.socket.connect = block_network
    socket.create_connection = block_network


def source(ex, key):
    r = read(ROOT / f"research/S014/experiments/{ex}/others/result.json")["evidence"][key]
    ref = EvidenceRef.from_dict(r)
    p = ref.resolve(ROOT)
    assert sha256(p.read_bytes()).hexdigest() == ref.sha256
    return p, r


def precheck():
    design = read(EX / "protocols/design.json")
    assert design["execution_authorized"] and design["planned_formal_fits_cap"] == 12
    assert len(set(design["baseline_columns"])) == 65
    # Algebra, boundaries and accounting only: zero model fits.
    assert (100 / 100 - 1 > 0) is False and (101 / 100 - 1 > 0) is True
    assert 1000 * (11 - 10 - 0.001 * (11 + 10)) / 100000 == 0.00979
    raw = pd.Series([0.0, 1.0, 0.0, 1.0, 1.0, 0.0])
    assert raw.shift(5).iloc[5] == 0 and raw.shift(5).iloc[:5].isna().all()
    assert not (np.array([2, 3, 4]) < 3)[1]
    write(
        OUT / "precheck.json",
        {"status": "PASS", "checks": 6, "formal_fits": 0, "new_accounts": 0, "new_source_calls": 0},
    )


def prepare():
    offline()
    assert not (OUT / "inputs.json").exists(), "Preserve prepared inputs"
    locked = read(EX / "protocols/published_design.json")
    for rel, ref in locked.items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT / rel).read_bytes()
    plan = read(EX / "protocols/design.json")
    refs = {}
    p, refs["features"] = source("EX010_20261017", "run-stock-lag-features")
    f = pd.read_csv(p).set_index("signal")
    p, refs["labels"] = source("EX008_20261017", "run-labels")
    labels = pd.read_csv(p)
    _, refs["entry_execution"] = source("EX008_20261017", "run-entries")
    _, refs["execution_audit"] = source("EX008_20261017", "audit")
    p, refs["annual_environment"] = source("EX016_20261017", "ex016-others-annual_followup-json")
    splits = read(p)["splits"]
    assert len(f) == 1642 and f.index.tolist() == list(range(1642))
    assert set(plan["baseline_columns"]) <= set(f.columns)
    assert not labels.duplicated(["signal", "horizon"]).any()
    closed = labels.loc[labels.status.eq("CLOSED")]
    expected = (
        closed.quantity
        * (
            closed.exit_price
            - closed.entry_price
            - 0.001 * (closed.entry_price + closed.exit_price)
        )
        / 100000
    )
    np.testing.assert_allclose(closed.net_return, expected, rtol=0, atol=2e-14)
    assert (closed.quantity % 100 == 0).all()
    assert labels.loc[~labels.entry_filled, "net_return"].dropna().eq(0).all()
    acceptance = read(ROOT / "research/S014/materials/20261018_methanol_completion/acceptance.json")
    assert acceptance["prepared"] == plan["data_reference"]
    v = acceptance["prepared"]
    bound = PreparedDataRef(UUID(v["space_id"]), UUID(v["preparation_id"]), v["manifest_sha256"])
    ctx = create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S014"),
        providers=ProviderConfig(bindings={}),
    )
    tables = {}
    identities = []
    for asset in acceptance["assets"]:
        req = DataRequest(
            Dataset(asset["dataset"]), asset["symbol"], asset["start"], asset["end"], asset["end"]
        )
        result = ctx.data.fetch(req, prepared=bound)
        assert result.ready and result.identity.content_sha256 == asset["content_sha256"]
        tables[asset["symbol"]] = result.dataframe
        identities.append({"symbol": asset["symbol"], "sha256": asset["content_sha256"]})
    cal = tables["CZCE"]
    dates = pd.DatetimeIndex(cal.loc[cal.IsOpen.eq(1), "Date"])
    assert len(dates) == 1642
    for row in labels.itertuples():
        assert pd.Timestamp(row.signal_date) == dates[row.signal]
    f["date"] = dates
    f["year"] = dates.year
    f["A"] = f.gap.lt(0) & f.intraday.gt(0)
    assert (f.A == f.gap_down_repair.eq(1)).all()
    mapping = tables["MA.ZCE"].set_index("Date")
    meth = []
    for i in range(2, len(dates)):
        t, p, q = dates[i], dates[i - 1], dates[i - 2]
        k = mapping.loc[p, "Contract"]
        tab = tables[k].set_index("Date")
        a, b = tab.loc[p], tab.loc[q]
        assert max(
            a.AvailableDate, b.AvailableDate, mapping.loc[p, "AvailableDate"]
        ) <= t + pd.Timedelta(hours=15)
        assert a.Close > 0 and b.Close > 0 and a.Volume > 0 and b.Volume > 0
        r = float(a.Close / b.Close - 1)
        meth.append(
            {
                "signal": i,
                "contract": k,
                "p": str(p.date()),
                "q": str(q.date()),
                "r": r,
                "z": float(r > 0),
                "roll": bool(k != mapping.loc[q, "Contract"]),
            }
        )
    m = pd.DataFrame(meth).set_index("signal")
    f = f.join(m)
    f["z_old5"] = f.z.shift(5)
    f["environment"] = "unready"
    corr = f.gap.rolling(20).corr(f.gap.shift())
    for s in splits:
        mask = (f.year == s["year"]) & (f.index >= s["signal"]) & corr.notna()
        f.loc[mask, "environment"] = np.where(corr.loc[mask] >= s["threshold"], "high", "low")
    h3 = labels.loc[labels.horizon.eq(3)].set_index("signal")
    h1 = labels.loc[labels.horizon.eq(1)].set_index("signal")
    for dest, origin in [
        ("Y3", "net_return"),
        ("maturity", "maturity"),
        ("entry", "entry"),
        ("entry_filled", "entry_filled"),
        ("quantity", "quantity"),
        ("entry_price", "entry_price"),
        ("exit_price", "exit_price"),
    ]:
        f[dest] = h3[origin].reindex(f.index)
    f["Y1"] = h1.net_return.where(h1.maturity.ge(0)).reindex(f.index)
    f["h1_maturity"] = h1.maturity.reindex(f.index)
    f["h1_entry"] = h1.entry.reindex(f.index)
    f["h1_quantity"] = h1.quantity.reindex(f.index)
    common = f.Y1.notna() & f.Y3.notna() & f.maturity.ge(0)
    assert (f.loc[common, "entry"] == f.loc[common, "h1_entry"]).all()
    assert (f.loc[common, "quantity"] == f.loc[common, "h1_quantity"]).all()
    assert (
        f.loc[common, "entry_price"].fillna(-1)
        == h1.entry_price.reindex(f.index[common]).fillna(-1)
    ).all()
    f["feature_ready"] = np.isfinite(
        f[plan["baseline_columns"] + ["z", "z_old5"]].to_numpy(float)
    ).all(1)
    f["label_ready"] = f.Y3.notna() & f.maturity.ge(0)
    csv(OUT / "inputs.csv", f.reset_index())
    csv(
        OUT / "calendar.csv",
        pd.DataFrame({"signal": range(1642), "date": dates, "year": dates.year}),
    )
    csv(
        OUT / "descriptive.csv",
        f.loc[
            f.A & f.z.notna() & f.label_ready,
            [
                "date",
                "year",
                "A",
                "z",
                "z_old5",
                "roll",
                "environment",
                "Y3",
                "Y1",
                "maturity",
                "entry",
                "entry_filled",
            ],
        ].reset_index(),
    )
    csv(OUT / "labels.csv", labels)
    csv(OUT / "methanol.csv", m.reset_index())
    coverage = []
    for y, g in f.groupby("year"):
        a = g.A
        coverage.append(
            {
                "year": int(y),
                "calendar": len(g),
                "parent": int(a.sum()),
                "methanol_ready_parent": int((a & g.z.notna()).sum()),
                "feature_ready_parent": int((a & g.feature_ready).sum()),
                "mature_parent": int((a & g.feature_ready & g.label_ready).sum()),
                "missing_historical_label_parent": int(
                    (a & g.feature_ready & g.maturity.isna()).sum()
                ),
                "unmature_parent": int((a & g.feature_ready & g.maturity.lt(0)).sum()),
            }
        )
    csv(OUT / "coverage.csv", pd.DataFrame(coverage))
    write(
        OUT / "inputs.json",
        {
            "status": "PASS",
            "source_evidence": refs,
            "data_reference": v,
            "assets": identities,
            "input_sha256": sha256((OUT / "inputs.csv").read_bytes()).hexdigest(),
            "label_source_rows": len(labels),
            "closed_cash_checks": len(closed),
            "methanol_rows": len(m),
            "environment_splits": splits,
            "coverage": coverage,
            "source_calls": 0,
            "new_labels": 0,
            "accounts": 0,
        },
    )
    print(
        json.dumps(
            {"input_status": "PASS", "methanol_rows": len(m), "label_cash_checks": len(closed)}
        )
    )


def fit_worker(task):
    offline()
    slot, year, name, cols, train_ids, test_ids, cut = task
    f = pd.read_csv(OUT / "inputs.csv").set_index("signal")
    x = f.loc[train_ids, cols].to_numpy(float)
    xt = f.loc[test_ids, cols].to_numpy(float)
    y = f.loc[train_ids, "Y3"].to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(xt).all() and np.isfinite(y).all()
    mean = x.mean(0)
    scale = x.std(0)
    scale[scale < 1e-12] = 1.0
    xx = (x - mean) / scale
    yy = y - y.mean()
    coef = np.linalg.solve(xx.T @ xx + 10 * np.eye(len(cols)), xx.T @ yy)
    trained = xx @ coef + y.mean()
    prediction = (xt - mean) / scale @ coef + y.mean()
    threshold = float(np.quantile(trained, 0.75))
    result = {
        "slot": slot,
        "year": year,
        "model": name,
        "status": "COMPLETE",
        "columns": cols,
        "train_signals": train_ids,
        "test_signals": test_ids,
        "cutoff": cut,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coef": coef.tolist(),
        "y_mean": float(y.mean()),
        "threshold": threshold,
        "predictions": prediction.tolist(),
        "max_training_maturity": int(f.loc[train_ids, "maturity"].max()),
        "input_sha256": sha256((OUT / "inputs.csv").read_bytes()).hexdigest(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    write(OUT / f"fits/fit_{slot:02d}.json", result)
    return slot


def fit():
    offline()
    assert not (OUT / "fits").exists(), "No repeat model fitting"
    assert read(OUT / "inputs.json")["status"] == "PASS"
    f = pd.read_csv(OUT / "inputs.csv").set_index("signal")
    plan = read(EX / "protocols/design.json")
    cols = plan["baseline_columns"]
    variants = {"B": cols, "Bz": cols + ["z"], "Bold": cols + ["z_old5"]}
    tasks = []
    test_all = []
    for year in plan["evaluation_years"]:
        full = f.loc[f.year.eq(year) & f.feature_ready]
        cut = int(full.index.min())
        test = full.loc[full.label_ready]
        train = f.loc[f.feature_ready & f.label_ready & f.maturity.lt(cut)]
        assert len(train) > len(cols) and train.maturity.max() < cut
        test_all.extend(test.index.tolist())
        for name, cs in variants.items():
            tasks.append(
                (
                    len(tasks) + 1,
                    year,
                    name,
                    cs,
                    list(map(int, train.index)),
                    list(map(int, test.index)),
                    cut,
                )
            )
    assert len(tasks) == 12
    (OUT / "fits").mkdir()
    # Reserve each slot before dispatch, including unknown/failed outcomes.
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        jobs = []
        for task in tasks:
            slot, year, name, *_ = task
            with (OUT / f"fits/reserved_{slot:02d}.json").open("x", encoding="utf-8") as h:
                json.dump(
                    {
                        "slot": slot,
                        "year": year,
                        "model": name,
                        "reserved_utc": datetime.now(timezone.utc).isoformat(),
                    },
                    h,
                )
            jobs.append(pool.submit(fit_worker, task))
        for job in jobs:
            job.result()
    p = f.loc[
        test_all,
        [
            "date",
            "year",
            "A",
            "z",
            "z_old5",
            "roll",
            "environment",
            "Y3",
            "Y1",
            "maturity",
            "entry",
            "entry_filled",
        ],
    ].copy()
    for slot, year, name, *_ in tasks:
        r = read(OUT / f"fits/fit_{slot:02d}.json")
        ix = r["test_signals"]
        p.loc[ix, f"score_{name}"] = r["predictions"]
        p.loc[ix, f"sel_{name}"] = np.array(r["predictions"]) >= r["threshold"]
    csv(OUT / "predictions.csv", p.reset_index())
    write(
        OUT / "fit_receipt.json",
        {
            "status": "COMPLETE",
            "fits_reserved": 12,
            "fits_completed": 12,
            "failed_fits": 0,
            "models": list(variants),
            "evaluation_rows": len(p),
            "parent_rows": int(p.A.sum()),
            "max_workers": 2,
            "native_threads": 1,
            "new_source_calls": 0,
            "new_accounts": 0,
            "prediction_sha256": sha256((OUT / "predictions.csv").read_bytes()).hexdigest(),
        },
    )
    print(json.dumps(read(OUT / "fit_receipt.json")))


if __name__ == "__main__":
    {"precheck": precheck, "prepare": prepare, "fit": fit}[sys.argv[1]]()
