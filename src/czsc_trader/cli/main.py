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
    from strategy_manager import StrategyRegistry, StrategyManagerError, CandidateKey
    from czsc_trader.application import BacktestRequest, load_candidate
    from czsc_trader.application.errors import ValidationError
    from .backtest import run_independent_backtest

    context = _context(args)
    try:
        request = BacktestRequest(symbol=args.symbol, asset_type=args.asset, start=args.start, end=args.end,
                                  initial_cash=args.init_cash, lot_size=args.lot_size)
    except (TypeError, ValueError) as exc:
        raise ValidationError("backtest_request_invalid", str(exc)) from exc
    try:
        strategy = (load_candidate(context, CandidateKey(args.strategy, args.candidate_id))
                    if args.candidate_id is not None else
                    StrategyRegistry(context.strategy_root).get_version(args.strategy, args.strategy_version))
    except (StrategyManagerError, ValueError, OSError) as exc:
        raise ValidationError("backtest_strategy_invalid", str(exc)) from exc
    output_root = Path(args.outputs_root)
    if not output_root.is_absolute():
        output_root = context.root / output_root
    return run_independent_backtest(context, strategy, request, output_root)


def build_parser() -> argparse.ArgumentParser:
    parser = CommandParser(prog="czsc-trader")
    resources = parser.add_subparsers(dest="resource", required=True, parser_class=CommandParser)

    backtest = resources.add_parser("backtest")
    backtest_actions = backtest.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    backtest_run = backtest_actions.add_parser("run", help="run an independent backtest and save reports")
    backtest_run.add_argument("--strategy", required=True)
    selection = backtest_run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--strategy-version", help="registered frozen version, for example v1")
    selection.add_argument("--candidate-id", help="registered candidate, for example C0621")
    backtest_run.add_argument("--outputs-root", default="outputs", help="output root, relative to repository by default")
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
