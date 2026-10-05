from __future__ import annotations

from pathlib import Path

from czsc_trader.experiment_archive import (
    iter_experiment_dirs,
    validate_experiment_archive,
)

from .context import RepositoryContext
from .errors import UsageError, ValidationError
from .results import CommandResult


def validate_archives(
    context: RepositoryContext,
    archive: Path | None = None,
    *,
    all_archives: bool = False,
) -> CommandResult:
    if all_archives == (archive is not None):
        raise UsageError(
            "archive_selection_invalid",
            "select exactly one archive or --all",
        )
    try:
        paths = (
            list(iter_experiment_dirs(context.experiments_root))
            if all_archives
            else [Path(archive).resolve()]
        )
        manifests = [validate_experiment_archive(path) for path in paths]
    except (OSError, ValueError) as exc:
        raise ValidationError(
            "experiment_archive_invalid",
            str(exc),
        ) from exc
    identities = [str(item.get("experiment_id", path.name)) for item, path in zip(manifests, paths)]
    return CommandResult(
        status="PASS",
        command="archive.validate",
        result={"validated_count": len(paths), "experiments": identities},
    )
