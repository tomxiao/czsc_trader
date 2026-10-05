from dataclasses import asdict
from importlib.metadata import version
import json
import os
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
EXP = ROOT / "experiments/S012/EX017_20261005"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    sources = ("experiment.py", "mechanism.py", "statistics.py")
    write(
        EXP / "experiment_binding.json",
        {
            "schema_version": 3,
            "module": "experiment",
            "qualname": "Experiment",
            "source_files": list(sources),
            "source_sha256": experiment_source_sha256(EXP, sources),
            "dependencies": [
                {"name": p, "version": version(p)}
                for p in ("numpy", "pandas", "scipy", "tsfresh", "expr_codegen")
            ],
        },
    )
    priors = []
    evidence = []
    for eid in ("EX015_20261005", "EX016_20261005"):
        path = ROOT / f"experiments/S012/{eid}/artifacts/rex"
        digest = json.loads((path / "execution_receipt.json").read_text(encoding="utf-8"))[
            "receipt_sha256"
        ]
        priors.append(load_experiment_input(path, expected_receipt_sha256=digest))
        evidence.append(PredecessorEvidence(path, digest))
    workers = max(1, (os.cpu_count() or 1) // 2)
    repo = RepositoryContext.discover(ROOT)
    check = preflight_experiment_archive(
        repo, EXP, max_workers=workers, predecessors=tuple(evidence)
    )
    write(EXP / "artifacts/preflight.json", asdict(check))
    print("PREFLIGHT", check.status, flush=True)
    loaded = load_experiment(EXP)
    ctx = create_formal_experiment_context(
        loaded.definition,
        repository_root=ROOT,
        data_space=DataSpace(Path("data/research/S012")),
        resources=ExperimentResources(workers, 12017, 1),
        workspace=ExperimentWorkspace(
            ROOT / ".tmp/s012-opportunity-20261005/normal/execution", ROOT
        ),
        predecessors=tuple(priors),
    )
    result = execute_experiment(loaded, ctx)
    shutil.copytree(ctx.workspace.root, EXP / "artifacts/rex")
    print("EXECUTION", result.outcome.value, dict(result.facts), flush=True)
    write(ROOT / ".tmp/s012-opportunity-20261005/normal/result.json", result.to_dict())


if __name__ == "__main__":
    main()
