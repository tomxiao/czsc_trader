"""Original C8880 entry/other exits, with TIME driven by a market-only clock."""
from strategy_runtime import ParameterSet
from .boundary_bear_recovery_range import BoundaryBearRecoveryRange
from .policy_kernel import calculate

MECHANISM = 'MARKET_EPISODE_TIME_ORIGINAL_BOUNDARY_RECOVERY'
PARENT_MECHANISM = 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'


class EpisodeClockRange(BoundaryBearRecoveryRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') != MECHANISM or type(p.get('episode_enabled')) is not bool:
            raise ValueError('Explicit episode mechanism and boolean switch required')
        parent = {key: value for key, value in p.items() if key != 'episode_enabled'}
        parent['mechanism'] = PARENT_MECHANISM
        super().__init__(ParameterSet(parent))
        self._parameters = parameters

    def calculate_history(self, inputs, sessions):
        if not self._parameters.values['episode_enabled']:
            # The exact inherited implementation is the sole OFF execution path.
            return super().calculate_history(inputs, sessions)
        return calculate(self._parameters.values, inputs, sessions)
