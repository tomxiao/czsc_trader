"""Explicit US equity inputs for the shared technical-inspection lifecycle."""
from dataclasses import dataclass
import math
from dataflows import EquityDataRequest, TimeInterval
from strategy_runtime import EquityInputBinding
from strategy_manager import freeze_contracts as f
from ..research_tools.delivery import EvaluationEvidenceRef


@dataclass(frozen=True)
class EquityInspectionReplay:
    coordinate: f.InspectionCoordinate
    input_binding: EquityInputBinding
    requests: tuple[EquityDataRequest, ...]
    window: TimeInterval
    initial_cash: float
    one_way_cost: float
    baseline: EvaluationEvidenceRef | None = None

    def __post_init__(self):
        if type(self.coordinate) is not f.InspectionCoordinate or type(self.input_binding) is not EquityInputBinding:
            raise TypeError('equity inspection requires typed coordinate and input binding')
        if type(self.window) is not TimeInterval or type(self.requests) is not tuple or len(self.requests) != 4:
            raise TypeError('equity inspection requires window and four prepared product requests')
        if any(type(x) is not EquityDataRequest for x in self.requests):
            raise TypeError('equity inspection requests must be EquityDataRequest')
        for value in (self.initial_cash, self.one_way_cost):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('finite equity inspection account values required')
        if self.initial_cash <= 0 or not 0 <= self.one_way_cost < 1:
            raise ValueError('invalid equity inspection account values')
        if self.baseline is not None and type(self.baseline) is not EvaluationEvidenceRef:
            raise TypeError('baseline requires EvaluationEvidenceRef')


@dataclass(frozen=True)
class EquityInspectionProtocol:
    method_version: str
    comparison: str
    float_tolerance: float
    pte: object

    def __post_init__(self):
        from paper_trading_engine.equity_inspection import EquityPteInspectionProtocol
        if self.method_version != 'candidate-inspection-v2' or self.comparison != 'ECONOMIC_V1':
            raise ValueError('unsupported equity inspection protocol')
        if type(self.float_tolerance) not in (int, float) or self.float_tolerance != 0:
            raise ValueError('equity inspection requires exact deterministic replay (zero tolerance)')
        if type(self.pte) is not EquityPteInspectionProtocol:
            raise TypeError('equity inspection requires typed PTE protocol')

    def to_dict(self):
        return {'method_version': self.method_version, 'comparison': self.comparison,
                'float_tolerance': self.float_tolerance, 'runtime_kind': 'US_EQUITY', 'pte': self.pte.to_dict()}
