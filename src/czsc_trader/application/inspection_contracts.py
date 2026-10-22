"""Public inputs to the two-goal technical inspection (no research assessment)."""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import math

from paper_trading_engine.inspection import PteInspectionProtocol
from strategy_manager import CandidateKey
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyInputBinding
from ..backtesting.execution_data import BacktestExecutionData
from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.delivery import EvaluationEvidenceRef


class InspectionDataKind(StrEnum):
    HISTORICAL = "HISTORICAL"
    SYNTHETIC = "SYNTHETIC"


class InspectionInputError(ValueError):
    """Rejected before execution; code and field are stable caller-facing facts."""
    def __init__(self, code: str, field: str, message: str):
        self.code, self.field, self.message = code, field, message
        super().__init__(f"{field}: {message}")


def _version(value, field):
    try:
        f._version(value)
    except (TypeError, ValueError) as exc:
        raise InspectionInputError("INVALID_VALUE", field, str(exc)) from exc


@dataclass(frozen=True, slots=True)
class FreezeTarget:
    version: str
    parent_version: str | None
    change_summary: str
    selection_data_cutoff: date
    forward_start: date

    def __post_init__(self):
        _version(self.version, "target.version")
        if self.parent_version is not None:
            _version(self.parent_version, "target.parent_version")
            if int(self.parent_version[1:]) >= int(self.version[1:]):
                raise InspectionInputError("INVALID_VALUE", "target.parent_version", "parent must precede target version")
        if type(self.change_summary) is not str or not self.change_summary.strip():
            raise InspectionInputError("INVALID_VALUE", "target.change_summary", "change summary is required")
        if type(self.selection_data_cutoff) is not date or type(self.forward_start) is not date:
            raise InspectionInputError("INVALID_TYPE", "target", "freeze dates require date")
        if self.forward_start <= self.selection_data_cutoff:
            raise InspectionInputError("INVALID_VALUE", "target.forward_start", "forward_start must follow selection cutoff")

    def to_dict(self):
        return {"version": self.version, "parent_version": self.parent_version,
                "change_summary": self.change_summary,
                "selection_data_cutoff": self.selection_data_cutoff.isoformat(),
                "forward_start": self.forward_start.isoformat()}


@dataclass(frozen=True, slots=True)
class InspectionReplay:
    coordinate: f.InspectionCoordinate
    input_binding: StrategyInputBinding
    execution_data: BacktestExecutionData
    initial_cash: float
    one_way_cost: float
    baseline: EvaluationEvidenceRef | None = None

    def __post_init__(self):
        for value, kind in ((self.coordinate, f.InspectionCoordinate),
                            (self.input_binding, StrategyInputBinding),
                            (self.execution_data, BacktestExecutionData)):
            if type(value) is not kind:
                raise InspectionInputError("INVALID_TYPE", "replays", f"inspection replay requires {kind.__name__}")
        if self.baseline is not None and type(self.baseline) is not EvaluationEvidenceRef:
            raise InspectionInputError("INVALID_TYPE", "replays.baseline", "baseline requires EvaluationEvidenceRef")
        for name, value in (("initial_cash", self.initial_cash), ("one_way_cost", self.one_way_cost)):
            if type(value) not in (float, int) or not math.isfinite(value):
                raise InspectionInputError("INVALID_VALUE", "replays." + name, f"{name} must be finite")
        if self.initial_cash <= 0 or not 0 <= self.one_way_cost < 1:
            raise InspectionInputError("INVALID_VALUE", "replays", "invalid cash or cost")


@dataclass(frozen=True, slots=True)
class InspectionProtocol:
    method_version: str
    comparison: str
    float_tolerance: float
    pte: PteInspectionProtocol

    def __post_init__(self):
        if self.method_version != "candidate-inspection-v2" or self.comparison != "ECONOMIC_V1":
            raise InspectionInputError("UNSUPPORTED_CONTRACT", "protocol", "unsupported technical inspection protocol")
        if type(self.float_tolerance) not in (float, int) or not math.isfinite(self.float_tolerance) or self.float_tolerance < 0:
            raise InspectionInputError("INVALID_VALUE", "protocol.float_tolerance", "tolerance must be finite and nonnegative")
        if type(self.pte) is not PteInspectionProtocol:
            raise InspectionInputError("INVALID_TYPE", "protocol.pte", "protocol requires PteInspectionProtocol")

    def to_dict(self):
        return {"method_version": self.method_version, "comparison": self.comparison,
                "float_tolerance": self.float_tolerance, "pte": self.pte.to_dict()}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {"method_version", "comparison", "float_tolerance", "pte"}:
            raise InspectionInputError("INVALID_FIELDS", "protocol", "inspection protocol fields differ")
        return cls(value["method_version"], value["comparison"], value["float_tolerance"],
                   PteInspectionProtocol.from_dict(value["pte"]))


@dataclass(frozen=True, slots=True)
class CandidateInspectionRequest:
    candidate: CandidateKey
    selection: f.DecisionReference
    research: ResearchContext
    experiment: ExperimentRef
    target: FreezeTarget
    protocol: InspectionProtocol
    replays: tuple[InspectionReplay, ...]
    data_kind: InspectionDataKind
    additional_files: tuple[f.FreezeFile, ...] = ()
    remaining_risks: tuple[str, ...] = ()

    def __post_init__(self):
        for name, kind in (("candidate", CandidateKey), ("selection", f.DecisionReference),
                           ("research", ResearchContext), ("experiment", ExperimentRef),
                           ("target", FreezeTarget), ("protocol", InspectionProtocol), ("data_kind", InspectionDataKind)):
            if type(getattr(self, name)) is not kind:
                raise InspectionInputError("INVALID_TYPE", name, f"inspection {name} requires {kind.__name__}")
        for name, kind in (("replays", InspectionReplay), ("additional_files", f.FreezeFile), ("remaining_risks", str)):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(x) is not kind for x in values):
                raise InspectionInputError("INVALID_TYPE", name, f"{name} requires typed tuple")
        if not self.replays or len({x.coordinate for x in self.replays}) != len(self.replays):
            raise InspectionInputError("INVALID_COORDINATES", "replays", "replays require nonempty unique coordinates")
        if self.research.strategy_id != self.candidate.strategy_id or self.experiment.strategy_id != self.candidate.strategy_id:
            raise InspectionInputError("IDENTITY_MISMATCH", "candidate", "inspection research family differs")
        if any(not x.strip() for x in self.remaining_risks):
            raise InspectionInputError("INVALID_VALUE", "remaining_risks", "risk must be nonempty")


class InspectionPublicationError(RuntimeError):
    """Execution may have completed, but formal evidence was not published."""
    def __init__(self, phase, partial_evidence, report_reference, message):
        self.phase = phase
        self.partial_evidence = tuple(partial_evidence)
        self.report_reference = report_reference
        super().__init__(message)
