from __future__ import annotations

from datetime import date, datetime
from dataclasses import replace
from types import SimpleNamespace
import shutil
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pathlib import Path
from dataflows import Dataflows, Dataset, DataSpace, ProviderBinding, ProviderConfig
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions

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


@pytest.fixture
def prepared_account(pte_frozen, tmp_path):
    """One private real preparation for the sole capital-contract consumer.

    Restart/pinned restoration has a dedicated missing-session recovery case;
    this fixture does not copy and restore a seed that has no other consumers.
    """
    data = tmp_path / "prepared-account"
    client = _client(pte_frozen[0].root, data, {
        date(2026, 9, 2): date(2026, 9, 3),
    })
    prepared = _prepare(client, "s900-v1", date(2026, 9, 2))
    assert client.dataflows.binding.base_dir == data.resolve()
    return client, prepared


# Independent risk: PTE03; responsibility-level assertions.
def test_PTE03_C01_prepared_data_is_isolated_by_account(pte_frozen, tmp_path):
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


# Independent risk: PTE03; responsibility-level assertions.
def test_PTE03_C02_failed_preparation_does_not_switch_the_account_space(pte_frozen, tmp_path):
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


@pytest.fixture
def fresh_minimum_depth_frozen(candidate_payload, tmp_path, monkeypatch):
    """Explicit regeneration path for the real synthetic depth-three package."""
    from czsc_trader.application import inspect_candidate, freeze_candidate, deploy_strategy
    from strategy_manager import PaperTradingApproval, StrategyRegistry
    from strategy_runtime import implementation_sha256
    import test_candidate_runtime_execution as data_support
    from managed_evaluation_support import fresh_managed_evaluation
    from assessment_delivery_support import fresh_completed
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
    monkeypatch.setattr("managed_evaluation_support._install_candidate_dataflows", with_warmup)
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


@pytest.fixture
def minimum_depth_frozen(tmp_path):
    """The consumer tests missing/repaired inputs, not the upstream freeze flow."""
    from czsc_trader.application import RepositoryContext
    from strategy_manager import StrategyRegistry

    repository = tmp_path / 'depth-three-repository'
    (repository / 'src/czsc_trader').mkdir(parents=True)
    (repository / 'pyproject.toml').write_text('', encoding='utf-8')
    seed = Path(__file__).resolve().parents[4] / 'tests/fixtures/published/depth-three'
    shutil.copytree(seed, repository / 'strategies')
    context = RepositoryContext.discover(repository)
    return context, StrategyRegistry(context.strategy_root).get_version('S900', 'v1')


# Independent risk: PTE03; responsibility-level assertions.
def test_PTE03_C03_missing_input_sessions_recovers_then_restart_keeps_successful_binding(
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


# Independent risk: PTE01; responsibility-level assertions.


@pytest.fixture
def cycle_transport(prepared_account, monkeypatch):
    """The real PTE adapter consumes a typed signal-allocation execution plan."""
    from copy import deepcopy
    from decimal import Decimal
    from paper_trading_engine.contracts import AdviceDecision
    from strategy_runtime import CycleTarget
    from strategy_runtime.contracts import signal_identity_for

    client, prepared = prepared_account
    original_plan = prepared.instance.propose_at
    captured = []
    parser = AdviceDecision.from_cli_payload

    def cycle_plan(**kwargs):
        proposal = original_plan(**kwargs)
        target = CycleTarget(True, Decimal("0.5"))
        signal = replace(proposal.signal, target_position=1., cycle_target=target, evidence={})
        identity = signal_identity_for(strategy=proposal.strategy, signal_date=proposal.signal_date,
            target_position=1., input_identities=proposal.input_identities,
            price_identities=proposal.price_identities, cycle_target=target)
        settings = dict(proposal.execution_policy.settings)
        settings["capital"] = {**dict(settings["capital"]), "mode": "signal_cash_fraction", "target_scope": "entry_cycle"}
        settings["capital"].pop("allocation_fraction", None)
        return replace(proposal, signal=signal, signal_identity=identity,
            execution_policy=replace(proposal.execution_policy, settings=settings))

    def capture(value):
        captured.append(deepcopy(value))
        return parser(value)

    monkeypatch.setattr(prepared.instance, "propose_at", cycle_plan)
    monkeypatch.setattr(AdviceDecision, "from_cli_payload", capture)
    value = _decision(client, prepared)
    return value, captured[0], parser
