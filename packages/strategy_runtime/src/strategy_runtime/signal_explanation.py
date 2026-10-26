"""Plain-text explanations bound to declared, recorded strategy facts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .observation import ObservationFormat, _fields, _key, _require, _text, _tuple


@dataclass(frozen=True, slots=True)
class SeriesValueRef:
    series_key: str

    def __post_init__(self):
        _key(self.series_key)


@dataclass(frozen=True, slots=True)
class GuideValueRef:
    series_key: str
    guide_key: str

    def __post_init__(self):
        _key(self.series_key)
        _key(self.guide_key)


@dataclass(frozen=True, slots=True)
class StateValueRef:
    state_key: str

    def __post_init__(self):
        _key(self.state_key)


SignalTextPart: TypeAlias = str | SeriesValueRef | GuideValueRef | StateValueRef


def _part_dict(part):
    if type(part) is str:
        return {"kind": "TEXT", "text": part}
    if isinstance(part, GuideValueRef):
        return {"kind": "GUIDE", "series_key": part.series_key, "guide_key": part.guide_key}
    if isinstance(part, SeriesValueRef):
        return {"kind": "SERIES", "series_key": part.series_key}
    return {"kind": "STATE", "state_key": part.state_key}


def _part_read(value):
    _require(type(value) is dict, "explanation part must be an object")
    kind = value.get("kind")
    if kind == "TEXT":
        return _fields(value, "kind text")["text"]
    if kind == "SERIES":
        return SeriesValueRef(_fields(value, "kind series_key")["series_key"])
    if kind == "GUIDE":
        _fields(value, "kind series_key guide_key")
        return GuideValueRef(value["series_key"], value["guide_key"])
    _require(kind == "STATE", "unknown explanation part kind")
    return StateValueRef(_fields(value, "kind state_key")["state_key"])


@dataclass(frozen=True, slots=True)
class SignalText:
    parts: tuple[SignalTextPart, ...]

    def __post_init__(self):
        _require(type(self.parts) is tuple and bool(self.parts), "signal text requires parts")
        for part in self.parts:
            _require(type(part) is str or isinstance(part, (SeriesValueRef, GuideValueRef, StateValueRef)),
                     "signal text requires typed references or plain text")
            if type(part) is str:
                _text(part)

    def to_dict(self):
        return {"parts": [_part_dict(part) for part in self.parts]}

    @classmethod
    def from_dict(cls, value):
        _fields(value, "parts")
        _require(type(value["parts"]) is list, "signal text parts must be a list")
        return cls(tuple(_part_read(part) for part in value["parts"]))


@dataclass(frozen=True, slots=True)
class SignalBasisDefinition:
    key: str
    text: SignalText

    def __post_init__(self):
        _key(self.key)
        _require(isinstance(self.text, SignalText), "basis requires typed signal text")

    def to_dict(self):
        return {"key": self.key, "text": self.text.to_dict()}

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key text")
        return cls(value["key"], SignalText.from_dict(value["text"]))


@dataclass(frozen=True, slots=True)
class SignalExplanationCase:
    key: str
    judgment: SignalText
    basis: tuple[SignalBasisDefinition, ...]
    next_watch: SignalText
    explanation: SignalText

    def __post_init__(self):
        _key(self.key)
        for text in (self.judgment, self.next_watch, self.explanation):
            _require(isinstance(text, SignalText), "explanation requires typed signal text")
        _tuple(self.basis, SignalBasisDefinition)
        _require(bool(self.basis), "explanation requires judgment basis")

    @property
    def texts(self):
        return (self.judgment, *(item.text for item in self.basis), self.next_watch, self.explanation)

    def to_dict(self):
        return {"key": self.key, "judgment": self.judgment.to_dict(),
                "basis": [item.to_dict() for item in self.basis],
                "next_watch": self.next_watch.to_dict(), "explanation": self.explanation.to_dict()}

    @classmethod
    def from_dict(cls, value):
        _fields(value, "key judgment basis next_watch explanation")
        _require(type(value["basis"]) is list, "explanation basis must be a list")
        return cls(value["key"], SignalText.from_dict(value["judgment"]),
                   tuple(SignalBasisDefinition.from_dict(item) for item in value["basis"]),
                   SignalText.from_dict(value["next_watch"]), SignalText.from_dict(value["explanation"]))


@dataclass(frozen=True, slots=True)
class SignalExplanationDefinition:
    state_key: str
    cases: tuple[SignalExplanationCase, ...]

    def __post_init__(self):
        _key(self.state_key)
        _tuple(self.cases, SignalExplanationCase)
        _require(bool(self.cases), "explanation requires cases")

    def validate_panel(self, panel):
        states = {state.key: state for state in panel.states}
        series = {item.key: item for item in panel.series}
        _require(self.state_key in states, "explanation selector state is undeclared")
        _require({case.key for case in self.cases} == {x.key for x in states[self.state_key].options},
                 "explanation cases must exactly cover selector options")
        for case in self.cases:
            for text in case.texts:
                for part in text.parts:
                    if isinstance(part, StateValueRef):
                        _require(part.state_key in states, "explanation state reference is undeclared")
                    elif isinstance(part, (SeriesValueRef, GuideValueRef)):
                        _require(part.series_key in series, "explanation series reference is undeclared")
                        if isinstance(part, GuideValueRef):
                            _require(part.guide_key in {g.key for g in series[part.series_key].guides},
                                     "explanation guide reference is undeclared")

    def to_dict(self):
        return {"state_key": self.state_key, "cases": [case.to_dict() for case in self.cases]}

    @classmethod
    def from_dict(cls, value):
        _fields(value, "state_key cases")
        _require(type(value["cases"]) is list, "explanation cases must be a list")
        return cls(value["state_key"], tuple(SignalExplanationCase.from_dict(x) for x in value["cases"]))


@dataclass(frozen=True, slots=True)
class SignalBasisSnapshot:
    key: str
    text: str

    def __post_init__(self):
        _key(self.key)
        _text(self.text)


@dataclass(frozen=True, slots=True)
class SignalExplanationSnapshot:
    state_key: str
    case_key: str
    judgment: str
    basis: tuple[SignalBasisSnapshot, ...]
    next_watch: str
    explanation: str

    def __post_init__(self):
        _key(self.state_key)
        _key(self.case_key)
        for text in (self.judgment, self.next_watch, self.explanation):
            _text(text)
        _tuple(self.basis, SignalBasisSnapshot)
        _require(bool(self.basis), "explanation snapshot requires basis")

    def to_dict(self):
        return {"state_key": self.state_key, "case_key": self.case_key, "judgment": self.judgment,
                "basis": [{"key": x.key, "text": x.text} for x in self.basis],
                "next_watch": self.next_watch, "explanation": self.explanation}

    @classmethod
    def from_dict(cls, value):
        _fields(value, "state_key case_key judgment basis next_watch explanation")
        _require(type(value["basis"]) is list, "explanation basis must be a list")
        return cls(**{**value, "basis": tuple(SignalBasisSnapshot(**_fields(x, "key text"))
                                             for x in value["basis"])})


def materialize_explanation(definition: SignalExplanationDefinition, panel) -> SignalExplanationSnapshot:
    """Resolve one declared case from the recorded facts; never infer trading conditions."""
    states = {x.key: x for x in panel.states}
    series = {x.key: x for x in panel.series}
    groups = {x.key: x for x in panel.groups}
    selector = states[definition.state_key]
    _require(selector.status == "AVAILABLE", "explanation selector state is unavailable")
    case = next((x for x in definition.cases if x.key == selector.value), None)
    _require(case is not None, "explanation case is undeclared")

    def reference(part):
        item = states[part.state_key] if isinstance(part, StateValueRef) else series[part.series_key]
        if item.status == "INACTIVE":
            return "不适用"
        _require(item.status == "AVAILABLE", "explanation required fact is unavailable")
        if isinstance(part, StateValueRef):
            return next(x.label for x in item.options if x.key == item.value)
        group = groups[item.group]
        value = (next(x.value for x in item.guides if x.key == part.guide_key)
                 if isinstance(part, GuideValueRef) else item.value)
        if group.format is ObservationFormat.PERCENT:
            return f"{value * 100:.{group.precision}f}%"
        number = f"{value:.{group.precision}f}"
        return number + (f" {group.unit}" if group.unit else "")

    def render(text):
        return "".join(part if type(part) is str else reference(part) for part in text.parts)

    return SignalExplanationSnapshot(definition.state_key, case.key, render(case.judgment),
        tuple(SignalBasisSnapshot(x.key, render(x.text)) for x in case.basis),
        render(case.next_watch), render(case.explanation))
