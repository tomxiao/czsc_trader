"""Public CLI and supported business API contracts."""

from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
from czsc_trader.cli.main import main


PUBLIC_API = {
    "open_research_execution",
    "get_research_overview", "diagnose_accounts", "validate_experiment",
    "project_selection_window_facts",
    "FrozenRuntimeMigrationRequest", "PreparedFrozenRuntimeMigration",
    "prepare_frozen_runtime_migration", "validate_frozen_runtime_migration",
    "validate_frozen_observation_upgrade",
    "FrozenRuntimeUpgradeRequest", "PreparedFrozenRuntimeUpgrade", "FrozenRuntimeUpgradeReceipt",
    "prepare_frozen_runtime_upgrade", "apply_frozen_runtime_upgrade",
    "CandidateInspectionRequest", "InspectionReplay",
    "EquityInspectionReplay", "EquityInspectionProtocol",
    "FreezeTarget", "InspectionProtocol", "InspectionDataKind", "InspectionInputError",
    "InspectionPublicationError", "describe_inspection_environment",
    "inspect_candidate", "record_research_decision", "freeze_candidate", "get_freeze_result",
    "assemble_delivery", "validate_delivery", "CandidateRegistrationRequest", "register_candidate",
    "load_candidate", "RepositoryContext", "CommandResult", "CommandError", "ValidationError",
    "create_research_batch", "update_research_intent", "create_research_context", "create_experiment",
    "ResearchBatchRequest", "ResearchIntentUpdate", "ExperimentRequest", "publish_evidence",
    "publish_evidence_many",
    "BacktestRequest", "BacktestEvaluation", "run_backtest", "list_installed_strategies", "strategy_info", "deploy_strategy",
    "validate_release_package",
}


def test_retired_packages_and_services_are_unavailable():
    for name in ("market_rules", "trading_execution_engine", "factor_signal_catalog",
                 "strategy_template_catalog", "czsc_trader.application.catalog_service",
                 "czsc_trader.application.template_service"):
        assert importlib.util.find_spec(name) is None, name


def test_cli_loads_dotenv_without_overriding_process_environment(minimal_repo, monkeypatch, capsys):
    (minimal_repo / ".env").write_text(
        "TUSHARE_TOKEN=repository-token\nSRT_TEST_SETTING=repository-value\n", encoding="utf-8",
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "process-token")
    monkeypatch.delenv("SRT_TEST_SETTING", raising=False)
    monkeypatch.chdir(minimal_repo)
    assert main(["backtest", "run", "--strategy", "S900", "--strategy-version", "v1",
                 "--symbol", "588080.SH", "--asset", "etf", "--start", "2026-01-01",
                 "--end", "2026-01-02", "--init-cash", "100000", "--lot-size", "100"]) != 0
    error = json.loads(capsys.readouterr().out)
    assert error["error"]["code"] == "backtest_strategy_invalid"
    assert os.environ["TUSHARE_TOKEN"] == "process-token"
    assert os.environ["SRT_TEST_SETTING"] == "repository-value"


def test_installed_cli_exposes_supported_command_surface():
    executable = Path(sys.executable).with_name("czsc-trader.exe" if sys.platform == "win32" else "czsc-trader")
    for arguments, expected in [(('--help',), '{backtest}'),
                                (('backtest', '--help'), '{run}'),
                                (('backtest', 'run', '--help'), '--strategy-version')]:
        result = subprocess.run([str(executable), *arguments], check=False, capture_output=True,
                                text=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert expected in result.stdout
        if arguments == ('backtest', 'run', '--help'):
            assert "--outputs-root" in result.stdout
            assert "--candidate-id" not in result.stdout
        assert "--repo-root" not in result.stdout


def test_removed_cli_commands_return_invalid_arguments(capsys):
    for command in ("data", "research", "candidate", "strategy", "experiment", "archive",
                    "news", "catalog", "template"):
        assert main([command, "--format", "json"]) != 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "FAIL"
        assert result["error"]["code"] == "invalid_arguments"


def test_public_business_api_is_explicit_and_importable():
    import czsc_trader.application as api
    assert set(api.__all__) == PUBLIC_API
    for name in PUBLIC_API:
        assert callable(getattr(api, name)), name
    for name in ("extract_news", "validate_catalog", "list_catalog", "show_catalog",
                 "validate_templates", "list_templates", "show_template", "instantiate_template"):
        with pytest.raises(AttributeError):
            getattr(api, name)
