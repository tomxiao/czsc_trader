"""S011 frozen parameters expressed with native V4 causal observations."""
import json
from datetime import date
from importlib.metadata import version
from pathlib import Path
from dataflows import InstrumentId, MarketId, AssetClass, BarFrequency, Dataset, DataCoverageRequirement
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, EquityAuxiliaryInput,
    equity_source_hash, ResearchExecutionSpec, CnEquitySpec, AccountPolicy, CashAvailabilityPolicy,
    DatasetObservationInput, ObservationAvailability)
from strategy_runtime.identity import ImplementationDependency
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType, StateRecord
from strategy_runtime.replay_contracts import StrategyComputation


def build_candidate(parameters, *, observation_source, candidate_id='C9951', source_root=None):
    source_root=Path(source_root or Path(__file__).parent)
    instrument=InstrumentId(MarketId.CN,AssetClass.ETF,'159326.SZ')
    source_files=('strategy.py','signal_math.py','cycle_planner.py')
    spec=ResearchExecutionSpec(CnEquitySpec(),BarFrequency.DAILY,
        AccountPolicy('CNY',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.001,float(parameters['premium']),0.)
    definition=EquityStrategyDefinition(instrument,spec,20,'strategy:step',source_files,
        equity_source_hash(source_root,source_files),json.dumps(dict(parameters),sort_keys=True,separators=(',',':')),
        dependencies=tuple(ImplementationDependency(name,version(name)) for name in ('numpy','pandas')),
        contract_version=4,auxiliary_inputs=(
            EquityAuxiliaryInput('hfq',instrument,observation_source,BarFrequency.DAILY,20,15*86400,'HFQ'),
            EquityAuxiliaryInput('intraday',instrument,observation_source,BarFrequency.M30,160,15*86400,'HFQ')),
        observation_inputs=(
            DatasetObservationInput('market',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH',
                history_start=date(2024,12,26),coverage=DataCoverageRequirement(maximum_start_lag_days=0,minimum_sessions=21),
                availability=ObservationAvailability('Asia/Shanghai','17:00'),max_staleness_days=15),
            DatasetObservationInput('spx',Dataset.GLOBAL_INDEX_DAILY,'SPX',history_start=date(2024,12,16),
                coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=30),
                availability=ObservationAvailability('America/New_York','17:00'),max_staleness_days=10)),
        feature_graph=FeatureGraph((),()),state_schema=StrategyStateSchema(
            account_fields=(StateField('locked_quantity',StateValueType.INT),StateField('had_position',StateValueType.BOOL))),
        computation=StrategyComputation.STATEFUL_STEP,initial_account=StateRecord((('locked_quantity',-1),('had_position',False))),
        planning_context=True)
    return EquityStrategyCandidate('S011',candidate_id,definition,source_root)
