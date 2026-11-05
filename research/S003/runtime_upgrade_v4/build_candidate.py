"""Build the reviewed native definition; no registration or release mutation."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from dataflows import AssetClass, BarFrequency, DataCoverageRequirement, Dataset, InstrumentId, MarketId, SourceRef
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec,
    EquityStrategyCandidate, EquityStrategyDefinition, ExecutionInput, ImplementationDependency,
    ResearchExecutionSpec, StrategyComputation, equity_source_hash)
from strategy_runtime.dataset_observations import DatasetObservationInput, FrozenDataAsset, ObservationAvailability
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StateField, StateRecord, StateValueType, StrategyStateSchema


def build_candidate(source: SourceRef, candidate_id='C9960'):
    root = Path(__file__).resolve().parent
    params = json.loads((root/'parameters.json').read_text(encoding='utf-8'))
    instrument = InstrumentId(MarketId.CN, AssetClass.ETF, '510500.SH')
    spec = ResearchExecutionSpec(CnEquitySpec(), BarFrequency.DAILY,
        AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.001,.10,0.)
    available = ObservationAvailability('Asia/Shanghai','15:00')
    zero = DataCoverageRequirement(minimum_observations=1, minimum_sessions=0, maximum_start_lag_days=None)
    observations = (
        DatasetObservationInput('constituent_moneyflow_seed', Dataset.STRATEGY_FEATURE_EVIDENCE,'S003-v1',
            history_start=date(2021,1,4),history_end=date(2026,9,8),coverage=zero,
            asset=FrozenDataAsset('seed.csv',sha256((root/'seed.csv').read_bytes()).hexdigest()),availability=available),
        DatasetObservationInput('incremental_constituent_weights',Dataset.INDEX_CONSTITUENT_WEIGHT,'000905.SH','snapshot',
            history_start=date(2025,9,4),coverage=zero,availability=available,required_from=date(2026,9,9)),
        DatasetObservationInput('incremental_constituent_moneyflow',Dataset.STOCK_MONEYFLOW,
            history_start=date(2026,9,9),coverage=zero,availability=available,required_from=date(2026,9,9)),
    )
    files = ('strategy.py','signals.py')
    definition = EquityStrategyDefinition(instrument,spec,1,'strategy:step',files,equity_source_hash(root,files),
        parameters_json=json.dumps(params,sort_keys=True,separators=(',',':')),
        dependencies=tuple(ImplementationDependency(name,version(name)) for name in ('numpy','pandas')),
        contract_version=4,computation=StrategyComputation.STATEFUL_STEP,feature_graph=FeatureGraph((),()),
        state_schema=StrategyStateSchema((StateField('core_quantity',StateValueType.INT),)),
        initial_account=StateRecord((('core_quantity',0),)),observation_inputs=observations,
        execution_input=ExecutionInput(instrument,source,BarFrequency.M30),planning_context=True)
    return EquityStrategyCandidate('S003',candidate_id,definition,root)
