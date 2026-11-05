"""Construct frozen S002-v1 on the native account contract."""
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


def build_candidate(version='v1', repository_root=None, candidate_id='C9901'):
    if version != 'v1':
        raise ValueError('S002 has one frozen version')
    source = (Path(repository_root) / 'research/S002/runtime_upgrade_v4'
              if repository_root is not None else Path(__file__).parent)
    parameters = json.loads((source / 'parameters.json').read_text(encoding='utf-8'))
    source_files = ('strategy.py', 'signal_math.py', 'cycle_planner.py')
    inputs = (DatasetObservationInput('adjusted_daily', Dataset.ETF_OHLCV, '510500.SH', 'daily',
        coverage=DataCoverageRequirement(maximum_start_lag_days=7, minimum_observations=300),
        availability=ObservationAvailability('Asia/Shanghai', '15:00')),)
    definition = EquityStrategyDefinition(InstrumentId(MarketId.CN, AssetClass.ETF, '510500.SH'),
        ResearchExecutionSpec(CnEquitySpec(), BarFrequency.DAILY,
            AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 100, .001, 0., 0.),
        1, 'strategy:step', source_files, equity_source_hash(source, source_files),
        parameters_json=json.dumps(parameters, ensure_ascii=False),
        dependencies=tuple(ImplementationDependency(name, package_version(name)) for name in ('czsc', 'pandas', 'numpy')),
        contract_version=4, feature_graph=FeatureGraph(),
        state_schema=StrategyStateSchema((StateField('locked_quantity', StateValueType.INT), StateField('had_position', StateValueType.BOOL))),
        initial_account=StateRecord((('locked_quantity', -1), ('had_position', False))),
        computation=StrategyComputation.STATEFUL_STEP, observation_inputs=inputs, planning_context=True)
    return EquityStrategyCandidate('S002', candidate_id, definition, source)
