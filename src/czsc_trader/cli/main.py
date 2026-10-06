from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import sys
import traceback

from dotenv import load_dotenv

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.errors import CommandError, InternalError, UsageError
from .output import write_error, write_result


class CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError("invalid_arguments", message)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--debug", action="store_true")


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _context(args: argparse.Namespace) -> RepositoryContext:
    context = RepositoryContext.discover(Path.cwd())
    load_dotenv(context.root / ".env", override=False)
    return context


def _backtest_run(args: argparse.Namespace):
    from strategy_manager import StrategyRegistry, StrategyManagerError
    from czsc_trader.application import (
        BacktestRequest, run_backtest, create_research_context, create_experiment,
        ExperimentRequest, publish_evidence, CommandResult,
    )
    from czsc_trader.research_tools import ResearchBatchRef, MaterialEvidenceWrite
    from czsc_trader.backtesting.service import _backtest_report_files
    from czsc_trader.application.errors import ValidationError

    context = _context(args)
    try:
        strategy = StrategyRegistry(context.strategy_root).get_version(
            args.strategy, args.strategy_version
        )
    except StrategyManagerError as exc:
        raise ValidationError("backtest_strategy_invalid", str(exc)) from exc
    try:
        research = create_research_context(context, ResearchBatchRef(strategy.strategy_id))
    except (StrategyManagerError, ValueError, OSError) as exc:
        raise ValidationError("backtest_research_context_invalid", str(exc)) from exc
    evaluation = run_backtest(research, strategy, BacktestRequest(
        symbol=args.symbol, asset_type=args.asset, start=args.start, end=args.end,
        initial_cash=args.init_cash, lot_size=args.lot_size))
    experiment = create_experiment(research, ExperimentRequest(
        f"{strategy.release_id} 账户回测", f"{args.symbol} 在指定窗口内的实际账户表现", date.today()))
    artifacts = {}
    media_types = {"csv": "text/csv", "json": "application/json", "html": "text/html", "md": "text/markdown"}
    for name, data in _backtest_report_files(evaluation).items():
        suffix = name.rsplit(".", 1)[1]
        reference = publish_evidence(research, MaterialEvidenceWrite(
            experiment, name, data, media_types[suffix], suffix))
        artifacts[name] = reference.repository_path
    return CommandResult("PASS", "backtest.run",
        {"experiment": experiment.to_dict(), "metrics": evaluation.metrics}, artifacts=artifacts)


def build_parser() -> argparse.ArgumentParser:
    parser = CommandParser(prog="czsc-trader")
    resources = parser.add_subparsers(dest="resource", required=True, parser_class=CommandParser)

    backtest = resources.add_parser("backtest")
    backtest_actions = backtest.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    backtest_run = backtest_actions.add_parser("run")
    backtest_run.add_argument("--strategy", required=True)
    backtest_run.add_argument("--strategy-version", required=True)
    backtest_run.add_argument("--symbol", required=True)
    backtest_run.add_argument("--asset", required=True, choices=("stock", "etf"))
    backtest_run.add_argument("--start", required=True, type=date.fromisoformat)
    backtest_run.add_argument("--end", required=True, type=date.fromisoformat)
    backtest_run.add_argument("--init-cash", required=True, type=float)
    backtest_run.add_argument("--lot-size", required=True, type=_positive_integer)
    _add_output_options(backtest_run)
    backtest_run.set_defaults(
        command_handler=_backtest_run,
        command_name="backtest.run",
    )

    return parser


def _command_hint(arguments: Sequence[str]) -> str:
    positional = [value for value in arguments[:2] if not value.startswith("-")]
    return ".".join(positional) if positional else "czsc-trader"


def _format_hint(arguments: Sequence[str]) -> str:
    for index, value in enumerate(arguments):
        if value == "--format" and index + 1 < len(arguments):
            return str(arguments[index + 1])
        if value.startswith("--format="):
            return value.partition("=")[2]
    return "json"


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(arguments)
    except UsageError as exc:
        return write_error(
            _command_hint(arguments),
            exc,
            output_format=_format_hint(arguments),
        )
    command = str(getattr(args, "command_name", args.resource))
    try:
        result = args.command_handler(args)
    except CommandError as exc:
        return write_error(command, exc, output_format=args.format)
    except Exception as exc:  # pragma: no cover - exercised through --debug later
        if getattr(args, "debug", False):
            traceback.print_exc()
        error = InternalError("internal_error", str(exc))
        return write_error(
            command,
            error,
            output_format=args.format,
        )
    return write_result(result, output_format=args.format)
