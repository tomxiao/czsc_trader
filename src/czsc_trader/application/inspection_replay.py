"""Isolated, cancellable candidate/frozen replay using the normal SRT/TXE path."""
from dataclasses import replace
from hashlib import sha256
import json
import pickle
import math

import pandas as pd
from dataflows import Dataflows, ProviderConfig
from strategy_runtime import StrategyRuntime, StrategyInit, StrategyInputBinding, ExecutionPolicy
from strategy_evaluator import compare_ledgers, LedgerComparisonRequest, LedgerComparisonMode, LedgerComparisonStatus
from trading_execution_engine import HistoricalExecutor
from ..backtesting.observation import ObservationExecutor
from ..backtesting.models import StrategyIdentity, StrategySnapshot
from ..backtesting.result import BacktestResult
from ..backtesting.signal_replay import SignalReplay
from ..backtesting.audit_adapter import build_replay_evidence
from ..backtesting.metrics import calculate_metrics


def _run(runtime, strategy, replay, root, source_root=None, binding=None):
    window = replay.input_binding.plan.tradable_window
    definition = runtime.describe(strategy, source_root=source_root, runtime_binding=binding)
    policy = definition.execution
    settings = dict(policy.settings)
    if policy.policy_type == "FROZEN_RULE":
        settings["capital"] = {**settings["capital"], "fee_rate": replay.one_way_cost}
    else:
        settings["one_way_cost"] = replay.one_way_cost
    policy = ExecutionPolicy(policy.policy_type, settings)
    data = replay.execution_data
    instance = runtime.create(StrategyInit(strategy, window, root, source_root=source_root,
        runtime_binding=binding, execution_policy=policy, pricing=data.pricing))
    # The candidate must authenticate the caller's original identity and plan.
    # Only the release side changes representation, after the candidate succeeded.
    bound = (StrategyInputBinding(replace(replay.input_binding.plan, strategy=instance.identity), replay.input_binding.prepared)
             if source_root is not None else replay.input_binding)
    prepared = instance.prepare_data(binding=bound)
    signals = instance.inspect_signals()
    reference = strategy.release_id if source_root else strategy.reference_id
    channel = HistoricalExecutor(strategy_reference=reference, symbol=data.symbol,
        execution_daily=data.execution_daily, execution_intraday=data.execution_intraday,
        execution_five_minute=data.execution_five_minute,
        evaluation_start=pd.Timestamp(window.start), evaluation_end=pd.Timestamp(window.end),
        initial_cash=replay.initial_cash, execution_policy=policy,
        order_types=definition.capabilities.order_types, checkpoints=definition.capabilities.checkpoints,
        pricing=data.pricing, market_rules=data.market_rules)
    executor = ObservationExecutor(instance.definition, channel)
    ledger = instance.run_window(executor=executor)
    identity = StrategyIdentity("REGISTERED" if source_root else "CANDIDATE", reference, "technical_inspection")
    result = BacktestResult(identity, ledger.decisions, ledger.orders, ledger.fills,
                            ledger.account_daily, ledger.trades, tuple(executor.observations))
    content = strategy.release_hash if source_root else strategy.runtime_identity_sha256
    payload_hash = sha256(json.dumps(dict(strategy.payload), default=dict, ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    support = {"mode": "srt_input_contract", "execution_policy": {"policy_type": policy.policy_type, "settings": dict(policy.settings)}}
    if policy.policy_type == "FROZEN_RULE":
        support.update(entry_order_type=policy.order_type_for("BUY"), exit_order_type=policy.order_type_for("SELL"))
    signal_replay = SignalReplay(StrategySnapshot(identity, payload_hash, content, dict(strategy.payload), runtime_root=source_root),
        strategy, ledger.decisions, signals.index.min(), signals.index.max(), pd.Timestamp(window.start),
        pd.Timestamp(window.end), root, prepared.data_identity, support)
    evidence = build_replay_evidence(signal_replay, data, result, replay.initial_cash, calculate_metrics(result, replay.initial_cash))
    observations = [{k: v for k, v in item.to_dict().items() if k not in
                    ("strategy", "signal_identity", "plan_identity")} for item in executor.observations]
    return evidence, signals, observations, bound


# ECONOMIC_V1 tolerates only these continuous output fields. Identity, quantities,
# counts, dates, target ratios and unknown extension fields always compare exactly.
_FLOAT_FIELDS = frozenset({
    "price", "limit_price", "fees", "cash", "cash_before", "equity", "close",
    "entry_price", "exit_price", "entry_fees", "exit_fees", "gross_pnl", "net_pnl",
    "gross_return", "net_return", "market_value", "pnl", "realized_pnl",
    "max_drawdown", "calmar", "win_loss_ratio", "return", "sharpe", "win_rate", "annual_return",
})
_ID_FIELDS = ("decision_id", "order_id", "fill_id", "cycle_id")
COMPARISON_EXCLUSIONS = ("strategy_hash", "content_hash", "economic renaming: decision_id/order_id/fill_id/cycle_id")


def _economic_payload(value):
    import copy
    result = copy.deepcopy(value)
    result.pop("strategy_hash", None)
    result.pop("content_hash", None)
    ids = {name: {} for name in _ID_FIELDS}
    for table in ("decisions", "orders", "fills", "account_daily", "trades"):
        for row in result.get(table, ()):
            for name, mapping in ids.items():
                raw = row.get(name)
                if raw is not None:
                    if raw not in mapping:
                        mapping[raw] = f"{name}:{len(mapping)}"
                    row[name] = mapping[raw]
    return result


def _differences(left, right, tolerance, path, found, *, field="", continuous=False):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                found.append({"path": f"{path}.{key}", "left": left.get(key), "right": right.get(key),
                              "tolerance": 0, "reason": "FIELD_MISSING"})
            else:
                # Input/configuration facts are always exact; whitelist is only
                # applied to emitted account records and the derived metrics.
                active = continuous or (path == "replay" and key in
                    ("decisions", "orders", "fills", "account_daily", "trades", "metrics"))
                _differences(left[key], right[key], tolerance, f"{path}.{key}", found, field=key, continuous=active)
    elif isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        if len(left) != len(right):
            found.append({"path": path, "left": len(left), "right": len(right), "tolerance": 0, "reason": "ROW_COUNT_DIFFERS"})
        for i, (a, b) in enumerate(zip(left, right)):
            _differences(a, b, tolerance, f"{path}[{i}]", found, field=field, continuous=continuous)
    else:
        numeric = type(left) in (int, float) and type(right) in (int, float)
        allowed = tolerance if continuous and field in _FLOAT_FIELDS and numeric else 0
        equal = ((math.isfinite(left) and math.isfinite(right) and abs(left - right) <= allowed)
                 if numeric else type(left) is type(right) and left == right)
        if not equal:
            found.append({"path": path, "left": left, "right": right, "tolerance": allowed, "reason": "VALUE_DIFFERS"})


def technical_ledger_differences(left, right, tolerance):
    """Full fixed ECONOMIC_V1 differences; SE separately checks ledger integrity."""
    result = []
    _differences(_economic_payload(left), _economic_payload(right), tolerance, "replay", result)
    return result


def _signal_difference(left, right):
    # Signals drive discrete strategy transitions; even float representations of
    # levels/flags must match exactly. Continuous tolerance is account-only.
    try:
        pd.testing.assert_frame_equal(left, right, check_exact=True)
    except AssertionError as exc:
        return str(exc)
    return None


def _signal_snapshot(frame):
    """Lossless scalar signal facts for later read-only result verification."""
    from datetime import date, datetime
    import numpy as np

    def scalar(value):
        if value is pd.NA or value is pd.NaT:
            return {"missing": type(value).__name__}
        if isinstance(value, (pd.Timestamp, date, datetime)):
            return value.isoformat()
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not math.isfinite(value):
            return {"nonfinite": "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"}
        if value is None or type(value) in (bool, str, int, float):
            return value
        raise TypeError(f"signal table contains unsupported scalar {type(value).__name__}")

    return {"columns": [scalar(x) for x in frame.columns], "dtypes": [str(x) for x in frame.dtypes],
            "index_name": frame.index.name, "index_dtype": str(frame.index.dtype),
            "index": [scalar(x) for x in frame.index],
            "rows": [[scalar(x) for x in row] for row in frame.itertuples(index=False, name=None)]}


def compute(connection, payload):
    """Only the parent can supply this in-memory pickle; never read artifact pickle."""
    try:
        from threadpoolctl import threadpool_limits
        base, space, candidate, verified, replay, workspace, tolerance = pickle.loads(payload)
        flows = Dataflows(base_dir=base, space=space, providers=ProviderConfig(bindings={}))
        runtime = StrategyRuntime(dataflows=flows)
        with threadpool_limits(limits=1):
            left, ls, lo, lb = _run(runtime, candidate, replay, workspace / "candidate")
            right, rs, ro, rb = _run(runtime, verified.release, replay, workspace / "release",
                                      verified.source_root, verified.runtime_binding)
        signal_error = _signal_difference(ls, rs)
        compared = compare_ledgers(LedgerComparisonRequest(left, right, LedgerComparisonMode.ECONOMIC, tolerance))
        differences = technical_ledger_differences(left.to_dict(), right.to_dict(), tolerance)
        result = {"method_version": "ECONOMIC_V1", "exclusions": list(COMPARISON_EXCLUSIONS),
                  "float_fields": sorted(_FLOAT_FIELDS), "differences": differences, "candidate": left.to_dict(), "release": right.to_dict(), "comparison": compared.to_dict(),
                  "candidate_binding": lb.to_dict(), "release_binding": rb.to_dict(),
                  "candidate_signals": _signal_snapshot(ls), "release_signals": _signal_snapshot(rs),
                  "signal_error": signal_error, "observations_equal": lo == ro,
                  "candidate_observations": lo, "release_observations": ro,
                  "passed": signal_error is None and lo == ro and not differences and compared.status is LedgerComparisonStatus.EQUIVALENT}
        connection.send((True, result))
    except BaseException as exc:
        connection.send((False, {"type": type(exc).__name__, "message": str(exc)}))
    finally:
        connection.close()
