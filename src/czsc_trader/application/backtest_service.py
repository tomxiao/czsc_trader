from __future__ import annotations

from datetime import date, datetime
from typing import Any

from strategy_manager import StrategyRegistry, StrategyVersion, canonical_sha256
from strategy_runtime import StrategyCandidate

from czsc_trader.backtesting import (
    BacktestRequestV2,
    resolve_candidate_snapshot,
    resolve_registered_strategy,
    run_backtest_v2,
)
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
    request: BacktestRequestV2,
    *,
    run_date: date | None = None,
    chart_descriptor: dict[str, Any] | None = None,
) -> CommandResult:
    """Replay a candidate or an authenticated frozen version through one engine.

    Candidate charts must be explicitly supplied by the caller. Version charts
    come from the authenticated deployment; overriding frozen content is refused.
    This operation does not register, freeze or deploy the supplied strategy.
    """
    if not isinstance(strategy, (StrategyCandidate, StrategyVersion)):
        raise TypeError("backtest strategy must be StrategyCandidate or StrategyVersion")
    if not isinstance(request, BacktestRequestV2):
        raise TypeError("backtest request must be BacktestRequestV2")
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
                chart_descriptor=chart_descriptor,
            )
        else:
            if chart_descriptor is not None:
                raise ValueError("frozen version chart override is not allowed")
            stored = StrategyRegistry(context.strategy_root).get_version(
                strategy.strategy_id,
                strategy.version,
            )
            if stored.to_dict() != strategy.to_dict():
                raise ValueError("backtest version differs from the frozen registry record")
            snapshot = resolve_registered_strategy(context, strategy.strategy_id, strategy.version)
        summary = run_backtest_v2(
            snapshot=snapshot,
            request=request,
            srt_data_root=context.tdr_srt_root,
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
