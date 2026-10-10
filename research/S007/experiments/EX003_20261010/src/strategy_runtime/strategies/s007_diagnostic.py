"""Research observation metadata; inherited trading and inputs are unmodified."""
from dataclasses import replace
from strategy_runtime import ObservationDefinition
from .s007_v1 import S007V1


class S007Diagnostic(S007V1):
    def __init__(self, parameters):
        super().__init__(parameters)
        self._definition = replace(self._definition, observation=ObservationDefinition((), ()))
