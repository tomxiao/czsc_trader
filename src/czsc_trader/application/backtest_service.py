from __future__ import annotations

from datetime import date, datetime

from strategy_manager import StrategyRegistry, StrategyVersion, canonical_sha256
from strategy_runtime import StrategyCandidate

from czsc_trader.backtesting import (
    BacktestRequest,
    resolve_candidate_snapshot,
    resolve_registered_strategy,
)
from czsc_trader.backtesting.service import _run_backtest
from czsc_trader.backtesting.execution_data import (
    BacktestExecutionDataNotReadyError,
)

from .context import RepositoryContext
from .errors import ExecutionError
from .results import CommandResult
from .runtime_acceptance import _plain


def run_backtest(
    context: RepositoryContext,
    strategy: StrategyCandidate | StrategyVersion,
    request: BacktestRequest,
    *,
    run_date: date | None = None,
) -> CommandResult:
    """Replay a candidate or an authenticated frozen version through one engine.

    TDR renders candidate and frozen-version charts from audited replay facts.
    This operation does not register, freeze or deploy the supplied strategy.
    """
    if not isinstance(strategy, (StrategyCandidate, StrategyVersion)):
        raise TypeError("backtest strategy must be StrategyCandidate or StrategyVersion")
    if not isinstance(request, BacktestRequest):
        raise TypeError("backtest request must be BacktestRequest")
    reference = (
        strategy.reference_id if isinstance(strategy, StrategyCandidate) else strategy.release_id
    )
    try:
        if isinstance(strategy, StrategyCandidate):
            payload = _plain(strategy.payload)
            snapshot = resolve_candidate_snapshot(
                context,
                strategy.reference_id,
                payload,
                canonical_sha256(payload),
                f"candidate:{strategy.reference_id}",
                runtime_root=strategy.source_root,
            )
        else:
            stored = StrategyRegistry(context.strategy_root).get_version(
                strategy.strategy_id,
                strategy.version,
            )
            if stored.to_dict() != strategy.to_dict():
                raise ValueError("backtest version differs from the frozen registry record")
            snapshot = resolve_registered_strategy(context, strategy.strategy_id, strategy.version)
        summary = _run_backtest(
            snapshot=snapshot,
            request=request,
            outputs_root=context.outputs_root,
            run_date=run_date or datetime.now().astimezone().date(),
            repository_root=context.root,
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
    return CommandResult(
        status="PASS",
        command="backtest.run",
        result={
            "strategy": snapshot.identity.reference,
            "metrics": summary.metrics,
            "audit_status": summary.manifest["audit"]["status"],
            "runtime_engine": summary.manifest["application"]["runtime_engine"],
        },
        artifacts={"output_dir": str(summary.output_dir)},
    )
