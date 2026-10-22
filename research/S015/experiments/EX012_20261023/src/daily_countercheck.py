"""Check whether minute effects survive already available daily information."""

# ruff: noqa: E402
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
OLD = ROOT / "research/S015/experiments/EX011_20261023"
WORK = ROOT / "research/S015/assets/runs" / HERE.name / "daily_countercheck"
CONTROLS = {
    "PRBody": ["base_r1", "base_r5", "base_vol20", "pressure", "calm_range", "body"],
    "AllDaily": [
        "base_r1",
        "base_r5",
        "base_vol20",
        "pressure",
        "calm_range",
        "body",
        "trend20",
        "location",
        "lower_wick",
        "efficiency5",
    ],
}


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
    refs = [
        EvidenceRef.from_dict(v) for v in read(OLD / "others/published_refs.json")["references"]
    ]

    def one(name, ex):
        r = next(v for v in refs if v.name == name and v.experiment.experiment_id == ex)
        r.resolve(ROOT)
        return r

    source_ref = one("incremental_study", "EX011_20261023")
    source = OLD / "src/incremental_study.py"
    assert sha256(source.read_bytes()).hexdigest() == source_ref.sha256
    spec = importlib.util.spec_from_file_location("retained_ex011", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected = {
        "source": source_ref,
        "features": one("features_reconstructed", "EX011_20261023"),
        "labels": one("event_labels", "EX010_20261023"),
        "results": one("incremental_results", "EX011_20261023"),
        "protocol": one("incremental_protocol", "EX011_20261023"),
    }
    return selected, module


def prepare():
    assert not (HERE / "others/protocol_refs.json").exists()
    refs, _ = inherited()
    protocol = {
        "user_instruction": "请你自主完成阶段二",
        "stage": 2,
        "mandate": "MANDATE/3",
        "predecessor": "COMPONENTS/5",
        "question": "EX011的分钟增量能否被已有当日开收盘变化以及其余已有日线组件解释？",
        "reason": "afternoon_reversal与afternoon结合可表达上午/下午总变动；EX011主控制没有body，不足排除日线开收盘信息的重复表达。此前结果和报告保留，不回写。",
        "controls": CONTROLS,
        "duplicate_exclusion": "trend5 equals base_r5, included once. AllDaily covers all eight EX010 daily component definitions plus simple r1/r5/vol20, avoiding exact duplicates.",
        "budget": {
            "primary_PRBody": 6,
            "AllDaily_sensitivity": 6,
            "total_paired_conditions": 12,
            "targets": 2,
            "folds": 4,
            "new_accounts": 0,
            "parameter_searches": 0,
        },
        "components": ["afternoon", "afternoon_reversal"],
        "horizons": [1, 2, 3],
        "method": "Authenticated EX011 feature matrix, authenticated EX010 labels and exact EX011 evaluate routine; alpha10, purged expanding folds, training-only scaling/negative residual terciles, seed13 block10/20x499 unchanged. Only control columns change.",
        "selection": "New falsification selected after EX011 results; entirely seen development data, no fresh holdout or confirmation.",
        "judgment": "Separate predictive association under a chosen model from unique information beyond all already available daily features. Preserve negative and unstable results. No new hard strategy gate.",
        "data": "No data fetch or extension; immutable inputs from previous publication; final cutoff2026-10-21.",
        "resources": {"processes": 1, "native_threads": 1},
        "inherited": {k: v.to_dict() for k, v in refs.items()},
    }
    save(HERE / "protocols/daily_countercheck.json", protocol)
    published = {
        p.name: material(p).to_dict()
        for p in (HERE / "protocols/daily_countercheck.json", Path(__file__))
    }
    save(HERE / "others/protocol_refs.json", published)
    print("Daily countercheck protocol and source published", flush=True)


def run():
    assert not (HERE / "others/countercheck_results.json").exists()
    prerefs = read(HERE / "others/protocol_refs.json")
    assert sha256(Path(__file__).read_bytes()).hexdigest() == prerefs[Path(__file__).name]["sha256"]
    for ref in prerefs.values():
        EvidenceRef.from_dict(ref).resolve(ROOT)
    refs, model = inherited()
    x = pd.read_csv(refs["features"].resolve(ROOT))
    labels = pd.read_csv(refs["labels"].resolve(ROOT))
    np.testing.assert_allclose(x.trend5, x.base_r5, atol=1e-14, equal_nan=True)
    results, records = [], []
    for control, columns in CONTROLS.items():
        # Change the in-memory imported function's explicit control list only.
        # mode P adds no implicit columns; retained source/files are never edited.
        model.BASE = columns
        for component in model.COMPONENTS:
            for horizon in (1, 2, 3):
                row, events = model.evaluate(x, labels, component, horizon, "P")
                row["control"] = control
                for event in events:
                    event["control"] = control
                results.append(row)
                records.extend(events)
    frame = pd.DataFrame(records)
    assert len(frame) == 3888
    assert not frame.duplicated(["component", "horizon", "control", "date"]).any()
    assert (frame.train_last_exit < frame.test_start).all()
    assert frame.date.max() <= "2026-10-21"
    for row in results:
        g = frame[
            (frame.component == row["component"])
            & (frame.control == row["control"])
            & (frame.horizon == row["horizon"])
        ]
        for target, actual in (("return", g.label), ("risk", g.downside)):
            base = (g[target + "_base_prediction"] - actual) ** 2
            added = (g[target + "_added_prediction"] - actual) ** 2
            np.testing.assert_allclose(
                1 - added.sum() / base.sum(), row["summary"][target + "_gain"], atol=1e-14
            )
    model.BASE = CONTROLS["AllDaily"]
    altered = labels.copy()
    altered.loc[altered.signal_position.ge(259), ["label", "downside"]] += 0.5
    _, changed = model.evaluate(x, altered, "afternoon_reversal", 3, "P")
    first = frame[
        (frame.component == "afternoon_reversal")
        & (frame.control == "AllDaily")
        & (frame.horizon == 3)
        & (frame.fold == 0)
    ]
    cols = [
        "group",
        "return_base_prediction",
        "return_added_prediction",
        "risk_base_prediction",
        "risk_added_prediction",
    ]
    np.testing.assert_allclose(
        first[cols], pd.DataFrame(changed).query("fold == 0")[cols], rtol=0, atol=0
    )
    WORK.mkdir(parents=True, exist_ok=True)
    frame.to_csv(WORK / "forward_predictions.csv", index=False)
    save(
        HERE / "others/countercheck_results.json",
        {"source_sha256": prerefs[Path(__file__).name]["sha256"], "comparisons": results},
    )
    checks = {
        "status": "PASS",
        "input_evidence_hashes": "PASS",
        "published_source_equals_executed": "PASS",
        "prediction_rows": len(frame),
        "paired_conditions": len(results),
        "chronological_purge": "PASS",
        "loss_recalculation": "PASS",
        "future_label_isolation": "PASS",
        "trend5_equals_base_r5": "PASS",
        "new_accounts": 0,
    }
    save(HERE / "others/final_checks.json", checks)
    print(json.dumps(checks), flush=True)
    for r in results:
        print(
            json.dumps(
                {
                    "c": r["component"],
                    "h": r["horizon"],
                    "control": r["control"],
                    "return": r["summary"]["return_gain"],
                    "risk": r["summary"]["risk_gain"],
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
