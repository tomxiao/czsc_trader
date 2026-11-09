"""Offline regression: disjoint file lanes, measured scheduling and explicit budgets."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BUDGET_SECONDS = 200
TEST_ROOTS = ("tests",) + tuple(f"packages/{name}/tests" for name in (
    "dataflows", "strategy_manager", "strategy_evaluator", "strategy_runtime",
    "strategy_chart", "execution_channels", "paper_trading_engine"))
INSPECTION_SEED_FILES = frozenset(f"tests/functional/test_candidate_{name}.py" for name in (
    "freeze", "contract_admission", "inspection_roundtrip", "inspection_failure"))


def discover_files(root=ROOT):
    return sorted({path.relative_to(root).as_posix() for directory in TEST_ROOTS
                   for path in (root / directory).rglob("*.py")
                   if path.name.startswith("test_") or path.name.endswith("_test.py")})


def measured_costs(files, history):
    """Use the latest available per-file result; new files still enter the plan."""
    keys = {name[:-3].replace("/", "."): name for name in files}
    costs = {}
    valid_runs = 0
    for run in sorted(history.glob("run-*"), key=lambda p: p.stat().st_mtime, reverse=True):
        totals = Counter()
        invalid = set()
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
                        name = keys[key]
                        totals[name] += float(case.get("time", "0"))
                        if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
                            invalid.add(name)
            except (ET.ParseError, ValueError, OSError):
                continue  # Old/incomplete telemetry is not a test result or admission gate.
        for name in invalid:
            totals.pop(name, None)
        if not totals:
            continue  # Empty/interrupted runs must not evict usable scheduling data.
        valid_runs += 1
        for name, seconds in totals.items():
            costs.setdefault(name, max(seconds, .1))
        if len(costs) == len(files) or valid_runs == 3:
            break
    return costs


def partition(files, costs, workers):
    # These consumers share one real inspected seed within a pytest process.
    # Group only discovered files; this is affinity, never a test allowlist.
    inspection = tuple(sorted(name for name in files if name in INSPECTION_SEED_FILES))
    jobs = [(name,) for name in files if name not in INSPECTION_SEED_FILES]
    if inspection:
        jobs.append(inspection)
    lanes = [[] for _ in range(min(workers, len(jobs)))]
    loads = [0.] * len(lanes)
    # Whole files preserve module fixtures. New files get a nonzero initial cost.
    for job in sorted(jobs, key=lambda group: (-sum(costs.get(name, 5.) for name in group), group)):
        index = min(range(len(lanes)), key=lambda i: loads[i])
        lanes[index].extend(job)
        loads[index] += sum(costs.get(name, 5.) for name in job)
    # Keep each directory subtree contiguous during pytest collection. In
    # pytest 9.1, explicit parent-directory files can rebuild child Directory
    # collectors; revisiting that child then loses its conftest fixture scope.
    # Ordering does not change the cost-balanced lane membership.
    return [sorted(lane) for lane in lanes]


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


def check_node_coverage(output):
    """Read the real Node TAP totals; skipped or cancelled JS is not a pass."""
    totals = {}
    for name in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
        matches = re.findall(rf'^# {name} (\d+)\s*$', output, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f'Node result summary missing or duplicated: {name}')
        totals[name] = int(matches[0])
    if not totals['tests'] or totals['pass'] != totals['tests']:
        raise ValueError(f'Node tests did not all pass: {totals}')
    if any(totals[name] for name in ('fail', 'cancelled', 'skipped', 'todo')):
        raise ValueError(f'Node tests incomplete: {totals}')
    return totals


def run_all(workers):
    began = time.monotonic()
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('Node.js is required for the PTE frontend tests')
    node_tests = sorted(str(path.relative_to(ROOT))
                        for package in ('paper_trading_engine', 'strategy_chart')
                        for path in (ROOT / 'packages' / package / 'tests').rglob('*')
                        if path.name.endswith(('.test.mjs', '.test.cjs')))
    if not node_tests:
        raise RuntimeError('Frontend test collection is empty')
    run_id = uuid4().hex
    run = ROOT / ".tmp/test-regression" / f"run-{run_id}"
    run.mkdir(parents=True)
    env = os.environ.copy()
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                      "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    # Keep ordinary Python source-validated bytecode between runs. Per-test
    # workspaces remain unique; their disposable bytecode is removed below.
    cache = ROOT / '.tmp/pycache' / 'regression'
    cache_reused = cache.exists()
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    env.update(TEMP=str(ROOT / ".tmp"), TMP=str(ROOT / ".tmp"), PYTHONUNBUFFERED="1",
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
    try:
        node_coverage = check_node_coverage((run / 'console.log').read_text(encoding='utf-8'))
    except ValueError as exc:
        node_coverage = {}
        coverage_error = '; '.join(x for x in (coverage_error, str(exc)) if x)
    temporary_bytecode = cache / ROOT.relative_to(ROOT.anchor) / '.tmp'
    assert temporary_bytecode.resolve().is_relative_to(cache.resolve())
    if temporary_bytecode.exists():
        shutil.rmtree(temporary_bytecode)
    seconds = round(time.monotonic()-began, 2)
    within_budget = seconds <= BUDGET_SECONDS
    passed = (not coverage_error and not coverage.get("failures") and not coverage.get('skipped')
              and all(r["exit_code"] == 0 for r in results))
    summary = dict(seconds=seconds, max_parallel=workers, files=len(files), coverage=coverage,
                   node_coverage=node_coverage,
                   environment=dict(host=platform.node(), python=sys.version, logical_cpus=os.cpu_count(),
                                    bytecode_cache='persistent Python source-validated cache; temporary sources pruned',
                                    bytecode_cache_reused=cache_reused,
                                    native_threads=1),
                   coverage_error=coverage_error, results=results, functional_pass=passed,
                   budget_seconds=BUDGET_SECONDS, budget_pass=within_budget)
    (run / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"TEST_LOG_ROOT={run}\nTOTAL_SECONDS={seconds}\nCOVERAGE={coverage}", flush=True)
    print(f"FULL_OFFLINE_REGRESSION={'PASS' if passed else 'FAIL'}", flush=True)
    print(f"EFFICIENCY_OBSERVATION={'WITHIN_BUDGET' if within_budget else 'OVER_BUDGET'} BUDGET_SECONDS={BUDGET_SECONDS}", flush=True)
    if coverage_error:
        print(coverage_error, flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-parallel", type=int, choices=range(1, 13), default=8)
    args = parser.parse_args()
    raise SystemExit(run_all(args.max_parallel))
