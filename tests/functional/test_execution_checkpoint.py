"""Completed calculations survive explicit restart without executable disk data."""
from evaluation_seed_support import prepare_request

from dataclasses import replace
from hashlib import sha256
import json
from multiprocessing import get_context
import os

import pandas as pd
import pytest
from strategy_manager.errors import RegistryError

from czsc_trader.research_tools._evaluation_codec import encode, decode
from czsc_trader.research_tools._execution_checkpoint import CheckpointStore, CheckpointIntegrityError
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from czsc_trader.research_tools.evidence import EvidenceRef
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def _persist_then_exit_without_cleanup(payload):
    # Trusted parent-created process transport, never bytes read from disk.
    import pickle
    root, experiment, result = pickle.loads(payload)
    store = CheckpointStore(root, experiment, "driver-crash", "CREATE", "a" * 64)
    store.save_result(result.request_hash, result)
    os._exit(23)


def test_driver_exit_releases_lock_and_preserves_completed_account(managed_evaluation):
    from czsc_trader.research_tools._evaluation_workers import pack

    context, request = managed_evaluation
    prepared = prepare_request(context, request)
    result = context.evaluation.evaluate(prepared)
    experiment = ExperimentRef("S900", request.experiment_id)
    child = get_context("spawn").Process(target=_persist_then_exit_without_cleanup,
        args=(pack((context.repository.root, experiment, result)),))
    child.start()
    try:
        child.join(timeout=30)
        assert not child.is_alive(), "checkpoint driver did not exit within 30 seconds"
        assert child.exitcode == 23
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        child.close()
    with CheckpointStore(context.repository.root, experiment, "driver-crash", "RESUME", "a" * 64) as store:
        restored = load_result(store, prepared, result.request_hash)
        assert restored.result_hash == result.result_hash
        evidence = serialize_evaluation_evidence(prepared, restored)
        validate_evaluation_evidence(evidence)
        assert evidence == serialize_evaluation_evidence(prepared, result)


def test_checkpoint_restores_real_account_for_authenticated_publication(managed_evaluation):
    context, request = managed_evaluation
    prepared = prepare_request(context, request)
    result = context.evaluation.evaluate(prepared)
    root = context.repository.root
    experiment = ExperimentRef("S900", request.experiment_id)
    with CheckpointStore(root, experiment, "account", "CREATE", "a" * 64) as store:
        assert load_result(store, prepared, result.request_hash) is None
        store.save_result(result.request_hash, result)
        store.save_result(result.request_hash, result)
        with pytest.raises(RegistryError, match="write lock"):
            CheckpointStore(root, experiment, "account", "RESUME", "a" * 64)
    with CheckpointStore(root, experiment, "account", "RESUME", "a" * 64) as store:
        restored = load_result(store, prepared, result.request_hash)
        assert restored.result_hash == result.result_hash
        assert restored.execution_data is prepared.execution_data
        for original, recovered in zip(result.runs, restored.runs, strict=True):
            assert recovered.signals.strategy_source is prepared.strategy
            assert recovered.observation == original.observation
            for name in ("decisions", "orders", "fills", "account_daily", "trades"):
                pd.testing.assert_frame_equal(getattr(original.execution, name), getattr(recovered.execution, name))
            pd.testing.assert_frame_equal(original.signals.decisions, recovered.signals.decisions)
        evidence = serialize_evaluation_evidence(prepared, restored)
        validate_evaluation_evidence(evidence)
        assert evidence == serialize_evaluation_evidence(prepared, result)
        with pytest.raises(CheckpointIntegrityError, match="prepared request differs"):
            load_result(store, replace(prepared, initial_cash=200_000), result.request_hash)
        path = store.root / "results" / f"{result.request_hash}.json"
        value = json.loads(path.read_bytes())
        value["payload"]["fields"]["result_hash"] = "b" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(CheckpointIntegrityError, match="checksum"):
            load_result(store, prepared, result.request_hash)
    with pytest.raises(CheckpointIntegrityError, match="implementation identity"):
        CheckpointStore(root, experiment, "account", "RESUME", "b" * 64)


def test_publication_resume_rechecks_actual_evidence_and_preserves_completed_fact(tmp_path):
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


def test_codec_retains_frame_precision_missing_values_dtypes_and_index():
    frame = pd.DataFrame({
        "binary64": [0.12345678901234567, float("nan"), float("inf")],
        "nullable": pd.Series([1, pd.NA, 3], dtype="Int64"),
        "text": pd.Series(["甲", pd.NA, "乙"], dtype="string"),
        "time": pd.to_datetime(["2026-10-22 11:00:00.123456789", None, "2026-10-23"], format="mixed"),
        "kind": pd.Categorical(["a", None, "b"], categories=["b", "a"], ordered=True),
    })
    frame.index = pd.date_range("2026-10-22", periods=3, tz="Asia/Shanghai", name="session")
    frame.attrs = {"labels": ("x", "y")}
    payload = json.loads(json.dumps(encode(frame), allow_nan=False))
    pd.testing.assert_frame_equal(frame, decode(payload, None))
    empty = frame.iloc[:0]
    pd.testing.assert_frame_equal(empty, decode(encode(empty), None))
    with pytest.raises(TypeError, match="unsupported checkpoint value"):
        encode(object())
    with pytest.raises(ValueError, match="unapproved"):
        decode({"tag": "record", "type": "os.system", "fields": {}}, None)


def test_codec_preserves_unavailable_observation_plan_identity_and_failure():
    from datetime import date
    from strategy_runtime import StrategyIdentity, ObservationUnavailable
    from czsc_trader.backtesting.observation import UnavailablePlanObservation
    from czsc_trader.backtesting.models import StrategyIdentity as AccountIdentity
    from czsc_trader.backtesting.result import BacktestResult

    observed = UnavailablePlanObservation(
        StrategyIdentity("S900", "S900-C0001", "a" * 64, "b" * 64, "159326.SZ"),
        "c" * 64, "d" * 64, "e" * 64, date(2026, 10, 20), date(2026, 10, 21), "BUY", 1.0,
        ObservationUnavailable("missing observation condition", "strategy_observation.v4"),
    )
    payload = json.loads(json.dumps(encode(observed), allow_nan=False))
    assert decode(payload, None) == observed
    assert payload["value"]["contract_version"] == "tdr_plan_observation.v1"
    assert payload["value"]["observation"]["status"] == "UNAVAILABLE"
    assert "series" not in payload["value"] and "facts" not in payload["value"]
    result = BacktestResult(AccountIdentity("CANDIDATE", "S900-C0001", "synthetic"),
                            *(pd.DataFrame() for _ in range(5)), observations=(observed,))
    restored = decode(json.loads(json.dumps(encode(result), allow_nan=False)), None)
    assert restored.observations == (observed,)
    assert restored.identity == result.identity
    for field, invalid in (
        ("contract_version", "strategy_observation.v4"),
        ("plan_identity", "invalid"), ("signal_date", "2026-10-21"),
        ("action", ""), ("target_position", True), ("target_position", 1.1),
        ("target_position", float("nan")),
        ("observation", {**observed.unavailable.to_dict(), "status": "READY"}),
    ):
        changed = {**payload, "value": {**payload["value"], field: invalid}}
        with pytest.raises((ValueError, TypeError)):
            decode(changed, None)
    with pytest.raises(ValueError, match="envelope"):
        decode({**payload, "value": {**payload["value"], "series": []}}, None)
    with pytest.raises(ValueError, match="checkpoint"):
        decode({**payload, "extra": True}, None)
    with pytest.raises(TypeError, match="typed identity and failure"):
        replace(observed, unavailable={"status": "UNAVAILABLE"})


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "CON", "trailing."])
def test_checkpoint_paths_are_scoped(tmp_path, run_id):
    with pytest.raises(ValueError):
        CheckpointStore(tmp_path, ExperimentRef("S900", "EX001_20261022"), run_id, "CREATE", "a" * 64)


def test_checkpoint_create_resume_and_closed_state_are_explicit(tmp_path):
    experiment = ExperimentRef("S900", "EX001_20261022")
    with pytest.raises(FileNotFoundError):
        CheckpointStore(tmp_path, experiment, "missing", "RESUME", "a" * 64)
    store = CheckpointStore(tmp_path, experiment, "run", "CREATE", "a" * 64)
    store.close()
    with pytest.raises(FileExistsError):
        CheckpointStore(tmp_path, experiment, "run", "CREATE", "a" * 64)
    with pytest.raises(RuntimeError, match="closed"):
        store.load_publication("b" * 64)
    with CheckpointStore(tmp_path, experiment, "run", "RESUME", "a" * 64) as resumed:
        # A parent interrupted before atomic rename has not completed publication.
        partial = resumed.root / "publications" / f"{'b' * 64}.json.interrupted.pending"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"incomplete")
        assert resumed.load_publication("b" * 64) is None
    (store.root / "manifest.json").write_text("truncated", encoding="utf-8")
    with pytest.raises(CheckpointIntegrityError, match="authenticate"):
        CheckpointStore(tmp_path, experiment, "run", "RESUME", "a" * 64)


def load_result(store, request, request_hash):
    # Codec fixtures authenticate once at this boundary. Live execution passes
    # the immutable contract from its session-owned preparation handle.
    from czsc_trader.research_tools.evaluation import _request_contract
    return store.load_result(request, request_hash, contract=_request_contract(request)[0])
