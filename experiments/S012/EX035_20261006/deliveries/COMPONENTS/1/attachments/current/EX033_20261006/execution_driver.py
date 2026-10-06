"""Run from repository root using runpy; retain original managed predecessors."""

from dataclasses import asdict
from importlib.metadata import version
import json
from pathlib import Path
import shutil
from dataflows import DataSpace
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    experiment_source_sha256,
    load_experiment,
    load_experiment_input,
)
from czsc_trader.application import (
    RepositoryContext,
    PredecessorEvidence,
    preflight_experiment_archive,
)
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment

ROOT = Path.cwd().resolve()
EXP = ROOT / "experiments/S012/EX033_20261006"


def write(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(x, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    sources = ("experiment.py", "mechanisms.py", "diagnostics.py")
    write(
        EXP / "experiment_binding.json",
        {
            "schema_version": 3,
            "module": "experiment",
            "qualname": "Experiment",
            "source_files": list(sources),
            "source_sha256": experiment_source_sha256(EXP, sources),
            "dependencies": [{"name": p, "version": version(p)} for p in ("numpy", "pandas")],
        },
    )
    loaded = load_experiment(EXP)
    if "--synthetic-only" in __import__("sys").argv:
        result = loaded.implementation.synthetic_precheck()
        print("SYNTHETIC PASS", len(result.checks), flush=True)
        return
    priors = []
    evidence = []
    for eid in ("EX032_20261006", "EX031_20261006", "EX004_20261004", "EX010_20261004"):
        p = ROOT / f"experiments/S012/{eid}/artifacts/rex"
        digest = json.loads((p / "execution_receipt.json").read_text(encoding="utf-8"))[
            "receipt_sha256"
        ]
        priors.append(load_experiment_input(p, expected_receipt_sha256=digest))
        evidence.append(PredecessorEvidence(p, digest))
    # This compact census is sequential with native threads 1, below half-CPU budget.
    workers = 1
    repo = RepositoryContext.discover(ROOT)
    check = preflight_experiment_archive(
        repo, EXP, max_workers=workers, predecessors=tuple(evidence)
    )
    write(EXP / "artifacts/preflight.json", asdict(check))
    print("PREFLIGHT", check.status, flush=True)
    if str(check.status).upper().split(".")[-1] != "PASS":
        raise ValueError("preflight not PASS")
    ctx = create_formal_experiment_context(
        loaded.definition,
        repository_root=ROOT,
        data_space=DataSpace(Path("data/research/S012")),
        resources=ExperimentResources(workers, 12033, 1),
        workspace=ExperimentWorkspace(
            ROOT / ".tmp/s012-execution-attribution-20261006/execution", ROOT
        ),
        predecessors=tuple(priors),
    )
    result = execute_experiment(loaded, ctx)
    shutil.copytree(ctx.workspace.root, EXP / "artifacts/rex")
    write(ROOT / ".tmp/s012-execution-attribution-20261006/result.json", result.to_dict())
    print("EXECUTION", result.outcome.value, dict(result.facts), flush=True)


if __name__ == "__main__":
    main()
