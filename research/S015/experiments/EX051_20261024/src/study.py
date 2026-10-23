"""Prospective cross-session process exploration using authenticated event labels."""
# ruff: noqa: E402

import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (
    ResearchBatchRef,
    ExperimentRef,
    ExecutionResources,
    EvidenceRef,
    MaterialEvidenceWrite,
)

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
BASE = HERE.parent
EX = ExperimentRef("S015", HERE.name)


def read(p):
    return json.loads(p.read_bytes())


def save(p, v):
    p.write_text(
        json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def module(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def context():
    return create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S015"),
        resources=ExecutionResources(4, 1, 13),
    )


def material(path):
    return publish_evidence(
        context(),
        MaterialEvidenceWrite(
            EX,
            path.stem,
            path.read_bytes(),
            {
                ".py": "text/x-python",
                ".json": "application/json",
                ".csv": "text/csv",
                ".md": "text/markdown",
            }[path.suffix],
            path.suffix[1:],
        ),
    )


def loader():
    home = BASE / "EX026_20261023"
    ref = EvidenceRef.from_dict(read(home / "others/protocol_refs.json")["study.py"])
    assert ref.resolve(ROOT).read_bytes() == (home / "src/study.py").read_bytes()
    return module(home / "src/study.py", "authenticated_event_loader"), ref


def parameters(mode):
    return {
        "mode": mode,
        "exit_mode": "fixed",
        "lookback": 3,
        "concentration": 0.75,
        "hold": 3,
        "allocation": 1.0,
        "start": "2025-01-02",
    }


def prepare():
    assert not (HERE / "others/protocol_refs.json").exists()
    old, ref = loader()
    events = read(BASE / "EX026_20261023/others/delivery_validation.json")["materials"][
        "events.csv"
    ]
    sources = {k: v.to_dict() for k, v in old.sources().items()}
    protocol = {
        "round": 1,
        "maximum_rounds": 20,
        "stage": 2,
        "question": "分散推进与集中冲击是否区分T+1实际买入后的剩余收益？",
        "definition": "m=median(log of eight 30m closes)+log(adjusted daily close/raw daily close); d=diff(m); D=m-m[-3]; q=max(positive d in3)/sum(positive d in3); prior20 logarithmic TR mean excludes today.",
        "arms": {
            m: parameters(m)
            for m in ("U", "momentum", "center", "distributed", "concentrated", "impulse")
        },
        "distributed": "D>0, at least2 of3 d>0, q<=.75, close>=m; concentrated:D>0,q>.75,close>=m; impulse:d>priorATR and close>=m.",
        "labels": "Reuse authenticated EX026 h1/h3/h5 events: one next-session entry attempt, actual lot/fee/limit contracts; three-day net primary; entry-day after buyfee secondary. Overlapping 100000-yuan standalone opportunities, never a continuous account.",
        "matching": "distributed vs concentrated, same calendar year, abs(log r3 difference)<=.03, vol ratio .5..2; closest squared scaled distance, reuse allowed; disclose balance and unique controls. Diagnostic not causal.",
        "episode": "First day of each contiguous permission spell reported separately to reveal duplicate observations; not a newly independent sample.",
        "statistics": "All and annual means, signed sums; h3 selected/excluded loss and profit amounts; 20-session block bootstrap499, seed13 for distributed-minus-concentrated descriptive interval; no new acceptance gate.",
        "scope": "Fixed509daily(75warmup+434development) and3472intraday, no new sources;2025-01-02..2026-10-21; repeated development selection.",
        "sources": sources,
        "loader": ref.to_dict(),
        "events": events,
        "next": "Move plausible competing processes to minimal public complete accounts; low event mean is evidence, not automatic veto of all prototype combinations.",
    }
    save(HERE / "protocols/process.json", protocol)
    paths = [
        HERE / "protocols/process.json",
        Path(__file__),
        HERE / "src/price_process.py",
        ROOT / "research/S015/materials/price_process_stage2_20261024.md",
    ]
    save(
        HERE / "others/protocol_refs.json",
        {str(p.relative_to(ROOT)): material(p).to_dict() for p in paths},
    )
    print("EX051_PROTOCOL_PUBLISHED", flush=True)


def summarize(g, col):
    y = g[col].dropna().to_numpy(float) / 100000
    return {
        "n": len(y),
        "mean": float(y.mean()) if len(y) else None,
        "positive": float(np.maximum(y, 0).sum()),
        "negative": float(-np.minimum(y, 0).sum()),
    }


def run():
    assert not (HERE / "others/results.json").exists()
    for key, ref in read(HERE / "others/protocol_refs.json").items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT / key).read_bytes()
    old, _ = loader()
    adj, raw, bars, rules, ids = old.inputs(old.sources())
    runtime = module(HERE / "src/price_process.py", "process_exploration")
    features = runtime.causal_features(adj, raw, bars)
    checks = 0
    for stop in range(75, len(adj) + 1):
        n = max(0, stop - 75)
        prefix = runtime.causal_features(adj.iloc[:stop], raw.iloc[:stop], bars.iloc[: 8 * n])
        pd.testing.assert_frame_equal(prefix, features.iloc[: len(prefix)])
        checks += 1
    x = features.iloc[1:].copy()
    x.index = x.index.strftime("%Y-%m-%d")
    for mode in runtime.MODES:
        x[mode] = [
            runtime.permission(row, parameters(mode)) for _, row in features.iloc[1:].iterrows()
        ]
        x[mode + "_first"] = x[mode] & ~x[mode].shift(fill_value=False)
    x.to_csv(HERE / "others/features.csv", index_label="date")
    events = pd.read_csv(
        EvidenceRef.from_dict(read(HERE / "protocols/process.json")["events"]).resolve(ROOT)
    )
    g = events.merge(x.reset_index(names="date"), on="date", validate="many_to_one")
    g["year"] = g.date.str[:4]
    rows = []
    for h in (1, 3, 5):
        for year in ("all", "2025", "2026"):
            hgroup = g[g.horizon.eq(h) & g.feature_ready]
            hgroup = hgroup if year == "all" else hgroup[hgroup.year.eq(year)]
            for mode in runtime.MODES:
                for sample in ("all", "first"):
                    sub = hgroup[hgroup[mode + ("_first" if sample == "first" else "")]]
                    rows.append(
                        {
                            "mode": mode,
                            "horizon": h,
                            "year": year,
                            "sample": sample,
                            "signals": len(sub),
                            "statuses": {
                                str(k): int(v) for k, v in sub.status.value_counts().items()
                            },
                            "net": summarize(sub, "net"),
                            "entry": summarize(sub, "entry_net"),
                            "later_gross": summarize(sub, "subsequent_gross"),
                        }
                    )
    fixed = g[g.horizon.eq(3) & g.net.notna() & g.feature_ready].copy()
    pairs = []
    for a in fixed[fixed.distributed].itertuples():
        pool = fixed[fixed.concentrated & fixed.year.eq(a.year)].copy()
        pool = pool[(pool.r3 - a.r3).abs().le(0.03) & (pool.vol20 / a.vol20).between(0.5, 2)]
        if pool.empty:
            continue
        pool["distance"] = ((pool.r3 - a.r3) / 0.03) ** 2 + (
            np.log(pool.vol20 / a.vol20) / np.log(2)
        ) ** 2
        b = pool.sort_values(["distance", "date"]).iloc[0]
        pairs.append(
            {
                "subject": a.date,
                "control": b.date,
                "delta": float(a.net - b.net) / 100000,
                "r3_diff": float(a.r3 - b.r3),
                "vol_ratio": float(a.vol20 / b.vol20),
            }
        )
    rng = np.random.default_rng(13)
    h = g[g.horizon.eq(3)].sort_values("date")
    draws = []
    for _ in range(499):
        pos = np.concatenate([(np.arange(20) + s) % 434 for s in rng.integers(0, 434, size=22)])[
            :434
        ]
        b = h.iloc[pos]
        a = b[b.distributed & b.net.notna()].net
        c = b[b.concentrated & b.net.notna()].net
        if len(a) and len(c):
            draws.append(float(a.mean() - c.mean()) / 100000)
    save(
        HERE / "others/results.json",
        {
            "rows": rows,
            "matching": {
                "pairs": pairs,
                "n": len(pairs),
                "distinct_controls": len({p["control"] for p in pairs}),
                "delta": float(np.mean([p["delta"] for p in pairs])) if pairs else None,
            },
            "bootstrap95": np.quantile(draws, [0.025, 0.975]).tolist(),
            "valid_draws": len(draws),
            "input_ids": ids,
            "physical_prefix_checks": checks,
            "account_count": 0,
            "rounds_used": 1,
        },
    )
    print(
        json.dumps(
            {
                "primary": [r for r in rows if r["horizon"] == 3 and r["year"] == "all"],
                "matched_n": len(pairs),
                "matched_delta": float(np.mean([p["delta"] for p in pairs])) if pairs else None,
                "bootstrap95": np.quantile(draws, [0.025, 0.975]).tolist(),
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
