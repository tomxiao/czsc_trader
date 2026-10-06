from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import BacktestRequest

from .execution_data import BacktestExecutionData
from .models import StrategySnapshot
from .signal_replay import SignalReplay


def build_manifest(
    *,
    request: BacktestRequest,
    snapshot: StrategySnapshot,
    data: BacktestExecutionData,
    signals: SignalReplay,
    metrics: dict[str, object],
    audit: dict[str, object],
    application: dict[str, str],
) -> dict[str, object]:
    manifest = {
        "schema_version": 5,
        "engine": "TDR_BACKTEST_V2",
        "strategy": {
            "kind": snapshot.identity.kind,
            "reference": snapshot.identity.reference,
            "source": snapshot.identity.source,
            "source_hash": snapshot.source_hash,
            "snapshot_hash": snapshot.content_hash,
        },
        "application": application,
        "execution_data": {
            "fingerprint": data.fingerprint,
            "cutoff": data.cutoff.isoformat(),
            "signal_adjustment": "hfq",
            "execution_adjustment": "none",
        },
        "request": {
            "symbol": request.symbol,
            "asset_type": request.asset_type,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "initial_cash": request.initial_cash,
            "lot_size": request.lot_size,
        },
        "ranges": {
            "calculation": [
                signals.calculation_start.date().isoformat(),
                signals.calculation_end.date().isoformat(),
            ],
            "evaluation": [
                signals.evaluation_start.date().isoformat(),
                signals.evaluation_end.date().isoformat(),
            ],
        },
        "metrics": metrics,
        "audit": audit,
    }
    if signals.support_data is not None:
        manifest["signal_support"] = signals.support_data
    return manifest
