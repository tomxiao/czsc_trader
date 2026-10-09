"""Typed identities and capabilities for one research batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import TYPE_CHECKING

from dataflows import Dataflows
from strategy_runtime import StrategyRuntime
from strategy_manager.validation import require_strategy_id

from ._records import _Record

if TYPE_CHECKING:
    from ..application.context import RepositoryContext
    from .evaluation_access import EvaluationAccess


@dataclass(frozen=True, slots=True)
class ResearchBatchRef(_Record):
    strategy_id: str

    def _validate(self):
        require_strategy_id(self.strategy_id)


@dataclass(frozen=True, slots=True)
class ExperimentRef(_Record):
    strategy_id: str
    experiment_id: str

    def _validate(self):
        require_strategy_id(self.strategy_id)
        if not re.fullmatch(r"EX(?!000_)[0-9]{3}_[0-9]{8}", self.experiment_id):
            raise ValueError("experiment_id must match EX001..EX999_YYYYMMDD")
        datetime.strptime(self.experiment_id.rsplit("_", 1)[1], "%Y%m%d")

    @property
    def repository_path(self) -> str:
        return f"research/{self.strategy_id}/experiments/{self.experiment_id}"

    def resolve(self, repository_root: Path) -> Path:
        from .evidence import managed_path

        return managed_path(repository_root, self.repository_path)


@dataclass(frozen=True, slots=True)
class ResearchContext:
    batch: ResearchBatchRef
    repository: RepositoryContext
    data: Dataflows
    runtime: StrategyRuntime
    evaluation: EvaluationAccess

    def __post_init__(self):
        from ..application.context import RepositoryContext
        from .evaluation_access import EvaluationAccess

        for value, expected in (
            (self.batch, ResearchBatchRef), (self.repository, RepositoryContext),
            (self.data, Dataflows), (self.runtime, StrategyRuntime),
            (self.evaluation, EvaluationAccess),
        ):
            if type(value) is not expected:
                raise TypeError(f"research context requires {expected.__name__}")
        binding = self.data.binding
        if binding.base_dir != self.repository.root or binding.space.path != Path(f"research/{self.strategy_id}/assets/data"):
            raise ValueError("research data must use the batch-owned repository space")
        if self.evaluation.data is not self.data or self.evaluation.strategy_id != self.strategy_id:
            raise ValueError("research evaluation must use the same batch and data capability")

    @property
    def strategy_id(self):
        return self.batch.strategy_id
