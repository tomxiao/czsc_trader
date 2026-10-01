from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyCandidate

from czsc_trader.application import BacktestRequestV2, RepositoryContext, run_backtest
from czsc_trader.application.errors import ExecutionError


@pytest.mark.parametrize("lot_size", [None, True, False, 1.0, 100.5, "100", 0, -1])
def test_backtest_lot_size_rejects_invalid_values(lot_size):
    with pytest.raises((TypeError, ValueError), match="lot_size"):
        BacktestRequestV2("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, lot_size)


def test_backtest_requires_explicit_lot_size():
    from czsc_trader.cli.main import build_parser
    from czsc_trader.application.errors import UsageError

    with pytest.raises(TypeError, match="lot_size"):
        BacktestRequestV2("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000)
    args = [
        "backtest", "run", "--strategy", "S001", "--strategy-version", "v1",
        "--symbol", "588080.SH", "--asset", "etf", "--start", "2026-09-14",
        "--end", "2026-09-21", "--init-cash", "100000",
    ]
    with pytest.raises(UsageError, match="lot-size"):
        build_parser().parse_args(args)
    assert build_parser().parse_args([*args, "--lot-size", "100"]).lot_size == 100
    for invalid in ("0", "-1", "1.5", "True"):
        with pytest.raises(UsageError, match="positive integer"):
            build_parser().parse_args([*args, "--lot-size", invalid])


@pytest.mark.parametrize("policy_type,settings", [
    ("FROZEN_RULE", {"instrument": {"lot_size": 100}}),
    ("INTRADAY_OVERLAY", {"lot_size": 100}),
])
def test_lot_size_conflict_fails_before_data_access(tmp_path, monkeypatch, policy_type, settings):
    from czsc_trader.backtesting.service import run_backtest_v2

    monkeypatch.setattr(
        "czsc_trader.backtesting.service.describe_snapshot_strategy",
        lambda *args, **kwargs: (None, SimpleNamespace(
            execution=SimpleNamespace(policy_type=policy_type, settings=settings),
        )),
    )
    def forbidden(**kwargs):
        pytest.fail("conflicting lot_size must fail before fetching data")
    monkeypatch.setattr("czsc_trader.backtesting.service.prepare_backtest_execution_data", forbidden)
    with pytest.raises(ValueError, match="lot_size differs"):
        run_backtest_v2(
            snapshot=None,
            request=BacktestRequestV2("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, 1),
            srt_data_root=tmp_path, outputs_root=tmp_path, run_date=date(2026, 9, 22),
            repository_root=tmp_path,
        )


def test_candidate_and_version_use_one_backtest_dispatch(
    functional_repo,
    candidate_payload,
    monkeypatch,
):
    context = RepositoryContext.discover(functional_repo)
    version = StrategyRegistry(context.strategy_root).get_version("S001", "v1")
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C001", payload, source)
    request = BacktestRequestV2("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, 100)
    observed = []

    def replay(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(
            metrics={},
            output_dir=context.outputs_root / "test",
            manifest={"audit": {"status": "PASS"}, "application": {"runtime_engine": "srt"}},
        )

    monkeypatch.setattr("czsc_trader.application.backtest_service.run_backtest_v2", replay)
    from dataflows import Dataflows
    flows = Dataflows({})
    for strategy in (candidate, version):
        assert run_backtest(context, strategy, request, dataflows=flows).status == "PASS"
    assert [item["snapshot"].identity.kind for item in observed] == ["CANDIDATE", "REGISTERED"]
    assert all(item["request"] is request for item in observed)
    assert all(item["dataflows"] is flows for item in observed)
    assert observed[0]["snapshot"].runtime_root == source
    assert observed[0]["snapshot"].identity.reference == candidate.reference_id
    assert observed[1]["snapshot"].identity.reference == version.release_id
    assert not (context.strategy_root / "S900").exists()

    with pytest.raises(ExecutionError, match="differs from the frozen registry"):
        run_backtest(context, replace(version, change_summary="changed"), request)
    with pytest.raises(ExecutionError, match="chart override"):
        run_backtest(context, version, request, chart_descriptor={})
    with pytest.raises(TypeError, match="strategy"):
        run_backtest(context, "S001-v1", request)
    with pytest.raises(TypeError, match="request"):
        run_backtest(context, version, {})
    assert len(observed) == 2


def test_unknown_cli_version_is_a_validation_failure(functional_repo, monkeypatch, capsys):
    import json
    from czsc_trader.cli.main import main

    monkeypatch.chdir(functional_repo)
    assert (
        main(
            [
                "backtest",
                "run",
                "--strategy",
                "S999",
                "--strategy-version",
                "v1",
                "--symbol",
                "588080.SH",
                "--asset",
                "etf",
                "--start",
                "2026-09-14",
                "--end",
                "2026-09-21",
                "--init-cash",
                "100000",
                "--lot-size", "100",
            ]
        )
        != 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "backtest_strategy_invalid"
