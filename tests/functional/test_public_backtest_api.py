from dataclasses import replace
from datetime import date

import pytest
from strategy_runtime import StrategyCandidate

from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation


@pytest.mark.parametrize("lot_size", [None, True, False, 1.0, 100.5, "100", 0, -1])
def test_backtest_lot_size_rejects_invalid_values(lot_size):
    with pytest.raises((TypeError, ValueError), match="lot_size"):
        BacktestRequest("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, lot_size)


def test_backtest_requires_explicit_lot_size():
    from czsc_trader.cli.main import build_parser
    from czsc_trader.application.errors import UsageError

    with pytest.raises(TypeError, match="lot_size"):
        BacktestRequest("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000)
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


def test_lot_size_conflict_fails_before_data_access(candidate_payload, minimal_repo, monkeypatch):
    from czsc_trader.application import RepositoryContext
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    context = RepositoryContext.discover(minimal_repo, explicit_root=minimal_repo)
    def forbidden(**kwargs):
        pytest.fail("conflicting lot_size must fail before fetching data")
    monkeypatch.setattr("czsc_trader.backtesting.service._prepare_backtest_execution_data", forbidden)
    with pytest.raises(ExecutionError, match="lot_size differs"):
        run_backtest(context, candidate, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 21), 100000, 1,
        ))
    assert not list(context.outputs_root.glob("*/manifest.json"))


def test_candidate_and_version_publish_authenticated_backtests(current_frozen, candidate_payload, monkeypatch):
    import json
    from pathlib import Path
    from test_backtest import execution_flows
    context, version = current_frozen
    payload, source = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows",
                        lambda repository_root, **kwargs: execution_flows(repository_root))
    results = [run_backtest(context, strategy, request) for strategy in (candidate, version)]
    assert all(result.status == "PASS" for result in results)
    outputs = [Path(result.artifacts["output_dir"]) for result in results]
    assert outputs[0] != outputs[1]
    manifests = [json.loads((output / "manifest.json").read_text(encoding="utf-8")) for output in outputs]
    assert [item["strategy"]["kind"] for item in manifests] == ["CANDIDATE", "REGISTERED"]
    assert [item["strategy"]["reference"] for item in manifests] == [candidate.reference_id, version.release_id]
    assert [item.result["strategy"] for item in results] == [candidate.reference_id, version.release_id]
    assert all(item.result["runtime_engine"] == "srt" and item.result["audit_status"] == "PASS" for item in results)
    assert manifests[0]["strategy"]["source_hash"] == candidate.runtime_identity_sha256
    assert manifests[1]["strategy"]["source_hash"] == version.release_hash
    assert not (context.strategy_root / "S900/versions/v2.json").exists()
    with pytest.raises(ExecutionError, match="differs from the frozen registry"):
        run_backtest(context, replace(version, change_summary="changed"), request)
    with pytest.raises(TypeError, match="dataflows"):
        run_backtest(context, version, request, dataflows=object())
    with pytest.raises(TypeError, match="chart_descriptor"):
        run_backtest(context, version, request, chart_descriptor={})
    with pytest.raises(TypeError, match="strategy"):
        run_backtest(context, "S001-v1", request)
    with pytest.raises(TypeError, match="request"):
        run_backtest(context, version, {})
    assert len(list(context.outputs_root.glob("*/manifest.json"))) == 2


def test_unknown_cli_version_is_a_validation_failure(minimal_repo, monkeypatch, capsys):
    import json
    from czsc_trader.cli.main import main

    monkeypatch.chdir(minimal_repo)
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
