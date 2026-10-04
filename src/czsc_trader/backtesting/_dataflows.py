"""Repository-owned data space for every TDR historical replay."""

from pathlib import Path

from dataflows import Dataflows, DataSpace, ProviderConfig


def create_backtest_dataflows(repository_root: Path, *, read_only: bool = False) -> Dataflows:
    root = Path(repository_root).resolve()
    providers = ProviderConfig(bindings={}) if read_only else ProviderConfig(env_file=root / ".env")
    return Dataflows(base_dir=root, space=DataSpace(Path("data/backtest")), providers=providers)
