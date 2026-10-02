from dataclasses import dataclass, replace

from .models import EvaluationProtocol, ValidationError


@dataclass(frozen=True)
class MarginSet:
    net_cagr_retention: float = 0.90
    max_drawdown_absolute: float = 0.02
    max_drawdown_relative: float = 0.15
    calmar_retention: float = 0.90
    profit_factor_retention: float = 0.85
    profit_factor_floor: float = 1.0
    minimum_closed_trades: int = 10
    negative_calmar_requires_positive: bool = False


@dataclass(frozen=True)
class EvaluationStandard:
    version: str
    margins: MarginSet


OPC_V3 = EvaluationStandard("opc-v3", MarginSet())

_HIGHER_IS_TIGHTER = {"net_cagr_retention", "calmar_retention", "profit_factor_retention", "profit_factor_floor", "minimum_closed_trades"}
_LOWER_IS_TIGHTER = {"max_drawdown_absolute", "max_drawdown_relative"}


def resolve_margins(protocol: EvaluationProtocol) -> MarginSet:
    standards = {OPC_V3.version: OPC_V3}
    standard = standards.get(protocol.standard_version)
    if standard is None:
        raise ValidationError(f"unsupported standard: {protocol.standard_version}", "UNSUPPORTED_STANDARD")
    defaults = standard.margins
    changes: dict[str, float | int] = {}
    for name, raw_value in protocol.tightened_margins:
        if name not in _HIGHER_IS_TIGHTER | _LOWER_IS_TIGHTER:
            raise ValidationError(f"unknown margin: {name}", "UNKNOWN_MARGIN")
        default = getattr(defaults, name)
        value = int(raw_value) if name == "minimum_closed_trades" else float(raw_value)
        loosened = (name in _HIGHER_IS_TIGHTER and value < default) or (name in _LOWER_IS_TIGHTER and value > default)
        if loosened:
            raise ValidationError(f"margin {name} cannot loosen OPC-v3 default", "MARGIN_LOOSENED")
        changes[name] = value
    return replace(defaults, **changes)
