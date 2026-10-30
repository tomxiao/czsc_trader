"""Explicit, single-writer checkpoints for completed calculation and publication.

These are disposable caches under .tmp, never formal research evidence. Recovery
requires a freshly prepared request and the same implementation identity.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from strategy_manager.write_lock import RegistryWriteLock
from strategy_runtime import canonical_sha256

from ._evaluation_codec import decode, encode
from ._records import _hash, _path
from .context import ExperimentRef
from .evidence import EvidenceRef, managed_path


class CheckpointIntegrityError(ValueError):
    """A cache exists but its identity, content or schema cannot be trusted."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _unique_object(items):
    value = dict(items)
    if len(value) != len(items):
        raise CheckpointIntegrityError("duplicate checkpoint JSON keys")
    return value


class CheckpointStore:
    def __init__(self, repository_root: Path, experiment: ExperimentRef, run_id: str,
                 mode, implementation_identity: str):
        if type(experiment) is not ExperimentRef:
            raise TypeError("checkpoint requires ExperimentRef")
        _path(run_id)
        if "/" in run_id or len(run_id) > 100:
            raise ValueError("checkpoint run_id must be one short path component")
        _hash(implementation_identity)
        mode = getattr(mode, "value", mode)
        if mode not in ("CREATE", "RESUME"):
            raise ValueError("checkpoint mode requires CREATE or RESUME")
        self.repository_root = Path(repository_root).resolve()
        self.experiment = experiment
        self.relative = f".tmp/research-execution/{experiment.strategy_id}/{run_id}"
        self.root = managed_path(self.repository_root, self.relative)
        self._closed = True
        self._lock = None
        if mode == "CREATE":
            self.root.mkdir(parents=True, exist_ok=False)
        elif not self.root.is_dir():
            raise FileNotFoundError("checkpoint run does not exist for RESUME")
        managed_path(self.repository_root, f"{self.relative}/.registry.lock")
        self._lock = RegistryWriteLock(self.root).hold()
        self._lock.__enter__()
        self._closed = False
        manifest = {"schema_version": 1, "experiment": experiment.to_dict(),
                    "run_id": run_id, "implementation_identity": implementation_identity}
        try:
            if mode == "CREATE":
                self._write("manifest.json", manifest)
            elif self._read("manifest.json", required=True) != manifest:
                raise CheckpointIntegrityError("checkpoint experiment or implementation identity differs")
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self._closed:
            self._closed = True
            self._lock.__exit__(None, None, None)

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()

    def _require_open(self):
        if self._closed:
            raise RuntimeError("checkpoint store is closed")

    def _target(self, name):
        self._require_open()
        return managed_path(self.repository_root, f"{self.relative}/{name}")

    def _read(self, name, *, required=False):
        path = self._target(name)
        if not path.exists():
            if required:
                raise CheckpointIntegrityError(f"checkpoint record is missing: {name}")
            return None
        try:
            envelope = json.loads(path.read_bytes(), object_pairs_hook=_unique_object,
                                  parse_constant=lambda value: (_ for _ in ()).throw(
                                      CheckpointIntegrityError(f"invalid JSON constant: {value}")))
            if type(envelope) is not dict or set(envelope) != {"sha256", "payload"}:
                raise CheckpointIntegrityError("checkpoint envelope differs")
            if sha256(_json(envelope["payload"])).hexdigest() != envelope["sha256"]:
                raise CheckpointIntegrityError("checkpoint content checksum differs")
            return envelope["payload"]
        except (OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
            raise CheckpointIntegrityError(f"cannot authenticate checkpoint {name}: {exc}") from exc

    def _write(self, name, payload):
        target = self._target(name)
        encoded = _json({"sha256": sha256(_json(payload)).hexdigest(), "payload": payload})
        if target.exists():
            if self._read(name, required=True) != payload:
                raise CheckpointIntegrityError("completed checkpoint cannot be replaced with different facts")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._target(f"{name}.{uuid4().hex}.pending")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def save_result(self, request_hash: str, result):
        from .evaluation import EvaluationResult, _evaluation_result_hash

        _hash(request_hash)
        if type(result) is not EvaluationResult or result.request_hash != request_hash:
            raise CheckpointIntegrityError("checkpoint result request identity differs")
        if _evaluation_result_hash(request_hash, result.runs) != result.result_hash:
            raise CheckpointIntegrityError("checkpoint result numeric hash differs")
        self._write(f"results/{request_hash}.json", encode(result))

    def load_result(self, request, request_hash: str):
        from .evaluation import EvaluationResult, _evaluation_result_hash, _request_contract

        _hash(request_hash)
        contract, binding_hash = _request_contract(request)
        if canonical_sha256(contract) != request_hash:
            raise CheckpointIntegrityError("prepared request differs from checkpoint lookup identity")
        if (Path(request.repository_root).resolve() != self.repository_root
                or request.experiment_id != self.experiment.experiment_id
                or request.strategy.strategy_family_id != self.experiment.strategy_id):
            raise CheckpointIntegrityError("prepared request belongs to another checkpoint experiment")
        payload = self._read(f"results/{request_hash}.json")
        if payload is None:
            return None
        try:
            result = decode(payload, request)
            if type(result) is not EvaluationResult or (
                result.request_hash, result.strategy_identity, result.runtime_binding_hash,
                result.data_identity, result.execution_mode,
            ) != (request_hash, request.strategy.runtime_identity_sha256, binding_hash,
                  request.execution_data.fingerprint, request.execution_mode):
                raise CheckpointIntegrityError("checkpoint result metadata differs from prepared request")
            if _evaluation_result_hash(request_hash, result.runs) != result.result_hash:
                raise CheckpointIntegrityError("checkpoint result numeric hash differs")
            return result
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise CheckpointIntegrityError(f"cannot restore checkpoint result: {exc}") from exc

    def save_equity_result(self, request_hash, result):
        from ._equity_checkpoint import encode_result
        _hash(request_hash)
        if result.request_hash != request_hash:
            raise CheckpointIntegrityError("equity checkpoint request differs")
        self._write(f"results/{request_hash}.json", encode_result(result))

    def load_equity_result(self, request, request_hash):
        from ._equity_checkpoint import decode_result
        from .equity_replay_v3 import PreparedEquityEvaluation
        if type(request) is not PreparedEquityEvaluation:
            raise TypeError("equity checkpoint restore requires session-owned V3 preparation")
        request = request.request
        _hash(request_hash)
        if request.experiment != self.experiment or not request.formal or request.prepared is None:
            raise CheckpointIntegrityError("equity checkpoint requires the same prepared experiment")
        payload = self._read(f"results/{request_hash}.json")
        if payload is None:
            return None
        try:
            return decode_result(payload, request_hash)
        except (TypeError, KeyError, ValueError) as exc:
            raise CheckpointIntegrityError(f"cannot restore equity checkpoint: {exc}") from exc

    def save_publication(self, publication_key: str, reference: EvidenceRef):
        """Key must bind request, result, experiment and publication name/schema."""
        _hash(publication_key)
        if type(reference) is not EvidenceRef or reference.experiment != self.experiment:
            raise CheckpointIntegrityError("publication reference belongs to another experiment")
        reference.resolve(self.repository_root)
        self._write(f"publications/{publication_key}.json",
                    {"publication_key": publication_key, "reference": reference.to_dict()})

    def load_publication(self, publication_key: str):
        _hash(publication_key)
        payload = self._read(f"publications/{publication_key}.json")
        if payload is None:
            return None
        try:
            if (type(payload) is not dict or set(payload) != {"publication_key", "reference"}
                    or payload["publication_key"] != publication_key):
                raise CheckpointIntegrityError("checkpoint publication lookup identity differs")
            reference = EvidenceRef.from_dict(payload["reference"])
            if reference.experiment != self.experiment:
                raise CheckpointIntegrityError("publication reference belongs to another experiment")
            reference.resolve(self.repository_root)
            return reference
        except (ValueError, TypeError, FileNotFoundError) as exc:
            raise CheckpointIntegrityError(f"checkpoint published evidence cannot be verified: {exc}") from exc
