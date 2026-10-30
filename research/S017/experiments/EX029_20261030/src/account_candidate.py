"""Declare already-installed numerical libraries used by the frozen entry source."""
import json
from importlib.metadata import version
from common import INSTRUMENT, SPEC, WORK, NAMES
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash, ImplementationDependency


def candidate(key, parameters):
    if (set(parameters) != {'entry_mechanism', 'max_holding_bars'}
            or parameters['entry_mechanism'] not in NAMES
            or type(parameters['max_holding_bars']) is not int or parameters['max_holding_bars'] not in (6, 13)):
        raise ValueError('Unapproved conditional prototype')
    source, files = WORK/'src', ('strategy.py',)
    dependencies = tuple(ImplementationDependency(name, version(name)) for name in ('numpy', 'pandas'))
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:decide', files,
        equity_source_hash(source, files), json.dumps(parameters), dependencies=dependencies,
        feedback_mode='CONFIRMED_EXECUTION', session_context=False, auxiliary_inputs=())
    return EquityStrategyCandidate('S017', key, definition, source)
