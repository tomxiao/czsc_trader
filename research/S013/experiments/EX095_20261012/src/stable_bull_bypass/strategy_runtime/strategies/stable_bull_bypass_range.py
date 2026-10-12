"""Original rules; bypass score only in stable rawbull with positive T body."""
from strategy_runtime import ParameterSet

from .boundary_bear_recovery_range import BoundaryBearRecoveryRange
from .policy_kernel import KEYS, MECHANISM, PARENT_MECHANISM, calculate


class StableBullBypassRange(BoundaryBearRecoveryRange):
    def __init__(self, parameters):
        p = parameters.values
        if set(p) != KEYS or p['mechanism'] != MECHANISM or type(p['bypass_enabled']) is not bool:
            raise ValueError('Exact stable-bull mechanism and explicit boolean bypass switch required')
        parent = {key: value for key, value in p.items() if key != 'bypass_enabled'}
        parent['mechanism'] = PARENT_MECHANISM
        super().__init__(ParameterSet(parent))
        self._parameters = parameters

    def calculate_history(self, inputs, sessions):
        if not self._parameters.values['bypass_enabled']:
            return super().calculate_history(inputs, sessions)
        return calculate(self._parameters.values, inputs, sessions)
