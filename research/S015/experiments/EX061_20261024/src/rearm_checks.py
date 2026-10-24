"""Signal-only rearm state-machine boundary checks; no account evaluation."""

# ruff: noqa: E402
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
OLD = HERE.parent / "EX059_20261024"
SIGNALS = [
    "target_position",
    "entry_allocation_fraction",
    "intent_age",
    "permission",
    "exit_signal",
    "entry_signal",
]


def read(path):
    return json.loads(path.read_bytes())


def module(home, name):
    path = home / "src/strategy_runtime/strategies/price_process.py"
    ref = EvidenceRef.from_dict(
        read(home / "others/protocol_refs.json")[str(path.relative_to(ROOT))]
    )
    assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj, ref


def features(steps, permitted=None):
    if permitted is None:
        permitted = [True] * len(steps)
    centers = 1 + np.cumsum(steps)
    return pd.DataFrame(
        {
            "feature_ready": True,
            "center_gain": 0.03,
            "m": centers,
            "p": centers + np.where(permitted, -0.01, 0.01),
            "dcenter": steps,
            "atr": 0.02,
            "r3": 0.03,
            "prior_positive": True,
            "up_count": 2,
            "concentration": 0.5,
        },
        index=pd.date_range("2025-01-02", periods=len(steps), freq="D"),
    )


def main():
    output = HERE / "others/rearm_checks.json"
    assert not output.exists()
    runtime, ref = module(HERE, "explicit_rearm_runtime")
    old, oldref = module(OLD, "implicit_rearm_runtime")
    base = dict(read(HERE / "protocols/accounts.json")["configurations"][0])
    base.update(allocation=1.0, exit_mode="fixed", hold=1, max_hold=10, rearm_mode="positive_step")
    examples = []
    f = features([0.01, 0.01, -0.01, 0.01, -0.01], [True, True, True, False, True])
    actual = runtime.intentions(f, base)
    assert actual.entry_signal.tolist() == [1.0, 0.0, 0.0, 0.0, 1.0]
    assert actual.exit_signal.tolist() == [0.0, 1.0, 0.0, 0.0, 0.0]
    assert actual.dcenter.iloc[4] < 0 and actual.entry_signal.iloc[4] == 1
    examples.append(
        {
            "name": "positive_step_latches_before_later_negative_step_entry",
            "rows": json.loads(
                actual.reset_index(names="synthetic_date").to_json(
                    orient="records", date_format="iso"
                )
            ),
            "checks": "Exit-day positive step does not rearm; later positive flat day rearms even without permission; a subsequent negative-step permitted day enters.",
        }
    )
    for rearm in ("immediate", "positive_step"):
        a = runtime.intentions(features([0.01] * 6), {**base, "rearm_mode": rearm})
        assert not (a.entry_signal.eq(1) & a.exit_signal.eq(1)).any()
        assert a.target_position.tolist() == [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    first = runtime.intentions(features([-0.01]), base)
    assert first.entry_signal.iloc[0] == 1
    examples.append(
        {
            "name": "initial_armed_state",
            "initial_negative_step_can_enter": True,
            "meaning": "positive_step is a post-exit rearm constraint, not an unconditional positive-entry-day filter.",
        }
    )
    rng = np.random.default_rng(13)
    random_features = features(
        rng.choice([-0.01, 0, 0.01], size=96), rng.choice([False, True], size=96)
    )
    equalities = []
    for hold in range(1, 6):
        for rearm in ("immediate", "positive_step"):
            params = {**base, "hold": hold, "max_hold": 10, "rearm_mode": rearm}
            fixed = runtime.intentions(random_features, params)
            for confirmation in range(hold, 6):
                checked = runtime.intentions(
                    random_features,
                    {**params, "exit_mode": "confirmed_guard", "confirmation": confirmation},
                )
                pd.testing.assert_frame_equal(fixed[SIGNALS], checked[SIGNALS], check_exact=True)
                equalities.append(
                    {"hold": hold, "confirmation": confirmation, "rearm_mode": rearm, "equal": True}
                )
    reproductions = []
    for row in read(OLD / "others/results.json")["rows"]:
        account_ref = EvidenceRef.from_dict(row["evidence"])
        evidence = read(account_ref.resolve(ROOT))
        run = next(r for r in evidence["runs"] if r["window_id"] == "full")
        retained = pd.DataFrame(run["ledgers"]["decisions"]["data"])
        selected = [c for c in retained if c not in SIGNALS]
        inputs = retained[selected].copy()
        inputs.index = pd.DatetimeIndex(pd.to_datetime(inputs.signal_date))
        legacy = old.intentions(inputs, row["parameters"])
        rearm = "immediate" if row["parameters"]["exit_mode"] == "fixed" else "positive_step"
        explicit = runtime.intentions(inputs, {**row["parameters"], "rearm_mode": rearm})
        pd.testing.assert_frame_equal(legacy[SIGNALS], explicit[SIGNALS], check_exact=True)
        np.testing.assert_allclose(
            explicit[SIGNALS].to_numpy(float),
            retained[SIGNALS].to_numpy(float),
            rtol=0,
            atol=0,
            equal_nan=True,
        )
        reproductions.append(
            {
                "candidate": row["candidate_id"],
                "exit_mode": row["parameters"]["exit_mode"],
                "mapped_rearm_mode": rearm,
                "rows": len(explicit),
                "retained_full_signals_equal_exactly": True,
                "evidence": account_ref.to_dict(),
            }
        )
    for value in (None, "unknown"):
        bad = {**base, "rearm_mode": value}
        try:
            runtime.intentions(f, bad)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid rearm mode was accepted")
    result = {
        "status": "PASS",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_runtime_source": ref.to_dict(),
        "old_runtime_source": oldref.to_dict(),
        "new_account_simulations": 0,
        "new_strategy_evaluations": 0,
        "boundary_examples": examples,
        "confirmation_at_least_hold_equalities": equalities,
        "legacy_mappings": reproductions,
        "limits": [
            "Synthetic rows are deliberately controlled state-machine inputs; their dates are labels, not an exchange calendar or new market experiment.",
            "Guard confirmation>=hold cannot cause earlier exit because failed_streak<=age and age>=hold already exits.",
            "Initial armed=True permits an initial negative-step entry; post-exit positive_step is a latched state.",
            "No economic effect is inferred from synthetic signals; only actual factorial accounts can isolate observed account effects.",
        ],
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "legacy_configurations": len(reproductions),
                "signal_rows": sum(r["rows"] for r in reproductions),
                "synthetic_equalities": len(equalities),
            }
        )
    )


if __name__ == "__main__":
    main()
