# Risk ownership: TDR-18
"""Source lifecycle and shared V4 identity contract; all fixtures are synthetic."""
from hashlib import sha256

import pytest

from czsc_trader.application.selection_source_reader import (
    SelectionSourceReader,
)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.equity_evaluation import EquityArtifact
from czsc_trader.research_tools.equity_replay import (
    _bytes, MaterializedEquity, primary_input_digest,
)


def _fixture(root, candidate="C0001", experiment="EX001_20261105", mutate=None):
    inputs = {"schema": "equity-input/v2", "data": {k: [] for k in ("bars", "sessions", "trading_facts", "constraints")},
        "products": {k: [] for k in ("bars", "sessions", "trading_facts", "constraints")}}
    inputs_art = EquityArtifact("equity_input", _bytes(inputs))
    request = dict(schema="equity-research/v4", candidate_definition={"contract_version": 4},
        content_sha256="a" * 64, instrument="US.TEST", window="window", history_start="start", initial_cash=100.,
        fee_rate=.001, engine_sources={}, python_version="3.12", pandas_version="2", warmup_bars=0,
        specification={}, price_basis="HFQ", quantity_basis="SIMULATED_INTEGER_UNITS")
    identity = {k: request[k] for k in ("instrument", "window", "history_start", "initial_cash", "fee_rate",
        "engine_sources", "python_version", "pandas_version")}
    identity.update(kind="BUY_HOLD", input_snapshot_sha256=primary_input_digest(inputs),
        definition={"warmup_bars": 0, "execution_spec": {}})
    account = {"schema": "equity-account/v1", "input_sha256": inputs_art.sha256,
        "owner": {"kind": "CANDIDATE", "candidate": candidate, "content_sha256": "a" * 64},
        "run": {"observations": [{"equity": 100.}]}}
    benchmark = {"schema": "equity-account/v1", "input_sha256": primary_input_digest(inputs),
        "owner": {"kind": "BENCHMARK", "run_identity": identity, "run_sha256": sha256(_bytes(identity)).hexdigest()},
        "run": {"observations": [{"equity": 101.}]}}
    if mutate:
        mutate(request, account, benchmark)
    candidate_art, benchmark_art = (EquityArtifact("equity_account", _bytes(value)) for value in (account, benchmark))
    artifacts = (inputs_art, candidate_art, benchmark_art)
    header = {"schema_version": 4, "request": request, "data": inputs["data"],
        "evaluation_identity": {"candidate": candidate}, "benchmark_identity": identity}
    header.update({key: {"kind": art.kind, "sha256": art.sha256} for key, art in zip(
        ("input_ref", "candidate_ref", "benchmark_ref"), artifacts)})
    content = _bytes(header)
    digest = sha256(content).hexdigest()
    ref = EvidenceRef(ExperimentRef("S999", experiment), digest + ".json", digest, "application/json", "source",
        "equity_research", 4)
    path = root / ref.repository_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    for item in artifacts:
        (path.parent / (item.sha256 + ".json")).write_bytes(item.content)
    return ref, header, MaterializedEquity(content, artifacts)


def _reader(root, **budgets):
    return SelectionSourceReader(root, max_source_bytes=budgets.get("source", 10_000_000),
        max_shared_bytes=budgets.get("shared", 10_000_000))


def test_TDR_18_C01_shared_inputs_benchmark_read_once_and_candidate_released(tmp_path):
    first, _, old = _fixture(tmp_path)
    second, _, _ = _fixture(tmp_path, "C0002", "EX002_20261105")
    with _reader(tmp_path) as reader:
        assert reader.prepare((first, second, first)) == (first, second)
        assert reader.unique_benchmark_count == 1
        one = reader.read(first)
        two = reader.read(second)
        assert one.inputs is two.inputs
        assert one.benchmark_run is two.benchmark_run
        assert one.candidate_run == old.payload["runs"]["candidate"]
        assert one.benchmark_run == old.payload["runs"]["buy_hold"]
        assert reader.stats.read_count == 8
        assert reader.stats.decode_count == 6
        assert reader.stats.source_bytes == sum(p.stat().st_size for p in tmp_path.rglob("*.json"))
        assert all(value is not one.candidate_run for value in reader._shared.values())
        with pytest.raises(ValueError, match="already consumed"):
            reader.read(first)
    assert not reader._shared and not reader._headers
