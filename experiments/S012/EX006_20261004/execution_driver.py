"""One-shot source binding, preflight and managed execution; never resumes sealed work."""
from datetime import timedelta
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
from dataclasses import asdict
from dataflows import LocalCacheConfig
from research_experiment import experiment_source_sha256, load_experiment, load_experiment_input, ExperimentResources, ExperimentWorkspace
from czsc_trader.application import RepositoryContext, preflight_experiment_archive, PredecessorEvidence
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment


def main():
    root = Path(__file__).resolve().parents[3]
    directory = root / sys.argv[1]
    if (directory / "experiment_manifest.json").exists() or (directory / "artifacts/rex/execution_receipt.json").exists():
        raise FileExistsError("Allocate successor; existing evidence is immutable")
    workers = max(1, (os.cpu_count() or 1) // 2)
    binding_path = directory / "experiment_binding.json"
    if not binding_path.exists():
        files = tuple(p.relative_to(directory).as_posix() for p in sorted(directory.glob("*.py")))
        binding = {"schema_version": 3, "module": "experiment", "qualname": "Experiment",
                   "source_files": files, "source_sha256": experiment_source_sha256(directory, files),
                   "dependencies": [{"name": p, "version": importlib.metadata.version(p)} for p in ("numpy", "pandas", "tsfresh")]}
        binding_path.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8", newline="\n")
    context = RepositoryContext.discover(root)
    loaded = load_experiment(directory)
    prior_specs, inputs = [], []
    for predecessor in loaded.definition.protocol.predecessor_experiment_ids:
        prior_workspace = root / "experiments/S012" / predecessor / "artifacts/rex"
        prior_receipt = json.loads((prior_workspace / "execution_receipt.json").read_text(encoding="utf-8"))
        prior = load_experiment_input(prior_workspace, expected_receipt_sha256=prior_receipt["receipt_sha256"])
        inputs.append(prior)
        prior_specs.append(PredecessorEvidence(prior_workspace, prior.receipt_sha256))
    report = preflight_experiment_archive(context, directory, max_workers=workers,
        native_threads_per_worker=1, predecessors=tuple(prior_specs))
    (directory / "artifacts").mkdir(exist_ok=True)
    (directory / "artifacts/preflight.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"preflight": report.status, "warnings": report.warnings}, ensure_ascii=False), flush=True)
    workspace = ExperimentWorkspace(root / ".tmp/s012/runs" / directory.name, root)
    resources = ExperimentResources(workers, loaded.definition.random_seed, 1)
    formal = create_formal_experiment_context(loaded.definition, repository_root=root,
        resources=resources, workspace=workspace, predecessors=tuple(inputs),
        cache=LocalCacheConfig(root / ".tmp/s012/dfls-stage2", "s012-stage2-v1", timedelta(days=7)))
    result = execute_experiment(loaded, formal)
    archive = directory / "artifacts/rex"
    shutil.copytree(workspace.root, archive)
    (directory / "artifacts/result.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"experiment": directory.name, "outcome": result.outcome.value,
                      "facts": result.to_dict()["facts"], "receipt": result.receipt.sha256}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
