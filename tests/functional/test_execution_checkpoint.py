# Risk ownership: TDR-08
"""Completed calculations survive explicit restart without executable disk data."""

from dataclasses import replace
from hashlib import sha256
import json

import pytest

from czsc_trader.research_tools._execution_checkpoint import CheckpointStore, CheckpointIntegrityError
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def test_TDR_08_C06_publication_resume_rechecks_actual_evidence_and_preserves_completed_fact(tmp_path):
    experiment = ExperimentRef("S900", "EX001_20261022")
    body = b'{"fact":1}'
    digest = sha256(body).hexdigest()
    reference = EvidenceRef(experiment, f"{digest}.json", digest, "application/json", "account")
    path = tmp_path / reference.repository_path
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    with CheckpointStore(tmp_path, experiment, "publication", "CREATE", "a" * 64) as store:
        assert store.load_publication("b" * 64) is None
        store.save_publication("b" * 64, reference)
        assert store.load_publication("b" * 64) == reference
        source = store.root / "publications" / f"{'b' * 64}.json"
        other = store.root / "publications" / f"{'c' * 64}.json"
        other.write_bytes(source.read_bytes())
        with pytest.raises(CheckpointIntegrityError, match="lookup identity"):
            store.load_publication("c" * 64)
        with pytest.raises(CheckpointIntegrityError, match="cannot be replaced"):
            store.save_publication("b" * 64, replace(reference, name="different"))
    with CheckpointStore(tmp_path, experiment, "publication", "RESUME", "a" * 64) as store:
        path.write_bytes(b"changed")
        with pytest.raises(CheckpointIntegrityError, match="cannot be verified"):
            store.load_publication("b" * 64)


def test_TDR_08_C01_equity_checkpoint_shares_artifacts_and_restores_without_replay(tmp_path, monkeypatch):
    from equity_test_support import setup_account_research
    from strategy_runtime import ExecutionResources
    from czsc_trader.research_tools import (
        ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)
    from czsc_trader.research_tools import equity_replay

    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1, 1, 17)
    other = replace(request, candidate=replace(request.candidate, candidate_id="C0002"))
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("shared-artifacts")) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in (request, other))
        outcomes = context.evaluation.evaluate_many(prepared, execution=execution)
        assert all(item.result is not None for item in outcomes), [item.error for item in outcomes]
        originals = tuple(item.result for item in outcomes)
        cache = execution.checkpoint.root
        paths = tuple((cache / "artifacts").glob("*.json"))
        # One input, one shared benchmark and two candidate ledgers.
        assert len(paths) == 4
        before = {path.name: path.stat().st_mtime_ns for path in paths}
        for result in originals:
            document = json.loads((cache / "results" / f"{result.request_hash}.json").read_bytes())["payload"]
            assert document["schema_version"] == 2 and len(document["artifact_refs"]) == 3
            assert "artifacts" not in document
            assert all(set(ref) == {"kind", "sha256"} for ref in document["artifact_refs"])
            execution.checkpoint.save_equity_result(result.request_hash, result)
        assert {path.name: path.stat().st_mtime_ns for path in paths} == before

    def unexpected(*args, **kwargs):
        raise AssertionError("completed checkpoint must not replay candidate or benchmark")

    monkeypatch.setattr(equity_replay, "_compute_account", unexpected)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=ExecutionCheckpointRequest("shared-artifacts", CheckpointMode.RESUME)) as execution:
        prepared = tuple(context.evaluation.prepare(item, execution=execution) for item in (request, other))
        restored = context.evaluation.evaluate_many(prepared, execution=execution)
        assert all(item.result is not None for item in restored), [item.error for item in restored]
        for original, outcome in zip(originals, restored, strict=True):
            assert outcome.result.content == original.content
            assert outcome.result.artifacts == original.artifacts
        assert execution.stats.reused_results == 2 and execution.stats.submitted == 0
        assert execution.equity_statistics.candidate_runs == execution.equity_statistics.benchmark_runs == 0


@pytest.mark.parametrize('corruption', [pytest.param('missing', id='TDR-08-C02'), pytest.param('bytes', id='TDR-08-C03')])
def test_equity_checkpoint_rejects_broken_artifact_closure(tmp_path, corruption, account_facts):
    prepared, result = account_facts
    with CheckpointStore(tmp_path, prepared.experiment, "damaged-artifacts", "CREATE", "a" * 64) as store:
        store.save_equity_result(result.request_hash, result)
        path = store.root / "results" / f"{result.request_hash}.json"
        document = json.loads(path.read_bytes())["payload"]
        reference = document["artifact_refs"][0]
        artifact_path = store.root / "artifacts" / f"{reference['sha256']}.json"
        if corruption == "missing":
            artifact_path.unlink()
        elif corruption in {"bytes", "kind"}:
            value = json.loads(artifact_path.read_bytes())["payload"]
            value["content" if corruption == "bytes" else "kind"] = "changed"
            artifact_path.write_bytes(_checkpoint_envelope(value))
        else:
            if corruption == "reference":
                reference["sha256"] = "../outside"
            elif corruption == "closure":
                document["artifact_refs"][1] = reference
            else:
                document.pop("schema_version")
                document["artifacts"] = [{"kind": item.kind, "sha256": item.sha256,
                                          "content": item.content.decode()} for item in result.artifacts]
                document.pop("artifact_refs")
            path.write_bytes(_checkpoint_envelope(document))
    with CheckpointStore(tmp_path, prepared.experiment, "damaged-artifacts", "RESUME", "a" * 64) as store:
        with pytest.raises(CheckpointIntegrityError, match="cannot restore equity checkpoint"):
            store.load_equity_result(prepared, result.request_hash)


def _checkpoint_envelope(payload):
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return canonical({"sha256": sha256(canonical(payload)).hexdigest(), "payload": payload})




def test_TDR_08_C05_checkpoint_execution_identity_drift_is_rejected(tmp_path):
    experiment = ExperimentRef('S900', 'EX001_20261022')
    with CheckpointStore(tmp_path, experiment, 'run', 'CREATE', 'a' * 64):
        pass
    with pytest.raises(CheckpointIntegrityError, match='implementation identity differs'):
        CheckpointStore(tmp_path, experiment, 'run', 'RESUME', 'b' * 64)


def test_TDR_08_C04_source_drift_blocks_preparation_before_checkpoint_reuse(tmp_path, monkeypatch):
    """TDR-08-C04: a completed result cannot authorize changed strategy bytes."""
    from equity_test_support import setup_account_research
    from czsc_trader.research_tools import ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode
    from czsc_trader.research_tools import equity_replay
    context, request, _, _ = setup_account_research(tmp_path)
    checkpoint = ExecutionCheckpointRequest('source-drift')
    with ResearchExecutionSession(context, experiment=request.experiment, checkpoint=checkpoint) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
    source = request.candidate.source_root / 'strategy.py'
    source.write_bytes(source.read_bytes() + b'\n# changed source\n')
    def no_replay(*args, **kwargs):
        raise AssertionError('changed source must be rejected before replay')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=request.experiment,
            checkpoint=replace(checkpoint, mode=CheckpointMode.RESUME)) as execution:
        with pytest.raises(ValueError, match='hash|source'):
            context.evaluation.prepare(request, execution=execution)
        assert execution.stats.submitted == execution.stats.reused_results == 0


def _persist_equity_then_exit(root, experiment, result):
    import os
    store = CheckpointStore(root, experiment, "driver-crash", "CREATE", "a" * 64)
    store.save_equity_result(result.request_hash, result)
    os._exit(23)


def test_TDR_08_C07_driver_exit_releases_lock_and_preserves_v4_account(tmp_path):
    from multiprocessing import get_context
    from equity_test_support import setup_account_research
    from strategy_manager.errors import RegistryError
    from strategy_runtime import ExecutionResources
    from czsc_trader.research_tools import ResearchExecutionSession

    context, request, _, _ = setup_account_research(tmp_path)
    context.evaluation.resources = ExecutionResources(1)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        result = outcome.result
        assert result is not None, outcome.error
    child = get_context("spawn").Process(target=_persist_equity_then_exit,
        args=(tmp_path, request.experiment, result))
    child.start()
    try:
        child.join(timeout=30)
        assert not child.is_alive(), "checkpoint writer did not finish"
        assert child.exitcode == 23
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        child.close()
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        with CheckpointStore(tmp_path, request.experiment, "driver-crash", "RESUME", "a" * 64) as store:
            restored = store.load_equity_result(prepared, result.request_hash)
            assert restored.content == result.content and restored.artifacts == result.artifacts
            with pytest.raises(RegistryError, match="write lock"):
                CheckpointStore(tmp_path, request.experiment, "driver-crash", "RESUME", "a" * 64)
