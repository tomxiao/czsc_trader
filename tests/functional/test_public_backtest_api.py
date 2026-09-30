from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyCandidate

from czsc_trader.application import BacktestRequestV2, RepositoryContext, run_backtest
from czsc_trader.application.errors import ExecutionError


def test_candidate_and_version_use_one_backtest_dispatch(
    functional_repo,
    candidate_payload,
    monkeypatch,
):
    context = RepositoryContext.discover(functional_repo)
    version = StrategyRegistry(context.strategy_root).get_version("S001", "v1")
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C001", payload, source)
    request = BacktestRequestV2("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000)
    observed = []

    def replay(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(
            metrics={},
            output_dir=context.outputs_root / "test",
            manifest={"audit": {"status": "PASS"}, "application": {"runtime_engine": "srt"}},
        )

    monkeypatch.setattr("czsc_trader.application.backtest_service.run_backtest_v2", replay)
    for strategy in (candidate, version):
        assert run_backtest(context, strategy, request).status == "PASS"
    assert [item["snapshot"].identity.kind for item in observed] == ["CANDIDATE", "REGISTERED"]
    assert all(item["request"] is request for item in observed)
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
            ]
        )
        != 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "backtest_strategy_invalid"
