"""Bind and execute once; persist any technical failure without retry."""
# ruff: noqa: E402 -- native thread limits must precede numerical imports.

import os

for variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[variable] = "1"

import argparse
from datetime import timedelta
import json
from pathlib import Path
import shutil
import traceback

from dataflows import Dataflows, LocalCacheConfig, DataRequest, Dataset
from research_experiment import (
    load_experiment,
    load_experiment_input,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_formal_experiment_context,
    execute_experiment,
)
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    assert not (ROOT / "artifacts").exists(), "Execution already exists"
    inputs = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
    names = (
        "experiment.py",
        "family_statistics.py",
        "run_experiment.py",
        "inputs.json",
        "01_goal.md",
        "02_design.md",
    )
    binding = dict(
        schema_version=3,
        module="experiment",
        qualname="Experiment",
        source_files=list(names),
        source_sha256=experiment_source_sha256(ROOT, names),
        dependencies=inputs["dependencies"],
    )
    path = ROOT / "experiment_binding.json"
    if path.exists():
        assert json.loads(path.read_text(encoding="utf-8")) == binding, "Bound source changed"
    else:
        write(path, binding)
    loaded = load_experiment(ROOT)
    previous = tuple(
        load_experiment_input(ROOT.parent / ex / "artifacts", expected_receipt_sha256=digest)
        for ex, digest in inputs["predecessors"].items()
    )
    resources = ExperimentResources(1, 20261001)
    cache = LocalCacheConfig(
        REPO / ".tmp/s011-regeneration/cache", "S011-20260928-regeneration-v1", timedelta(days=1)
    )
    flows = Dataflows(env_file=REPO / ".env", cache=cache)
    requests = tuple(
        DataRequest(dataset, symbol, start, "2026-09-28", "2026-09-28", frequency)
        for dataset, symbol, start, frequency in (
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "30m"),
            (Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "000300.SH", "2024-12-26", "daily"),
            (Dataset.GLOBAL_INDEX_DAILY, "SPX", "2024-12-16", "daily"),
            (Dataset.TRADING_CALENDAR, "SSE", "2025-02-06", "daily"),
        )
    )
    report = preflight_experiment(
        loaded, resources=resources, predecessors=previous, dataflows=flows, data_requests=requests
    )
    write(ROOT / "preflight.json", report.to_dict())
    print(json.dumps(report.to_dict()), flush=True)
    report.require_pass()
    if not args.execute:
        return
    workspace_root = REPO / ".tmp/s011-completion/EX37-execution"
    assert not workspace_root.exists(), "Execution workspace already exists"
    workspace = ExperimentWorkspace(workspace_root, REPO)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        predecessors=previous,
        cache=cache,
    )
    failure, result = None, None
    try:
        result = execute_experiment(loaded, context)
    except Exception:
        failure = traceback.format_exc()
        workspace.path("technical_failure.txt").write_text(failure, encoding="utf-8", newline="\n")
    shutil.copytree(workspace.root, ROOT / "artifacts")
    status = "TECHNICAL_FAILURE" if failure else "COMPLETE"
    (ROOT / "03_execution.md").write_text(
        f"# EX37 执行\n\n状态：`{status}`。单一受管上下文、固定提议队列；详细回执与账户见 artifacts。\n",
        encoding="utf-8",
        newline="\n",
    )
    (ROOT / "04_conclusion.md").write_text(
        "# EX37 结论\n\n"
        + (
            "技术失败停止，保留全部证据，不原地重试。"
            if failure
            else "512个固定联合扰动和1个同源码成本压力账户执行完成；补齐诊断不增加独立样本，交付结论另见正式报告。"
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if failure:
        build_experiment_manifest(
            ROOT,
            dict(
                experiment_id=ROOT.name,
                strategy_id="S011",
                credential_id="SGC-S011-001",
                status=status,
                symbol="159326.SZ",
                development_cutoff="2026-09-28",
            ),
        )
        validate_experiment_archive(ROOT)
        raise RuntimeError(failure)
    print(json.dumps({"status": status, "receipt": result.receipt.sha256}), flush=True)


if __name__ == "__main__":
    main()
