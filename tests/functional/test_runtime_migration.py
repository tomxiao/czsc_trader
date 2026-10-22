"""Frozen migration preparation is local and explicitly separates equivalence.

Release acceptance covers the six explicitly reviewed historical source adapters.
Synthetic feature boundaries exercise each unchanged decision kernel. They do
not stand in for market-data, transaction-ledger or production acceptance.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import importlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from czsc_trader.application import (
    FrozenRuntimeMigrationRequest, RepositoryContext,
    prepare_frozen_runtime_migration, validate_release_package,
)
from czsc_trader.application.runtime_acceptance import prospective_release
from strategy_manager import StrategyRegistry
from strategy_manager.freeze_contracts import FrozenVersionReference
from czsc_trader.application.runtime_migration import _migration_original
from strategy_runtime import (
    DecisionFeedback, ExecutionCapabilities, ExecutionPlan, ExecutionState, HistoryCalculationContext,
    OrderSide, OrderType, ParameterSet, PlanLeg, PlannedOrder, PortfolioSnapshot,
    PriceReference, RuntimeBinding, SignalHistoryMode, StrategyIdentity,
    StrategyImplementationV2, StrategyRuntime, TradableWindow, TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import HistoricalExecutor


pytestmark = pytest.mark.release_acceptance

ROOT = Path(__file__).resolve().parents[2]
REFERENCES = ("S001-v1", "S001-v2", "S002-v1", "S003-v1", "S007-v1", "S011-v1")
BASELINE_IDENTITIES = {
    "S001-v1": ("3dccd608cf8ee762a8f359d197aca93463183b50a4da5771ca3ca694063ab692", "5d62e13496e033ba6991e6d56b5f8886bf67d408a25dbcdb31141bddf475d228"),
    "S001-v2": ("2c4a339ca5dec89c03491e5fd15fc8560d7aa0424f8af2be1fcdf9b93b51a2da", "65996ee0fcc3915a109c391129136d2a0dd9f5db81a85361263757a38fdf2f67"),
    "S002-v1": ("707e3d3fb7feea4d5f04e71e3ca8fa026562c6a76e666fffd86e53e7e4f00715", "2ebb2179a78593083bf43a2132de26e8fe54c5dd202b8f8b1601c4821ba0b923"),
    "S003-v1": ("eb0ebf6c80385f8c9d0d34fa466059ab9364055af79b7bf0fe2f9168f683d174", "cfcbf8165b9472c9d91356a43d43686116e728c32f900d491e346d862dcd0498"),
    "S007-v1": ("19c6bdb05c7fb1daae5bb71f0bd61cd09d7987f049e2dac6c95e3f2a063259b2", "c45f8a3792b49afcca152901a620e1b88df7f8a69112aa70a2edf6f972f5e95e"),
    "S011-v1": ("369b89c170906d74ac884cd1f9b08d22e5ba773998d8be1b58086784e4c12f2c", "a8945d9257d59e195b4f161cb4b572a0fab8e3ef6a20c45c2d048cf9e1ae2c04"),
}


@pytest.fixture(scope="module")
def preparations(frozen_seed_root):
    live = RepositoryContext.discover(ROOT)
    workspace = frozen_seed_root / "runtime-migration"
    baseline = workspace / ("baseline_" + uuid4().hex)
    context = RepositoryContext(baseline, baseline / "research", baseline / "research/registrations", baseline / "strategies")
    for ref, identity in BASELINE_IDENTITIES.items():
        family, version = ref.split("-")
        old, manifest, _, source = _migration_original(live, FrozenVersionReference(family, version, *identity))
        package = source
        for _ in Path(manifest["runtime_root"]).parts:
            package = package.parent
        shutil.copytree(package, context.strategy_root / family / "releases" / version)
        path = context.strategy_root / family / "versions" / f"{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(old.to_dict()), encoding="utf-8")
        deployment = context.strategy_root / "deployments" / f"{ref}.json"
        deployment.parent.mkdir(exist_ok=True)
        value = {"schema_version": 1, "strategy_version_id": ref, "strategy_version_hash": old.release_hash,
                 "release_package": f"{family}/releases/{version}", "package_hash": manifest["package_hash"]}
        from strategy_manager import canonical_sha256
        value["receipt_hash"] = canonical_sha256(value)
        deployment.write_text(json.dumps(value), encoding="utf-8")
    original = {str(path): sha256(path.read_bytes()).hexdigest()
                for path in context.strategy_root.rglob("*") if path.is_file()}
    results = {ref: prepare_frozen_runtime_migration(context, FrozenRuntimeMigrationRequest(
        ref, f"C{9800 + index:04d}", baseline / ".tmp" / ref.replace("-", "_"),
    )) for index, ref in enumerate(REFERENCES)}
    yield context, results
    actual = {str(path): sha256(path.read_bytes()).hexdigest()
              for path in context.strategy_root.rglob("*") if path.is_file()}
    assert actual == original, "preparation must never modify or create frozen strategy files"


@pytest.mark.parametrize("reference", REFERENCES)
def test_real_frozen_preparation_authenticates_new_identity_and_plain_import(preparations, reference, monkeypatch):
    _, results = preparations
    result = results[reference]
    assert result.original_source_sha256 != result.migrated_source_sha256
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["registered"] is metadata["frozen"] is metadata["deployed"] is False
    assert metadata["candidate_identity"]["content_sha256"] == result.migrated_content_sha256
    definition = StrategyRuntime().describe(result.candidate)
    assert definition.implementation.contract_version == 2
    assert definition.decision_feedback is DecisionFeedback.MARKET_INTENT
    assert result.candidate.payload["decision_feedback"] == "MARKET_INTENT"
    assert metadata["decision_feedback_review"] == "REVIEWED_MARKET_INTENT_NO_ACTUAL_FILL_DEPENDENCY"
    monkeypatch.syspath_prepend(str(result.metadata_path.parent.parent))
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    prefix = result.metadata_path.parent.name + ".strategy_runtime"
    for path in sorted(result.candidate.source_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(prefix + "." + ".".join(path.relative_to(result.candidate.source_root).with_suffix("").parts))
        assert Path(module.__file__).resolve() == path.resolve()
    assert result.equivalence_status == "NOT_YET_NUMERICALLY_VERIFIED"
    with pytest.raises(ValueError, match="already implements contract version 2"):
        prepare_frozen_runtime_migration(RepositoryContext.discover(ROOT), FrozenRuntimeMigrationRequest(
            reference, "C9899", result.metadata_path.parent / "no-second-migration"))
    if reference == "S007-v1":
        assert metadata["market_intent_history"] == "CANONICAL_REPLAY"


def _implementations(preparations, reference, monkeypatch):
    context, results = preparations
    strategy_id, version = reference.rsplit("-", 1)
    stored = StrategyRegistry(context.strategy_root).get_version(strategy_id, version)
    _, binding, source = validate_release_package(context, reference)
    release = prospective_release(stored)
    StrategyRuntime().describe(release, source_root=source, runtime_binding=RuntimeBinding.from_dict(binding))
    monkeypatch.syspath_prepend(str(context.root.parent))
    monkeypatch.syspath_prepend(str(results[reference].metadata_path.parent.parent))
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    module_suffix = release.payload["runtime"]["module"].removeprefix("strategy_runtime.")
    old_module = importlib.import_module(context.root.name + "." + ".".join(source.relative_to(context.root).parts) + "." + module_suffix)
    new_module = importlib.import_module(results[reference].metadata_path.parent.name + ".strategy_runtime." + module_suffix)
    factory_name = release.payload["runtime"]["qualname"]
    old = getattr(old_module, factory_name).from_parameters(ParameterSet(release.payload["parameters"]))
    new = getattr(new_module, factory_name).from_parameters(ParameterSet(results[reference].candidate.payload["parameters"]))
    return old, new


def _synthetic_features(reference, implementations, monkeypatch):
    dates = pd.bdate_range("2024-12-26", periods=400, name="dt")
    inputs = {}
    for implementation in implementations:
        function = (implementation.calculate_context_history if isinstance(implementation, StrategyImplementationV2)
                    else implementation.calculate_history)
        namespace = function.__func__.__globals__
        if reference.startswith("S001"):
            scores = pd.DataFrame({"factor_score": np.tile([0.0, 1.0, 1.0, 0.0], 100)}, index=dates)
            monkeypatch.setitem(namespace, "_calculate_s001_scores", lambda *args, scores=scores: scores)
            inputs = {namespace[key]: pd.DataFrame() for key in ("_INTRADAY", "_DAILY", "_WEEKLY")}
        elif reference == "S002-v1":
            entry = implementation._signal["entry_state"]
            states = pd.Series(np.tile([entry, entry, "NON_ENTRY", "NON_ENTRY"], 100), index=dates)
            monkeypatch.setitem(namespace, "_calculate_signal_states", lambda *args, states=states, **kwargs: states)
            inputs = {namespace["_INPUT_DAILY"]: pd.DataFrame()}
        elif reference == "S003-v1":
            panel = pd.DataFrame({"observed_weight_ratio": 1.0,
                                  "moneyflow_breadth": np.sin(np.arange(400) / 7)}, index=dates)
            monkeypatch.setitem(namespace, "_seed_history", lambda *args, panel=panel: panel)
            inputs = {namespace["_SEED"]: pd.DataFrame()}
        elif reference == "S007-v1":
            desired = np.full(400, 0.07)
            desired[0] = 0.2
            panel = pd.DataFrame({name: desired / orientation
                                  for name, orientation in implementation._score["orientations"].items()}, index=dates)
            monkeypatch.setitem(namespace, "resolve_s007_feature_panel", lambda *args, panel=panel: panel)
            monkeypatch.setitem(namespace, "causal_percentile", lambda values, *args: values)
        else:
            wave = np.sin(np.arange(400) / 7)
            panel = pd.DataFrame({"tail": -wave, "market": -wave,
                                  "spx": wave, "risk5": 0.03}, index=dates)
            monkeypatch.setitem(namespace, "features", lambda *args, panel=panel: panel)
    if reference == "S011-v1":
        calculation_dates = dates[dates >= "2025-02-05"]
    elif reference == "S002-v1":
        # Its real FULL_PUBLICATION_REPLAY scope requests decision dates after
        # 300-session indicator warm-up; continuous intent starts in that input
        # publication, not at the first requested output row.
        calculation_dates = dates[-60:]
    else:
        calculation_dates = dates
    return inputs, calculation_dates


@pytest.mark.parametrize("reference", REFERENCES)
@pytest.mark.parametrize("mode", [SignalHistoryMode.CONTINUOUS, SignalHistoryMode.WINDOW])
@pytest.mark.parametrize("window_length", [1, 12])
def test_synthetic_kernel_equivalence_retains_market_intent_across_windows(preparations, reference, mode, window_length, monkeypatch):
    old, new = _implementations(preparations, reference, monkeypatch)
    inputs, calculation_dates = _synthetic_features(reference, (old, new), monkeypatch)
    signal_dates = calculation_dates[-window_length:]
    context = HistoryCalculationContext(mode, TradableWindow(
        signal_dates[0].date() + timedelta(days=1), signal_dates[-1].date() + timedelta(days=1)),
        tuple(signal_dates.date), tuple(calculation_dates.date))
    sessions = context.sessions
    expected = (old.calculate_history(inputs, sessions) if mode is SignalHistoryMode.CONTINUOUS
                else old.calculate_window_history(inputs, sessions))
    expected = expected.reindex(sessions)
    actual = new.calculate_context_history(inputs, context)
    pd.testing.assert_frame_equal(actual, new.calculate_context_history(inputs, context))
    pd.testing.assert_frame_equal(actual, expected, check_names=False, check_freq=False, check_index_type=False)
    if reference == "S007-v1":
        assert actual.target_position.eq(1).all(), "canonical market intent must retain causal hysteresis"


def test_migration_rejects_unsafe_or_reused_workspace_without_frozen_changes(preparations):
    context, results = preparations
    with pytest.raises(ValueError, match="under repository .tmp"):
        prepare_frozen_runtime_migration(context, FrozenRuntimeMigrationRequest("S001-v1", "C9899", Path("strategies/new")))
    with pytest.raises(FileExistsError, match="already exists"):
        prepare_frozen_runtime_migration(context, FrozenRuntimeMigrationRequest("S001-v1", "C9899", results["S001-v1"].metadata_path.parent))


def _definitions(preparations, reference):
    context, results = preparations
    family, version = reference.rsplit("-", 1)
    stored = StrategyRegistry(context.strategy_root).get_version(family, version)
    _, binding, source = validate_release_package(context, reference)
    runtime = StrategyRuntime()
    return (
        runtime.describe(prospective_release(stored), source_root=source,
                         runtime_binding=RuntimeBinding.from_dict(binding)),
        runtime.describe(results[reference].candidate),
    )


def _raw_plan(definition, target, portfolio, state):
    return build_execution_plan(
        deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
        available_cash=float(portfolio.available_cash), position_quantity=portfolio.position_quantity,
        target_position=float(target), policy=definition.execution,
        signal_reference_price=10., execution_reference_price=10.,
    )


def _typed_plan(definition, target, signal, trading, portfolio, state, raw):
    """Test channel adapter: public planner facts to the TXE plan contract."""
    identity = StrategyIdentity(definition.strategy_family_id, definition.release_id,
                                definition.release_hash, definition.implementation.source_sha256,
                                definition.tradable_symbol)

    def order(value):
        return PlannedOrder(OrderSide(value["side"]), int(value["quantity"]),
                            OrderType(value["order_type"]),
                            None if value.get("limit_price") is None else Decimal(str(value["limit_price"])))

    orders = tuple(order(value) for value in raw.get("orders", ()))
    legs = tuple(PlanLeg(
        sequence=int(value["sequence"]), role=value["role"], checkpoint=value["checkpoint"],
        submit_after=time.fromisoformat(value["submit_after"]), submit_before=time.fromisoformat(value["submit_before"]),
        dependency_sequence=value["dependency_sequence"], dependency_required_status=value["dependency_required_status"],
        order=order(value["order"]),
    ) for value in raw.get("plan_legs", ()))
    capital = raw.get("capital_rule", {"mode": "available_cash_fraction" if raw.get("plan_mode") == "CORE_SETUP" else "full_available_cash",
                                      "allocation_fraction": definition.execution.settings.get("core_fraction", 1.) if raw.get("plan_mode") == "CORE_SETUP" else 1.})
    quantities = dict(actual_quantity=portfolio.position_quantity,
                      target_quantity=int(raw["target_quantity"]),
                      cycle_target_quantity=int(raw["cycle_target_quantity"]),
                      plan_mode=str(raw.get("plan_mode", "TARGET_POSITION")),
                      capital_mode=capital["mode"], allocation_fraction=Decimal(str(capital["allocation_fraction"])),
                      orders=orders, legs=legs)
    inputs, prices = {"synthetic_features": "c" * 64}, {"synthetic_quotes": "d" * 64}
    signal_identity = signal_identity_for(strategy=identity, signal_date=signal,
        target_position=float(target), input_identities=inputs, price_identities=prices)
    return ExecutionPlan(
        strategy=identity, signal_identity=signal_identity,
        plan_identity=plan_identity_for(signal_identity=signal_identity, **quantities),
        symbol=identity.symbol, signal_date=signal, trading_date=trading,
        generated_at=datetime.combine(signal, time(20, 30), ZoneInfo("Asia/Shanghai")),
        expected_portfolio_revision=portfolio.revision, expected_state_revision=state.revision,
        target_position=float(target), action=raw["action"], available_cash=portfolio.available_cash,
        fee_rate=Decimal(str(raw["fee_rate"])), estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
        unallocated_cash=Decimal(str(raw["unallocated_cash"])),
        references=PriceReference(Decimal(10), Decimal(10), "ADJUSTED_CLOSE", "UNADJUSTED_CLOSE"),
        required_capabilities=ExecutionCapabilities(
            tuple(sorted({value.order_type for value in orders + tuple(leg.order for leg in legs)})),
            tuple(sorted({leg.checkpoint for leg in legs}))),
        input_identities=inputs, price_identities=prices, **quantities,
    )


def _execute_kernel(definition, history):
    signals = history.index[-60:].as_unit("ns")
    trading = pd.DatetimeIndex(signals + pd.offsets.BDay())
    pricing_dates = trading.insert(0, signals[0])
    daily = pd.DataFrame({"dt": pricing_dates, "open": 10., "high": 10.2, "low": 9.8, "close": 10.})
    intraday = daily.copy()
    intraday["dt"] += pd.Timedelta(hours=10)
    five_minute = pd.concat([daily.assign(dt=pricing_dates + pd.Timedelta(hours=9, minutes=35)),
                             daily.assign(dt=pricing_dates + pd.Timedelta(hours=11, minutes=30))], ignore_index=True)
    executor = HistoricalExecutor(
        strategy_reference=definition.release_id, symbol=definition.tradable_symbol,
        execution_daily=daily, execution_intraday=intraday,
        evaluation_start=trading[0], evaluation_end=trading[-1], initial_cash=100_000.,
        execution_policy=definition.execution, order_types=definition.capabilities.order_types,
        checkpoints=definition.capabilities.checkpoints, execution_five_minute=five_minute,
    )
    for signal, execution in zip(signals, trading, strict=True):
        generated = datetime.combine(signal.date(), time(20, 30), ZoneInfo("Asia/Shanghai"))
        portfolio, state = executor.snapshot(TradingPoint(execution.date(), generated))
        target = history.loc[signal, "target_position"]
        raw = _raw_plan(definition, target, portfolio, state)
        plan = _typed_plan(definition, target, signal.date(), execution.date(), portfolio, state, raw)
        outcome = executor.execute(plan)
        assert executor.execute(plan) == outcome, "migration must retain retry idempotence"
    return executor.finish()


def _relational_ledger(result):
    """Retain links/cycle grouping while replacing content-derived identity text."""
    maps = {}
    output = []
    for name in ("decisions", "orders", "fills", "account_daily", "trades"):
        frame = getattr(result, name).copy()
        for column in ("decision_id", "order_id", "fill_id", "cycle_id"):
            if column in frame:
                mapping = maps.setdefault(column, {})
                frame[column] = frame[column].map(lambda value: mapping.setdefault(value, len(mapping)))
        output.append(frame)
    return output


@pytest.mark.parametrize("reference,mode", [(reference, mode) for reference in REFERENCES
    for mode in (SignalHistoryMode.CONTINUOUS, SignalHistoryMode.WINDOW)])
def test_actual_policies_and_txe_economic_ledgers_remain_equivalent(preparations, reference, mode, monkeypatch):
    old, new = _implementations(preparations, reference, monkeypatch)
    definitions = _definitions(preparations, reference)
    assert definitions[0].execution == definitions[1].execution
    assert definitions[0].capabilities == definitions[1].capabilities
    inputs, calculation_dates = _synthetic_features(reference, (old, new), monkeypatch)
    signal_dates = calculation_dates[-60:]
    context = HistoryCalculationContext(mode, TradableWindow(
        (signal_dates[0] + pd.offsets.BDay()).date(), (signal_dates[-1] + pd.offsets.BDay()).date()),
        tuple(signal_dates.date), tuple(calculation_dates.date))
    histories = ((old.calculate_history(inputs, context.sessions) if mode is SignalHistoryMode.CONTINUOUS
                  else old.calculate_window_history(inputs, context.sessions)),
                 new.calculate_context_history(inputs, context))
    ledgers = [_execute_kernel(definition, history) for definition, history in zip(definitions, histories, strict=True)]
    for actual, expected in zip(_relational_ledger(ledgers[1]), _relational_ledger(ledgers[0]), strict=True):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    result = ledgers[1]
    assert not result.fills.empty, "equivalence requires real synthetic fills, not two idle accounts"
    assert result.fills.quantity.mod(100).eq(0).all()
    settings = definitions[1].execution.settings
    fee = settings["one_way_cost"] if definitions[1].execution.policy_type == "INTRADAY_OVERLAY" else settings["capital"]["fee_rate"]
    np.testing.assert_allclose(result.fills.fees, result.fills.quantity * result.fills.price * fee, rtol=0, atol=1e-12)
    assert not result.trades.empty
    assert result.account_daily.cash.ge(0).all()
    assert result.account_daily.cash_before.iloc[0] == 100_000.
    assert result.account_daily.quantity_before.iloc[0] == 0, "market intent must never carry account positions into replay"



@pytest.mark.parametrize("reference", REFERENCES)
def test_existing_nonzero_account_cash_and_cycle_are_preserved_by_migrated_planner(preparations, reference):
    old, new = _definitions(preparations, reference)
    generated = datetime(2026, 10, 16, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    for cash, quantity, cycle in (("12345.67", 600, 600), ("99.50", 200, 600)):
        portfolio = PortfolioSnapshot("existing-account", old.tradable_symbol, Decimal(cash),
            Decimal(cash) + quantity * Decimal(10), quantity, 17, generated)
        state = ExecutionState(23, generated, cycle)
        for target in (0., 1.):
            if old.execution.policy_type == "INTRADAY_OVERLAY" and quantity != cycle:
                # An incomplete core is an explicit error in the actual old and new policy.
                from strategy_runtime import RuntimeContractError
                for definition in (old, new):
                    with pytest.raises(RuntimeContractError, match="differs from core quantity"):
                        _raw_plan(definition, target, portfolio, state)
                continue
            plans = [_raw_plan(definition, target, portfolio, state) for definition in (old, new)]
            assert plans[0] == plans[1]
            assert plans[1]["actual_quantity"] == quantity
            assert plans[1]["cycle_target_quantity"] == cycle
            assert plans[1]["available_cash"] == float(cash)
            assert state.revision == 23 and portfolio.revision == 17
