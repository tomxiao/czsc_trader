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


def _add_repository_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path)
    _add_output_options(parser)


def _context(args: argparse.Namespace) -> RepositoryContext:
    context = RepositoryContext.discover(Path.cwd(), explicit_root=getattr(args, "repo_root", None))
    load_dotenv(context.root / ".env", override=False)
    return context


def _data_validate(args: argparse.Namespace):
    from czsc_trader.application.data_service import validate_data

    return validate_data(_context(args), args.symbol)


def _data_prepare(args: argparse.Namespace):
    from czsc_trader.application.data_service import PrepareDataCommand, prepare_data

    return prepare_data(
        _context(args),
        PrepareDataCommand(
            symbol=args.symbol,
            asset_type=args.asset,
            start=args.start,
            end=args.end,
        ),
    )


def _backtest_run(args: argparse.Namespace):
    from czsc_trader.application.backtest_service import BacktestCommand, run_backtest

    return run_backtest(
        _context(args),
        BacktestCommand(
            strategy_id=args.strategy,
            strategy_version=args.strategy_version,
            symbol=args.symbol,
            asset_type=args.asset,
            start=args.start,
            end=args.end,
            init_cash=args.init_cash,
        ),
    )


def _repository_path(context: RepositoryContext, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (context.root / value).resolve()


def _archive_validate(args: argparse.Namespace):
    from czsc_trader.application.archive_service import validate_archives

    context = _context(args)
    archive = _repository_path(context, args.archive) if args.archive else None
    return validate_archives(context, archive, all_archives=args.all)


def _experiment_preflight(args: argparse.Namespace):
    from czsc_trader.application.experiment_service import (
        PredecessorEvidence,
        preflight_experiment_archive,
    )

    context = _context(args)
    predecessors: list[PredecessorEvidence] = []
    for value in args.predecessor:
        path, separator, receipt = value.rpartition("=")
        if not separator or not path or not receipt:
            raise UsageError(
                "invalid_predecessor_evidence",
                "--predecessor must use WORKSPACE=RECEIPT_SHA256",
            )
        predecessors.append(
            PredecessorEvidence(
                workspace=_repository_path(context, Path(path)),
                receipt_sha256=receipt,
            )
        )
    return preflight_experiment_archive(
        context,
        _repository_path(context, args.experiment),
        max_workers=args.max_workers,
        native_threads_per_worker=args.native_threads_per_worker,
        max_evaluations=args.max_evaluations,
        predecessors=tuple(predecessors),
    )


def _strategy_command(args: argparse.Namespace):
    from czsc_trader.cli.strategy_commands import run_strategy_command

    return run_strategy_command(args, _context(args))


def _candidate_command(args: argparse.Namespace):
    from czsc_trader.cli.candidate_commands import run_candidate_command

    return run_candidate_command(args, _context(args))


def _research_command(args: argparse.Namespace):
    from czsc_trader.cli.research_commands import run_research_command

    return run_research_command(args, _context(args))


def _news_extract(args: argparse.Namespace):
    from czsc_trader.application.news_service import extract_news

    return extract_news(
        _context(args),
        input_path=args.input,
        scope_path=args.scope,
        output_dir=args.output_dir,
        limit=args.limit,
        workers=args.workers,
    )


def _catalog_validate(args: argparse.Namespace):
    from czsc_trader.application.catalog_service import validate_catalog

    return validate_catalog(_context(args))


def _catalog_list(args: argparse.Namespace):
    from czsc_trader.application.catalog_service import list_catalog

    return list_catalog(
        _context(args),
        kind=args.kind,
        family=args.family,
        status=args.status,
        query=args.query,
    )


def _catalog_show(args: argparse.Namespace):
    from czsc_trader.application.catalog_service import show_catalog

    return show_catalog(_context(args), args.id)


def _template_validate(args: argparse.Namespace):
    from czsc_trader.application.template_service import validate_templates

    return validate_templates(_context(args))


def _template_list(args: argparse.Namespace):
    from czsc_trader.application.template_service import list_templates

    return list_templates(
        _context(args),
        operator=args.operator,
        status=args.status,
        query=args.query,
    )


def _template_show(args: argparse.Namespace):
    from czsc_trader.application.template_service import show_template

    return show_template(_context(args), args.id)


def _template_instantiate(args: argparse.Namespace):
    from czsc_trader.application.template_service import instantiate_template

    context = _context(args)
    return instantiate_template(context, _repository_path(context, args.spec))


def build_parser() -> argparse.ArgumentParser:
    parser = CommandParser(prog="czsc-trader")
    resources = parser.add_subparsers(dest="resource", required=True, parser_class=CommandParser)

    data = resources.add_parser("data")
    data_actions = data.add_subparsers(dest="action", required=True, parser_class=CommandParser)
    data_prepare = data_actions.add_parser("prepare")
    data_prepare.add_argument("--symbol", required=True)
    data_prepare.add_argument("--asset", required=True, choices=("stock", "etf"))
    data_prepare.add_argument("--start", required=True, type=date.fromisoformat)
    data_prepare.add_argument("--end", required=True, type=date.fromisoformat)
    _add_repository_root(data_prepare)
    data_prepare.set_defaults(
        command_handler=_data_prepare,
        command_name="data.prepare",
    )
    data_validate = data_actions.add_parser("validate")
    data_validate.add_argument("--symbol", required=True)
    _add_repository_root(data_validate)
    data_validate.set_defaults(command_handler=_data_validate, command_name="data.validate")
    from czsc_trader.cli.candidate_commands import add_candidate_parser
    from czsc_trader.cli.strategy_commands import add_strategy_parser
    from czsc_trader.cli.research_commands import add_research_parser

    add_research_parser(resources, _add_repository_root, _research_command)
    add_candidate_parser(resources, _add_repository_root, _candidate_command)
    add_strategy_parser(resources, _add_repository_root, _strategy_command)

    news = resources.add_parser("news")
    news_actions = news.add_subparsers(dest="action", required=True, parser_class=CommandParser)
    news_extract = news_actions.add_parser("extract")
    news_extract.add_argument("--input", required=True, type=Path)
    news_extract.add_argument("--scope", required=True, type=Path)
    news_extract.add_argument("--output-dir", required=True, type=Path)
    news_extract.add_argument("--limit", type=int)
    news_extract.add_argument("--workers", type=int, default=4)
    _add_repository_root(news_extract)
    news_extract.set_defaults(
        command_handler=_news_extract,
        command_name="news.extract",
    )

    catalog = resources.add_parser("catalog")
    catalog_actions = catalog.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    catalog_validate = catalog_actions.add_parser("validate")
    _add_repository_root(catalog_validate)
    catalog_validate.set_defaults(
        command_handler=_catalog_validate,
        command_name="catalog.validate",
    )
    catalog_list = catalog_actions.add_parser("list")
    catalog_list.add_argument("--kind", choices=("all", "factor", "signal"), default="all")
    catalog_list.add_argument("--family")
    catalog_list.add_argument("--status", choices=("DISCOVERED", "READY", "DEPRECATED"))
    catalog_list.add_argument("--query")
    _add_repository_root(catalog_list)
    catalog_list.set_defaults(
        command_handler=_catalog_list,
        command_name="catalog.list",
    )
    catalog_show = catalog_actions.add_parser("show")
    catalog_show.add_argument("--id", required=True)
    _add_repository_root(catalog_show)
    catalog_show.set_defaults(
        command_handler=_catalog_show,
        command_name="catalog.show",
    )

    template = resources.add_parser("template")
    template_actions = template.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    template_validate = template_actions.add_parser("validate")
    _add_repository_root(template_validate)
    template_validate.set_defaults(
        command_handler=_template_validate,
        command_name="template.validate",
    )
    template_list = template_actions.add_parser("list")
    template_list.add_argument(
        "--operator",
        choices=(
            "WEIGHTED_SCORE",
            "GATED_SCORE",
            "REGIME_WEIGHTED_SCORE",
            "EVENT_HOLD",
            "CORE_OVERLAY",
        ),
    )
    template_list.add_argument("--status", choices=("READY", "DEPRECATED"))
    template_list.add_argument("--query")
    _add_repository_root(template_list)
    template_list.set_defaults(
        command_handler=_template_list,
        command_name="template.list",
    )
    template_show = template_actions.add_parser("show")
    template_show.add_argument("--id", required=True)
    _add_repository_root(template_show)
    template_show.set_defaults(
        command_handler=_template_show,
        command_name="template.show",
    )
    template_instantiate = template_actions.add_parser("instantiate")
    template_instantiate.add_argument("--spec", required=True, type=Path)
    _add_repository_root(template_instantiate)
    template_instantiate.set_defaults(
        command_handler=_template_instantiate,
        command_name="template.instantiate",
    )

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
    _add_output_options(backtest_run)
    backtest_run.set_defaults(
        command_handler=_backtest_run,
        command_name="backtest.run",
    )

    experiment = resources.add_parser("experiment")
    experiment_actions = experiment.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    experiment_preflight = experiment_actions.add_parser("preflight")
    experiment_preflight.add_argument("--experiment", required=True, type=Path)
    experiment_preflight.add_argument(
        "--predecessor",
        action="append",
        default=[],
        metavar="WORKSPACE=RECEIPT_SHA256",
    )
    experiment_preflight.add_argument("--max-workers", type=int, default=1)
    experiment_preflight.add_argument("--native-threads-per-worker", type=int, default=1)
    experiment_preflight.add_argument("--max-evaluations", type=int)
    _add_repository_root(experiment_preflight)
    experiment_preflight.set_defaults(
        command_handler=_experiment_preflight,
        command_name="experiment.preflight",
    )

    archive = resources.add_parser("archive")
    archive_actions = archive.add_subparsers(
        dest="action", required=True, parser_class=CommandParser
    )
    archive_validate = archive_actions.add_parser("validate")
    selection = archive_validate.add_mutually_exclusive_group(required=True)
    selection.add_argument("--archive", type=Path)
    selection.add_argument("--all", action="store_true")
    _add_repository_root(archive_validate)
    archive_validate.set_defaults(
        command_handler=_archive_validate,
        command_name="archive.validate",
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
        if _format_hint(arguments) == "html":
            sys.stderr.write(f"{exc.code}: {exc.message}\n")
            return exc.exit_code
        return write_error(
            _command_hint(arguments),
            exc,
            output_format=_format_hint(arguments),
        )
    command = str(getattr(args, "command_name", args.resource))
    try:
        result = args.command_handler(args)
    except CommandError as exc:
        if args.format == "html":
            sys.stderr.write(f"{exc.code}: {exc.message}\n")
            return exc.exit_code
        return write_error(command, exc, output_format=args.format)
    except Exception as exc:  # pragma: no cover - exercised through --debug later
        if getattr(args, "debug", False):
            traceback.print_exc()
        error = InternalError("internal_error", str(exc))
        if args.format == "html":
            sys.stderr.write(f"{error.code}: {error.message}\n")
            return error.exit_code
        return write_error(
            command,
            error,
            output_format=args.format,
        )
    return write_result(result, output_format=args.format)
