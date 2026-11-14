"""Application orchestration for frozen binary equity strategy implementations."""
import pandas as pd

from dataflows import TimeInterval
from execution_channels.contracts import DecisionPoint
from execution_channels.instruments import TimeInterval as ExecutionInterval
from execution_channels.planning.frozen_equity import FrozenEquityIntent, plan_frozen_equity
from execution_channels.serialization import from_record, to_record
from .ec_boundary import execution_spec, strategy_portfolio


def run_frozen_equity(instance, bars, constraints, executor, *, start, end, fee_rate,
                      auxiliary_histories=None, sessions=None, trading_sessions=()):
    """Use causal SRT targets and the channel's sole sizing and execution path."""
    candidate = instance.candidate
    if candidate.definition.account_replay:
        raise ValueError('V4 requires the stateful account channel')
    candidate.verify()
    specification = execution_spec(instance.specification)
    if executor.spec.fingerprint != specification.fingerprint or executor.fee_rate != fee_rate:
        raise ValueError('execution contract differs from declared frozen strategy policy')
    starts, ends = pd.to_datetime(bars.BarStart), pd.to_datetime(bars.Date)
    available = pd.to_datetime(bars.AvailableDate) + pd.Timedelta(seconds=specification.data_latency_seconds)
    dated_constraints = {pd.Timestamp(row.Date): row for _, row in constraints.iterrows()}
    if not ends.is_monotonic_increasing or ends.duplicated().any():
        raise ValueError('bars must be unique and ordered')
    for index in range(len(bars)):
        if starts.iloc[index] < start or ends.iloc[index] > end:
            continue
        bar = bars.iloc[index]
        completed = bars.loc[(ends <= starts.iloc[index]) & (available <= starts.iloc[index])]
        explicit_gaps = 'BarStatus' in bars
        history = completed.loc[completed.BarStatus.eq('OBSERVED')] if explicit_gaps else completed
        if len(history) < candidate.warmup_bars:
            raise ValueError('insufficient causal warmup at window start')
        constraint = dated_constraints.get(starts.iloc[index])
        if constraint is None or pd.Timestamp(constraint.AvailableDate) > starts.iloc[index]:
            raise ValueError('no dated trading constraints available at execution start')
        portfolio = executor.snapshot_at(history.Date.iloc[-1], starts.iloc[index])
        interval = TimeInterval(starts.iloc[index].to_pydatetime(), ends.iloc[index].to_pydatetime())
        if explicit_gaps and completed.BarStatus.iloc[-1] != 'OBSERVED':
            point = DecisionPoint(history.Date.iloc[-1].to_pydatetime(), interval.start,
                ExecutionInterval(interval.start, interval.end))
            intent = FrozenEquityIntent(point, float(portfolio.quantity > 0),
                float(history.Close.iloc[-1]), None, True)
        else:
            proposal = instance.propose(history.drop(columns=['BarStatus','ExecutionBlocked'], errors='ignore'),
                interval, strategy_portfolio(portfolio), auxiliary_histories=auxiliary_histories,
                sessions=sessions, trading_sessions=trading_sessions)
            intent = from_record(FrozenEquityIntent, to_record(proposal))
        plan = plan_frozen_equity(intent, portfolio, specification, owner=candidate.candidate_id,
            implementation=candidate.implementation_hash, fee_rate=fee_rate)
        executor.execute(plan, bar, constraint=constraint)
    return executor.finish()
