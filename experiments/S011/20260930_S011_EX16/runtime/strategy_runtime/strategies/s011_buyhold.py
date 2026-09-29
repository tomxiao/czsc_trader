"""Fixed investable BuyHold comparator, using the same SRT order contract."""
import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    StrategyImplementation, RuntimeDefinition, ImplementationRef, ParameterSet,
    InputRequirement, InputContract, CutoffRule, DecisionContract, ExecutionPolicy,
    MonitoringPolicy, RequiredCapabilities, HistoryPolicy,
    next_session_calendar_window, next_session_calculation_scope,
)


class S011BuyHold(StrategyImplementation):
    def __init__(self, candidate):
        if dict(candidate.payload['parameters'])!={'premium':.003}:
            raise ValueError('benchmark parameters are fixed')
        req=(
            InputRequirement('daily',Dataset.ETF_OHLCV.value,'159326.SZ','daily',1,CutoffRule.SIGNAL_SESSION),
            InputRequirement('execution',Dataset.ETF_UNADJUSTED_DAILY.value,'159326.SZ','daily',1,CutoffRule.SIGNAL_SESSION),
            InputRequirement('calendar',Dataset.TRADING_CALENDAR.value,'SSE','daily',0,CutoffRule.LATEST_AVAILABLE))
        ref=candidate.payload['runtime']
        self._definition=RuntimeDefinition(
            schema_version=2,strategy_family_id='S011',version=None,
            release_id=candidate.reference_id,release_hash=candidate.runtime_identity_sha256,
            implementation=ImplementationRef(ref['module'],ref['qualname'],1,ref['source_sha256']),
            parameters=ParameterSet(candidate.payload['parameters']),inputs=InputContract(req),
            decision=DecisionContract('TARGET_POSITION',0.,1.,'NEXT_SESSION_OPEN'),
            execution=ExecutionPolicy('FROZEN_RULE',{
                'capital':{'fee_rate':.001,'mode':'full_available_cash','target_scope':'entry_cycle'},
                'entry':{'order_type':'LIMIT','limit_parameter':.003},
                'exit':{'order_type':'MARKET','limit_ratio':.1},
                'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}),
            monitoring=MonitoringPolicy('BENCHMARK_ONLY',{}),
            capabilities=RequiredCapabilities(tuple(sorted({r.dataset for r in req})),('LIMIT','MARKET')),
            tradable_symbol='159326.SZ',identity_kind='CANDIDATE',candidate_id=candidate.candidate_id,
            history=HistoryPolicy('CANONICAL_REPLAY','2025-02-05','2025-02-05'))

    @classmethod
    def from_candidate(cls,candidate):return cls(candidate)

    @property
    def definition(self):return self._definition

    def calendar_window(self,window):return next_session_calendar_window(self.definition,window)

    def derive_calculation_scope(self,window,dates):
        return next_session_calculation_scope(self.definition,window,dates)

    def calculate_history(self,inputs,sessions):
        return pd.DataFrame({'target_position':1.,'reason':'BUY_AND_HOLD'},index=sessions)
