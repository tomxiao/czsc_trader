"""Offline regression: disjoint file lanes, measured scheduling and explicit budgets."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOTS = ("tests",) + tuple(f"packages/{name}/tests" for name in (
    "dataflows", "strategy_manager", "strategy_evaluator", "strategy_runtime",
    "strategy_chart", "execution_channels", "paper_trading_engine"))


def discover_files(root=ROOT):
    return sorted({path.relative_to(root).as_posix() for directory in TEST_ROOTS
                   for path in (root / directory).rglob("*.py")
                   if path.name.startswith("test_") or path.name.endswith("_test.py")})


def measured_costs(files, history):
    """Use the latest available per-file result; new files still enter the plan."""
    keys = {name[:-3].replace("/", "."): name for name in files}
    costs = {}
    for run in sorted(history.glob("run-*"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        totals = Counter()
        for report in run.glob("*.xml"):
            if report.stem.startswith("repair"):
                continue
            try:
                cases = ET.parse(report).iter("testcase")
                for case in cases:
                    key = case.get("classname", "")
                    while key and key not in keys:
                        key = key.rpartition(".")[0]
                    if key:
                        totals[keys[key]] += float(case.get("time", "0"))
            except (ET.ParseError, ValueError, OSError):
                continue  # Old/incomplete telemetry is not a test result or admission gate.
        for name, seconds in totals.items():
            costs.setdefault(name, max(seconds, .1))
        if len(costs) == len(files):
            break
    return costs


def partition(files, costs, workers):
    lanes = [[] for _ in range(min(workers, len(files)))]
    loads = [0.] * len(lanes)
    # Whole files preserve module fixtures. New files get a nonzero initial cost.
    for name in sorted(files, key=lambda p: (-costs.get(p, 5.), p)):
        index = min(range(len(lanes)), key=lambda i: loads[i])
        lanes[index].append(name)
        loads[index] += costs.get(name, 5.)
    return lanes


def check_coverage(run, names):
    expected, observed = Counter(), Counter()
    failures = skipped = 0
    for name in names:
        items = json.loads((run / f"{name}-collected.json").read_text(encoding="utf-8"))
        expected.update(tuple(item) for item in items)
        for case in ET.parse(run / f"{name}.xml").iter("testcase"):
            observed[(case.get("classname"), case.get("name"))] += 1
            failures += case.find("failure") is not None or case.find("error") is not None
            skipped += case.find("skipped") is not None
    if expected != observed or any(n != 1 for n in expected.values()):
        missing, extra = expected-observed, observed-expected
        duplicates = {key: n for key, n in expected.items() if n != 1}
        raise ValueError(f"test coverage mismatch: missing={sum(missing.values())}, "
                         f"extra={sum(extra.values())}, duplicates={len(duplicates)}; "
                         f"examples={list(missing)[:3] + list(extra)[:3] + list(duplicates)[:3]}")
    return dict(nodes=sum(observed.values()), failures=failures, skipped=skipped)


def run_all(workers):
    began = time.monotonic()
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('Node.js is required for the PTE frontend tests')
    node_tests = sorted(str(path.relative_to(ROOT)) for path in
                        (ROOT / 'packages/paper_trading_engine/tests').rglob('*.test.mjs'))
    if not node_tests:
        raise RuntimeError('PTE frontend test collection is empty')
    run_id = uuid4().hex
    run = ROOT / ".tmp/test-regression" / f"run-{run_id}"
    run.mkdir(parents=True)
    env = os.environ.copy()
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                      "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    cache = ROOT / '.tmp/pycache' / f'regression-{run_id}'
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    env.update(TEMP=str(ROOT / ".tmp"), TMP=str(ROOT / ".tmp"),
               PYTHONPYCACHEPREFIX=str(cache), CZSC_TEST_BYTECODE_ROOT=str(cache))
    preflight = subprocess.run([sys.executable, str(ROOT / "scripts/test_preflight.py"), str(run)],
                              cwd=ROOT, env=env, capture_output=True, text=True)
    (run / "preflight.log").write_text(preflight.stdout + preflight.stderr, encoding="utf-8")
    print(preflight.stdout.strip(), flush=True)
    if preflight.returncode:
        print(preflight.stderr, flush=True)
        return 1
    files = discover_files()
    lanes = partition(files, measured_costs(files, run.parent), workers)
    assert Counter(f for lane in lanes for f in lane) == Counter(files)
    names = [f"lane_{i+1:02}" for i in range(len(lanes))]
    (run / "plan.json").write_text(json.dumps(dict(zip(names, lanes)), indent=2), encoding="utf-8")
    processes, results = [], []
    try:
        for name, selection in zip(names, lanes):
            command = [sys.executable, "-m", "pytest", "-c", "pyproject.toml", "-q",
                       "--durations=10", "--release-acceptance", f"--junitxml={run/name}.xml", *selection]
            log = (run / f"{name}.log").open("w", encoding="utf-8")
            child_env = dict(env, CZSC_PYTEST_RUN_ID=f"{run_id}-{name}",
                             CZSC_PYTEST_COLLECTION=str(run / f"{name}-collected.json"))
            (run / f"{name}-selection.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
            started = time.monotonic()
            process = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=log, stderr=subprocess.STDOUT)
            processes.append((name, process, log, started))
        pending = list(processes)
        while pending:
            for entry in pending[:]:
                name, process, log, started = entry
                if process.poll() is None:
                    continue
                log.close()
                result = dict(lane=name, exit_code=process.returncode, seconds=round(time.monotonic()-started, 2))
                results.append(result)
                print(f"LANE_RESULT {name} EXIT={result['exit_code']} SECONDS={result['seconds']}", flush=True)
                pending.remove(entry)
            if pending:
                time.sleep(.1)
    finally:
        for _, process, log, _ in processes:
            if process.poll() is None:
                process.terminate()
                process.wait()
            log.close()
    coverage_error = None
    try:
        coverage = check_coverage(run, names)
    except (OSError, ValueError, ET.ParseError) as exc:
        coverage, coverage_error = {}, str(exc)
    commands = {
        "console": [node, "--test-isolation=none", "--test", "--test-reporter=tap", *node_tests],
        "ruff": [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts/test_regression.py",
                 "conftest.py", *(str(Path(p).parent) for p in TEST_ROOTS[1:])],
    }
    for name, command in commands.items():
        started = time.monotonic()
        with (run / f"{name}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        results.append(dict(lane=name, exit_code=result.returncode, seconds=round(time.monotonic()-started, 2)))
    shutil.rmtree(cache)
    seconds = round(time.monotonic()-began, 2)
    passed = (not coverage_error and not coverage.get("failures") and not coverage.get('skipped')
              and all(r["exit_code"] == 0 for r in results))
    summary = dict(seconds=seconds, max_parallel=workers, files=len(files), coverage=coverage,
                   environment=dict(host=platform.node(), python=sys.version, logical_cpus=os.cpu_count(),
                                    bytecode_cache='fresh run-local cache shared by child processes',
                                    native_threads=1),
                   coverage_error=coverage_error, results=results, functional_pass=passed, budget_pass=seconds <= 180)
    (run / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"TEST_LOG_ROOT={run}\nTOTAL_SECONDS={seconds}\nCOVERAGE={coverage}", flush=True)
    print(f"FULL_OFFLINE_REGRESSION={'PASS' if passed else 'FAIL'}", flush=True)
    print(f"EFFICIENCY_ACCEPTANCE={'PASS' if seconds <= 180 else 'FAIL'} BUDGET_SECONDS=180", flush=True)
    if coverage_error:
        print(coverage_error, flush=True)
    return 1 if not passed else (0 if seconds <= 180 else 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-parallel", type=int, choices=range(1, 13), default=8)
    args = parser.parse_args()
    raise SystemExit(run_all(args.max_parallel))
