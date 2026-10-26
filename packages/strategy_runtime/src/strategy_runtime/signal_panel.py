"""Strategy-owned signal display semantics and immutable observation snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import math
import re
from typing import Mapping

from .errors import RuntimeContractError
from .signal_explanation import (
    SignalExplanationDefinition, SignalExplanationSnapshot, materialize_explanation,
)
from .observation import ConstantGuide, EvidenceGuide, ObservationFormat


def _require(condition, message):
    if not condition:
        raise RuntimeContractError(message)


def _key(value):
    _require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value),
             "invalid signal panel key")


def _text(value, *, optional=False):
    _require(type(value) is str and (optional or bool(value.strip())),
             "signal panel text is required")


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value),
             "signal panel value must be a finite number")


def _tuple(values, kind):
    _require(type(values) is tuple and all(isinstance(x, kind) for x in values),
             "signal panel requires a typed tuple")
    _require(len({x.key for x in values}) == len(values), "duplicate signal panel keys")


def _fields(value, expected):
    _require(type(value) is dict and set(value) == set(expected.split()),
             "invalid signal panel fields")
    return value


def _list(value):
    _require(type(value) is list, "signal panel collections must be lists")
    return value


def _enum(kind, value):
    _require(type(value) in (str, kind), "signal panel enum must be a string")
    try:
        return kind(value)
    except ValueError as exc:
        raise RuntimeContractError("unsupported signal panel enum") from exc


class SignalRender(StrEnum):
    LINE = "LINE"
    STEP = "STEP"
    BAR = "BAR"


class SignalAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SignalGroup:
    """One numeric axis: every member inherits this unit and price/value basis."""

    key: str
    label: str
    unit: str
    basis: str
    format: ObservationFormat = ObservationFormat.NUMBER
    precision: int = 4
    description: str = ""

    def __post_init__(self):
        _key(self.key)
        for value in (self.label, self.unit, self.basis):
            _text(value)
        _text(self.description, optional=True)
        _require(isinstance(self.format, ObservationFormat) and self.format in (
            ObservationFormat.NUMBER, ObservationFormat.PERCENT, ObservationFormat.INTEGER,
        ), "signal group requires a numeric format")
        _require(type(self.precision) is int and 0 <= self.precision <= 10,
                 "signal precision must be an integer in [0, 10]")
        _require(self.format is not ObservationFormat.INTEGER or self.precision == 0,
                 "integer signal format requires zero precision")

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key label unit basis format precision description")
        return cls(**{**value, "format": _enum(ObservationFormat, value["format"])})


@dataclass(frozen=True, slots=True)
class SignalSeriesDefinition:
    key: str
    label: str
    group: str
    value_field: str
    render: SignalRender = SignalRender.LINE
    status_field: str | None = None
    segment_field: str | None = None
    reason_field: str | None = None
    guides: tuple[ConstantGuide | EvidenceGuide, ...] = ()
    description: str = ""

    def __post_init__(self):
        for value in (self.key, self.group, self.value_field):
            _key(value)
        _text(self.label)
        _text(self.description, optional=True)
        _require(isinstance(self.render, SignalRender), "signal render must be typed")
        for value in (self.status_field, self.segment_field, self.reason_field):
            if value is not None:
                _key(value)
        _tuple(self.guides, (ConstantGuide, EvidenceGuide))

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key label group value_field render status_field segment_field reason_field guides description")
        guides = []
        for guide in _list(value["guides"]):
            _require(type(guide) is dict and guide.get("kind") in ("CONSTANT", "EVIDENCE"),
                     "invalid signal guide kind")
            if guide["kind"] == "CONSTANT":
                _fields(guide, "kind key label value")
                guides.append(ConstantGuide(guide["key"], guide["label"], guide["value"]))
            else:
                _fields(guide, "kind key label value_field")
                guides.append(EvidenceGuide(guide["key"], guide["label"], guide["value_field"]))
        return cls(**{**value, "render": _enum(SignalRender, value["render"]), "guides": tuple(guides)})


@dataclass(frozen=True, slots=True)
class SignalStateOption:
    key: str
    label: str

    def __post_init__(self):
        _key(self.key)
        _text(self.label)


@dataclass(frozen=True, slots=True)
class SignalStateDefinition:
    key: str
    label: str
    value_field: str
    options: tuple[SignalStateOption, ...]
    status_field: str | None = None
    reason_field: str | None = None
    description: str = ""

    def __post_init__(self):
        _key(self.key)
        _key(self.value_field)
        _text(self.label)
        _text(self.description, optional=True)
        _tuple(self.options, SignalStateOption)
        _require(bool(self.options), "signal state requires declared options")
        for value in (self.status_field, self.reason_field):
            if value is not None:
                _key(value)

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key label value_field options status_field reason_field description")
        return cls(**{**value, "options": tuple(
            SignalStateOption(**_fields(x, "key label")) for x in _list(value["options"])
        )})


@dataclass(frozen=True, slots=True)
class SignalPanelDefinition:
    groups: tuple[SignalGroup, ...]
    series: tuple[SignalSeriesDefinition, ...]
    states: tuple[SignalStateDefinition, ...] = ()
    explanation: SignalExplanationDefinition | None = None

    def __post_init__(self):
        _tuple(self.groups, SignalGroup)
        _tuple(self.series, SignalSeriesDefinition)
        _tuple(self.states, SignalStateDefinition)
        _require(self.explanation is None or isinstance(self.explanation, SignalExplanationDefinition),
                 "signal explanation must be typed")
        if self.explanation is not None:
            self.explanation.validate_panel(self)
        _require(bool(self.series or self.states), "signal panel must declare content")
        _require(not {x.key for x in self.series} & {x.key for x in self.states},
                 "signal series and states repeat keys")
        _require({x.group for x in self.series} == {x.key for x in self.groups},
                 "signal series must reference exactly the declared groups")
        for group in self.groups:
            if group.format is ObservationFormat.INTEGER:
                for series in self.series:
                    if series.group == group.key:
                        for guide in series.guides:
                            if isinstance(guide, ConstantGuide):
                                _require(float(guide.value).is_integer(), "integer signal guide is fractional")

    @property
    def evidence_fields(self) -> tuple[str, ...]:
        values = set()
        for item in (*self.series, *self.states):
            values.update(x for x in (item.value_field, item.status_field, item.reason_field) if x is not None)
            if isinstance(item, SignalSeriesDefinition):
                if item.segment_field is not None:
                    values.add(item.segment_field)
                values.update(g.value_field for g in item.guides if isinstance(g, EvidenceGuide))
        return tuple(sorted(values))

    def to_dict(self):
        value = {
            "groups": [asdict(x) for x in self.groups],
            "series": [{**asdict(x), "guides": [
                {"kind": "CONSTANT" if isinstance(g, ConstantGuide) else "EVIDENCE", **asdict(g)}
                for g in x.guides
            ]} for x in self.series],
            "states": [asdict(x) | {"options": [asdict(o) for o in x.options]} for x in self.states],
        }
        if self.explanation is not None:
            value["explanation"] = self.explanation.to_dict()
        return value

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict, "signal panel requires an object")
        _fields(value, "groups series states" + (" explanation" if "explanation" in value else ""))
        return cls(
            tuple(SignalGroup.from_dict(x) for x in _list(value["groups"])),
            tuple(SignalSeriesDefinition.from_dict(x) for x in _list(value["series"])),
            tuple(SignalStateDefinition.from_dict(x) for x in _list(value["states"])),
            SignalExplanationDefinition.from_dict(value["explanation"]) if "explanation" in value else None,
        )


def _availability(status, value, reason):
    _require(isinstance(status, SignalAvailability), "signal availability must be typed")
    if status is SignalAvailability.AVAILABLE:
        _require(value is not None and reason is None, "available signal requires value and no unavailable reason")
    else:
        _require(value is None, "inactive or unavailable signal must not expose a value")
        if reason is not None:
            _text(reason)
        if status is SignalAvailability.UNAVAILABLE:
            _require(reason is not None, "unavailable signal requires a reason")


@dataclass(frozen=True, slots=True)
class ObservedSignalSeries:
    key: str
    label: str
    group: str
    render: SignalRender
    description: str
    value: float | None
    status: SignalAvailability
    reason: str | None
    segment_id: str | None
    guides: tuple[ConstantGuide, ...]

    def __post_init__(self):
        for value in (self.key, self.group):
            _key(value)
        _text(self.label)
        _text(self.description, optional=True)
        _require(isinstance(self.render, SignalRender), "signal render must be typed")
        _availability(self.status, self.value, self.reason)
        _tuple(self.guides, ConstantGuide)
        if self.status is SignalAvailability.AVAILABLE:
            _number(self.value)
            if self.segment_id is not None:
                _text(self.segment_id)
                _require(len(self.segment_id) <= 128, "signal segment identity is too long")
        else:
            _require(self.segment_id is None and not self.guides,
                     "inactive or unavailable signal cannot expose segments or guides")

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key label group render description value status reason segment_id guides")
        return cls(**{**value, "render": _enum(SignalRender, value["render"]),
                      "status": _enum(SignalAvailability, value["status"]), "guides": tuple(
                          ConstantGuide(**_fields(g, "key label value")) for g in _list(value["guides"])
                      )})


@dataclass(frozen=True, slots=True)
class ObservedSignalState:
    key: str
    label: str
    description: str
    options: tuple[SignalStateOption, ...]
    value: str | None
    status: SignalAvailability
    reason: str | None

    def __post_init__(self):
        _key(self.key)
        _text(self.label)
        _text(self.description, optional=True)
        _tuple(self.options, SignalStateOption)
        _require(bool(self.options), "signal state requires declared options")
        _availability(self.status, self.value, self.reason)
        if self.status is SignalAvailability.AVAILABLE:
            _require(type(self.value) is str and self.value in {x.key for x in self.options},
                     "signal state is not declared")

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key label description options value status reason")
        return cls(**{**value, "status": _enum(SignalAvailability, value["status"]), "options": tuple(
            SignalStateOption(**_fields(x, "key label")) for x in _list(value["options"])
        )})


@dataclass(frozen=True, slots=True)
class SignalPanelSnapshot:
    groups: tuple[SignalGroup, ...]
    series: tuple[ObservedSignalSeries, ...]
    states: tuple[ObservedSignalState, ...] = ()
    explanation: SignalExplanationSnapshot | None = None

    def __post_init__(self):
        _tuple(self.groups, SignalGroup)
        _tuple(self.series, ObservedSignalSeries)
        _tuple(self.states, ObservedSignalState)
        _require(self.explanation is None or isinstance(self.explanation, SignalExplanationSnapshot),
                 "observed explanation must be typed")
        if self.explanation is not None:
            selector = next((x for x in self.states if x.key == self.explanation.state_key), None)
            _require(selector is not None and selector.status is SignalAvailability.AVAILABLE
                     and selector.value == self.explanation.case_key,
                     "observed explanation differs from recorded state")
        _require(bool(self.series or self.states), "signal panel must declare content")
        _require(not {x.key for x in self.series} & {x.key for x in self.states},
                 "signal series and states repeat keys")
        _require({x.group for x in self.series} == {x.key for x in self.groups},
                 "signal series must reference exactly the declared groups")
        integer_groups = {x.key for x in self.groups if x.format is ObservationFormat.INTEGER}
        for series in self.series:
            if series.group in integer_groups and series.status is SignalAvailability.AVAILABLE:
                _require(all(float(v).is_integer() for v in (series.value, *(g.value for g in series.guides))),
                         "integer signal value is fractional")

    def to_dict(self):
        value = {
            "groups": [asdict(x) for x in self.groups],
            "series": [{**asdict(x), "guides": [asdict(g) for g in x.guides]} for x in self.series],
            "states": [{**asdict(x), "options": [asdict(o) for o in x.options]} for x in self.states],
        }
        if self.explanation is not None:
            value["explanation"] = self.explanation.to_dict()
        return value

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict, "signal panel requires an object")
        _fields(value, "groups series states" + (" explanation" if "explanation" in value else ""))
        return cls(
            tuple(SignalGroup.from_dict(x) for x in _list(value["groups"])),
            tuple(ObservedSignalSeries.from_dict(x) for x in _list(value["series"])),
            tuple(ObservedSignalState.from_dict(x) for x in _list(value["states"])),
            SignalExplanationSnapshot.from_dict(value["explanation"]) if "explanation" in value else None,
        )


def materialize_signal_panel(definition: SignalPanelDefinition, evidence: Mapping[str, object]) -> SignalPanelSnapshot:
    """Copy declared evidence into a typed snapshot, without business inference."""
    _require(isinstance(definition, SignalPanelDefinition) and isinstance(evidence, Mapping),
             "signal panel materialization requires typed declaration and evidence")

    def value(field):
        _require(field in evidence, f"signal panel evidence missing {field}")
        return evidence[field]

    def status(item):
        return SignalAvailability.AVAILABLE if item.status_field is None else _enum(SignalAvailability, value(item.status_field))

    def reason(item, availability):
        if availability is SignalAvailability.AVAILABLE or item.reason_field is None:
            return None
        return value(item.reason_field)

    series = []
    for item in definition.series:
        availability = status(item)
        available = availability is SignalAvailability.AVAILABLE
        segment_id = value(item.segment_field) if available and item.segment_field else None
        if available and item.segment_field:
            _text(segment_id)
        guides = tuple(ConstantGuide(g.key, g.label, g.value if isinstance(g, ConstantGuide) else value(g.value_field))
                       for g in item.guides) if available else ()
        series.append(ObservedSignalSeries(
            item.key, item.label, item.group, item.render, item.description,
            value(item.value_field) if available else None, availability, reason(item, availability),
            segment_id, guides,
        ))
    states = []
    for item in definition.states:
        availability = status(item)
        states.append(ObservedSignalState(
            item.key, item.label, item.description, item.options,
            value(item.value_field) if availability is SignalAvailability.AVAILABLE else None,
            availability, reason(item, availability),
        ))
    panel = SignalPanelSnapshot(definition.groups, tuple(series), tuple(states))
    if definition.explanation is not None:
        return SignalPanelSnapshot(panel.groups, panel.series, panel.states,
                                   materialize_explanation(definition.explanation, panel))
    return panel
