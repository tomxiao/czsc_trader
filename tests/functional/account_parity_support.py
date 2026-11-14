"""Explicit synthetic source facts for cross-market account acceptance."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import (AssetClass, BarFrequency, InstrumentId, MarketId, SourceRef,
    TradingSession, TimeInterval, EquitySourceCoverage, EquityFrequencyFacts,
    ProviderConfig, versioned_equity_bindings, PriceAdjustment, AcquisitionMethod)
from strategy_runtime import (CnEquitySpec, UsEquitySpec, ResearchExecutionSpec,
    AccountPolicy, CashAvailabilityPolicy, EquityStrategyDefinition, EquityStrategyCandidate,
    equity_source_hash, StrategyComputation, ExecutionPolicy)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema
from czsc_trader.application import RepositoryContext, ResearchBatchRequest, ExperimentRequest
from czsc_trader.research_tools import EquityEvaluationRequest, EquitySources, EvaluationBenchmark, EquityBuyHold
from research_scaffold_support import seeded_research_context


STEP = '''from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx, state):
    target = (.25, .5, .25, 0.)[(state.revision + 1) % 4]
    return AccountStepResult(AccountDecision.from_facts(target, 'synthetic allocation',
        facts={'target': target}, next_watch='next completed bar'), cycle_values=StateRecord())
'''


def setup_account(root, market, frequency, *, gap_kind=None):
    repository = RepositoryContext(root, root/'research', root/'research/registrations', root/'strategies')
    instrument = InstrumentId(market, AssetClass.STOCK, '600000.SH' if market is MarketId.CN else 'TEST')
    spec = ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(), frequency,
        AccountPolicy(instrument.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        100 if market is MarketId.CN else 1, .01, .01, 0.)
    zone = ZoneInfo(instrument.timezone)
    sessions = tuple(TradingSession(date(2026,10,day),instrument.timezone,tuple(
        TimeInterval(datetime(2026,10,day,a,b,tzinfo=zone),datetime(2026,10,day,c,d,tzinfo=zone))
        for a,b,c,d in (((9,30,11,30),(13,0,15,0)) if market is MarketId.CN else ((9,30,16,0),))))
        for day in (26,27,28,29,30))
    next_day = timedelta(days=3)
    following = TradingSession(sessions[-1].session_date + next_day, instrument.timezone,
        tuple(TimeInterval(part.start + next_day, part.end + next_day) for part in sessions[-1].segments))
    source = SourceRef('synthetic-account-parity','v1')
    versions = []
    for freq in BarFrequency:
        grid = tuple(part for session in sessions for part in session.bars(freq))
        starts, ends = [p.start for p in grid], [p.end for p in grid]
        bars = pd.DataFrame({'Date':ends,'BarStart':starts,'AvailableDate':ends,
            'Open':10.,'High':11.,'Low':9.,'Close':10.,'Volume':1000000.,'Amount':10000000.})
        bars['Amount'] = bars.Close * bars.Volume
        if gap_kind is not None:
            bars['BarStatus'], bars['ExecutionBlocked'] = 'OBSERVED', False
            local = bars.BarStart.dt.tz_convert(instrument.timezone)
            missing = local.dt.day.eq(28)
            if gap_kind == 'checkpoint':
                missing &= (freq is BarFrequency.M30) & local.dt.hour.eq(11) & local.dt.minute.eq(0)
            elif gap_kind != 'day':
                raise ValueError('unknown synthetic gap kind')
            bars.loc[missing,['Open','High','Low','Close','Volume','Amount']] = float('nan')
            bars.loc[missing,'BarStatus'] = 'MISSING'
        rules = pd.DataFrame({'Date':starts,'AvailableDate':starts,'Tradable':True,
            'PriceLimitLower':1. if market is MarketId.CN else None,
            'PriceLimitUpper':20. if market is MarketId.CN else None})
        versions.append(EquityFrequencyFacts(freq,bars,rules,PriceAdjustment.BACKWARD,AcquisitionMethod.PROVIDER_ADJUSTED))
    coverage = EquitySourceCoverage(sessions[0].session_date,sessions[-1].session_date,
        'Synthetic complete HFQ source receipt, not real security-history admission.')
    bindings = versioned_equity_bindings(instrument=instrument,source=source,coverage=coverage,
        sessions=sessions,frequencies=tuple(versions),following_session=following)
    context, experiment = seeded_research_context(repository,
        ResearchBatchRequest('S999', 'Account parity fixture', str(instrument.symbol),
                             {'goal': 'synthetic software acceptance'}),
        ExperimentRequest('Account parity', 'Software acceptance only', date(2026, 10, 30)),
        actor='DEV', reason='isolated fixture',
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=spec)
    from strategy_runtime import ExecutionResources
    context.evaluation.resources=ExecutionResources(1,1)
    source_root = experiment.resolve(root)/'src'
    source_root.mkdir(exist_ok=True)
    (source_root/'strategy.py').write_text(STEP,encoding='utf-8')
    definition=EquityStrategyDefinition(instrument,spec,1,
        'strategy:step',
        ('strategy.py',),equity_source_hash(source_root,('strategy.py',)),contract_version=5,execution_policy=ExecutionPolicy("TARGET_POSITION",{}),
        computation=StrategyComputation.STATEFUL_STEP,feature_graph=FeatureGraph((),()),state_schema=StrategyStateSchema())
    candidate=EquityStrategyCandidate('S999','C0001',definition,source_root)
    grid=tuple(part for session in sessions for part in session.bars(frequency))
    request=EquityEvaluationRequest(experiment,candidate,TimeInterval(grid[1].start,grid[-1].end),
        sessions[0].session_date,EquitySources(source,source,source),100000.,.001,
        benchmark=EvaluationBenchmark(EquityBuyHold(spec)),drawdown_basis='BAR_CLOSE',concentration_basis='MAX_SINGLE')
    return context,request
