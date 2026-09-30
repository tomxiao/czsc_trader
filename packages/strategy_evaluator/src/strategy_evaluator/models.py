from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Mapping


class ValidationError(ValueError):
    def __init__(self, message: str, code: str = "INVALID_INPUT") -> None:
        super().__init__(message)
        self.code = code


class MetricStatus(str, Enum):
    VALID = "VALID"
    LOW_SAMPLE = "LOW_SAMPLE"
    NO_CLOSED_TRADES = "NO_CLOSED_TRADES"
    NO_WINS = "NO_WINS"
    NO_LOSSES = "NO_LOSSES"
    UNAVAILABLE = "UNAVAILABLE"


def _exact(data: Mapping[str, Any], required: set[str], optional: set[str] = set()) -> None:
    unknown = set(data) - required - optional
    missing = required - set(data)
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", "UNKNOWN_FIELDS")
    if missing:
        raise ValidationError(f"missing fields: {sorted(missing)}", "MISSING_FIELDS")


def _pairs(value: Any, name: str) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} must be an object", "INVALID_MAPPING")
    return tuple(sorted((str(k), v) for k, v in value.items()))


def _enum(cls: type[Enum], value: Any, name: str) -> Any:
    try:
        return cls(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"invalid {name}: {value}", "INVALID_ENUM") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return (
            value.to_dict()
            if isinstance(value, Record)
            else {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
        )
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


class Record:
    def to_dict(self) -> dict[str, Any]:
        mapping_fields = {"tightened_margins", "objective_values", "worst_scores"}
        result = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in mapping_fields:
                result[field.name] = {key: _json_value(item) for key, item in value}
            else:
                result[field.name] = _json_value(value)
        return result


@dataclass(frozen=True)
class TargetRequirement(Record):
    metric: str
    direction: str
    minimum_improvement: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TargetRequirement:
        _exact(data, {"metric", "direction", "minimum_improvement"})
        return cls(str(data["metric"]), str(data["direction"]), float(data["minimum_improvement"]))


@dataclass(frozen=True)
class EvaluationProtocol(Record):
    schema_version: int
    standard_version: str
    experiment_id: str
    research_objective: str
    development_cutoff: str
    incumbent_id: str
    incumbent_hash: str
    decision_windows: tuple[str, ...]
    target_windows: tuple[str, ...]
    execution_policy_hash: str
    tightened_margins: tuple[tuple[str, Any], ...]
    shortlist_limit: int
    target_requirements: tuple[TargetRequirement, ...]
    candidate_manifest: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvaluationProtocol:
        required = {
            "schema_version",
            "standard_version",
            "experiment_id",
            "research_objective",
            "development_cutoff",
            "incumbent_id",
            "incumbent_hash",
            "decision_windows",
            "target_windows",
            "execution_policy_hash",
            "tightened_margins",
            "shortlist_limit",
            "target_requirements",
            "candidate_manifest",
        }
        _exact(data, required)
        return cls(
            int(data["schema_version"]),
            str(data["standard_version"]),
            str(data["experiment_id"]),
            str(data["research_objective"]),
            str(data["development_cutoff"]),
            str(data["incumbent_id"]),
            str(data["incumbent_hash"]),
            tuple(map(str, data["decision_windows"])),
            tuple(map(str, data["target_windows"])),
            str(data["execution_policy_hash"]),
            _pairs(data["tightened_margins"], "tightened_margins"),
            int(data["shortlist_limit"]),
            tuple(TargetRequirement.from_dict(x) for x in data["target_requirements"]),
            str(data["candidate_manifest"]),
        )


@dataclass(frozen=True)
class CandidateDescriptor(Record):
    candidate_id: str
    candidate_hash: str
    execution_policy_hash: str
    is_incumbent: bool = False
    behavior_hash: str = ""
    parameter_distance: float = 0.0
    family: str = ""
    generation_stage: str = ""
    parent_candidate_id: str | None = None
    parameter_group: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidateDescriptor:
        _exact(
            data,
            {"candidate_id", "candidate_hash", "execution_policy_hash"},
            {
                "is_incumbent",
                "behavior_hash",
                "parameter_distance",
                "family",
                "generation_stage",
                "parent_candidate_id",
                "parameter_group",
            },
        )
        parent = data.get("parent_candidate_id")
        return cls(
            str(data["candidate_id"]),
            str(data["candidate_hash"]),
            str(data["execution_policy_hash"]),
            bool(data.get("is_incumbent", False)),
            str(data.get("behavior_hash", "")),
            float(data.get("parameter_distance", 0.0)),
            str(data.get("family", "")),
            str(data.get("generation_stage", "")),
            None if parent is None else str(parent),
            str(data.get("parameter_group", "")),
        )


@dataclass(frozen=True)
class MetricObservation(Record):
    candidate_id: str
    window_id: str
    scenario_id: str
    measurement_tier: str
    net_cagr: float
    total_return: float
    max_drawdown: float
    calmar: float | None
    calmar_status: MetricStatus
    profit_factor: float | None
    profit_factor_status: MetricStatus
    closed_trades: int
    turnover: float | None = None
    cost_drag: float | None = None
    objective_values: tuple[tuple[str, float], ...] = ()
    frequency_window_days: int | None = None
    rolling_closed_trades_median: float | None = None
    rolling_closed_trades_p10: float | None = None
    win_loss_ratio: float | None = None
    win_loss_ratio_status: MetricStatus = MetricStatus.UNAVAILABLE

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MetricObservation:
        required = {
            "candidate_id",
            "window_id",
            "scenario_id",
            "measurement_tier",
            "net_cagr",
            "total_return",
            "max_drawdown",
            "calmar",
            "calmar_status",
            "profit_factor",
            "profit_factor_status",
            "closed_trades",
        }
        _exact(
            data,
            required,
            {
                "turnover",
                "cost_drag",
                "objective_values",
                "frequency_window_days",
                "rolling_closed_trades_median",
                "rolling_closed_trades_p10",
                "win_loss_ratio",
                "win_loss_ratio_status",
            },
        )
        return cls(
            str(data["candidate_id"]),
            str(data["window_id"]),
            str(data["scenario_id"]),
            str(data["measurement_tier"]),
            float(data["net_cagr"]),
            float(data["total_return"]),
            float(data["max_drawdown"]),
            None if data["calmar"] is None else float(data["calmar"]),
            _enum(MetricStatus, data["calmar_status"], "calmar_status"),
            None if data["profit_factor"] is None else float(data["profit_factor"]),
            _enum(MetricStatus, data["profit_factor_status"], "profit_factor_status"),
            int(data["closed_trades"]),
            None if data.get("turnover") is None else float(data["turnover"]),
            None if data.get("cost_drag") is None else float(data["cost_drag"]),
            tuple(
                (key, float(value))
                for key, value in _pairs(data.get("objective_values", {}), "objective_values")
            ),
            None
            if data.get("frequency_window_days") is None
            else int(data["frequency_window_days"]),
            None
            if data.get("rolling_closed_trades_median") is None
            else float(data["rolling_closed_trades_median"]),
            None
            if data.get("rolling_closed_trades_p10") is None
            else float(data["rolling_closed_trades_p10"]),
            None if data.get("win_loss_ratio") is None else float(data["win_loss_ratio"]),
            _enum(
                MetricStatus,
                data.get("win_loss_ratio_status", MetricStatus.UNAVAILABLE.value),
                "win_loss_ratio_status",
            ),
        )


@dataclass(frozen=True)
class TrialRecord(Record):
    trial_id: str
    candidate_id: str
    strategy_hash: str
    behavior_hash: str
    status: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TrialRecord:
        _exact(data, {"trial_id", "candidate_id", "strategy_hash", "behavior_hash", "status"})
        return cls(
            *(
                str(data[name])
                for name in ("trial_id", "candidate_id", "strategy_hash", "behavior_hash", "status")
            )
        )


@dataclass(frozen=True)
class MetricComparison(Record):
    metric: str
    window_id: str
    candidate_value: float | None
    incumbent_value: float | None
    normalized_score: float | None
    comparable: bool
    passed: bool
    reason_code: str


@dataclass(frozen=True)
class ShortlistResult(Record):
    candidate_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateProfile(Record):
    candidate_id: str
    eligible: bool
    target_achieved: bool
    worst_scores: tuple[tuple[str, float], ...]
    pareto_layer: int | None = None
    median_score: float = 0.0
    turnover: float | None = None
    parameter_distance: float = 0.0
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankingResult(Record):
    incumbent_id: str
    profiles: tuple[CandidateProfile, ...]
    champion_id: str | None
    tied_champion_ids: tuple[str, ...] = ()
