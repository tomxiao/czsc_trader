from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import UsageError


def _is_repository_root(path: Path) -> bool:
    if (path / "pyproject.toml").is_file() and (path / "src" / "czsc_trader").is_dir():
        return True
    marker = path / "runtime-root.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload == {
            "schema_version": 1,
            "kind": "czsc-trader-runtime",
            "strategy_root": "strategies",
        }
        and (path / "strategies").is_dir()
    )


@dataclass(frozen=True)
class RepositoryContext:
    """Repository-relative paths required by application services."""

    root: Path
    research_root: Path
    research_registry_root: Path
    raw_dir: Path
    research_data_root: Path
    tdr_srt_root: Path
    strategy_root: Path
    experiments_root: Path
    outputs_root: Path

    @classmethod
    def discover(
        cls,
        start: Path,
        *,
        explicit_root: Path | None = None,
    ) -> "RepositoryContext":
        candidate = Path(explicit_root if explicit_root is not None else start).resolve()
        candidates = (candidate, *candidate.parents) if explicit_root is None else (candidate,)
        root = next((path for path in candidates if _is_repository_root(path)), None)
        if root is None:
            raise UsageError(
                "repository_root_not_found",
                f"repository root not found from: {candidate}",
                context={"path": str(candidate)},
            )
        return cls(
            root=root,
            research_root=root / "research",
            research_registry_root=root / "research" / "registrations",
            raw_dir=root / "data" / "raw",
            research_data_root=root / "data" / "raw",
            tdr_srt_root=root / "data" / "backtest",
            strategy_root=root / "strategies",
            experiments_root=root / "experiments",
            outputs_root=root / "outputs",
        )
