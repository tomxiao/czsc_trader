from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from czsc_trader.cli.main import _context, build_parser, main


EXPECTED_ACTIONS = {"backtest": {"run"}}


def test_repository_context_loads_dotenv_without_overriding_process_environment(
    functional_repo: Path,
    monkeypatch,
) -> None:
    (functional_repo / ".env").write_text(
        "TUSHARE_TOKEN=repository-token\nSRT_TEST_SETTING=repository-value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "process-token")
    monkeypatch.delenv("SRT_TEST_SETTING", raising=False)

    monkeypatch.chdir(functional_repo)
    context = _context(argparse.Namespace())

    assert context.root == functional_repo.resolve()
    assert os.environ["TUSHARE_TOKEN"] == "process-token"
    assert os.environ["SRT_TEST_SETTING"] == "repository-value"


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(actions) == 1
    return actions[0]


def _command_surface(parser: argparse.ArgumentParser) -> dict[str, set[str]]:
    resources = _subparsers(parser)
    return {
        resource: set(_subparsers(resource_parser).choices)
        for resource, resource_parser in resources.choices.items()
    }


def test_ft_t08_installed_cli_exposes_supported_command_surface() -> None:
    executable = Path(sys.executable).with_name(
        "czsc-trader.exe" if sys.platform == "win32" else "czsc-trader"
    )
    completed = subprocess.run(
        [str(executable), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    assert all(resource in completed.stdout for resource in EXPECTED_ACTIONS)
    parser = build_parser()
    assert _command_surface(parser) == EXPECTED_ACTIONS
    resources = _subparsers(parser)
    backtest_actions = _subparsers(resources.choices["backtest"])
    run_options = {
        option
        for action in backtest_actions.choices["run"]._actions
        for option in action.option_strings
    }
    assert "--outputs-root" not in run_options
    assert "--repo-root" not in run_options


def test_removed_cli_commands_fail_without_running_handlers(capsys) -> None:
    for command in (
        "data",
        "research",
        "candidate",
        "strategy",
        "experiment",
        "archive",
        "news",
        "catalog",
        "template",
    ):
        assert main([command, "--format", "json"]) != 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "FAIL"
        assert result["error"]["code"] == "invalid_arguments"


def test_public_business_exports_resolve_existing_implementations() -> None:
    from importlib import import_module
    import czsc_trader.application as api

    for name, module in api._EXPORTS.items():
        assert getattr(api, name) is getattr(
            import_module("czsc_trader.application." + module), name
        )
    assert "freeze_candidate" not in api.__all__
    assert "extract_news" not in api.__all__


def test_public_research_apis_preserve_validation(functional_repo, tmp_path) -> None:
    import pytest
    from czsc_trader.application import (
        RepositoryContext,
        ValidationError,
        evaluate_research_request,
        preflight_experiment_archive,
        validate_catalog,
        list_catalog,
        show_catalog,
        validate_templates,
        list_templates,
        show_template,
        instantiate_template,
    )

    repo = Path(__file__).resolve().parents[2]
    context = RepositoryContext.discover(repo)
    report = preflight_experiment_archive(
        context,
        repo / "tests/fixtures/s008_research_cases/20260924_S008_EX99",
    )
    assert report.status == "PASS" and report.warnings
    with pytest.raises(ValidationError) as error:
        evaluate_research_request(RepositoryContext.discover(functional_repo), Path("missing.json"))
    assert error.value.code == "research_evaluation_failed"
    assert validate_catalog(context).status == "PASS"
    assert (
        list_catalog(context, kind="factor", family=None, status="READY", query=None).status
        == "PASS"
    )
    assert (
        show_catalog(context, "F-PROJECT-ER60").result["definition"]["factor_id"]
        == "F-PROJECT-ER60"
    )
    assert validate_templates(context).status == "PASS"
    assert list_templates(context, operator=None, status="READY", query=None).status == "PASS"
    assert (
        show_template(context, "STC-T04-EVENT-HOLD").result["template"]["operator"] == "EVENT_HOLD"
    )
    spec = tmp_path / "prototype.json"
    payload = {
        "schema_version": 1,
        "template_id": "STC-T04-EVENT-HOLD",
        "bindings": [
            {
                "slot": "entry_events",
                "source_id": "SIG-CZSC-cxt_bi_base_V230228",
                "source_kind": "SIGNAL",
                "state": "满足",
                "weight": None,
            }
        ],
        "parameters": {"holding_sessions": 5},
    }
    spec.write_text(json.dumps(payload), encoding="utf-8")
    assert instantiate_template(context, spec).result["instance"]["instance_id"].startswith("STI-")
    payload["bindings"][0]["source_id"] = "SIG-NOT-IN-FSC"
    spec.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError) as error:
        instantiate_template(context, spec)
    assert error.value.code == "strategy_template_binding_invalid"
