"""The account-facing adapter uses authenticated local SM/SRT contracts."""

from dataclasses import replace
from datetime import date, datetime
import json
import subprocess

import pytest

from strategy_manager import Qualification
from paper_trading_engine import AccountStrategyBinding
from paper_trading_engine.errors import AdviceClientError
from paper_trading_engine.srt_advice_client import SrtAdviceClient


@pytest.mark.parametrize(
    "field,value",
    [
        ("strategy_id", "S1"),
        ("version", "v0"),
        ("release_hash", "A" * 64),
        ("name", ""),
        ("symbol", "bad"),
        ("qualification", "PAPER_READY"),
        ("qualification", Qualification.RESEARCH),
        ("selection_data_cutoff", "2026-09-02"),
        ("selection_data_cutoff", datetime(2026, 9, 2)),
        ("fee_rate", True),
        ("fee_rate", float("nan")),
        ("fee_rate", float("inf")),
        ("fee_rate", -0.1),
        ("fee_rate", 1.0),
    ],
)
def test_binding_rejects_invalid_fields(field, value):
    binding = AccountStrategyBinding(
        "S900",
        "v1",
        "a" * 64,
        "Test",
        Qualification.PAPER_READY,
        date(2026, 9, 2),
        "588080.SH",
        0.001,
    )
    with pytest.raises((ValueError, TypeError)):
        replace(binding, **{field: value})


def test_real_frozen_binding_uses_public_approval_without_cli(pte_frozen, monkeypatch, tmp_path):
    context, version = pte_frozen
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("no CLI subprocess"))
    client = SrtAdviceClient(repo_root=context.root, data_dir=tmp_path)
    binding = client.validate_account_binding(
        strategy_id="S900", strategy_version="v1", symbol="588080.SH", asset="etf"
    )
    assert type(binding) is AccountStrategyBinding
    assert binding.release_id == version.release_id
    assert binding.release_hash == version.release_hash
    assert binding.qualification is Qualification.PAPER_READY
    assert binding.selection_data_cutoff == date.fromisoformat(version.selection_data_cutoff)
    commit = context.research_root / "S900/freeze_requests/request1/committed.json"
    commit.parent.mkdir(parents=True)
    commit.write_text("{}", encoding="utf-8")
    assert client.validate_account_binding(
        strategy_id="S900", strategy_version="v1", symbol="588080.SH", asset="etf",
    ) == binding


@pytest.mark.parametrize(
    "failure", ["missing_deployment", "wrong_deployment_hash", "stale_approval", "symbol", "asset", "package"]
)
def test_real_binding_rejects_invalid_runtime_or_approval(pte_frozen, tmp_path, failure):
    context, _ = pte_frozen
    kwargs = dict(strategy_id="S900", strategy_version="v1", symbol="588080.SH", asset="etf")
    if failure == "missing_deployment":
        (context.strategy_root / "deployments/S900-v1.json").unlink()
    elif failure == "wrong_deployment_hash":
        path = context.strategy_root / "deployments/S900-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["strategy_version_hash"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
    elif failure == "stale_approval":
        path = context.strategy_root / "S900/lifecycle.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[-1]["release_hash"] = "0" * 64
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    elif failure == "package":
        package = context.strategy_root / "S900/releases/v1"
        manifest = json.loads((package / "release_manifest.json").read_text(encoding="utf-8"))
        (package / manifest["runtime_binding"]).write_text("{}", encoding="utf-8")
    else:
        kwargs[failure] = "510500.SH" if failure == "symbol" else "stock"
    from strategy_runtime import RuntimeCompatibilityError, RuntimeContractError

    match = "package file differs" if failure == "package" else None
    with pytest.raises((AdviceClientError, RuntimeCompatibilityError, RuntimeContractError), match=match):
        SrtAdviceClient(repo_root=context.root, data_dir=tmp_path).validate_account_binding(
            **kwargs
        )
