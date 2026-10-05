"""Synthetic control-command fixtures with real stores and installed bindings."""

from paper_trading_engine import cli
from paper_trading_engine.srt_advice_client import SrtAdviceClient


def engine_arguments(repo_root, database):
    return cli.build_parser().parse_args([
        "once", "--repo-root", str(repo_root), "--database", str(database),
        "--data-dir", str(database.parent / "data"),
        "--config-root", str(database.parent),
    ])


def installed_binding(context, *, symbol="588080.SH"):
    return SrtAdviceClient(
        repo_root=context.strategy_root.parent,
        data_dir=context.strategy_root.parent / "data",
    ).validate_account_binding(
        strategy_id="S900", strategy_version="v1", symbol=symbol, asset="etf",
    )


def create_bound_account(store, account_id, binding):
    return store.create_virtual_account(
        account_id, account_id, binding.release_id, binding.release_hash, 100_000,
        strategy_id=binding.strategy_id, strategy_version=binding.version,
        release_hash=binding.release_hash, strategy_name_snapshot=binding.name,
        qualification_snapshot=binding.qualification.value,
        selection_data_cutoff=binding.selection_data_cutoff.isoformat(),
        symbol=binding.symbol,
    )
