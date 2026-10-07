"""PTE environment paths are explicit, relative and independent of release roots."""

from pathlib import Path
from datetime import datetime

import pytest

from dataflows import DataSpace
from paper_trading_engine import data_space
from paper_trading_engine.cli import build_parser
from paper_trading_engine.runtime_config import PteRuntimeConfig
from paper_trading_engine.errors import AdviceClientError
from paper_trading_engine.srt_advice_client import SrtAdviceClient


@pytest.mark.parametrize("value", [Path("."), Path("../other"), Path("C:/market")])
def test_runtime_rejects_nonrelative_or_escaping_data_space(value):
    with pytest.raises(ValueError):
        PteRuntimeConfig(data_space=value)


def test_cli_converts_environment_space_to_typed_contract(tmp_path):
    args = build_parser().parse_args([
        "serve", "--repo-root", str(tmp_path), "--data-space", "markets/cn",
    ])
    assert args.data_space == DataSpace(Path("markets/cn"))


def test_advice_data_access_requires_host_injection(tmp_path):
    client = SrtAdviceClient(repo_root=tmp_path, data_dir=tmp_path / "data")
    with pytest.raises(AdviceClientError, match="host-configured DFLS"):
        client.latest_completed_signal_date(datetime(2026, 9, 14, 22))


def test_host_injects_space_and_credentials_location_without_reading_credentials(tmp_path, monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(data_space, "Dataflows", create)
    data_space.create_dataflows(
        data_dir=tmp_path / "shared/data", space=DataSpace(Path("market")),
        config_root=tmp_path / "shared/config",
    )
    assert captured["base_dir"] == tmp_path / "shared/data"
    assert captured["space"] == DataSpace(Path("market"))
    assert captured["providers"].env_file == tmp_path / "shared/config/.env"
