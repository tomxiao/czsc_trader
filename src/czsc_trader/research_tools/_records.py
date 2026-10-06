"""Strict record serialization shared by TDR public contracts."""
from dataclasses import fields, is_dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath
import re
from types import UnionType
from typing import TypeVar, Union, get_args, get_origin, get_type_hints

def _text(value: str, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be nonempty")


def _hash(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected lowercase SHA-256")


def _path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or "\\" in value
        or ":" in value
        or any(part.endswith((".", " ")) for part in path.parts)
        or any(
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?", p) for p in path.parts
        )
        or any(ord(c) < 32 or c in '<>"|?*' for c in value)
    ):
        raise ValueError("expected safe relative POSIX path")


def _unique(values, name: str) -> None:
    values = tuple(values)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")


def _matches(value, annotation) -> bool:
    if isinstance(annotation, TypeVar):
        return _matches(value, annotation.__bound__)
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(_matches(value, part) for part in get_args(annotation))
    if origin is tuple:
        args = get_args(annotation)
        return type(value) is tuple and all(_matches(v, args[0]) for v in value)
    if annotation is float:
        return type(value) is float and math.isfinite(value)
    return type(value) is annotation


class _Record:
    def __post_init__(self):
        for name, annotation in get_type_hints(type(self)).items():
            if not _matches(getattr(self, name), annotation):
                raise TypeError(f"{type(self).__name__}.{name} requires {annotation}")
        self._validate()

    def _validate(self):
        pass

    def to_dict(self) -> dict[str, object]:
        return _encode(self)

    @classmethod
    def from_dict(cls, value):
        result = _decode(value, cls)
        if type(result) is not cls:
            raise ValueError("delivery record type differs")
        return result


def _encode(value):
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(x) for x in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _decode(value, annotation):
    if isinstance(annotation, TypeVar):
        annotation = annotation.__bound__
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        for part in get_args(annotation):
            try:
                return _decode(value, part)
            except (ValueError, TypeError, KeyError):
                pass
        raise ValueError(f"value does not match {annotation}")
    if origin is tuple:
        if type(value) is not list:
            raise TypeError("serialized tuple must be an array")
        return tuple(_decode(x, get_args(annotation)[0]) for x in value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        names = {f.name for f in fields(annotation)}
        if type(value) is not dict or set(value) != names | {"type"}:
            raise ValueError("record fields differ from schema")
        if value["type"] != annotation.__name__:
            raise ValueError("record discriminator differs")
        hints = get_type_hints(annotation)
        return annotation(**{key: _decode(value[key], hints[key]) for key in names})
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            raise TypeError("serialized enum must be a string")
        return annotation(value)
    if not _matches(value, annotation):
        raise TypeError(f"value requires {annotation}")
    return value


def _canonical(value) -> bytes:
    return json.dumps(
        _encode(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value) -> str:
    return sha256(_canonical(value)).hexdigest()


