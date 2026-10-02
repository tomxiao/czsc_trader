"""Typed strategy observation declarations and immutable per-plan facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
import math
import re
from typing import TYPE_CHECKING

from .errors import RuntimeContractError

if TYPE_CHECKING:
    from .contracts import ExecutionPlan, StrategyIdentity
    from .models import RuntimeDefinition

OBSERVATION_CONTRACT_VERSION = "strategy_observation.v2"


def _require(condition, message):
    if not condition:
        raise RuntimeContractError(message)


def _key(value):
    _require(
        isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value),
        "invalid observation key",
    )


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), "observation text is required")


def _number(value):
    _require(
        type(value) in (int, float) and math.isfinite(value),
        "observation value must be finite numeric data",
    )
    return float(value)


def _tuple(values, kind):
    _require(
        type(values) is tuple and all(isinstance(x, kind) for x in values),
        "observation requires a typed tuple",
    )
    _require(len({x.key for x in values}) == len(values), "duplicate observation keys")


def _fields(value, expected):
    _require(
        type(value) is dict and set(value) == set(expected.split()), "invalid observation fields"
    )
    return value


class ObservationValueType(StrEnum):
    NUMBER = "NUMBER"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    TEXT = "TEXT"


class ObservationFormat(StrEnum):
    NUMBER = "NUMBER"
    PERCENT = "PERCENT"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    TEXT = "TEXT"


@dataclass(frozen=True, slots=True)
class ConstantGuide:
    key: str
    label: str
    value: float

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _number(self.value)


@dataclass(frozen=True, slots=True)
class EvidenceGuide:
    key: str
    label: str
    value_field: str

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _key(self.value_field)


@dataclass(frozen=True, slots=True)
class ObservationSeries:
    key: str
    label: str
    value_field: str
    guides: tuple[ConstantGuide | EvidenceGuide, ...] = ()

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _key(self.value_field)
        _tuple(self.guides, (ConstantGuide, EvidenceGuide))


@dataclass(frozen=True, slots=True)
class ObservationFact:
    key: str
    label: str
    value_field: str
    value_type: ObservationValueType
    format: ObservationFormat

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _key(self.value_field)
        _require(
            isinstance(self.value_type, ObservationValueType)
            and isinstance(self.format, ObservationFormat),
            "observation fact requires typed value/format",
        )
        allowed = {
            ObservationValueType.NUMBER: (ObservationFormat.NUMBER, ObservationFormat.PERCENT),
            ObservationValueType.INTEGER: (ObservationFormat.INTEGER,),
            ObservationValueType.BOOLEAN: (ObservationFormat.BOOLEAN,),
            ObservationValueType.TEXT: (ObservationFormat.TEXT,),
        }
        _require(
            self.format in allowed[self.value_type],
            "observation fact format differs from value type",
        )

    def validate_value(self, value):
        if self.value_type is ObservationValueType.NUMBER:
            _number(value)
        else:
            kind = {
                ObservationValueType.INTEGER: int,
                ObservationValueType.BOOLEAN: bool,
                ObservationValueType.TEXT: str,
            }[self.value_type]
            _require(type(value) is kind, "observation fact value type differs")


@dataclass(frozen=True, slots=True)
class ObservationDefinition:
    series: tuple[ObservationSeries, ...]
    facts: tuple[ObservationFact, ...]

    def __post_init__(self):
        _tuple(self.series, ObservationSeries)
        _tuple(self.facts, ObservationFact)
        _require(
            not {x.key for x in self.series} & {x.key for x in self.facts},
            "series and facts repeat observation keys",
        )

    def to_dict(self):
        return {
            "contract_version": OBSERVATION_CONTRACT_VERSION,
            "series": [
                {
                    **asdict(x),
                    "guides": [
                        {
                            "kind": "CONSTANT" if isinstance(g, ConstantGuide) else "EVIDENCE",
                            **asdict(g),
                        }
                        for g in x.guides
                    ],
                }
                for x in self.series
            ],
            "facts": [asdict(x) for x in self.facts],
        }

    @classmethod
    def from_dict(cls, value):
        _fields(value, "contract_version series facts")
        _require(
            value["contract_version"] == OBSERVATION_CONTRACT_VERSION,
            "unsupported observation contract",
        )
        _require(
            type(value["series"]) is list and type(value["facts"]) is list,
            "observation collections must be lists",
        )
        series = []
        for raw in value["series"]:
            _fields(raw, "key label value_field guides")
            _require(type(raw["guides"]) is list, "observation guides must be a list")
            guides = []
            for guide in raw["guides"]:
                _require(
                    type(guide) is dict and guide.get("kind") in ("CONSTANT", "EVIDENCE"),
                    "invalid guide kind",
                )
                kind = ConstantGuide if guide["kind"] == "CONSTANT" else EvidenceGuide
                field = "value" if kind is ConstantGuide else "value_field"
                _fields(guide, f"kind key label {field}")
                guides.append(kind(guide["key"], guide["label"], guide[field]))
            series.append(
                ObservationSeries(raw["key"], raw["label"], raw["value_field"], tuple(guides))
            )
        facts = []
        for raw in value["facts"]:
            _fields(raw, "key label value_field value_type format")
            facts.append(
                ObservationFact(
                    raw["key"],
                    raw["label"],
                    raw["value_field"],
                    ObservationValueType(raw["value_type"]),
                    ObservationFormat(raw["format"]),
                )
            )
        return cls(tuple(series), tuple(facts))

    @property
    def sha256(self):
        from .models import canonical_sha256

        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class ObservedSeries:
    key: str
    label: str
    value: float
    guides: tuple[ConstantGuide, ...]

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _number(self.value)
        _tuple(self.guides, ConstantGuide)


@dataclass(frozen=True, slots=True)
class ObservedFact:
    key: str
    label: str
    value_type: ObservationValueType
    format: ObservationFormat
    value: float | int | bool | str

    def __post_init__(self):
        ObservationFact(
            self.key, self.label, self.key, self.value_type, self.format
        ).validate_value(self.value)


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    strategy: StrategyIdentity
    definition_sha256: str
    signal_identity: str
    plan_identity: str
    signal_date: date
    valid_session: date
    action: str
    target_position: float
    series: tuple[ObservedSeries, ...]
    facts: tuple[ObservedFact, ...]

    def __post_init__(self):
        from .contracts import StrategyIdentity

        _require(
            isinstance(self.strategy, StrategyIdentity),
            "observation strategy identity must be typed",
        )
        for value in (self.definition_sha256, self.signal_identity, self.plan_identity):
            _require(
                isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
                "invalid observation identity hash",
            )
        _require(
            type(self.signal_date) is date
            and type(self.valid_session) is date
            and self.signal_date < self.valid_session,
            "invalid observation sessions",
        )
        _text(self.action)
        _number(self.target_position)
        _tuple(self.series, ObservedSeries)
        _tuple(self.facts, ObservedFact)
        _require(
            not {x.key for x in self.series} & {x.key for x in self.facts},
            "duplicate observation keys",
        )

    def to_dict(self):
        value = asdict(self)
        value.update(
            contract_version=OBSERVATION_CONTRACT_VERSION,
            status="READY",
            signal_date=self.signal_date.isoformat(),
            valid_session=self.valid_session.isoformat(),
        )
        value["series"] = [
            {**asdict(x), "guides": [asdict(g) for g in x.guides]} for x in self.series
        ]
        value["facts"] = [asdict(x) for x in self.facts]
        return value

    @classmethod
    def from_dict(cls, value):
        from .contracts import StrategyIdentity

        _fields(
            value,
            "contract_version status strategy definition_sha256 signal_identity plan_identity signal_date valid_session action target_position series facts",
        )
        _require(
            value["contract_version"] == OBSERVATION_CONTRACT_VERSION
            and value["status"] == "READY",
            "unsupported ready observation contract",
        )
        _fields(value["strategy"], "strategy_id reference_id release_hash runtime_sha256 symbol")
        _require(
            type(value["series"]) is list and type(value["facts"]) is list,
            "observation collections must be lists",
        )
        series = []
        for raw in value["series"]:
            _fields(raw, "key label value guides")
            _require(type(raw["guides"]) is list, "observation guides must be a list")
            guides = tuple(ConstantGuide(**_fields(g, "key label value")) for g in raw["guides"])
            series.append(ObservedSeries(raw["key"], raw["label"], raw["value"], guides))
        facts = []
        for raw in value["facts"]:
            _fields(raw, "key label value_type format value")
            facts.append(
                ObservedFact(
                    raw["key"],
                    raw["label"],
                    ObservationValueType(raw["value_type"]),
                    ObservationFormat(raw["format"]),
                    raw["value"],
                )
            )
        return cls(
            StrategyIdentity(**value["strategy"]),
            value["definition_sha256"],
            value["signal_identity"],
            value["plan_identity"],
            date.fromisoformat(value["signal_date"]),
            date.fromisoformat(value["valid_session"]),
            value["action"],
            value["target_position"],
            tuple(series),
            tuple(facts),
        )


@dataclass(frozen=True, slots=True)
class ObservationUnavailable:
    message: str

    def __post_init__(self):
        _text(self.message)

    def to_dict(self):
        return {
            "contract_version": OBSERVATION_CONTRACT_VERSION,
            "status": "UNAVAILABLE",
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value):
        _fields(value, "contract_version status message")
        _require(
            value["contract_version"] == OBSERVATION_CONTRACT_VERSION
            and value["status"] == "UNAVAILABLE",
            "unsupported unavailable observation contract",
        )
        return cls(value["message"])


def unavailable_observation(message: str) -> ObservationUnavailable:
    return ObservationUnavailable(message)


def materialize_observation(
    definition: RuntimeDefinition, plan: ExecutionPlan
) -> StrategyObservation:
    from .models import RuntimeDefinition
    from .contracts import ExecutionPlan

    _require(
        isinstance(definition, RuntimeDefinition) and isinstance(plan, ExecutionPlan),
        "observation requires a runtime definition and execution plan",
    )
    _require(
        plan.strategy.strategy_id == definition.strategy_family_id
        and plan.strategy.runtime_sha256 == definition.runtime_sha256
        and plan.strategy.reference_id == definition.release_id
        and plan.strategy.release_hash == definition.release_hash
        and plan.symbol == definition.tradable_symbol,
        "observation plan differs from runtime definition",
    )

    def value(field):
        _require(field in plan.evidence, f"observation evidence missing {field}")
        return plan.evidence[field]

    series = tuple(
        ObservedSeries(
            s.key,
            s.label,
            _number(value(s.value_field)),
            tuple(
                ConstantGuide(
                    g.key,
                    g.label,
                    g.value if isinstance(g, ConstantGuide) else _number(value(g.value_field)),
                )
                for g in s.guides
            ),
        )
        for s in definition.observation.series
    )
    facts = tuple(
        ObservedFact(f.key, f.label, f.value_type, f.format, value(f.value_field))
        for f in definition.observation.facts
    )
    return StrategyObservation(
        plan.strategy,
        definition.observation.sha256,
        plan.signal_identity,
        plan.plan_identity,
        plan.signal_date,
        plan.trading_date,
        plan.action,
        plan.target_position,
        series,
        facts,
    )
