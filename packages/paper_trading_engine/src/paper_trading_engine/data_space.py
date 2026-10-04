"""Host assembly of PTE's environment-scoped market data service."""

from pathlib import Path

from dataflows import Dataflows, DataSpace, ProviderConfig


def create_dataflows(*, data_dir: Path, space: DataSpace, config_root: Path) -> Dataflows:
    """Bind a relative data space to the environment's stable shared data root."""
    return Dataflows(
        base_dir=data_dir,
        space=space,
        providers=ProviderConfig(env_file=config_root / ".env"),
    )
