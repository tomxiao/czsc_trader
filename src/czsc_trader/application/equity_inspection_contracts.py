"""Explicit V5 equity inputs for technical inspection."""
from dataclasses import dataclass, field
import math
from dataflows import DataRequest, TimeInterval
from strategy_runtime import EquityInputBinding, StepDataWindow
from strategy_manager import freeze_contracts as f
from paper_trading_engine.execution_reference import ExecutionReferenceBinding


@dataclass(frozen=True)
class EquityInspectionReplay:
    coordinate: f.InspectionCoordinate
    input_binding: EquityInputBinding
    requests: tuple[DataRequest, ...]
    window: TimeInterval
    initial_cash: float
    one_way_cost: float
    execution_reference: ExecutionReferenceBinding = field(kw_only=True)
    step_data_windows: tuple[StepDataWindow, ...] = field(default=(), kw_only=True)

    def __post_init__(self):
        if type(self.coordinate) is not f.InspectionCoordinate or type(self.input_binding) is not EquityInputBinding:
            raise TypeError('equity inspection requires typed coordinate and input binding')
        if (type(self.execution_reference) is not ExecutionReferenceBinding or
                self.execution_reference.parameters.instrument != self.input_binding.instrument):
            raise ValueError('inspection requires independent RAW execution prices for the same instrument')
        if self.input_binding.auxiliary_inputs or self.input_binding.observation_bindings:
            raise ValueError('V5 inspection strategy data requires step_data_windows')
        if type(self.window) is not TimeInterval or type(self.requests) is not tuple:
            raise TypeError('equity inspection requires window and prepared product requests')
        if any(not isinstance(x, DataRequest) for x in self.requests):
            raise TypeError('equity inspection requests must be typed DataRequest')
        keys = tuple(key for key, _ in self.input_binding.bind_requests(self.requests))
        if len(set(keys)) != len(keys) or set(keys) != set(self.input_binding.expected_identities):
            raise ValueError('equity inspection requires exact host product coverage')
        for value in (self.initial_cash, self.one_way_cost):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('finite equity inspection account values required')
        if self.initial_cash <= 0 or not 0 <= self.one_way_cost < 1:
            raise ValueError('invalid equity inspection account values')
        if type(self.step_data_windows) is not tuple or any(type(x) is not StepDataWindow for x in self.step_data_windows):
            raise TypeError('inspection requires typed strategy data grants')
        if len({window.name for window in self.step_data_windows}) != len(self.step_data_windows):
            raise ValueError('inspection strategy data grants must be unique')


@dataclass(frozen=True)
class EquityInspectionProtocol:
    method_version: str
    comparison: str
    float_tolerance: float
    pte: object

    def __post_init__(self):
        from paper_trading_engine.equity_inspection import EquityPteInspectionProtocol
        if self.method_version != 'candidate-inspection-v5' or self.comparison != 'ECONOMIC_V1':
            raise ValueError('equity inspection requires candidate-inspection-v5 and ECONOMIC_V1')
        if type(self.float_tolerance) not in (int, float) or self.float_tolerance != 0:
            raise ValueError('equity inspection requires exact deterministic replay (zero tolerance)')
        if type(self.pte) is not EquityPteInspectionProtocol:
            raise TypeError('equity inspection requires typed PTE protocol')

    def to_dict(self):
        return {'method_version': self.method_version, 'comparison': self.comparison,
                'float_tolerance': self.float_tolerance,
                'runtime_kind': 'ACCOUNT_REPLAY',
                'pte': self.pte.to_dict()}
