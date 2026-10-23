from __future__ import annotations

from datetime import date, datetime
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
import json
import shutil
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pathlib import Path
from dataflows import Dataflows, Dataset, DataSpace, ProviderBinding, ProviderConfig
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions
from strategy_runtime import DecisionFeedback, SignalHistoryMode, StrategyRuntime, canonical_sha256

from paper_trading_engine.account_data_preparer import AccountDataPreparer
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.srt_advice_client import SrtAdviceClient




def _flows(tmp_path, *, publication=None, adjustment_factor=1.) -> Dataflows:
    # Aug 31 / Sep 1 / Sep 2 satisfy the real depth-three input; the remaining
    # sessions cover cross-date preparation. Listing predates the source window
    # so a missing history session cannot be excused by an IPO boundary.
    dates = pd.bdate_range(end="2026-09-04", periods=5)
    bars = pd.DataFrame(
        {
            "Date": dates,
            "Open": 6.0,
            "High": 6.1,
            "Low": 5.9,
            "Close": 6.0,
            "Volume": 1000.0,
            "Amount": 6000.0,
        }
    )

    def market(request):
        frame = bars.loc[
            pd.to_datetime(bars["Date"]).between(request.start, request.end)
        ].copy()
        if request.dataset is Dataset.ETF_OHLCV:
            for field in ("Open", "High", "Low", "Close"):
                frame[field] *= adjustment_factor
            frame["Volume"] /= adjustment_factor
        if publication is not None and request.dataset is Dataset.ETF_UNADJUSTED_DAILY:
            publication["calls"] += 1
            if not publication["complete"]:
                frame = (frame.iloc[:0] if publication.get("empty")
                         else frame.iloc[[0, -1]]).copy()
            publication.setdefault("sessions", []).append(frame["Date"].nunique())
        metadata = {
            "vendor": "test",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
        }
        pro = SimpleNamespace(
            fund_basic=lambda **kwargs: pd.DataFrame({
                "ts_code": [request.symbol], "list_date": ["20240101"],
            }),
            trade_cal=lambda **kwargs: pd.DataFrame({
                "cal_date": pd.date_range(kwargs["start_date"], kwargs["end_date"]).strftime("%Y%m%d"),
                "is_open": (pd.date_range(kwargs["start_date"], kwargs["end_date"]).dayofweek < 5).astype(int),
            }),
        )
        coverage = verify_daily_sessions(pro, request.symbol, frame,
            start=request.start, end=request.end)
        quality = build_quality_evidence(frame, expected_dates=coverage["expected_dates"])
        metadata.update(daily_session_coverage=coverage,
            ohlcv_quality_evidence=bind_quality_frame(quality, frame,
                adjustment=metadata["adjustment"]))
        frame.attrs = {name: metadata[name] for name in
                       ("daily_session_coverage", "ohlcv_quality_evidence")}
        return frame, metadata

    def calendar(request):
        days = pd.date_range(request.start, request.end)
        return pd.DataFrame(
            {"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}
        ), {"vendor": "test"}

    def flow(request):
        return pd.DataFrame({"Date": pd.bdate_range(request.start, request.end), "Flow": 0.8, "TotalShare": 0.8}), {"vendor": "test"}

    return Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("market")),
        providers=ProviderConfig(bindings={
            dataset: ProviderBinding("synthetic", "v1", provider)
            for dataset, provider in {
                Dataset.ETF_SHARE_SIZE: flow,
                Dataset.ETF_OHLCV: market,
                Dataset.ETF_UNADJUSTED_DAILY: market,
                Dataset.TRADING_CALENDAR: calendar,
            }.items()
        }),
    )


def _client(repo_root, tmp_path, account_sessions, *, adjustment_factor=1.):
    return SrtAdviceClient(
        repo_root=repo_root,
        data_dir=tmp_path,
        dataflows=_flows(tmp_path, adjustment_factor=adjustment_factor),
        now=lambda: datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        session_resolver=lambda signal_date: account_sessions.get(signal_date),
    )



def _prepare(client, account_id, signal_date):
    prepared = client.prepare_account_data(
        account_id=account_id, strategy_id="S900", strategy_version="v1",
        symbol="588080.SH", asset="etf", signal_date=signal_date,
    )
    assert prepared is not None
    return prepared


def _verify(client, account_id):
    return client.verify_account_data(
        account_id=account_id, strategy_id="S900", strategy_version="v1",
        symbol="588080.SH", asset="etf",
    )


def _decision(client, prepared):
    return client.get_decision(
        0, 100_000, 100_000, trading_date=date(2026, 9, 3),
        portfolio_revision=0, state_revision=0, strategy_id="S900",
        strategy_version="v1", account_id="s900-v1", symbol="588080.SH",
        asset="etf", prepared=prepared,
    )


def _tree_bytes(root):
    return {path.relative_to(root): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture(scope="module")
def prepared_account_cache():
    return {}


@pytest.fixture
def prepared_account(pte_frozen, tmp_path, frozen_seed_root, prepared_account_cache, monkeypatch):
    """Reuse real immutable inputs, then authenticate a private restored account."""
    if not prepared_account_cache:
        seed = frozen_seed_root / "pte-prepared-account"
        client = _client(pte_frozen[0].root, seed, {date(2026, 9, 2): date(2026, 9, 3)})
        prepared = _prepare(client, "s900-v1", date(2026, 9, 2))
        prepared_account_cache.update(
            root=seed, files=_tree_bytes(seed), identity=prepared.data_identity,
            binding=prepared.input_binding, reference=prepared.data_reference,
        )
    seed = prepared_account_cache
    assert _tree_bytes(seed["root"]) == seed["files"]
    data = tmp_path / "prepared-account"
    shutil.copytree(seed["root"], data)
    client = _client(pte_frozen[0].root, data, {
        date(2026, 9, 2): date(2026, 9, 3), date(2026, 9, 3): date(2026, 9, 4),
    })
    # Restore through the public entry point. It must use the copied, hash-bound
    # inputs rather than silently preparing a new data identity or reading seed paths.
    with monkeypatch.context() as guard:
        guard.setattr(client.dataflows, "prepare", lambda *_a, **_k: pytest.fail(
            "restored account must consume its copied authenticated inputs"))
        prepared = _prepare(client, "s900-v1", date(2026, 9, 2))
    assert prepared.data_identity == seed["identity"]
    assert prepared.input_binding == seed["binding"]
    assert prepared.data_reference == seed["reference"]
    assert client.dataflows.binding.base_dir == data.resolve()
    yield client, prepared
    assert _tree_bytes(seed["root"]) == seed["files"]


def test_pte_prepares_then_uses_one_account_strategy_instance(pte_frozen, tmp_path, monkeypatch):
    client = _client(pte_frozen[0].root, tmp_path, {date(2026, 9, 2): date(2026, 9, 3)}, adjustment_factor=.3)
    prepared = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )
    assert prepared is not None

    monkeypatch.setattr(client.dataflows, "prepare", lambda *_a, **_k: pytest.fail(
        "decision must not prepare new inputs"))

    continuous_original_plan = prepared.instance.plan_at

    def continuous_plan(**kwargs):
        assert kwargs["history_mode"] is SignalHistoryMode.CONTINUOUS
        return continuous_original_plan(**kwargs)

    monkeypatch.setattr(prepared.instance, "plan_at", continuous_plan)

    decision = client.get_decision(
        0,
        100_000,
        100_000,
        trading_date=date(2026, 9, 3),
        portfolio_revision=0,
        state_revision=0,
        strategy_id="S900",
        strategy_version="v1",
        account_id="s900-v1",
        symbol="588080.SH",
        asset="etf",
        prepared=prepared,
    )
    assert client.prepared_through("s900-v1", "S900", "v1") == date(2026, 9, 2)
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert decision.signal_date == date(2026, 9, 2)
    assert decision.valid_session == date(2026, 9, 3)
    assert decision.runtime_sha256 == prepared.strategy.runtime_sha256
    assert decision.strategy_output is not None
    assert decision.signal_reference_price == pytest.approx(1.8)
    assert decision.execution_reference_price == 6.
    assert decision.orders and all(order.limit_price >= 6. for order in decision.orders)
    assert decision.observation is not None
    assert decision.observation["status"] == "READY"
    assert decision.observation["series"][0]["key"] == "fixture"

    # Restart consumes exactly the same authenticated input binding offline.
    flows = _flows(tmp_path, adjustment_factor=.3)
    monkeypatch.setattr(flows, "prepare", lambda *_a, **_k: pytest.fail(
        "restart must read pinned data"))
    reopened = SrtAdviceClient(repo_root=pte_frozen[0].root, data_dir=tmp_path, dataflows=flows)
    restored = _prepare(reopened, "s900-v1", date(2026, 9, 2))
    assert restored.data_identity == prepared.data_identity
    assert restored.data_reference == prepared.data_reference
    assert restored.input_binding == prepared.input_binding
    assert _verify(reopened, "s900-v1") == prepared.result

    # Inject a unit-contract fault at the genuine SRT output boundary.
    from strategy_runtime import ExecutionPriceBasis, ExecutionPricing
    from paper_trading_engine.srt_advice_client import AdviceClientError
    original_plan = prepared.instance.plan_at
    def wrong_units(**kwargs):
        plan = original_plan(**kwargs)
        return replace(plan, references=replace(plan.references,
            pricing=ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2026, 9, 1), .3),
            execution_basis="NORMALIZED_HFQ_CLOSE"))
    monkeypatch.setattr(prepared.instance, "plan_at", wrong_units)
    with pytest.raises(AdviceClientError, match="unadjusted prices and real shares"):
        _decision(client, prepared)


def test_prepared_data_is_isolated_by_account(pte_frozen, tmp_path):
    client = _client(pte_frozen[0].root, tmp_path, {
        date(2026, 9, 2): date(2026, 9, 3), date(2026, 9, 3): date(2026, 9, 4),
    })
    first = _prepare(client, "s900-v1", date(2026, 9, 2))
    second = _prepare(client, "s900-v1-alt", date(2026, 9, 2))
    assert first.data_reference == second.data_reference
    advanced = _prepare(client, "s900-v1", date(2026, 9, 3))
    assert advanced.available_through == date(2026, 9, 3)
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 4)
    assert client.prepared_through("s900-v1-alt", "S900", "v1") == date(2026, 9, 2)
    assert client.tradable_date("s900-v1-alt", "S900", "v1") == date(2026, 9, 3)
    assert _verify(client, "s900-v1-alt") == second.result
    assert first.strategy == advanced.strategy
    assert first.data_identity != advanced.data_identity
    assert first.input_binding != advanced.input_binding
    assert first.instance.prepare_data(binding=first.input_binding) == first.result
    assert _verify(client, "s900-v1") == advanced.result
    assert client.prepared_through("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 4)


@pytest.mark.parametrize(
    "change",
    ["unversioned-storage", "missing-runtime", "changed-runtime", "changed-symbol"],
)
def test_account_replaces_incompatible_space_without_mutating_old_data(
    prepared_account, change,
):
    client, first = prepared_account
    client.now = lambda: datetime(2026, 9, 3, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account_root = client.data_dir / "accounts/s900-v1"
    current = account_root / "current.json"
    index = json.loads(current.read_text(encoding="utf-8"))
    entry = index["releases"]["S900-v1"]
    old_space = account_root / entry["data_dir"]
    old_files = {path.relative_to(old_space): path.read_bytes()
                 for path in old_space.rglob("*") if path.is_file()}
    # Explicit persisted-input faults, followed by real public preparation.
    index.pop("index_sha256")
    if change == "unversioned-storage":
        index.pop("prepared_storage_revision")
    elif change == "missing-runtime":
        entry.pop("runtime_sha256")
    elif change == "changed-runtime":
        entry["runtime_sha256"] = "0" * 64
    elif change == "changed-symbol":
        index["symbol"] = "510500.SH"
    index["index_sha256"] = canonical_sha256(index)
    current.write_text(json.dumps(index), encoding="utf-8")
    second = _prepare(client, "s900-v1", date(2026, 9, 3))
    assert {path.relative_to(old_space): path.read_bytes()
            for path in old_space.rglob("*") if path.is_file()} == old_files
    assert first.instance.prepare_data(binding=first.input_binding) == first.result
    assert second.strategy == first.strategy
    assert second.strategy.symbol == "588080.SH"
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 4)
    assert _verify(client, "s900-v1") == second.result


def test_failed_preparation_does_not_switch_the_account_space(pte_frozen, tmp_path):
    from paper_trading_engine.srt_advice_client import AdviceClientError

    client = _client(pte_frozen[0].root, tmp_path, {
        date(2026, 9, 2): date(2026, 9, 3), date(2026, 9, 3): date(2026, 9, 4),
    })
    publication = {"complete": True, "calls": 0, "empty": True}
    client.dataflows = _flows(tmp_path, publication=publication)
    original = _prepare(client, "s900-v1", date(2026, 9, 2))
    current = tmp_path / "accounts/s900-v1/current.json"
    published = current.read_bytes()
    publication["complete"] = False
    with pytest.raises(AdviceClientError, match="preparation failed"):
        _prepare(client, "s900-v1", date(2026, 9, 3))
    assert current.read_bytes() == published
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert _verify(client, "s900-v1") == original.result


def test_default_session_resolver_drives_public_preparation_contract(pte_frozen, tmp_path):
    client = SrtAdviceClient(repo_root=pte_frozen[0].root, data_dir=tmp_path, dataflows=_flows(tmp_path))
    prepared = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )

    assert prepared is not None
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert client.prepare_account_data(
        account_id="closed-session",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 5),
    ) is None
    assert not (tmp_path / "accounts/closed-session/current.json").exists()
    assert client.latest_completed_signal_date(
        datetime(2026, 9, 5, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == date(2026, 9, 4)
    assert client.latest_completed_signal_date(
        datetime(2026, 9, 7, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == date(2026, 9, 7)


def test_scheduler_prepares_current_account_data_then_runs_decision(new_store, pte_frozen,
    tmp_path, monkeypatch,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = new_store(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s900-v1",
        "S900-v1模拟账户",
        "legacy",
        "a" * 64,
        "100000",
        strategy_id="S900",
        strategy_name_snapshot="合成策略",
        strategy_version="v1",
        release_hash=pte_frozen[1].release_hash,
        qualification_snapshot="PAPER_READY",
        selection_data_cutoff=pte_frozen[1].selection_data_cutoff,
        symbol="588080.SH",
        asset_type="etf",
    )
    client = SrtAdviceClient(
        repo_root=pte_frozen[0].root,
        data_dir=data_dir,
        dataflows=_flows(data_dir),
        now=lambda: datetime(2026, 9, 2, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    preparation_calls = []
    original_prepare = client.prepare_account_data

    def record_preparation(**kwargs):
        preparation_calls.append(kwargs)
        return original_prepare(**kwargs)

    monkeypatch.setattr(client, "prepare_account_data", record_preparation)
    accounts = AccountEngine(store, client)

    class Engine:
        def refresh_decision(self, account_id, *, prepared):
            return accounts.refresh_account(account_id, prepared=prepared)

    scheduler = RuntimeScheduler(
        Engine(),
        AccountStrategyCycle(
            accounts, AccountDataPreparer(advice=client), store
        ),
        store,
        preparation_time="20:30",
    )

    finished = Event()
    original_setting = store.set_setting

    def record_setting(key, value):
        original_setting(key, value)
        if key == "last_account_strategy_cycle:s900-v1_success_at":
            finished.set()

    monkeypatch.setattr(store, "set_setting", record_setting)
    scheduler.tick_daily(datetime(2026, 9, 2, 20, 30))
    assert finished.wait(5), store.operation_failures()
    assert store.get_setting("last_data_prepare_date:s900-v1") == "2026-09-02"
    assert store.operation_failures() == []
    assert preparation_calls == [{
        "account_id": "s900-v1", "strategy_id": "S900", "strategy_version": "v1",
        "symbol": "588080.SH", "asset": "etf", "signal_date": date(2026, 9, 2),
    }]
    decisions = store.account_decisions("s900-v1")
    assert len(decisions) == 1
    assert decisions[0]["signal_date"] == "2026-09-02"
    assert decisions[0]["valid_session"] == "2026-09-03"
    restored = client.prepare_account_data(
        account_id="s900-v1", strategy_id="S900", strategy_version="v1",
        symbol="588080.SH", asset="etf", signal_date=date(2026, 9, 2),
    )
    assert decisions[0]["payload"]["prepared_data_reference"] == restored.data_reference
    store.close()


@pytest.fixture
def minimum_depth_frozen(candidate_payload, tmp_path, monkeypatch):
    """Author and actually inspect/freeze/deploy one independent depth-three seed."""
    from czsc_trader.application import inspect_candidate, freeze_candidate, deploy_strategy
    from strategy_manager import PaperTradingApproval, StrategyRegistry
    from strategy_runtime import implementation_sha256
    import test_candidate_runtime_execution as data_support
    from test_research_contract_upgrade import fresh_managed_evaluation
    from test_assessment_delivery import fresh_completed
    from test_candidate_freeze import _build_inspection, approve

    payload, source_root = candidate_payload
    source = source_root / payload["runtime"]["source_files"][0]
    source.write_text(source.read_text(encoding="utf-8").replace(
        "                1,\n                CutoffRule.SIGNAL_SESSION,",
        "                3,\n                CutoffRule.SIGNAL_SESSION,",
    ), encoding="utf-8")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=source_root,
    )
    install = data_support._install_candidate_dataflows

    def with_warmup(patches, flow, daily, **kwargs):
        # Valid evidence contains enough authentic synthetic sessions before the
        # evaluation starts; the later PTE supplier deliberately omits one.
        days = pd.bdate_range(end=pd.Timestamp(daily["dt"].min()) - pd.offsets.BDay(), periods=2)
        prefix = pd.concat([daily.iloc[[0]]] * 2, ignore_index=True)
        prefix["dt"] = days
        flow_prefix = pd.concat([flow.iloc[[0]]] * 2, ignore_index=True)
        flow_prefix["Date"] = days
        return install(patches, pd.concat([flow_prefix, flow], ignore_index=True),
                       pd.concat([prefix, daily], ignore_index=True), **kwargs)

    monkeypatch.setattr(data_support, "_install_candidate_dataflows", with_warmup)
    monkeypatch.setattr("test_research_contract_upgrade._install_candidate_dataflows", with_warmup)
    evaluation = fresh_managed_evaluation.__wrapped__(candidate_payload, tmp_path, monkeypatch)
    context, inspection, source = _build_inspection(fresh_completed.__wrapped__(evaluation))
    report = inspect_candidate(context, inspection)
    assert report.status.value == "PASS", report
    receipt = freeze_candidate(context, approve(context, report, source))
    assert receipt.status.value == "COMMITTED", receipt
    deploy_strategy(context, "S900-v1")
    registry = StrategyRegistry(context.strategy_root)
    version = registry.get_version("S900", "v1")
    registry.approve_paper_trading(PaperTradingApproval(
        "S900", "v1", version.release_hash, "test", "synthetic depth-three approval",
    ))
    return context, version


def test_missing_input_sessions_recovers_then_restart_keeps_successful_binding(
    minimum_depth_frozen, tmp_path,
):
    from paper_trading_engine.srt_advice_client import AdviceClientError

    publication = {"complete": False, "calls": 0}
    flows = _flows(tmp_path, publication=publication)
    moments = iter((
        datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 9, 2, 22, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    ))
    client = SrtAdviceClient(
        repo_root=minimum_depth_frozen[0].root, data_dir=tmp_path / "pte", dataflows=flows,
        now=lambda: next(moments),
        session_resolver=lambda _: date(2026, 9, 3),
    )
    with pytest.raises(AdviceClientError, match="omit expected trading sessions") as failed:
        _prepare(client, "s900-v1", date(2026, 9, 2))
    assert "'missing_dates': ['2026-09-01']" in str(failed.value)
    assert publication["calls"] == 1
    assert publication["sessions"] == [2]
    with pytest.raises(AdviceClientError, match="cannot read prepared-data index"):
        client.prepared_through("s900-v1", "S900", "v1")
    publication["complete"] = True
    prepared = _prepare(client, "s900-v1", date(2026, 9, 2))
    assert publication["calls"] == 2
    assert publication["sessions"] == [2, 3]
    requirement = prepared.input_binding.plan.requests["execution"].coverage
    assert requirement.minimum_sessions == 3
    assert requirement.observations_through == "2026-09-02"
    # The real authenticated frozen release and its successful binding reopen offline.
    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")), providers=ProviderConfig({}))
    reopened = SrtAdviceClient(
        repo_root=minimum_depth_frozen[0].root, data_dir=tmp_path / "pte", dataflows=offline,
    )
    restored = _prepare(reopened, "s900-v1", date(2026, 9, 2))
    assert restored.result == prepared.result
    assert restored.input_binding == prepared.input_binding
    decision = _decision(reopened, restored)
    assert decision.runtime_sha256 == prepared.strategy.runtime_sha256
    assert decision.strategy["release_hash"] == minimum_depth_frozen[1].release_hash
    assert publication["calls"] == 2


def test_pte_observation_failure_is_explicit_and_does_not_change_execution(prepared_account, monkeypatch):
    from dataclasses import replace
    from strategy_runtime import StrategyObservation
    from paper_trading_engine.contracts import AdviceContractError, AdviceDecision

    client, prepared = prepared_account
    result = _decision(client, prepared)
    assert result.observation["status"] == "READY"
    assert StrategyObservation.from_dict(result.observation).plan_identity == result.plan_identity
    original_plan = prepared.instance.plan_at

    def missing_observation_evidence(**kwargs):
        return replace(original_plan(**kwargs), evidence={})

    # Only the observation evidence is removed after actual SRT planning.
    with monkeypatch.context() as faults:
        faults.setattr(prepared.instance, "plan_at", missing_observation_evidence)
        unavailable = _decision(client, prepared)
    assert unavailable.observation["status"] == "UNAVAILABLE"
    assert unavailable.plan_identity == result.plan_identity
    assert unavailable.signal_identity == result.signal_identity
    assert unavailable.orders == result.orders
    assert unavailable.target_quantity == result.target_quantity
    transport = []
    original_parse = AdviceDecision.from_cli_payload

    def capture_payload(value):
        transport.append(value)
        return original_parse(value)

    monkeypatch.setattr(AdviceDecision, "from_cli_payload", capture_payload)
    assert _decision(client, prepared).plan_identity == result.plan_identity
    transport[0]["result"]["observation"]["plan_identity"] = "0" * 64
    with pytest.raises(AdviceContractError, match="another decision"):
        original_parse(transport[0])


def test_pte_transports_equity_mode_and_rejects_mismatched_scope(prepared_account, monkeypatch):
    """The SRT boundary supplies a typed plan; PTE must retain its capital contract."""
    from copy import deepcopy
    from paper_trading_engine.contracts import AdviceContractError, AdviceDecision
    from strategy_runtime.contracts import plan_identity_for, signal_identity_for

    client, prepared = prepared_account
    original_plan = prepared.instance.plan_at

    def equity_plan(**kwargs):
        plan = original_plan(**kwargs)
        signal_identity = signal_identity_for(
            strategy=plan.strategy, signal_date=plan.signal_date, target_position=.5,
            input_identities=plan.input_identities, price_identities=plan.price_identities,
        )
        plan_identity = plan_identity_for(
            signal_identity=signal_identity, actual_quantity=plan.actual_quantity,
            target_quantity=plan.target_quantity, cycle_target_quantity=plan.cycle_target_quantity,
            plan_mode=plan.plan_mode, capital_mode="target_equity_fraction",
            allocation_fraction=plan.allocation_fraction, orders=plan.orders, legs=plan.legs,
        )
        return replace(plan, capital_mode="target_equity_fraction", target_position=.5,
                       signal_identity=signal_identity, plan_identity=plan_identity)

    transport = []
    original_parse = AdviceDecision.from_cli_payload

    def capture_payload(value):
        transport.append(deepcopy(value))
        return original_parse(value)

    monkeypatch.setattr(prepared.instance, "plan_at", equity_plan)
    monkeypatch.setattr(AdviceDecision, "from_cli_payload", capture_payload)
    decision = _decision(client, prepared)
    assert decision.capital_mode == "target_equity_fraction"
    assert decision.allocation_fraction == 1.
    assert decision.observation["target_position"] == .5
    assert transport[0]["result"]["capital_rule"] == {
        "mode": "target_equity_fraction", "target_scope": "decision", "allocation_fraction": 1.,
    }
    for mode, scope, allocation, message in (
        ("target_equity_fraction", "entry_cycle", 1., "scope"),
        ("full_available_cash", "decision", 1., "scope"),
        ("target_equity_fraction", "decision", .5, "allocation fraction one"),
    ):
        bad = deepcopy(transport[0])
        bad["result"]["capital_rule"] = {
            "mode": mode, "target_scope": scope, "allocation_fraction": allocation,
        }
        with pytest.raises(AdviceContractError, match=message):
            original_parse(bad)


@pytest.fixture
def cycle_transport(prepared_account, monkeypatch):
    """The real PTE adapter consumes a typed signal-allocation execution plan."""
    from copy import deepcopy
    from decimal import Decimal
    from paper_trading_engine.contracts import AdviceDecision
    from strategy_runtime import CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus
    from strategy_runtime.contracts import plan_identity_for, signal_identity_for

    client, prepared = prepared_account
    original_plan = prepared.instance.plan_at
    captured = []
    parser = AdviceDecision.from_cli_payload

    def cycle_plan(**kwargs):
        original = original_plan(**kwargs)
        target = CycleTarget(True, Decimal("0.5"))
        signal = signal_identity_for(
            strategy=original.strategy, signal_date=original.signal_date, target_position=1.,
            input_identities=original.input_identities, price_identities=original.price_identities, cycle_target=target,
        )
        quantity = original.target_quantity // 200 * 100
        order = replace(original.orders[0], quantity=quantity)
        state = EntryCycleState(
            canonical_sha256({"account": "s900-v1", "opening_signal": signal}), signal,
            Decimal("0.5"), original.available_cash / 2, quantity, Decimal(0), EntryCyclePhase.ACTIVE,
        )
        cycle_fields = dict(cycle_target=target, entry_cycle_before=None, entry_cycle_after=state,
                            cycle_status=EntryCyclePlanStatus.OPEN)
        identity = plan_identity_for(
            signal_identity=signal, actual_quantity=0, target_quantity=quantity, cycle_target_quantity=quantity,
            plan_mode="NONE", capital_mode="signal_cash_fraction", allocation_fraction=Decimal("0.5"),
            orders=(order,), legs=(), **cycle_fields,
            available_cash=original.available_cash, fee_rate=original.fee_rate,
        )
        cost = order.limit_price * quantity * (1 + original.fee_rate)
        return replace(
            original, signal_identity=signal, plan_identity=identity,
            target_quantity=quantity, cycle_target_quantity=quantity, target_position=1.,
            capital_mode="signal_cash_fraction", allocation_fraction=Decimal("0.5"),
            orders=(order,), estimated_order_cost=cost, unallocated_cash=original.available_cash - cost,
            evidence={}, **cycle_fields,
        )

    def capture(value):
        captured.append(deepcopy(value))
        return parser(value)

    monkeypatch.setattr(prepared.instance, "plan_at", cycle_plan)
    monkeypatch.setattr(AdviceDecision, "from_cli_payload", capture)
    value = _decision(client, prepared)
    return value, captured[0], parser


def test_pte_v6_transports_typed_cycle_and_preserves_legacy_serialization(cycle_transport):
    from decimal import Decimal
    from pte_support import decision

    value, payload, _ = cycle_transport
    assert value.contract_version == "advice.v6"
    assert value.entry_cycle_before is None
    assert value.entry_cycle_after.cash_budget == Decimal("50000")
    assert value.cycle_target.entry_fraction == Decimal("0.5")
    assert value.to_store_payload()["entry_cycle_after"] == payload["result"]["entry_cycle_after"]
    assert "entry_cycle_before" in value.to_store_payload()
    assert "entry_cycle_before" not in decision().to_store_payload()


@pytest.mark.parametrize("mutation", ["budget", "order", "signal_fraction", "missing_state", "old_version", "fee", "cash"])
def test_pte_v6_rejects_identity_or_cycle_transport_tampering(cycle_transport, mutation):
    from paper_trading_engine.contracts import AdviceContractError

    _, payload, parser = cycle_transport
    value = payload["result"]
    if mutation == "budget":
        value["entry_cycle_after"]["cash_budget"] = "75000"
    elif mutation == "order":
        value["orders"][0]["limit_price"] += .001
        value["order"]["limit_price"] += .001
    elif mutation == "signal_fraction":
        value["cycle_target"]["entry_fraction"] = "0.75"
    elif mutation == "missing_state":
        value.pop("entry_cycle_before")
    elif mutation == "fee":
        value["fee_rate"] /= 2
    elif mutation == "cash":
        value["available_cash"] += 1
    else:
        value["contract_version"] = "advice.v4"
    with pytest.raises(AdviceContractError):
        parser(payload)


@pytest.mark.parametrize('feedback', list(DecisionFeedback))
def test_contract_two_feedback_gates_binding_and_prepared_decisions(
    prepared_account, monkeypatch, feedback,
):
    from paper_trading_engine.errors import AdviceClientError

    client, prepared = prepared_account
    release = client._load_release('S900', 'v1')
    original_describe = StrategyRuntime.describe
    authenticated = original_describe(StrategyRuntime(client.repo_root / 'strategies'), release,
                                      symbol='588080.SH')
    assert authenticated.implementation.contract_version == 2
    assert authenticated.decision_feedback is DecisionFeedback.MARKET_INTENT
    # Inject an unsupported typed declaration after real source authentication.
    # Both public PTE entry points must enforce their own business boundary.
    definition = replace(authenticated, decision_feedback=feedback)

    def describe(runtime, *args, **kwargs):
        assert original_describe(runtime, *args, **kwargs) == authenticated
        return definition

    monkeypatch.setattr(StrategyRuntime, 'describe', describe)
    monkeypatch.setattr(prepared.instance, '_algorithm', replace(
        prepared.instance._algorithm, definition=definition,
    ))
    kwargs = {'strategy_id': 'S900', 'strategy_version': 'v1',
              'symbol': '588080.SH', 'asset': 'etf'}
    if feedback is DecisionFeedback.MARKET_INTENT:
        binding = client.validate_account_binding(**kwargs)
        result = _decision(client, prepared)
        assert binding.release_hash == release.release_hash
        assert result.strategy['release_hash'] == release.release_hash
        assert result.orders and result.runtime_sha256 == definition.runtime_sha256
    else:
        with pytest.raises(AdviceClientError, match=f'MARKET_INTENT.*{feedback.value}'):
            client.validate_account_binding(**kwargs)
        with pytest.raises(AdviceClientError, match=f'MARKET_INTENT.*{feedback.value}'):
            _decision(client, prepared)


@pytest.mark.parametrize('feedback', list(DecisionFeedback))
def test_legacy_contract_feedback_cannot_bypass_pte_boundary(
    prepared_account, monkeypatch, feedback,
):
    from paper_trading_engine.errors import AdviceClientError

    client, prepared = prepared_account
    authenticated = prepared.instance.definition
    definition = replace(authenticated,
                         implementation=replace(authenticated.implementation, contract_version=1),
                         decision_feedback=feedback)
    original_describe = StrategyRuntime.describe

    def describe(runtime, *args, **kwargs):
        assert original_describe(runtime, *args, **kwargs) == authenticated
        return definition

    monkeypatch.setattr(StrategyRuntime, 'describe', describe)
    monkeypatch.setattr(prepared.instance, '_algorithm', replace(
        prepared.instance._algorithm, definition=definition,
    ))
    kwargs = {'strategy_id': 'S900', 'strategy_version': 'v1',
              'symbol': '588080.SH', 'asset': 'etf'}
    if feedback in {DecisionFeedback.UNDECLARED, DecisionFeedback.MARKET_INTENT}:
        # The transition allowance preserves legacy binding admission. This
        # fixture's actual kernel remains V2; it does not represent a V1 replay.
        binding = client.validate_account_binding(**kwargs)
        assert binding.release_hash == prepared.strategy.release_hash
    else:
        with pytest.raises(AdviceClientError, match=f'MARKET_INTENT.*{feedback.value}'):
            client.validate_account_binding(**kwargs)
        with pytest.raises(AdviceClientError, match=f'MARKET_INTENT.*{feedback.value}'):
            _decision(client, prepared)
