"""Build the reviewed native definition; no registration or release mutation."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from dataflows import AssetClass, BarFrequency, DataCoverageRequirement, Dataset, InstrumentId, MarketId, SourceRef
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, EquityAuxiliaryInput,
    EquityStrategyCandidate, EquityStrategyDefinition, ImplementationDependency,
    ResearchExecutionSpec, StrategyComputation, equity_source_hash)
from strategy_runtime.dataset_observations import DatasetObservationInput, FrozenDataAsset, ObservationAvailability
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StateField, StateRecord, StateValueType, StrategyStateSchema


def build_candidate(source: SourceRef, candidate_id='C9960'):
    root = Path(__file__).resolve().parent
    params = json.loads((root/'parameters.json').read_text(encoding='utf-8'))
    instrument = InstrumentId(MarketId.CN, AssetClass.ETF, '588080.SH')
    spec = ResearchExecutionSpec(CnEquitySpec(), BarFrequency.DAILY,
        AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.001,.20,0.)
    available = ObservationAvailability('Asia/Shanghai','15:00')
    zero = DataCoverageRequirement(minimum_observations=1, minimum_sessions=0, maximum_start_lag_days=None)
    observations = (
        DatasetObservationInput('feature_seed',Dataset.STRATEGY_FEATURE_EVIDENCE,'S007-v1',
            history_start=date(2021,1,4),history_end=date(2026,9,2),coverage=zero,
            asset=FrozenDataAsset('seed.csv',sha256((root/'seed.csv').read_bytes()).hexdigest()),availability=available),
        DatasetObservationInput('incremental_shibor_daily',Dataset.SHIBOR_DAILY,history_start=date(2026,8,1),coverage=zero,availability=available,required_from=date(2026,9,3)),
        DatasetObservationInput('incremental_chinext_daily_basic',Dataset.INDEX_DAILY_BASIC,'399006.SZ',history_start=date(2026,8,1),coverage=zero,availability=available,required_from=date(2026,9,3)),
        DatasetObservationInput('incremental_etf_share_size',Dataset.ETF_SHARE_SIZE,'588080.SH',history_start=date(2026,8,1),coverage=zero,availability=available,required_from=date(2026,9,3)),
        DatasetObservationInput('incremental_spx_daily',Dataset.GLOBAL_INDEX_DAILY,'SPX',history_start=date(2026,7,25),coverage=zero,
            availability=ObservationAvailability('America/New_York','16:00'),required_from=date(2026,9,3)),
    )
    files = ('strategy.py','signals.py','cycle_planner.py')
    definition = EquityStrategyDefinition(instrument,spec,1,'strategy:step',files,equity_source_hash(root,files),
        parameters_json=json.dumps(params,sort_keys=True,separators=(',',':')),
        dependencies=tuple(ImplementationDependency(name,version(name)) for name in ('numpy','pandas')),
        contract_version=4,computation=StrategyComputation.STATEFUL_STEP,feature_graph=FeatureGraph((),()),
        state_schema=StrategyStateSchema((StateField('locked_quantity',StateValueType.INT),StateField('had_position',StateValueType.BOOL))),
        initial_account=StateRecord((('locked_quantity',-1),('had_position',False))),observation_inputs=observations,
        auxiliary_inputs=(EquityAuxiliaryInput('adjusted_daily',instrument,source,BarFrequency.DAILY,21,86400*15,'HFQ'),),
        planning_context=True)
    return EquityStrategyCandidate('S007',candidate_id,definition,root)
