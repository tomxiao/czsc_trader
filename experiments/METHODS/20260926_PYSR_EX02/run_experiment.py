"""Budget-strengthened successor to PYSR EX01; all other contracts are inherited."""

from __future__ import annotations

import argparse
import importlib.util
import time
from pathlib import Path

import numpy as np


def load_predecessor():
    path = Path(__file__).resolve().parent.parent / "20260926_PYSR_EX01" / "run_experiment.py"
    spec = importlib.util.spec_from_file_location("pysr_ex01", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("EX01 source cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fit_large(x: np.ndarray, y: np.ndarray, name: str, experiment: Path):
    from pysr import PySRRegressor

    root = experiment.parents[2] / ".tmp"
    output = root / "pysr_runs_ex02"
    temporary = root / "pysr_temp_ex02"
    output.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    model = PySRRegressor(
        niterations=300,
        populations=8,
        population_size=40,
        ncycles_per_iteration=100,
        maxsize=12,
        maxdepth=6,
        binary_operators=["+", "-", "*"],
        unary_operators=[],
        precision=32,
        parallelism="serial",
        deterministic=True,
        random_state=20260926,
        model_selection="best",
        progress=False,
        verbosity=0,
        timeout_in_seconds=300,
        output_directory=str(output),
        tempdir=str(temporary),
        run_id=f"EX02_{name}",
    )
    started = time.monotonic()
    model.fit(x, y, variable_names=[f"x{index}" for index in range(x.shape[1])])
    return model, time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--synthetic-only", action="store_true")
    args = parser.parse_args()
    predecessor = load_predecessor()
    predecessor.synthetic_precheck()
    if args.synthetic_only:
        print("SYNTHETIC_PASS")
        return
    predecessor.fit_pysr = fit_large
    predecessor.run(args.source_root.resolve(), Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
