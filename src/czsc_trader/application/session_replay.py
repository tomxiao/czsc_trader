"""Historical session host: strategy proposals, EC plans and confirmed outcomes."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from strategy_runtime import SignalHistoryMode, RuntimeCompatibilityError, RuntimeExecutionError
from execution_channels.serialization import from_record, to_record
from execution_channels.session_contracts import TradingPoint, ExecutionOutcomeStatus
from execution_channels.contracts import ReplayPoint, ExecutionPrecision
from execution_channels.planning.projection import project_window_plan
from .ec_boundary import session_execution_plan


def replay_sessions(strategy, executor):
    capabilities = executor.capabilities
    missing_orders = set(strategy.definition.capabilities.order_types) - {x.value for x in capabilities.order_types}
    missing_checks = set(strategy.definition.capabilities.checkpoints) - set(capabilities.checkpoints)
    if missing_orders or missing_checks:
        raise RuntimeCompatibilityError('window executor lacks required capabilities')
    zone = ZoneInfo('Asia/Shanghai')
    for point in strategy.decision_points():
        proposal = strategy.propose_at(point=point, history_mode=SignalHistoryMode.WINDOW)
        before = executor.snapshot(from_record(TradingPoint, to_record(point)))
        plan = session_execution_plan(proposal, *before)
        if (set(plan.required_capabilities.order_types) - set(capabilities.order_types)
                or set(plan.required_capabilities.checkpoints) - set(capabilities.checkpoints)):
            raise RuntimeCompatibilityError('window executor lacks required plan capabilities')
        start = datetime.combine(plan.trading_date, time.min, tzinfo=zone)
        replay_point = ReplayPoint(datetime.combine(plan.signal_date, time(15), tzinfo=zone),
            plan.generated_at, start, start + timedelta(days=1), plan.trading_date.isoformat(),
            ExecutionPrecision.SESSION)
        # The display host retains the original proposal, never reconstructs a signal from fills.
        executor.observe_proposal(proposal, plan)
        outcome = executor.execute_plan(project_window_plan(plan, replay_point), plan)
        if outcome.plan_identity != plan.plan_identity or outcome.status is not ExecutionOutcomeStatus.SETTLED:
            raise RuntimeExecutionError('window executor did not settle the plan: ' + plan.plan_identity)
    return executor.finish()
