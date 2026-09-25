from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from czsc_trader.cli.main import _context, build_parser, main


EXPECTED_ACTIONS = {
    "data": {"prepare", "validate"},
    "research": {"create", "evaluate", "intent"},
    "candidate": {"review", "evaluate", "freeze"},
    "strategy": {
        "list",
        "info",
        "deploy",
    },
    "backtest": {"run"},
    "experiment": {"preflight"},
    "archive": {"validate"},
    "news": {"extract"},
    "catalog": {"validate", "list", "show"},
    "template": {"validate", "list", "show", "instantiate"},
}


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

    context = _context(argparse.Namespace(repo_root=functional_repo))

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


def test_ft_t08_strategy_cli_does_not_require_research_evaluator() -> None:
    code = """
import importlib.abc
import sys

class BlockStrategyEvaluator(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "strategy_evaluator" or fullname.startswith("strategy_evaluator."):
            raise ModuleNotFoundError("blocked research-only dependency")
        return None

sys.meta_path.insert(0, BlockStrategyEvaluator())
from czsc_trader.cli.main import build_parser
parsed = build_parser().parse_args(["strategy", "list"])
assert parsed.command_name == "strategy.list"
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_ft_t08_candidate_and_srt_commands_parse() -> None:
    parser = build_parser()
    documented_commands = (
        [
            "research",
            "create",
            "--input",
            "research-intent.json",
            "--actor",
            "tomxiao",
            "--reason",
            "批准研究立项",
        ],
        [
            "candidate",
            "review",
            "--package",
            "research/S008/candidates/S008-C001",
            "--mandate",
            "evaluation-mandate.json",
        ],
        [
            "research",
            "evaluate",
            "--input",
            "experiments/S008/20260924_S008_EX67/evaluation_request.json",
        ],
        [
            "candidate",
            "freeze",
            "S008-C001",
            "--change-summary",
            "首个冻结版本",
        ],
        ["strategy", "info", "S008-v1"],
    )

    parsed = [parser.parse_args(command) for command in documented_commands]

    assert [item.command_name for item in parsed] == [
        "research.create",
        "candidate.review",
        "research.evaluate",
        "candidate.freeze",
        "strategy.info",
    ]


def test_experiment_preflight_cli_reports_legacy_warning(capsys) -> None:
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "tests" / "fixtures" / "s008_research_cases" / "20260924_S008_EX99"

    exit_code = main(
        [
            "experiment",
            "preflight",
            "--experiment",
            str(fixture),
            "--max-evaluations",
            "1",
            "--repo-root",
            str(repo),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["command"] == "experiment.preflight"
    assert payload["warnings"]


def test_research_evaluate_reports_contract_errors_as_validation_failures(
    functional_repo: Path, capsys
) -> None:
    exit_code = main(
        [
            "research",
            "evaluate",
            "--input",
            "experiments/S008/EX67/evaluation_request.json",
            "--repo-root",
            str(functional_repo),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["status"] == "FAIL"
    assert payload["command"] == "research.evaluate"
    assert payload["error"]["code"] == "research_evaluation_failed"


def test_ft_t08_catalog_cli_validates_lists_and_shows(capsys) -> None:
    repo = Path(__file__).resolve().parents[2]
    root = ["--repo-root", str(repo)]
    for arguments in (
        ["catalog", "validate", *root],
        ["catalog", "list", "--kind", "factor", "--status", "READY", *root],
        ["catalog", "show", "--id", "F-PROJECT-ER60", *root],
    ):
        assert main(arguments) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS"
    assert payload["result"]["definition"]["factor_id"] == "F-PROJECT-ER60"


def test_ft_t08_template_cli_validates_lists_shows_and_instantiates(capsys, tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    root = ["--repo-root", str(repo)]
    for arguments in (
        ["template", "validate", *root],
        ["template", "list", "--status", "READY", *root],
        ["template", "show", "--id", "STC-T04-EVENT-HOLD", *root],
    ):
        assert main(arguments) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS"
    assert payload["result"]["template"]["operator"] == "EVENT_HOLD"

    spec = tmp_path / "prototype.json"
    spec.write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert main(["template", "instantiate", "--spec", str(spec), *root]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["result"]["instance"]["instance_id"].startswith("STI-")

    invalid = json.loads(spec.read_text(encoding="utf-8"))
    invalid["bindings"][0]["source_id"] = "SIG-NOT-IN-FSC"
    spec.write_text(json.dumps(invalid), encoding="utf-8")
    assert main(["template", "instantiate", "--spec", str(spec), *root]) != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["error"]["code"] == "strategy_template_binding_invalid"
