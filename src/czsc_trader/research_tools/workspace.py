"""Caller-owned locations for candidate, decision, inspection and freeze storage."""

from dataclasses import dataclass

from strategy_manager import CandidateKey, ResearchEvidenceLocation
from strategy_manager.validation import require_strategy_id

from .delivery import _Record, _path, _unique, ExperimentOwner


@dataclass(frozen=True, slots=True)
class CandidateLocation(_Record):
    key: CandidateKey
    experiment_id: str

    def _validate(self):
        ExperimentOwner(self.key.strategy_id, self.experiment_id)


@dataclass(frozen=True, slots=True)
class FreezeJournalLocation(_Record):
    strategy_id: str
    path: str

    def _validate(self):
        require_strategy_id(self.strategy_id)
        _path(self.path)


@dataclass(frozen=True, slots=True)
class ResearchWorkspace(_Record):
    registry_path: str
    candidates: tuple[CandidateLocation, ...] = ()
    evidence: tuple[ResearchEvidenceLocation, ...] = ()
    freeze_journals: tuple[FreezeJournalLocation, ...] = ()

    def _validate(self):
        _path(self.registry_path)
        _unique((x.key for x in self.candidates), "candidate location")
        _unique((x.owner for x in self.evidence), "evidence owner location")
        _unique((x.path.casefold() for x in self.evidence), "evidence root")
        _unique((x.strategy_id for x in self.freeze_journals), "freeze journal owner")
        _unique((x.path.casefold() for x in self.freeze_journals), "freeze journal root")
