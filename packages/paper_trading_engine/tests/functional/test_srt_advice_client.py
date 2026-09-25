from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
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
from paper_trading_engine.store import PaperStore


ROOT = Path(__file__).resolve().parents[4]


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

    return Dataflows(
        {
            Dataset.ETF_OHLCV.value: market,
            Dataset.ETF_UNADJUSTED_DAILY.value: market,
            Dataset.TRADING_CALENDAR.value: calendar,
        }
    )


def _client(tmp_path, account_sessions):
    return SrtAdviceClient(
        repo_root=ROOT,
        data_dir=tmp_path,
        now=lambda: datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        session_resolver=lambda signal_date: account_sessions.get(signal_date),
    )


def test_pte_prepares_then_uses_one_account_strategy_instance(tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
    prepared = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
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
        strategy_id="S002",
        strategy_version="v1",
        account_id="s002-v1",
        symbol="510500.SH",
        asset="etf",
        prepared=prepared,
    )
    assert client.prepared_through("s002-v1", "S002", "v1") == date(2026, 9, 2)
    assert client.tradable_date("s002-v1", "S002", "v1") == date(2026, 9, 3)
    assert decision.signal_date == date(2026, 9, 2)
    assert decision.valid_session == date(2026, 9, 3)
    assert decision.strategy_output is not None
    assert decision.observation is not None
    assert decision.observation["status"] == "READY"
    assert decision.observation["series"][0]["key"] == "event_state"


def test_prepared_data_is_isolated_by_account(tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(tmp_path, {date(2026, 9, 2): date(2026, 9, 3)})
    for account_id, strategy_id, symbol in (
        ("s002-v1", "S002", "510500.SH"),
        ("s002-v1-alt", "S002", "510500.SH"),
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
    assert (tmp_path / "accounts/s002-v1/current.json").is_file()
    assert (tmp_path / "accounts/s002-v1-alt/current.json").is_file()
    assert [path.name for path in (tmp_path / "accounts/s002-v1/spaces").iterdir()] == [
        "s002-v1_20260902T220000000000"
    ]
    assert [
        path.name for path in (tmp_path / "accounts/s002-v1-alt/spaces").iterdir()
    ] == ["s002-v1-alt_20260902T220000000000"]
    assert client.tradable_date("s002-v1", "S002", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s002-v1-alt", "S002", "v1") == date(2026, 9, 3)


def test_account_reuses_its_strategy_space_across_trading_dates(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(
        tmp_path,
        {
            date(2026, 9, 2): date(2026, 9, 3),
            date(2026, 9, 3): date(2026, 9, 4),
        },
    )

    first = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )
    second = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 3),
    )

    assert first is not None
    assert second is not None
    spaces = tuple((tmp_path / "accounts/s002-v1/spaces").iterdir())
    assert [path.name for path in spaces] == ["s002-v1_20260902T220000000000"]
    assert sorted(path.name for path in (spaces[0] / "preparations").iterdir()) == [
        "20260903_20260903",
        "20260904_20260904",
    ]
    assert client.prepared_through("s002-v1", "S002", "v1") == date(2026, 9, 3)
    assert client.tradable_date("s002-v1", "S002", "v1") == date(2026, 9, 4)


@pytest.mark.parametrize(
    "change",
    ["unversioned-storage", "missing-runtime", "changed-runtime", "changed-symbol"],
)
def test_account_replaces_incompatible_space_without_mutating_old_data(
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
        repo_root=ROOT,
        data_dir=tmp_path,
        now=lambda: next(moments),
        session_resolver=lambda signal_date: signal_date.replace(day=signal_date.day + 1),
    )
    first = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )
    assert first is not None
    account_root = tmp_path / "accounts/s002-v1"
    old_space = next((account_root / "spaces").iterdir())
    old_manifest = next(old_space.glob("preparations/*/prepared-data.json"))
    old_manifest_bytes = old_manifest.read_bytes()
    current = account_root / "current.json"
    index = json.loads(current.read_text(encoding="utf-8"))
    entry = index["releases"]["S002-v1"]
    assert entry["runtime_sha256"] == first.strategy.runtime_sha256
    index.pop("index_sha256")
    symbol = "510500.SH"
    if change == "unversioned-storage":
        index.pop("prepared_storage_revision")
    elif change == "missing-runtime":
        entry.pop("runtime_sha256")
    elif change == "changed-runtime":
        entry["runtime_sha256"] = "0" * 64
    elif change == "changed-symbol":
        symbol = "588080.SH"
    index["index_sha256"] = canonical_sha256(index)
    current.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    second = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol=symbol,
        asset="etf",
        signal_date=date(2026, 9, 3),
    )
    assert second is not None
    assert sorted(path.name for path in (account_root / "spaces").iterdir()) == [
        "s002-v1_20260902T220000000000",
        "s002-v1_20260903T220000000000",
    ]
    assert old_manifest.read_bytes() == old_manifest_bytes
    published = json.loads(current.read_text(encoding="utf-8"))
    assert published["prepared_storage_revision"] == 1
    assert published["symbol"] == second.strategy.symbol == symbol
    assert published["releases"]["S002-v1"]["release_hash"] == first.strategy.release_hash
    assert published["releases"]["S002-v1"]["runtime_sha256"] == (
        second.strategy.runtime_sha256
    )
    assert published["trading_date"] == "2026-09-04"


def test_failed_preparation_does_not_switch_the_account_space(tmp_path, monkeypatch):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = _client(
        tmp_path,
        {
            date(2026, 9, 2): date(2026, 9, 3),
            date(2026, 9, 3): date(2026, 9, 4),
        },
    )
    assert client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    ) is not None
    current = tmp_path / "accounts/s002-v1/current.json"
    published = current.read_bytes()
    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows",
        lambda: (_ for _ in ()).throw(AssertionError("preparation failed")),
    )

    with pytest.raises(AssertionError, match="preparation failed"):
        client.prepare_account_data(
            account_id="s002-v1",
            strategy_id="S002",
            strategy_version="v1",
            symbol="510500.SH",
            asset="etf",
            signal_date=date(2026, 9, 3),
        )

    assert current.read_bytes() == published
    assert client.tradable_date("s002-v1", "S002", "v1") == date(2026, 9, 3)


def test_closed_day_does_not_prepare_or_publish_account_data(tmp_path):
    client = _client(tmp_path, {date(2026, 9, 5): None})
    result = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 5),
    )
    assert result is None
    assert not (tmp_path / "accounts/s002-v1/current.json").exists()


def test_default_session_resolver_drives_public_preparation_contract(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "paper_trading_engine.srt_advice_client.Dataflows", lambda: _flows()
    )
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    client = SrtAdviceClient(repo_root=ROOT, data_dir=tmp_path)
    prepared = client.prepare_account_data(
        account_id="s002-v1",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 2),
    )

    assert prepared is not None
    assert client.tradable_date("s002-v1", "S002", "v1") == date(2026, 9, 3)
    assert client.prepare_account_data(
        account_id="closed-session",
        strategy_id="S002",
        strategy_version="v1",
        symbol="510500.SH",
        asset="etf",
        signal_date=date(2026, 9, 5),
    ) is None
    assert client.latest_completed_signal_date(
        datetime(2026, 9, 5, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == date(2026, 9, 4)
    assert client.latest_completed_signal_date(
        datetime(2026, 9, 7, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == date(2026, 9, 7)


def test_account_binding_validation_loads_frozen_s003_and_s007_resources(tmp_path):
    client = SrtAdviceClient(repo_root=ROOT, data_dir=tmp_path)

    s003 = client.validate_account_binding(
        strategy_id="S003", strategy_version="v1", symbol="510500.SH", asset="etf",
    )
    s007 = client.validate_account_binding(
        strategy_id="S007", strategy_version="v1", symbol="588080.SH", asset="etf",
    )

    assert s003["release_id"] == "S003-v1"
    assert s007["release_id"] == "S007-v1"


def test_scheduler_prepares_current_account_data_then_runs_decision(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    monkeypatch.setattr(
        "paper_trading_engine.srt_advice_client.Dataflows", lambda: _flows()
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = PaperStore(tmp_path / "runtime.db")
    store.create_virtual_account(
        "s002-v1",
        "S002-v1模拟账户",
        "legacy",
        "a" * 64,
        "100000",
        strategy_id="S002",
        strategy_name_snapshot="三连跌五日策略",
        strategy_version="v1",
        release_hash="67326ee14e0b67b3cbebb6ba7fd3d10e6fc053002d2a5f1323fe3489a2f84ee9",
        qualification_snapshot="PAPER_READY",
        selection_data_cutoff="2026-09-08",
        symbol="510500.SH",
        asset_type="etf",
    )
    client = SrtAdviceClient(
        repo_root=ROOT,
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

    assert (data_dir / "accounts/s002-v1/current.json").is_file()
    assert store.get_setting("last_data_prepare_date:s002-v1") == "2026-09-02"
    assert store.operation_failures() == []
    decisions = store.account_decisions("s002-v1")
    assert len(decisions) == 1
    assert decisions[0]["signal_date"] == "2026-09-02"
    assert decisions[0]["valid_session"] == "2026-09-03"
    store.close()
