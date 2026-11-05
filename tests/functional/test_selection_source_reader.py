"""Source lifecycle and shared V4 identity contract; all fixtures are synthetic."""
from dataclasses import replace
from hashlib import sha256

import pytest

from czsc_trader.application.selection_source_reader import (
    SelectionSourceBudgetError, SelectionSourceReader,
)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.equity_evaluation import EquityArtifact
from czsc_trader.research_tools.equity_replay import (
    _bytes, MaterializedEquity, primary_input_digest,
)


def _fixture(root, candidate="C0001", experiment="EX001_20261105", mutate=None):
    inputs = {"schema": "equity-input/v1", "data": {k: [] for k in ("bars", "sessions", "actions", "constraints")},
        "products": {k: [] for k in ("bars", "sessions", "actions", "constraints")}}
    inputs_art = EquityArtifact("equity_input", _bytes(inputs))
    request = dict(schema="equity-research/v4", candidate_definition={"contract_version": 4},
        content_sha256="a" * 64, instrument="US.TEST", window="window", history_start="start", initial_cash=100.,
        fee_rate=.001, engine_sources={}, python_version="3.12", pandas_version="2", warmup_bars=0,
        specification={})
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


def test_shared_inputs_benchmark_read_once_and_candidate_released(tmp_path):
    first, _, old = _fixture(tmp_path)
    second, _, _ = _fixture(tmp_path, "C0002")
    with _reader(tmp_path) as reader:
        assert reader.prepare((first, second, first)) == (first, second)
        assert reader.unique_benchmark_count == 1
        one = reader.read(first)
        two = reader.read(second)
        assert one.inputs is two.inputs
        assert one.benchmark_run is two.benchmark_run
        assert one.candidate_run == old.payload["runs"]["candidate"]
        assert one.benchmark_run == old.payload["runs"]["buy_hold"]
        assert reader.stats.read_count == reader.stats.decode_count == 6
        assert reader.stats.source_bytes == sum(p.stat().st_size for p in tmp_path.rglob("*.json"))
        assert all(value is not one.candidate_run for value in reader._shared.values())
        with pytest.raises(ValueError, match="already consumed"):
            reader.read(first)
    assert not reader._shared and not reader._headers


def test_equal_hash_different_paths_still_verified_but_shared_decode(tmp_path):
    first, _, _ = _fixture(tmp_path)
    second, _, _ = _fixture(tmp_path, "C0002", "EX002_20261105")
    with _reader(tmp_path) as reader:
        reader.prepare((first, second))
        reader.read(first)
        reader.read(second)
        assert reader.stats.read_count == 8
        assert reader.stats.decode_count == 6


def test_old_materialization_payload_still_independent(tmp_path):
    _, _, materialized = _fixture(tmp_path)
    first, second = materialized.payload, materialized.payload
    first["runs"]["candidate"]["observations"][0]["equity"] = 999.
    first["audit_inputs"]["bars"].append("mutated")
    assert second["runs"]["candidate"]["observations"][0]["equity"] == 100.
    assert second["audit_inputs"]["bars"] == []


@pytest.mark.parametrize("mutation,message", [
    (lambda r, c, b: c["owner"].update(candidate="C9999"), "owner differs"),
    (lambda r, c, b: c.update(input_sha256="b" * 64), "input identity differs"),
    (lambda r, c, b: r.update(fee_rate=.2), "economic identity differs"),
    (lambda r, c, b: b["owner"].update(run_sha256="c" * 64), "owner differs"),
])
def test_new_and_old_paths_share_identity_failures(tmp_path, mutation, message):
    ref, _, materialized = _fixture(tmp_path, mutate=mutation)
    with pytest.raises(ValueError, match=message):
        _ = materialized.payload
    with _reader(tmp_path) as reader:
        reader.prepare((ref,))
        with pytest.raises(ValueError, match=message):
            reader.read(ref)


@pytest.mark.parametrize("target", ["header", "candidate_ref", "input_ref", "benchmark_ref"])
def test_corrupt_source_is_explicit_and_never_reread(tmp_path, target):
    ref, header, _ = _fixture(tmp_path)
    path = tmp_path / ref.repository_path
    if target != "header":
        path = path.parent / (header[target]["sha256"] + ".json")
    path.write_bytes(b"corrupt")
    with _reader(tmp_path) as reader:
        reader.prepare((ref, ref))
        with pytest.raises(ValueError, match="checksum"):
            reader.read(ref)
        reads = reader.stats.read_count
        with pytest.raises(ValueError):
            reader.read(ref)
        assert reader.stats.read_count == reads


def test_budgets_reject_before_account_decode(tmp_path):
    ref, _, _ = _fixture(tmp_path)
    for budget in ({"source": 1}, {"shared": 1}):
        with _reader(tmp_path, **budget) as reader:
            with pytest.raises(SelectionSourceBudgetError):
                reader.prepare((ref,))
            assert reader.stats.decode_count <= 1
            assert not reader._shared


def test_missing_source_is_local_failure(tmp_path):
    first, _, _ = _fixture(tmp_path)
    second, _, _ = _fixture(tmp_path, "C0002")
    (tmp_path / first.repository_path).unlink()
    with _reader(tmp_path) as reader:
        reader.prepare((first, second))
        with pytest.raises(FileNotFoundError):
            reader.read(first)
        assert reader.read(second).candidate_run


def test_malformed_json_is_rejected(tmp_path):
    ref, _, _ = _fixture(tmp_path)
    content = b'{"schema_version":4,"schema_version":4}'
    digest = sha256(content).hexdigest()
    ref = replace(ref, evidence_id=digest + ".json", sha256=digest)
    (tmp_path / ref.repository_path).write_bytes(content)
    with _reader(tmp_path) as reader:
        reader.prepare((ref,))
        with pytest.raises(ValueError, match="duplicate"):
            reader.read(ref)


@pytest.mark.parametrize("fields", [dict(schema=None, schema_version=None), dict(schema_version=3),
    dict(media_type="text/plain")])
def test_source_requires_explicit_v4_json_identity(tmp_path, fields):
    ref, _, _ = _fixture(tmp_path)
    ref = replace(ref, **fields)
    with _reader(tmp_path) as reader:
        reader.prepare((ref,))
        with pytest.raises(ValueError, match="V4 evidence"):
            reader.read(ref)
        assert reader.stats.read_count == 0


def test_corrupt_second_copy_not_hidden_by_shared_hash_cache(tmp_path):
    first, _, _ = _fixture(tmp_path)
    second, header, _ = _fixture(tmp_path, "C0002", "EX002_20261105")
    second_input = (tmp_path / second.repository_path).parent / (header["input_ref"]["sha256"] + ".json")
    second_input.write_bytes(b"corrupt")
    with _reader(tmp_path) as reader:
        reader.prepare((first, second))
        reader.read(first)
        with pytest.raises(ValueError, match="checksum"):
            reader.read(second)


@pytest.mark.parametrize("field", ["request", "evaluation_identity", "benchmark_identity", "data",
    "candidate_definition", "benchmark_definition"])
def test_malformed_header_nested_shape_is_source_local(tmp_path, field):
    broken, header, _ = _fixture(tmp_path)
    healthy, _, _ = _fixture(tmp_path, "C0002")
    if field == "candidate_definition":
        header["request"][field] = []
    elif field == "benchmark_definition":
        header["benchmark_identity"]["definition"] = []
    else:
        header[field] = []
    content = _bytes(header)
    digest = sha256(content).hexdigest()
    broken = replace(broken, evidence_id=digest + ".json", sha256=digest)
    (tmp_path / broken.repository_path).write_bytes(content)
    with _reader(tmp_path) as reader:
        reader.prepare((broken, healthy))
        with pytest.raises(ValueError, match="must be an object"):
            reader.read(broken)
        assert reader.read(healthy).candidate_run
