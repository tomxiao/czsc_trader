"""EX056 declared mean/median opportunity diagnostics; no account or new filter."""

from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
import os
from pathlib import Path

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

# ruff: noqa: E402
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
BASE = HERE.parent
MODES = ("U", "center", "below", "falling_below", "center_above", "center_below")


def read(path):
    return json.loads(path.read_bytes())


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def authenticate(reference):
    ref = EvidenceRef.from_dict(reference)
    if ref.experiment.strategy_id != "S015":
        raise ValueError("Only S015 is authorized")
    return ref, ref.resolve(ROOT)


def authenticate_protocols(home):
    refs = read(home / "others/protocol_refs.json")
    for key, value in refs.items():
        _, frozen = authenticate(value)
        assert frozen.read_bytes() == (ROOT / key).read_bytes(), key
    return refs


def parameters(mode, kind):
    return {
        "mode": mode,
        "exit_mode": "fixed",
        "lookback": 3,
        "concentration": 0.75,
        "hold": 3,
        "allocation": 1.0,
        "start": "2025-01-02",
        "center_kind": kind,
    }


def amount(values):
    return {
        "observations": len(values),
        "positive_count": int(values.gt(0).sum()),
        "negative_count": int(values.lt(0).sum()),
        "zero_count": int(values.eq(0).sum()),
        "positive_amount_yuan": float(values.clip(lower=0).sum()),
        "negative_amount_yuan": float(-values.clip(upper=0).sum()),
        "net_amount_yuan": float(values.sum()),
        "mean_yuan": float(values.mean()) if len(values) else None,
        "mean_return_on_100000": float(values.mean() / 100000) if len(values) else None,
    }


def summarize(base, mode, label):
    known = base[label].notna()
    denominator = amount(base.loc[known, label])
    parts = {}
    for name, mask in (("selected", base[mode]), ("rejected", ~base[mode])):
        part = amount(base.loc[known & mask, label])
        for sign in ("positive", "negative"):
            for unit in ("count", "amount_yuan"):
                key = f"{sign}_{unit}"
                part[f"{sign}_{'amount' if unit == 'amount_yuan' else 'count'}_fraction"] = (
                    part[key] / denominator[key] if denominator[key] else None
                )
        part.update(
            {
                "signals": int(mask.sum()),
                "signal_fraction": float(mask.mean()) if len(mask) else None,
                "unobserved_labels": int((mask & ~known).sum()),
                "status_counts": {
                    str(k): int(v) for k, v in base.loc[mask, "status"].value_counts().items()
                },
            }
        )
        parts[name] = part
    for key in (
        "observations",
        "positive_count",
        "negative_count",
        "zero_count",
        "positive_amount_yuan",
        "negative_amount_yuan",
        "net_amount_yuan",
    ):
        assert np.isclose(
            parts["selected"][key] + parts["rejected"][key], denominator[key], rtol=1e-12, atol=1e-8
        ), (mode, label, key)
    return {"mode": mode, "label": label, "denominator": denominator, **parts}


def main():
    target = HERE / "others/opportunity_cost.json"
    if target.exists():
        raise FileExistsError("Preserve existing diagnostic output")
    current_refs = authenticate_protocols(HERE)
    assert "event_diagnostic" in read(HERE / "protocols/accounts.json")
    ex51 = BASE / "EX051_20261024"
    authenticate_protocols(ex51)
    event_ref, event_path = authenticate(read(ex51 / "protocols/process.json")["events"])
    oldhome = BASE / "EX026_20261023"
    oldref, oldpath = authenticate(read(oldhome / "others/protocol_refs.json")["study.py"])
    assert oldpath.read_bytes() == (oldhome / "src/study.py").read_bytes()
    # Execute the authenticated loader at its experiment location, preserving its relative paths.
    old = load(oldhome / "src/study.py", "ex056_authenticated_event_inputs_local")
    sources = old.sources()
    adj, raw, bars, rules, ids = old.inputs(sources)
    assert ids == read(ex51 / "others/results.json")["input_ids"]
    ex55 = BASE / "EX055_20261024"
    runtime_refs = authenticate_protocols(ex55)
    runtime_path = ex55 / "src/strategy_runtime/strategies/price_process.py"
    key = str(runtime_path.relative_to(ROOT))
    runtime_ref, frozen = authenticate(runtime_refs[key])
    assert frozen.read_bytes() == runtime_path.read_bytes()
    runtime = load(runtime_path, "ex056_authenticated_price_process")
    events = pd.read_csv(event_path)
    events = events[events.horizon.eq(3)]
    assert len(events) == 434 and events.date.is_unique
    rows, diagnostics, features_metadata = [], {}, {}
    readiness = None
    for kind in ("median", "mean"):
        all_features = runtime.causal_features(adj, raw, bars, lookback=3, center_kind=kind)
        x = all_features.iloc[1:].copy()
        for mode in MODES:
            x[mode] = [runtime.permission(row, parameters(mode, kind)) for _, row in x.iterrows()]
        assert x.U.equals(x.feature_ready) and int(x.feature_ready.sum()) == 431
        if readiness is None:
            readiness = x.feature_ready.copy()
        else:
            pd.testing.assert_series_equal(readiness, x.feature_ready)
        x.index = x.index.strftime("%Y-%m-%d")
        if kind == "median":
            previous = pd.read_csv(ex51 / "others/features.csv").set_index("date")
            for col in ("m", "p", "r1", "r5", "center_gain"):
                np.testing.assert_allclose(x[col], previous[col], rtol=1e-12, atol=1e-14)
            for col in ("U", "center"):
                assert x[col].equals(previous[col])
        feature_bytes = x.to_csv(index_label="date").encode("utf-8")
        feature_path = HERE / "others" / f"opportunity_features_{kind}.csv"
        feature_path.write_bytes(feature_bytes)
        features_metadata[kind] = {
            "path": feature_path.relative_to(HERE).as_posix(),
            "sha256": sha256(feature_bytes).hexdigest(),
            "ready": 431,
        }
        merged = events.merge(x.reset_index(names="date"), on="date", validate="one_to_one")
        base = merged[merged.feature_ready]
        groups = {
            "all": pd.Series(True, index=base.index),
            "year_2025": base.date.str.startswith("2025"),
            "year_2026": base.date.str.startswith("2026"),
        }
        for horizon in ("r1", "r5"):
            groups[horizon + "_positive"] = base[horizon].gt(0)
            groups[horizon + "_negative"] = base[horizon].lt(0)
            groups[horizon + "_zero"] = base[horizon].eq(0)
        groups["r1_and_r5_positive"] = base.r1.gt(0) & base.r5.gt(0)
        for group, mask in groups.items():
            for mode in MODES:
                for label in ("entry_net", "net"):
                    rows.append(
                        {
                            "center_kind": kind,
                            "lookback": 3,
                            "group": group,
                            "group_opportunities": int(mask.sum()),
                            **summarize(base.loc[mask], mode, label),
                        }
                    )
        diagnostics[kind] = {
            "combination_signals": int(base.center_below.sum()),
            "combination_signal_dates": base.loc[base.center_below, "date"].tolist(),
            "signal_close_up_count": int((base.center_below & base.r1.gt(0)).sum()),
            "signal_five_day_up_count": int((base.center_below & base.r5.gt(0)).sum()),
            "signal_both_up_count": int((base.center_below & base.r1.gt(0) & base.r5.gt(0)).sum()),
            "outcomes": [
                r
                for r in rows
                if r["center_kind"] == kind
                and r["mode"] == "center_below"
                and r["group"] in ("r1_positive", "r5_positive", "r1_and_r5_positive")
            ],
        }
    result = {
        "experiment": HERE.name,
        "round": 6,
        "additional_rounds": 0,
        "account_replays": 0,
        "population": {
            "all_development_sessions": 434,
            "feature_ready_opportunities": 431,
            "unready": 3,
            "horizon": 3,
        },
        "sources": {
            "events": event_ref.to_dict(),
            "loader": oldref.to_dict(),
            "runtime": runtime_ref.to_dict(),
            "current_protocol_refs": current_refs,
        },
        "input_ids": ids,
        "features": features_metadata,
        "rows": rows,
        "positive_signal_diagnostic": diagnostics,
        "semantics": {
            "amounts": "Each opportunity independently starts with100000 yuan; overlapping positive/negative sums are not a continuous account PnL.",
            "labels": "entry_net after buyfee may be observed before net after two fees and closure. Unfilled/right-censored labels remain missing, never zero-filled.",
            "ratios": "Selected/rejected amounts and signed observation counts divided by their label-specific group totals. Every all-group denominator uses the common431 feature_ready population; yearly/sign groups are explicit subpopulations, not new filters.",
            "signal_returns": "r1/r5 are completed signal-day adjusted close log changes; strictlypositive/strictlynegative/zero are separate. Outcomes remain T+1 actual entry and three-session event outcomes.",
            "selection": "Mean was selected after EX055 outcomes. This diagnosis uses the same repeatedly seen development sample and is not independent confirmation.",
            "execution": "EX026 event labels allow one buy attempt; account cycle retries and capital ownership differ. No new account is computed or inferred.",
        },
        "checks": {
            "input_identities_match_EX051": True,
            "median_features_match_EX051": True,
            "common_ready_431": True,
            "amount_and_count_partitions_reconcile": True,
        },
    }
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "positive_signal_counts": {
                    k: {
                        j: v
                        for j, v in x.items()
                        if j.endswith("count") or j == "combination_signals"
                    }
                    for k, x in diagnostics.items()
                },
                "checks": result["checks"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
