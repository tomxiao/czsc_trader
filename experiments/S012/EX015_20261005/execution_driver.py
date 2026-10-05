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
EXP = ROOT / "experiments/S012/EX015_20261005"
WORK = ROOT / ".tmp/s012-opportunity-20261005"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def main():
    source = ("experiment.py", "analysis.py")
    write(
        EXP / "experiment_binding.json",
        {
            "schema_version": 3,
            "module": "experiment",
            "qualname": "Experiment",
            "source_files": list(source),
            "source_sha256": experiment_source_sha256(EXP, source),
            "dependencies": [
                {"name": p, "version": version(p)}
                for p in ("numpy", "pandas", "scipy", "tsfresh", "expr_codegen")
            ],
        },
    )
    predecessors = []
    evidence = []
    for eid in ("EX013_20261005", "EX010_20261004", "EX014_20261005"):
        path = ROOT / f"experiments/S012/{eid}/artifacts/rex"
        digest = json.loads((path / "execution_receipt.json").read_text(encoding="utf-8"))[
            "receipt_sha256"
        ]
        predecessors.append(load_experiment_input(path, expected_receipt_sha256=digest))
        evidence.append(PredecessorEvidence(path, digest))
    if not predecessors[0].facts["full_history_ready"]:
        raise RuntimeError("EX013全历史数据门未通过，不能启动收益研究")
    workers = max(1, (os.cpu_count() or 1) // 2)
    repo = RepositoryContext.discover(ROOT)
    preflight = preflight_experiment_archive(
        repo, EXP, max_workers=workers, predecessors=tuple(evidence)
    )
    write(EXP / "artifacts/preflight.json", asdict(preflight))
    print("PREFLIGHT", preflight.status, flush=True)
    loaded = load_experiment(EXP)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=ROOT,
        data_space=DataSpace(Path("data/research/S012")),
        resources=ExperimentResources(workers, loaded.definition.random_seed, 1),
        workspace=ExperimentWorkspace(WORK / "mechanism-execution-authorized", ROOT),
        predecessors=tuple(predecessors),
    )
    result = execute_experiment(loaded, context)
    shutil.copytree(context.workspace.root, EXP / "artifacts/rex")
    write(WORK / "mechanism-result.json", result.to_dict())
    print("EXECUTION", result.outcome.value, dict(result.facts), flush=True)


if __name__ == "__main__":
    main()
