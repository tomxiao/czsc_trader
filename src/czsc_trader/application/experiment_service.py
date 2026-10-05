from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from research_experiment import ExperimentResources, load_experiment, load_experiment_input

from czsc_trader.research_tools import preflight_experiment

from .context import RepositoryContext
from .errors import ValidationError
from .research_paths import repository_path
from .results import CommandResult


@dataclass(frozen=True, slots=True)
class PredecessorEvidence:
    """One explicitly pinned predecessor supplied to experiment preflight."""

    workspace: Path
    receipt_sha256: str

    def __post_init__(self):
        if not isinstance(self.workspace, Path):
            raise TypeError("predecessor workspace requires Path")
        if not isinstance(self.receipt_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.receipt_sha256):
            raise ValueError("predecessor receipt requires lowercase SHA-256")


def preflight_experiment_archive(
    context: RepositoryContext,
    experiment: Path,
    *,
    max_workers: int = 1,
    native_threads_per_worker: int = 1,
    predecessors: tuple[PredecessorEvidence, ...] = (),
) -> CommandResult:
    """Validate an experiment before the formal execution boundary."""

    try:
        if type(predecessors) is not tuple or any(type(x) is not PredecessorEvidence for x in predecessors):
            raise TypeError("predecessors requires tuple[PredecessorEvidence, ...]")
        loaded = load_experiment(repository_path(context, experiment))
        resources = ExperimentResources(
            max_workers=max_workers,
            random_seed=loaded.definition.random_seed,
            native_threads_per_worker=native_threads_per_worker,
        )
        inputs = tuple(
            load_experiment_input(
                repository_path(context, item.workspace),
                expected_receipt_sha256=item.receipt_sha256,
            )
            for item in predecessors
        )
        report = preflight_experiment(
            loaded,
            resources=resources,
            predecessors=inputs,
        )
    except Exception as exc:
        raise ValidationError(
            "experiment_preflight_invalid",
            str(exc),
            context={"experiment": str(experiment)},
        ) from exc

    if not report.passed:
        raise ValidationError(
            "experiment_preflight_failed",
            "experiment did not pass preflight",
            context=report.to_dict(),
        )
    warnings = tuple(item.message for item in report.checks if item.status.value == "WARNING")
    return CommandResult(
        status="PASS",
        command="experiment.preflight",
        result=report.to_dict(),
        warnings=warnings,
    )


__all__ = ["PredecessorEvidence", "preflight_experiment_archive"]
