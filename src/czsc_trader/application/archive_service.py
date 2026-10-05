from __future__ import annotations

from pathlib import Path

from czsc_trader.experiment_archive import validate_experiment_archive

from .context import RepositoryContext
from .errors import UsageError, ValidationError
from .research_paths import repository_path
from .results import CommandResult


def validate_archives(context: RepositoryContext, archives: tuple[Path, ...]) -> CommandResult:
    """Validate the caller's explicit, nonempty archive selection without scanning."""
    if type(archives) is not tuple or not archives or any(not isinstance(x, Path) for x in archives):
        raise UsageError("archive_selection_invalid", "archives requires a nonempty tuple of Path")
    try:
        paths = tuple(repository_path(context, path) for path in archives)
        if len(set(paths)) != len(paths):
            raise ValueError("archive selection contains duplicate paths")
        manifests = [validate_experiment_archive(path) for path in paths]
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationError("experiment_archive_invalid", str(exc)) from exc
    return CommandResult(
        status="PASS", command="archive.validate",
        result={"validated_count": len(paths),
                "experiments": [str(item["experiment_id"]) for item in manifests]},
    )
