from __future__ import annotations

from datetime import date, datetime
from threading import Event
from types import SimpleNamespace
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pathlib import Path
from dataflows import Dataflows, Dataset, DataSpace, ProviderBinding, ProviderConfig
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions
from strategy_runtime import canonical_sha256

from paper_trading_engine.account_data_preparer import AccountDataPreparer
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.srt_advice_client import SrtAdviceClient




def _flows(tmp_path, *, publication=None) -> Dataflows:
    dates = pd.bdate_range(end="2026-09-04", periods=700)
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
                "ts_code": [request.symbol], "list_date": [dates[0].strftime("%Y%m%d")],
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


def _client(repo_root, tmp_path, account_sessions):
    return SrtAdviceClient(
        repo_root=repo_root,
        data_dir=tmp_path,
        dataflows=_flows(tmp_path),
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


def test_pte_prepares_then_uses_one_account_strategy_instance(pte_frozen, tmp_path, monkeypatch):
    client = _client(pte_frozen[0].root, tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
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
    assert decision.observation is not None
    assert decision.observation["status"] == "READY"
    assert decision.observation["series"][0]["key"] == "fixture"


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


def test_account_reuses_its_strategy_space_across_trading_dates(pte_frozen, tmp_path):
    client = _client(pte_frozen[0].root, tmp_path, {
        date(2026, 9, 2): date(2026, 9, 3), date(2026, 9, 3): date(2026, 9, 4),
    })
    first = _prepare(client, "s900-v1", date(2026, 9, 2))
    second = _prepare(client, "s900-v1", date(2026, 9, 3))
    assert first.strategy == second.strategy
    assert first.data_identity != second.data_identity
    assert first.input_binding != second.input_binding
    assert first.instance.prepare_data(binding=first.input_binding) == first.result
    assert _verify(client, "s900-v1") == second.result
    assert client.prepared_through("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 4)


@pytest.mark.parametrize(
    "change",
    ["unversioned-storage", "missing-runtime", "changed-runtime", "changed-symbol"],
)
def test_account_replaces_incompatible_space_without_mutating_old_data(pte_frozen,
    tmp_path, change,
):
    moments = iter((
        datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 9, 3, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    ))
    client = SrtAdviceClient(
        repo_root=pte_frozen[0].root, data_dir=tmp_path, dataflows=_flows(tmp_path),
        now=lambda: next(moments),
        session_resolver=lambda signal_date: signal_date.replace(day=signal_date.day + 1),
    )
    first = _prepare(client, "s900-v1", date(2026, 9, 2))
    account_root = tmp_path / "accounts/s900-v1"
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


def test_restart_restores_exact_input_binding_without_prepare(pte_frozen, tmp_path, monkeypatch):
    client = _client(pte_frozen[0].root, tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
    kwargs = dict(account_id="s900-v1", strategy_id="S900", strategy_version="v1",
                  symbol="588080.SH", asset="etf", signal_date=date(2026, 9, 2))
    original = client.prepare_account_data(**kwargs)
    flows = _flows(tmp_path)
    monkeypatch.setattr(flows, "prepare", lambda *_a, **_k: pytest.fail("restart must read pinned data"))
    reopened = SrtAdviceClient(repo_root=pte_frozen[0].root, data_dir=tmp_path, dataflows=flows)
    restored = reopened.prepare_account_data(**kwargs)
    assert restored.data_identity == original.data_identity
    assert restored.data_reference == original.data_reference
    assert reopened.verify_account_data(
        account_id="s900-v1", strategy_id="S900", strategy_version="v1",
        symbol="588080.SH", asset="etf",
    ) == original.result


@pytest.fixture
def minimum_depth_frozen(candidate_payload, tmp_path, monkeypatch):
    """Author and actually inspect/freeze/deploy one independent depth-three seed."""
    from czsc_trader.application import inspect_candidate, freeze_candidate, deploy_strategy
    from strategy_manager import PaperTradingApproval, StrategyRegistry
    from strategy_runtime import implementation_sha256
    import test_candidate_runtime_execution as data_support
    from test_research_contract_upgrade import managed_evaluation
    from test_assessment_delivery import completed
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
    evaluation = managed_evaluation.__wrapped__(candidate_payload, tmp_path, monkeypatch)
    context, inspection, source = _build_inspection(completed.__wrapped__(evaluation))
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


def test_pte_observation_failure_is_explicit_and_does_not_change_execution(pte_frozen, tmp_path, monkeypatch):
    from dataclasses import replace
    from strategy_runtime import StrategyObservation
    from paper_trading_engine.contracts import AdviceContractError, AdviceDecision

    client = _client(pte_frozen[0].root, tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
    prepared = _prepare(client, "s900-v1", date(2026, 9, 2))
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
