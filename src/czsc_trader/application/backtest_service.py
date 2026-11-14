from __future__ import annotations

from strategy_manager import StrategyRegistry, StrategyVersion
from dataflows import Dataflows

from czsc_trader.backtesting import (
    BacktestRequest,
    resolve_registered_strategy,
)
from czsc_trader.backtesting.service import _run_backtest, BacktestEvaluation
from czsc_trader.backtesting.execution_data import (
    BacktestExecutionDataNotReadyError,
    BacktestExecutionDataPreparationError,
)

from ..research_tools.context import ResearchContext
from .errors import ExecutionError
from .context import RepositoryContext
from .runtime_acceptance import _plain

def run_backtest(
    context: ResearchContext,
    strategy: StrategyVersion,
    request: BacktestRequest,
) -> BacktestEvaluation:
    """Explicitly backtest an existing frozen version without publishing reports.

    Equity account replay uses the V5 research execution session for either market.
    """
    if not isinstance(context, ResearchContext):
        raise TypeError("backtest requires ResearchContext")
    from strategy_runtime.equity_definition import EquityStrategyCandidate
    from ..research_tools.equity_evaluation import EquityEvaluationRequest
    if type(strategy) in (EquityStrategyCandidate,) or type(request) is EquityEvaluationRequest:
        raise TypeError("Equity account replay requires ResearchExecutionSession and a V5 EquityEvaluationRequest")
    if context.execution_spec is not None:
        raise ValueError("explicit equity context cannot execute an exchange-bound legacy request")
    if type(strategy) is not StrategyVersion:
        raise TypeError("run_backtest requires a frozen StrategyVersion")
    if not isinstance(request, BacktestRequest):
        raise TypeError("backtest request must be BacktestRequest")
    if strategy.strategy_id != context.strategy_id:
        raise ExecutionError("backtest_failed", "backtest strategy belongs to another research batch",
                             context={"strategy": strategy.release_id, "symbol": request.symbol})
    return _run_authenticated_backtest(context.repository, strategy, request, context.data)


def _run_authenticated_backtest(
    repository: RepositoryContext,
    strategy: StrategyVersion,
    request: BacktestRequest,
    dataflows: Dataflows,
) -> BacktestEvaluation:
    """Shared calculation and identity checks for research and independent runs."""
    if type(strategy) is not StrategyVersion:
        raise TypeError("authenticated backtest requires a frozen StrategyVersion")
    reference = strategy.release_id
    try:
        stored = StrategyRegistry(repository.strategy_root).get_version(
            strategy.strategy_id, strategy.version)
        if stored.to_dict() != strategy.to_dict():
            raise ValueError("backtest version differs from the frozen registry record")
        if stored.strategy_payload.get("runtime", {}).get("kind") == "ACCOUNT_REPLAY":
            raise ValueError(
                "backtest run uses the legacy request format. For V5 equity account replay, "
                "use ResearchExecutionSession with EquityEvaluationRequest and explicit step_data_windows."
            )
        snapshot = resolve_registered_strategy(repository, strategy.strategy_id, strategy.version)
        summary = _run_backtest(
            snapshot=snapshot,
            request=request,
            repository_root=repository.root,
            dataflows=dataflows,
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
    except BacktestExecutionDataPreparationError as exc:
        raise ExecutionError(
            "backtest_failed",
            str(exc),
            context={
                "strategy": reference,
                "symbol": request.symbol,
                "input": exc.input_name,
                "data_error": {
                    "code": exc.error.code,
                    "message": exc.error.message,
                    "context": _plain(exc.error.context),
                },
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
