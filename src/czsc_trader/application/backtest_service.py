from __future__ import annotations

from strategy_manager import StrategyRegistry, StrategyVersion, canonical_sha256
from strategy_runtime import StrategyCandidate

from czsc_trader.backtesting import (
    BacktestRequest,
    resolve_candidate_snapshot,
    resolve_registered_strategy,
)
from czsc_trader.backtesting.service import _run_backtest, BacktestEvaluation
from czsc_trader.backtesting.execution_data import (
    BacktestExecutionDataNotReadyError,
)

from ..research_tools.context import ResearchContext
from .errors import ExecutionError
from .runtime_acceptance import _plain


def run_backtest(
    context: ResearchContext,
    strategy: StrategyCandidate | StrategyVersion,
    request: BacktestRequest,
) -> BacktestEvaluation:
    """Replay a candidate or an authenticated frozen version through one engine.

    Returns audited candidate or frozen-version accounts without storing reports.
    This operation does not register, freeze or deploy the supplied strategy.
    """
    if not isinstance(context, ResearchContext):
        raise TypeError("backtest requires ResearchContext")
    repository = context.repository
    if not isinstance(strategy, (StrategyCandidate, StrategyVersion)):
        raise TypeError("backtest strategy must be StrategyCandidate or StrategyVersion")
    if not isinstance(request, BacktestRequest):
        raise TypeError("backtest request must be BacktestRequest")
    reference = (
        strategy.reference_id if isinstance(strategy, StrategyCandidate) else strategy.release_id
    )
    try:
        batch_id = strategy.strategy_family_id if isinstance(strategy, StrategyCandidate) else strategy.strategy_id
        if batch_id != context.strategy_id:
            raise ValueError("backtest strategy belongs to another research batch")
        if isinstance(strategy, StrategyCandidate):
            payload = _plain(strategy.payload)
            snapshot = resolve_candidate_snapshot(
                repository,
                strategy.reference_id,
                payload,
                canonical_sha256(payload),
                f"candidate:{strategy.reference_id}",
                runtime_root=strategy.source_root,
            )
        else:
            stored = StrategyRegistry(repository.strategy_root).get_version(
                strategy.strategy_id,
                strategy.version,
            )
            if stored.to_dict() != strategy.to_dict():
                raise ValueError("backtest version differs from the frozen registry record")
            snapshot = resolve_registered_strategy(repository, strategy.strategy_id, strategy.version)
        summary = _run_backtest(
            snapshot=snapshot,
            request=request,
            repository_root=repository.root,
            dataflows=context.data,
        )
    except BacktestExecutionDataNotReadyError as exc:
        raise ExecutionError(
            "backtest_data_not_ready",
            str(exc),
            context={
                "strategy": reference,
                "symbol": request.symbol,
                "requested_cutoff": exc.requested_cutoff.isoformat(),
                "published_cutoff": exc.published_cutoff.isoformat(),
                "first_unpublished_session": exc.first_unpublished_session.isoformat(),
            },
        ) from exc
    except Exception as exc:
        raise ExecutionError(
            "backtest_failed",
            str(exc),
            context={
                "strategy": reference,
                "symbol": request.symbol,
            },
        ) from exc
    return summary
