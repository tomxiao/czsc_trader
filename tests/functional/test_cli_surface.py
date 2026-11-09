# Risk ownership: TDR-04
"""Public CLI and supported business API contracts."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess
import sys

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


def test_TDR_04_C03_retired_packages_and_services_are_unavailable():
    for name in ("market_rules", "trading_execution_engine", "factor_signal_catalog",
                 "strategy_template_catalog", "czsc_trader.application.catalog_service",
                 "czsc_trader.application.template_service"):
        assert importlib.util.find_spec(name) is None, name


def test_TDR_04_C01_installed_cli_exposes_supported_command_surface():
    executable = Path(sys.executable).with_name("czsc-trader.exe" if sys.platform == "win32" else "czsc-trader")
    result = subprocess.run([str(executable), 'backtest', 'run', '--help'], check=False,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ''
    assert '--strategy-version' in result.stdout and '--outputs-root' in result.stdout
    assert '--candidate-id' not in result.stdout and '--repo-root' not in result.stdout
    import czsc_trader.application as api
    assert set(api.__all__) == PUBLIC_API
    assert all(callable(getattr(api, name)) for name in PUBLIC_API)


def test_TDR_04_C05_removed_cli_commands_return_invalid_arguments(capsys):
    assert main(['candidate', '--format', 'json']) != 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'FAIL'
    assert result['error']['code'] == 'invalid_arguments'
