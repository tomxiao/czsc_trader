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
EXP = ROOT / "experiments/S012/EX016_20261005"


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
    path = ROOT / "experiments/S012/EX015_20261005/artifacts/rex"
    digest = json.loads((path / "execution_receipt.json").read_text(encoding="utf-8"))[
        "receipt_sha256"
    ]
    prior = load_experiment_input(path, expected_receipt_sha256=digest)
    workers = max(1, (os.cpu_count() or 1) // 2)
    repo = RepositoryContext.discover(ROOT)
    check = preflight_experiment_archive(
        repo, EXP, max_workers=workers, predecessors=(PredecessorEvidence(path, digest),)
    )
    write(EXP / "artifacts/preflight.json", asdict(check))
    print("PREFLIGHT", check.status, flush=True)
    loaded = load_experiment(EXP)
    ctx = create_formal_experiment_context(
        loaded.definition,
        repository_root=ROOT,
        data_space=DataSpace(Path("data/research/S012")),
        resources=ExperimentResources(workers, 12016, 1),
        workspace=ExperimentWorkspace(
            ROOT / ".tmp/s012-opportunity-20261005/confirm/execution", ROOT
        ),
        predecessors=(prior,),
    )
    result = execute_experiment(loaded, ctx)
    shutil.copytree(ctx.workspace.root, EXP / "artifacts/rex")
    print("EXECUTION", result.outcome.value, dict(result.facts), flush=True)
    write(ROOT / ".tmp/s012-opportunity-20261005/confirm/result.json", result.to_dict())


if __name__ == "__main__":
    main()
