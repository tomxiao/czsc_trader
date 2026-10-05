from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import UsageError

if TYPE_CHECKING:
    from ..research_tools.delivery import DeliveryWorkspace
    from ..research_tools.workspace import ResearchWorkspace


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
    """Repository resources and caller-supplied delivery/research locations.

    Delivery operations require delivery_workspace; discovery never creates it.
    Candidate, evidence and freeze operations require research_workspace.
    """

    root: Path
    research_root: Path
    research_registry_root: Path
    raw_dir: Path
    research_data_root: Path
    tdr_srt_root: Path
    strategy_root: Path
    experiments_root: Path
    outputs_root: Path
    delivery_workspace: DeliveryWorkspace | None = None
    research_workspace: ResearchWorkspace | None = None

    def __post_init__(self):
        if self.delivery_workspace is not None:
            from ..research_tools.delivery import DeliveryWorkspace

            if type(self.delivery_workspace) is not DeliveryWorkspace:
                raise TypeError("delivery_workspace requires DeliveryWorkspace")
        if self.research_workspace is not None:
            from ..research_tools.workspace import ResearchWorkspace

            if type(self.research_workspace) is not ResearchWorkspace:
                raise TypeError("research_workspace requires ResearchWorkspace")

    @classmethod
    def discover(
        cls,
        start: Path,
        *,
        explicit_root: Path | None = None,
        delivery_workspace: DeliveryWorkspace | None = None,
        research_workspace: ResearchWorkspace | None = None,
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
            delivery_workspace=delivery_workspace,
            research_workspace=research_workspace,
        )
