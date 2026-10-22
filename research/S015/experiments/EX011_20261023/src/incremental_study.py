"""Fixed, chronological component follow-up; no account or strategy search."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (
    EvidenceRef,
    ExecutionResources,
    ExperimentRef,
    MaterialEvidenceWrite,
    ResearchBatchRef,
)

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parents[1]
EX = ExperimentRef("S015", HERE.name)
WORK = ROOT / "research/S015/assets/runs" / HERE.name / "incremental_information"
OLD = ROOT / "research/S015/experiments/EX010_20261023"
COMPONENTS = ("afternoon", "afternoon_reversal")
BASE = ["base_r1", "base_r5", "base_vol20", "pressure"]
FOLDS = ((100, 184), (184, 268), (268, 352), (352, 434))


def read(p):
    return json.loads(p.read_bytes())


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )


def context():
    return create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S015"),
        resources=ExecutionResources(max_workers=1, native_threads_per_worker=1, random_seed=13),
    )


def material(p):
    media = {
        ".py": "text/x-python",
        ".json": "application/json",
        ".csv": "text/csv",
        ".md": "text/markdown",
    }[p.suffix]
    return publish_evidence(
        context(), MaterialEvidenceWrite(EX, p.stem, p.read_bytes(), media, p.suffix[1:])
    )


def inherited():
    refs = {
        r["name"]: EvidenceRef.from_dict(r)
        for r in read(OLD / "others/published_refs.json")["references"]
    }
    names = (
        "component_study",
        "component_protocol",
        "input_facts",
        "event_labels",
        "archive_diagnosis_S011-v1",
        "archive_diagnosis_C0031",
        "component_results",
    )
    for name in names:
        refs[name].resolve(ROOT)
    source = OLD / "src/component_study.py"
    assert sha256(source.read_bytes()).hexdigest() == refs["component_study"].sha256
    spec = importlib.util.spec_from_file_location("prior_component_study", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return refs, module


def prepare():
    assert not (HERE / "others/protocol_refs.json").exists()
    refs, _ = inherited()
    authorization = {
        "user_instruction": "请你自主完成阶段二",
        "interpretation": "完成S015新目标阶段二的必要增量补证、反证检查和研究判断；阶段三另行决定。",
        "branch": "codex/s015-stage2-dual-objective",
        "base_head": "761f4e399d999f595e86fcadfe526117ccfeb541",
        "scope": "现有159326.SZ日线和30分钟数据，截止2026-10-21；不增加策略账户、候选、搜索或新数据。",
    }
    save(HERE / "others/authorization.json", authorization)
    protocol = {
        "stage": 2,
        "mandate": "MANDATE/3",
        "parent": "COMPONENTS/4",
        "question": "分钟组件在已有日线卖压和振幅以外，是否有稳定的短期收益或下行风险增量？",
        "hypotheses": {
            "afternoon": "午后下跌可能代表短暂流动性压力，随后反弹；竞争解释是全天卖压的重复代理或持续坏消息。",
            "afternoon_reversal": "午后相对上午转弱可能保留日内时序信息；竞争解释是噪声、市场阶段或极少极端日。",
        },
        "primary": "PR baseline: r1/r5/vol20 + pressure + calm_range, versus adding ONE minute component. 2 components x 3 horizons = 6 paired comparisons.",
        "sensitivity": "P: omit calm_range; PROther: PR plus the OTHER minute component. 12 further paired comparisons, not hidden primary trials.",
        "total_budget": {
            "paired_comparisons": 18,
            "outcomes_per_comparison": 2,
            "folds": 4,
            "new_strategy_accounts": 0,
            "parameter_searches": 0,
        },
        "horizons": [1, 2, 3],
        "components": list(COMPONENTS),
        "folds": FOLDS,
        "model": "Ridge alpha10, intercept unpenalized, training-only mean/std. All labels must exit strictly before first test decision. No test-driven tuning.",
        "grouping": "Negative minute residual after training-only ridge on baseline; training residual terciles. Higher score means relatively weaker afternoon, following observed EX010 reversal. No threshold search.",
        "selection_disclosure": "EX010 results and all development samples already seen. Components, inverse orientation and controls chosen after EX010. This is conditional developmental evidence, NOT a fresh holdout or confirmation.",
        "labels": "Reuse authenticated EX010 independent 100k event labels, T+1 limit buy and T+h+1 market sell, .1% each way; conservative entry-day inclusive downside geometry. No equity curve from overlapping labels.",
        "cost_sensitivity": "At identical fills/quantities deduct another .1% buy+sell notional. Fee-only sensitivity, not a resized .2% executable account or cost acceptance.",
        "diagnostics": [
            "2025/2026 and four folds",
            "leave out five largest absolute labels",
            "fixed archived S011/C0031 end-of-T position states",
            "gain/loss opportunity fractions for each residual tercile",
            "499 moving-block10 and block20 gain intervals, seed13",
        ],
        "uncertainty": "Bootstrap resamples chronological prediction losses, not model fitting; intervals exploratory, shared samples and many comparisons preclude confirmatory significance claims.",
        "judgment": "RSCH synthesizes direction, incremental loss, consistency, concentration and uncertainty; no added strategy hard acceptance gates. Negative or inconclusive results close stage2 validly.",
        "availability": "T17:30 features only through T15:00 bars. Provider historical publication clock not independently certified. Existing data and prepared hashes unchanged.",
        "resources": {"processes": 1, "native_threads": 1, "seed": 13},
        "inherited_evidence": {
            k: refs[k].to_dict()
            for k in (
                "component_study",
                "component_protocol",
                "input_facts",
                "event_labels",
                "archive_diagnosis_S011-v1",
                "archive_diagnosis_C0031",
                "component_results",
            )
        },
    }
    save(HERE / "protocols/incremental_protocol.json", protocol)
    published = {
        p.name: material(p).to_dict()
        for p in (
            HERE / "others/authorization.json",
            HERE / "protocols/incremental_protocol.json",
            Path(__file__),
        )
    }
    save(HERE / "others/protocol_refs.json", published)
    print("EX011 protocol/source published before follow-up computation", flush=True)


def ridge(train, y, test):
    mean, sd = train.mean(0), train.std(0)
    sd = np.where(sd < 1e-12, 1, sd)
    a = (train - mean) / sd
    beta = np.linalg.solve(a.T @ a + 10 * np.eye(a.shape[1]), a.T @ (y - y.mean()))
    return y.mean() + ((test - mean) / sd) @ beta


def summary(g):
    out = {"n": len(g)}
    for target in ("return", "risk"):
        baseline = g[f"{target}_base_loss"].mean()
        out[f"{target}_gain"] = float(1 - g[f"{target}_added_loss"].mean() / baseline)
    positive, negative = g.label.clip(lower=0), (-g.label).clip(lower=0)
    for group in (-1, 0, 1):
        selected = g.group.eq(group)
        out[f"group_{group}"] = {
            "n": int(selected.sum()),
            "mean_label": float(g.loc[selected, "label"].mean()) if selected.any() else None,
            "mean_fee_sensitive_label": float(g.loc[selected, "fee_sensitive_label"].mean())
            if selected.any()
            else None,
            "mean_downside": float(g.loc[selected, "downside"].mean()) if selected.any() else None,
            "positive_amount_fraction": float(positive[selected].sum() / positive.sum())
            if positive.sum()
            else None,
            "negative_amount_fraction": float(negative[selected].sum() / negative.sum())
            if negative.sum()
            else None,
        }
    out["high_low_return"] = (
        float(g.loc[g.group.eq(1), "label"].mean() - g.loc[g.group.eq(-1), "label"].mean())
        if g.group.eq(1).any() and g.group.eq(-1).any()
        else None
    )
    return out


def intervals(g, block):
    rng = np.random.default_rng(13)
    n = len(g)
    draws = []
    for _ in range(499):
        starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
        ids = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        draws.append(
            [
                1
                - g[f"{t}_added_loss"].to_numpy()[ids].mean()
                / g[f"{t}_base_loss"].to_numpy()[ids].mean()
                for t in ("return", "risk")
            ]
        )
    ci = np.quantile(draws, [0.025, 0.975], axis=0)
    return {t: ci[:, i].tolist() for i, t in enumerate(("return", "risk"))}


def evaluate(x, labels, component, horizon, control):
    columns = BASE.copy()
    if control != "P":
        columns.append("calm_range")
    if control == "PROther":
        columns.append(next(c for c in COMPONENTS if c != component))
    b = x[columns].to_numpy(float)
    f = x[component].to_numpy(float)
    lab = labels[labels.horizon.eq(horizon)].set_index("signal_date")
    y = x.date.map(lab.label).to_numpy(float)
    risk = x.date.map(lab.downside).to_numpy(float)
    end = x.date.map(lab.label_end_position).to_numpy(float)
    fee_extra = x.date.map(
        lab.quantity * (lab.buy_price + lab.sell_price) * 0.001 / 100000
    ).to_numpy(float)
    valid = (
        np.isfinite(y)
        & np.isfinite(risk)
        & np.isfinite(f)
        & np.isfinite(b).all(1)
        & x.date.map(lab.status).eq("FILLED").to_numpy()
    )
    positions = np.arange(len(x))
    records = []
    for fold, (left, right) in enumerate(FOLDS):
        start, stop = left + 75, right + 75
        train = np.flatnonzero(valid & (positions < start) & (end < start))
        test = np.flatnonzero(valid & (positions >= start) & (positions < stop))
        assert len(train) > 80 and len(test) > 20
        train_score = -(f[train] - ridge(b[train], f[train], b[train]))
        score = -(f[test] - ridge(b[train], f[train], b[test]))
        q1, q2 = np.quantile(train_score, [1 / 3, 2 / 3])
        group = np.where(score >= q2, 1, np.where(score <= q1, -1, 0))
        added = np.column_stack((b, f))
        predictions = {}
        for target, outcome in (("return", y), ("risk", risk)):
            for name, matrix in (("base", b), ("added", added)):
                predictions[f"{target}_{name}"] = ridge(matrix[train], outcome[train], matrix[test])
        for j, p in enumerate(test):
            row = {
                "date": x.date.iloc[p],
                "component": component,
                "horizon": horizon,
                "control": control,
                "fold": fold,
                "group": int(group[j]),
                "residual_score": float(score[j]),
                "label": float(y[p]),
                "fee_sensitive_label": float(y[p] - fee_extra[p]),
                "downside": float(risk[p]),
                "train_n": len(train),
                "train_last_exit": int(end[train].max()),
                "test_start": start,
            }
            for k, pred in predictions.items():
                row[k + "_prediction"] = float(pred[j])
                row[k + "_loss"] = float(
                    (pred[j] - (y[p] if k.startswith("return") else risk[p])) ** 2
                )
            for account in ("S011-v1", "C0031"):
                row[account + "_held"] = bool(x[account + "_held"].iloc[p])
            records.append(row)
    g = pd.DataFrame(records)
    result = {
        "component": component,
        "horizon": horizon,
        "control": control,
        "summary": summary(g),
        "years": {str(k): summary(v) for k, v in g.groupby(g.date.str[:4])},
        "folds": {str(k): summary(v) for k, v in g.groupby("fold")},
        "drop_top5_abs_label": summary(g.drop(g.label.abs().nlargest(5).index)),
        "gain_intervals": {str(block): intervals(g, block) for block in (10, 20)},
        "states": {
            account: {str(k): summary(v) for k, v in g.groupby(account + "_held")}
            for account in ("S011-v1", "C0031")
        },
    }
    return result, records


def run():
    assert not (HERE / "others/incremental_results.json").exists()
    prerefs = read(HERE / "others/protocol_refs.json")
    for name, ref in prerefs.items():
        EvidenceRef.from_dict(ref).resolve(ROOT)
        path = (
            Path(__file__)
            if name.endswith(".py")
            else HERE / ("protocols" if "protocol" in name else "others") / name
        )
        assert sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    refs, previous = inherited()
    raw, adjusted, minute, facts = previous.inputs()
    prior_facts = read(refs["input_facts"].resolve(ROOT))
    assert facts["identities"] == prior_facts["identities"]
    x = previous.features(raw, minute)
    assert np.isfinite(x.iloc[75:].to_numpy(float)).all()
    changed = raw.copy()
    changed.loc[301:, "Close"] *= 1.05
    clipped_m = minute[
        pd.to_datetime(minute.Date).dt.normalize() <= pd.Timestamp(raw.Date.iloc[300])
    ]
    np.testing.assert_allclose(
        x.iloc[:301],
        previous.features(changed, clipped_m).iloc[:301],
        rtol=0,
        atol=0,
        equal_nan=True,
    )
    x.insert(0, "date", pd.to_datetime(raw.Date).dt.strftime("%Y-%m-%d"))
    for account in ("S011-v1", "C0031"):
        daily = pd.read_csv(refs["archive_diagnosis_" + account].resolve(ROOT))
        x[account + "_held"] = x.date.map(daily.set_index("date").quantity.gt(0).to_dict())
        assert x.loc[x.date.ge("2025-02-06"), account + "_held"].notna().all()
    WORK.mkdir(parents=True, exist_ok=True)
    x.to_csv(WORK / "features_reconstructed.csv", index=False)
    labels = pd.read_csv(refs["event_labels"].resolve(ROOT))
    reconstructed = previous.event_labels(adjusted, raw)
    pd.testing.assert_frame_equal(labels, reconstructed, check_dtype=False, rtol=1e-11, atol=1e-14)
    result, events = [], []
    for control in ("PR", "P", "PROther"):
        for component in COMPONENTS:
            for horizon in (1, 2, 3):
                r, records = evaluate(x, labels, component, horizon, control)
                result.append(r)
                events.extend(records)
    frame = pd.DataFrame(events)
    assert not frame.duplicated(["component", "horizon", "control", "date"]).any()
    assert (frame.train_last_exit < frame.test_start).all()
    assert frame.date.max() <= "2026-10-21"
    frame.to_csv(WORK / "forward_predictions.csv", index=False)
    save(HERE / "others/input_facts.json", facts)
    save(
        HERE / "others/incremental_results.json",
        {
            "source_sha256": prerefs[Path(__file__).name]["sha256"],
            "paired_comparisons": 18,
            "primary_comparisons": 6,
            "comparisons": result,
        },
    )
    # An independent augmented least-squares solution checks the ridge convention.
    rng = np.random.default_rng(91)
    a, y, b = rng.normal(size=(100, 6)), rng.normal(size=100), rng.normal(size=(20, 6))
    aa = (a - a.mean(0)) / a.std(0)
    beta = np.linalg.lstsq(
        np.vstack((aa, np.sqrt(10) * np.eye(6))),
        np.concatenate((y - y.mean(), np.zeros(6))),
        rcond=None,
    )[0]
    np.testing.assert_allclose(
        ridge(a, y, b), y.mean() + ((b - a.mean(0)) / a.std(0)) @ beta, atol=1e-14
    )
    repeat, _ = evaluate(x, labels, "afternoon", 1, "PR")
    assert repeat == result[0]
    checks = {
        "status": "PASS",
        "input_hashes_unchanged": True,
        "feature_causal_future_perturbation": "PASS",
        "published_labels_exact_reconstruction": "PASS",
        "ridge_independent_lstsq": "PASS",
        "deterministic_repeat": "PASS",
        "chronological_purge": "PASS",
        "published_source_equals_executed": True,
        "paired_comparisons": 18,
        "forward_prediction_rows": len(frame),
        "new_strategy_accounts": 0,
        "parameter_searches": 0,
        "max_processes": 1,
        "native_threads": 1,
    }
    save(HERE / "others/final_checks.json", checks)
    print(json.dumps(checks), flush=True)
    for r in result:
        print(
            json.dumps(
                {
                    "component": r["component"],
                    "h": r["horizon"],
                    "control": r["control"],
                    "return_gain": r["summary"]["return_gain"],
                    "risk_gain": r["summary"]["risk_gain"],
                    "years": {k: [v["return_gain"], v["risk_gain"]] for k, v in r["years"].items()},
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run"))
    args = parser.parse_args()
    {"prepare": prepare, "run": run}[args.mode]()
