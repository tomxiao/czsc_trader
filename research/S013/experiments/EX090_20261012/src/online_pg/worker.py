"""Two independent family processes, each serial over T, with BLAS threads1.

Pipe communication uses threads only to drain the two process streams. There is
no serial fallback, no mutable input cache, and no independent real input read.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import pickle
import subprocess
import sys

import pandas as pd


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runner(features, labels, old_scores, prob_path, gain_path):
    source = Path(__file__).resolve()
    kernel = _load('online_pg_parallel_kernel', source.with_name('kernel.py'))
    kernel.validate(features, labels, old_scores)
    payload = pickle.dumps((features, labels, old_scores), protocol=5)
    env = os.environ.copy()
    for name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[name] = '1'
    processes = []
    try:
        for family in kernel.FAMILIES:
            args = [sys.executable, '-B', '-X', 'utf8', str(source), family, str(Path(prob_path).resolve()), str(Path(gain_path).resolve())]
            processes.append(subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(process.communicate, payload) for process in processes]
            blocks = []
            for family, process, future in zip(kernel.FAMILIES, processes, futures):
                output, error = future.result()
                if process.returncode != 0:
                    raise RuntimeError(f'Online PG family worker {family} failed; no fallback: {error.decode("utf-8", errors="replace")}')
                score, trace = pickle.loads(output)
                expected_columns = tuple(f'{family}_{kind}' for kind in kernel.KINDS)
                if tuple(score.columns) != expected_columns or not score.index.equals(features.index) or any(row['family'] != family for row in trace):
                    raise ValueError('Family worker returned incompatible score/trace identity')
                blocks.append((score, trace))
        scores = pd.concat([block[0] for block in blocks], axis=1)
        traces = [row for block in blocks for row in block[1]]
        if tuple(scores.columns) != kernel.MODELS:
            raise ValueError('Merged family ordering differs from fixed eight models')
        return scores, traces
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise ValueError('Only explicit family and frozen probability/gain source paths accepted')
    import kernel

    family, probability_path, gain_path = sys.argv[1:]
    probability_core = _load('online_pg_frozen_probability', probability_path)
    gain_core = _load('online_pg_frozen_gain', gain_path)
    feature_frame, label_frame, historical_scores = pickle.load(sys.stdin.buffer)
    result = kernel.forecasts(feature_frame, label_frame, historical_scores, probability_core, gain_core, families=(family,))
    pickle.dump(result, sys.stdout.buffer, protocol=5)
