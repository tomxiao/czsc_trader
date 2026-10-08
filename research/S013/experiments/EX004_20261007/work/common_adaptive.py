"""Adaptive S013 source identity; all evaluation and prices use the public host."""
from dataclasses import replace
from strategy_runtime import StrategyCandidate, implementation_sha256
from common import WORK, DEPENDENCIES
from common import ROOT as ROOT, context as context, save as save
from common import cache_read as cache_read, cache_write as cache_write
from common import request as original_request

SOURCE = WORK / 'adaptive_range/strategy_runtime'
FILES = ('strategies/adaptive_range.py', 'strategies/range_reversion.py')


def candidate(number, parameters):
    return StrategyCandidate('S013', f'C{number:04}', {
        'runtime': {'module': 'strategy_runtime.strategies.adaptive_range',
            'qualname': 'AdaptiveRange', 'contract_version': 1,
            'source_files': list(FILES),
            'source_sha256': implementation_sha256(FILES, source_root=SOURCE)},
        'parameters': parameters}, source_root=SOURCE)


def request(number, parameters, execution_data=None, dependencies=DEPENDENCIES):
    base = original_request(number, parameters['bull'], execution_data, dependencies)
    actual = candidate(number, parameters)
    return replace(base, strategy=actual, runtime_binding={
        'candidate_id': actual.reference_id, 'source_files': list(FILES),
        'implementation_sha256': actual.payload['runtime']['source_sha256']})
