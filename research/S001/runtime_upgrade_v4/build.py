"""Construct both frozen S001 revisions as native account candidates."""
from datetime import date
from importlib.metadata import version as package_version
from pathlib import Path
import json
from dataflows import InstrumentId, MarketId, AssetClass, Dataset, DataCoverageRequirement, BarFrequency
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash,
    DatasetObservationInput, ObservationAvailability, ResearchExecutionSpec, CnEquitySpec,
    AccountPolicy, CashAvailabilityPolicy)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType, StateRecord
from strategy_runtime.replay_contracts import StrategyComputation
from strategy_runtime.identity import ImplementationDependency


def build_candidate(version='v1', repository_root=None, candidate_id=None):
    if version not in ('v1', 'v2'):
        raise ValueError('S001 supports frozen v1/v2')
    source = (Path(repository_root) / 'research/S001/runtime_upgrade_v4'
              if repository_root is not None else Path(__file__).parent)
    parameters = json.loads((source / f'parameters-{version}.json').read_text(encoding='utf-8'))
    source_files = ('strategy.py', 'signal_math.py', 'cycle_planner.py')
    inputs = tuple(DatasetObservationInput(name, Dataset.ETF_OHLCV, '588080.SH', frequency,
        history_start=date(2020, 11, 16), coverage=DataCoverageRequirement(maximum_start_lag_days=7, minimum_observations=minimum),
        availability=ObservationAvailability('Asia/Shanghai', '15:00'))
        for name, frequency, minimum in (('adjusted_daily', 'daily', 60),
            ('adjusted_30m', '30m', 500), ('adjusted_weekly', 'weekly', 10)))
    definition = EquityStrategyDefinition(InstrumentId(MarketId.CN, AssetClass.ETF, '588080.SH'),
        ResearchExecutionSpec(CnEquitySpec(), BarFrequency.DAILY,
            AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 100, .001, 0., 0.),
        1, 'strategy:step', source_files, equity_source_hash(source, source_files),
        parameters_json=json.dumps(parameters, ensure_ascii=False),
        dependencies=tuple(ImplementationDependency(name, package_version(name)) for name in ('czsc', 'pandas', 'numpy')),
        contract_version=4, feature_graph=FeatureGraph(),
        state_schema=StrategyStateSchema((StateField('locked_quantity', StateValueType.INT), StateField('had_position', StateValueType.BOOL))),
        initial_account=StateRecord((('locked_quantity', -1), ('had_position', False))),
        computation=StrategyComputation.STATEFUL_STEP, observation_inputs=inputs, planning_context=True)
    return EquityStrategyCandidate('S001', candidate_id or {'v1': 'C9903', 'v2': 'C9904'}[version], definition, source)
