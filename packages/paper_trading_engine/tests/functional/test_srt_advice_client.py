from __future__ import annotations

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset
from strategy_runtime import canonical_sha256

from paper_trading_engine.account_data_preparer import AccountDataPreparer
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.srt_advice_client import SrtAdviceClient




def _flows() -> Dataflows:
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
        return frame, {
            "vendor": "test",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
        }

    def calendar(request):
        days = pd.date_range(request.start, request.end)
        return pd.DataFrame(
            {"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}
        ), {"vendor": "test"}

    def flow(request):
        return pd.DataFrame({"Date": pd.bdate_range(request.start, request.end), "Flow": 0.8}), {"vendor": "test"}

    return Dataflows(
        {
            "etf.share": flow,
            Dataset.ETF_OHLCV.value: market,
            Dataset.ETF_UNADJUSTED_DAILY.value: market,
            Dataset.TRADING_CALENDAR.value: calendar,
        }
    )


def _client(repo_root, tmp_path, account_sessions):
    return SrtAdviceClient(
        repo_root=repo_root,
        data_dir=tmp_path,
        now=lambda: datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        session_resolver=lambda signal_date: account_sessions.get(signal_date),
    )


def test_pte_prepares_then_uses_one_account_strategy_instance(pte_frozen, tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
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

    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows",
        lambda: (_ for _ in ()).throw(AssertionError("decision must use prepared data")),
    )
    monkeypatch.setattr(
        client,
        "_instance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("decision must not reload the prepared strategy")
        ),
    )
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
    assert decision.strategy_output is not None
    assert decision.observation is not None
    assert decision.observation["status"] == "READY"
    assert decision.observation["series"][0]["key"] == "fixture"


def test_prepared_data_is_isolated_by_account(pte_frozen, tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(pte_frozen[0].root, tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
    for account_id, strategy_id, symbol in (
        ("s900-v1", "S900", "588080.SH"),
        ("s900-v1-alt", "S900", "588080.SH"),
    ):
        prepared = client.prepare_account_data(
            account_id=account_id,
            strategy_id=strategy_id,
            strategy_version="v1",
            symbol=symbol,
            asset="etf",
            signal_date=date(2026, 9, 2),
        )
        assert prepared is not None
    assert (tmp_path / "accounts/s900-v1/current.json").is_file()
    assert (tmp_path / "accounts/s900-v1-alt/current.json").is_file()
    assert [path.name for path in (tmp_path / "accounts/s900-v1/spaces").iterdir()] == [
        "s900-v1_20260902T220000000000"
    ]
    assert [
        path.name for path in (tmp_path / "accounts/s900-v1-alt/spaces").iterdir()
    ] == ["s900-v1-alt_20260902T220000000000"]
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s900-v1-alt", "S900", "v1") == date(2026, 9, 3)


def test_account_reuses_its_strategy_space_across_trading_dates(pte_frozen,
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(pte_frozen[0].root,
        tmp_path,
        {
            date(2026, 9, 2): date(2026, 9, 3),
            date(2026, 9, 3): date(2026, 9, 4),
        },
    )

    first = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )
    second = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 3),
    )

    assert first is not None
    assert second is not None
    spaces = tuple((tmp_path / "accounts/s900-v1/spaces").iterdir())
    assert [path.name for path in spaces] == ["s900-v1_20260902T220000000000"]
    assert sorted(path.name for path in (spaces[0] / "preparations").iterdir()) == [
        "20260903_20260903",
        "20260904_20260904",
    ]
    assert client.prepared_through("s900-v1", "S900", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 4)


@pytest.mark.parametrize(
    "change",
    ["unversioned-storage", "missing-runtime", "changed-runtime", "changed-symbol"],
)
def test_account_replaces_incompatible_space_without_mutating_old_data(pte_frozen,
    tmp_path, monkeypatch, change,
):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    moments = iter(
        (
            datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            datetime(2026, 9, 3, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    )
    client = SrtAdviceClient(
        repo_root=pte_frozen[0].root,
        data_dir=tmp_path,
        now=lambda: next(moments),
        session_resolver=lambda signal_date: signal_date.replace(day=signal_date.day + 1),
    )
    first = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )
    assert first is not None
    account_root = tmp_path / "accounts/s900-v1"
    old_space = next((account_root / "spaces").iterdir())
    old_manifest = next(old_space.glob("preparations/*/prepared-data.json"))
    old_manifest_bytes = old_manifest.read_bytes()
    current = account_root / "current.json"
    index = json.loads(current.read_text(encoding="utf-8"))
    entry = index["releases"]["S900-v1"]
    assert entry["runtime_sha256"] == first.strategy.runtime_sha256
    index.pop("index_sha256")
    symbol = "588080.SH"
    if change == "unversioned-storage":
        index.pop("prepared_storage_revision")
    elif change == "missing-runtime":
        entry.pop("runtime_sha256")
    elif change == "changed-runtime":
        entry["runtime_sha256"] = "0" * 64
    elif change == "changed-symbol":
        index["symbol"] = "510500.SH"
    index["index_sha256"] = canonical_sha256(index)
    current.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    second = client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol=symbol,
        asset="etf",
        signal_date=date(2026, 9, 3),
    )
    assert second is not None
    assert sorted(path.name for path in (account_root / "spaces").iterdir()) == [
        "s900-v1_20260902T220000000000",
        "s900-v1_20260903T220000000000",
    ]
    assert old_manifest.read_bytes() == old_manifest_bytes
    published = json.loads(current.read_text(encoding="utf-8"))
    assert published["prepared_storage_revision"] == 2
    assert published["symbol"] == second.strategy.symbol == symbol
    assert published["releases"]["S900-v1"]["release_hash"] == first.strategy.release_hash
    assert published["releases"]["S900-v1"]["runtime_sha256"] == (
        second.strategy.runtime_sha256
    )
    assert published["trading_date"] == "2026-09-04"


def test_failed_preparation_does_not_switch_the_account_space(pte_frozen, tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(pte_frozen[0].root,
        tmp_path,
        {
            date(2026, 9, 2): date(2026, 9, 3),
            date(2026, 9, 3): date(2026, 9, 4),
        },
    )
    assert client.prepare_account_data(
        account_id="s900-v1",
        strategy_id="S900",
        strategy_version="v1",
        symbol="588080.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    ) is not None
    current = tmp_path / "accounts/s900-v1/current.json"
    published = current.read_bytes()
    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows",
        lambda: (_ for _ in ()).throw(AssertionError("preparation failed")),
    )

    with pytest.raises(AssertionError, match="preparation failed"):
        client.prepare_account_data(
            account_id="s900-v1",
            strategy_id="S900",
            strategy_version="v1",
            symbol="588080.SH",
            asset="etf",
            signal_date=date(2026, 9, 3),
        )

    assert current.read_bytes() == published
    assert client.tradable_date("s900-v1", "S900", "v1") == date(2026, 9, 3)


def test_default_session_resolver_drives_public_preparation_contract(pte_frozen,
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "paper_trading_engine.srt_advice_client.Dataflows", lambda: _flows()
    )
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = SrtAdviceClient(repo_root=pte_frozen[0].root, data_dir=tmp_path)
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
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    monkeypatch.setattr(
        "paper_trading_engine.srt_advice_client.Dataflows", lambda: _flows()
    )
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
        selection_data_cutoff="2026-09-08",
        symbol="588080.SH",
        asset_type="etf",
    )
    client = SrtAdviceClient(
        repo_root=pte_frozen[0].root,
        data_dir=data_dir,
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

    scheduler.tick_daily(datetime(2026, 9, 2, 20, 30))
    for worker in tuple(scheduler._account_workers.values()):
        worker.join(5)

    assert (data_dir / "accounts/s900-v1/current.json").is_file()
    assert store.get_setting("last_data_prepare_date:s900-v1") == "2026-09-02"
    assert store.operation_failures() == []
    decisions = store.account_decisions("s900-v1")
    assert len(decisions) == 1
    assert decisions[0]["signal_date"] == "2026-09-02"
    assert decisions[0]["valid_session"] == "2026-09-03"
    store.close()


def test_pte_observation_failure_is_explicit_and_does_not_change_execution(pte_frozen,tmp_path,monkeypatch):
    from dataclasses import replace
    from strategy_runtime import StrategyObservation
    from paper_trading_engine.srt_advice_client import _decision_from_plan
    from paper_trading_engine.contracts import AdviceContractError, AdviceDecision
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(pte_frozen[0].root,tmp_path,{date(2026,9,2):date(2026,9,3)})
    prepared = client.prepare_account_data(account_id='s900-v1',strategy_id='S900',strategy_version='v1',symbol='588080.SH',asset='etf',signal_date=date(2026,9,2))
    captured = []
    original = __import__('paper_trading_engine.srt_advice_client',fromlist=['_decision_from_plan'])._decision_from_plan
    def capture(plan,identity,definition):
        captured.append((plan,identity,definition))
        return original(plan,identity,definition)
    monkeypatch.setattr('paper_trading_engine.srt_advice_client._decision_from_plan',capture)
    result = client.get_decision(0,100000,100000,trading_date=date(2026,9,3),portfolio_revision=0,state_revision=0,strategy_id='S900',strategy_version='v1',account_id='s900-v1',symbol='588080.SH',asset='etf',prepared=prepared)
    plan,identity,definition = captured[0]
    unavailable = _decision_from_plan(replace(plan,evidence={}),identity,definition)
    assert unavailable.observation['status'] == 'UNAVAILABLE'
    assert unavailable.plan_identity == result.plan_identity
    assert unavailable.orders == result.orders and unavailable.target_quantity == result.target_quantity
    observed = StrategyObservation.from_dict(result.observation)
    assert observed.plan_identity == result.plan_identity
    # Reuse the actual transport payload and reject facts from another decision.
    transport = []
    original_parse = AdviceDecision.from_cli_payload
    def parse(value):
        transport.append(value)
        return original_parse(value)
    monkeypatch.setattr(AdviceDecision,'from_cli_payload',parse)
    _decision_from_plan(plan,identity,definition)
    transport[0]['result']['observation']['plan_identity'] = '0'*64
    with pytest.raises(AdviceContractError, match='another decision'):
        original_parse(transport[0])
