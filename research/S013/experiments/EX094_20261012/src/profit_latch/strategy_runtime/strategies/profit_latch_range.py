"""Original C8880 policy with a one-way, entry-volatility profit-floor latch."""
from collections.abc import Mapping
import math
from strategy_runtime import ParameterSet
from .boundary_bear_recovery_range import BoundaryBearRecoveryRange
from .policy_kernel import calculate

MECHANISM = 'PROFIT_LATCH_SIGNAL_ANCHOR_ORIGINAL_BOUNDARY_RECOVERY'
PARENT_MECHANISM = 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'


class ProfitLatchRange(BoundaryBearRecoveryRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') != MECHANISM or not isinstance(p.get('profit_latch'), Mapping):
            raise ValueError('Explicit profit-latch mechanism and complete settings required')
        c = p['profit_latch']
        if set(c) != {'enabled', 'volatility_window', 'activation_multiple'} or type(c['enabled']) is not bool:
            raise ValueError('Exact profit_latch fields and boolean enabled required')
        if type(c['volatility_window']) is not int or not 10 <= c['volatility_window'] <= 60:
            raise ValueError('volatility_window must be integer10..60')
        if type(c['activation_multiple']) is not float or not math.isfinite(c['activation_multiple']) or not .5 <= c['activation_multiple'] <= 3.:
            raise ValueError('activation_multiple must be finite float .5..3')
        parent = {key: value for key, value in p.items() if key != 'profit_latch'}
        parent['mechanism'] = PARENT_MECHANISM
        super().__init__(ParameterSet(parent))
        self._parameters = parameters
        self._warmup = max(self._warmup, c['volatility_window'] + 1)

    def calculate_history(self, inputs, sessions):
        if not self._parameters.values['profit_latch']['enabled']:
            return super().calculate_history(inputs, sessions)
        return calculate(self._parameters.values, inputs, sessions)
