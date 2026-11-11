"""Explicit, single-writer checkpoints for completed calculation and publication.

These are disposable caches under .tmp, never formal research evidence. Recovery
requires a freshly prepared request and the same implementation identity.
"""

from __future__ import annotations

from collections import OrderedDict
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from strategy_manager.write_lock import RegistryWriteLock

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


def _file_identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


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
        self._installed_blobs = {}
        # Bound decoded byte retention: current input, benchmark and adjacent
        # candidate results. Never retain the entire experiment's accounts.
        self._loaded_artifacts = OrderedDict()
        if mode == "CREATE":
            self.root.mkdir(parents=True, exist_ok=False)
        elif not self.root.is_dir():
            raise FileNotFoundError("checkpoint run does not exist for RESUME")
        managed_path(self.repository_root, f"{self.relative}/.registry.lock")
        self._lock = RegistryWriteLock(self.root).hold()
        self._lock.__enter__()
        self._closed = False
        manifest = {"schema_version": 2, "experiment": experiment.to_dict(),
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
            self._installed_blobs.clear()
            self._loaded_artifacts.clear()
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
        if target.exists():
            if self._read(name, required=True) != payload:
                raise CheckpointIntegrityError("completed checkpoint cannot be replaced with different facts")
            return
        body = _json(payload)
        # Encode the metadata once; preserve the canonical envelope bytes.
        encoded = b'{"payload":' + body + b',"sha256":"' + sha256(body).hexdigest().encode('ascii') + b'"}'
        self._write_bytes(name, encoded)

    def _write_bytes(self, name: str, content: bytes) -> None:
        """Durably install immutable bytes; never replace an existing fact."""
        if type(content) is not bytes or not content:
            raise TypeError('checkpoint content requires nonempty bytes')
        target = self._target(name)
        if target.exists():
            before = _file_identity(target)
            if target.read_bytes() != content:
                raise CheckpointIntegrityError('completed checkpoint cannot be replaced with different facts')
            if _file_identity(target) != before:
                raise CheckpointIntegrityError('checkpoint changed while reading')
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._target(f"{name}.{uuid4().hex}.pending")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            # Atomic create-without-replace, also under external filesystem races.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != content:
                    raise CheckpointIntegrityError('completed checkpoint cannot be replaced with different facts') from None
        finally:
            temporary.unlink(missing_ok=True)

    def _save_blob(self, digest: str, content: bytes) -> None:
        _hash(digest)
        target = self._target(f'blobs/{digest}.json')
        cached = self._installed_blobs.get(digest)
        if cached is not None and target.exists() and _file_identity(target) == cached:
            return
        self._write_bytes(f'blobs/{digest}.json', content)
        self._installed_blobs[digest] = _file_identity(target)

    def _read_blob(self, digest: str) -> bytes:
        _hash(digest)
        target = self._target(f'blobs/{digest}.json')
        before = _file_identity(target)
        content = target.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise CheckpointIntegrityError('cannot authenticate checkpoint blob content')
        if _file_identity(target) != before:
            raise CheckpointIntegrityError('checkpoint blob changed while reading')
        self._installed_blobs[digest] = before
        return content

    def publication_blob(self, digest: str, content: bytes) -> Path:
        """Return the exact saved bytes for an explicit evidence publication."""
        _hash(digest)
        if type(content) is not bytes or not content:
            raise TypeError('publication blob requires nonempty bytes')
        target = self._target(f'blobs/{digest}.json')
        before = _file_identity(target)
        if self._installed_blobs.get(digest) != before:
            if self._read_blob(digest) != content:
                raise CheckpointIntegrityError('checkpoint publication bytes differ')
        return target


    def save_equity_result(self, request_hash, result):
        from ._equity_checkpoint import encode_result
        _hash(request_hash)
        if result.request_hash != request_hash:
            raise CheckpointIntegrityError("equity checkpoint request differs")
        payload = encode_result(result)
        # Commit dependencies first. An interrupted result commit can leave an
        # unused object, but cannot expose a completed result without its bytes.
        for artifact in result.artifacts:
            self._save_blob(artifact.sha256, artifact.content)
        self._save_blob(result.result_hash, result.content)
        self._write(f"results/{request_hash}.json", payload)

    def _load_equity_artifact(self, kind, digest):
        from .equity_evaluation import EquityArtifact
        _hash(digest)
        name = f"blobs/{digest}.json"
        target = self._target(name)
        key = (kind, digest)
        cached = self._loaded_artifacts.get(key)
        if cached is not None and target.exists() and _file_identity(target) == cached[0]:
            self._loaded_artifacts.move_to_end(key)
            return cached[1]
        before = _file_identity(target) if target.exists() else None
        artifact = EquityArtifact(kind, self._read_blob(digest))
        if artifact.sha256 != digest:
            raise CheckpointIntegrityError("equity checkpoint artifact bytes differ")
        after = _file_identity(target)
        if before != after:
            raise CheckpointIntegrityError("checkpoint artifact changed while reading")
        self._loaded_artifacts[key] = (after, artifact)
        self._loaded_artifacts.move_to_end(key)
        while len(self._loaded_artifacts) > 4:
            self._loaded_artifacts.popitem(last=False)
        return artifact

    def load_equity_result(self, request, request_hash):
        from ._equity_checkpoint import decode_result
        from .equity_replay import PreparedAccountEvaluation
        if type(request) is not PreparedAccountEvaluation:
            raise TypeError("equity checkpoint restore requires session-owned V4 preparation")
        request = request.request
        _hash(request_hash)
        if request.experiment != self.experiment or request.prepared is None:
            raise CheckpointIntegrityError("equity checkpoint requires the same prepared experiment")
        payload = self._read(f"results/{request_hash}.json")
        if payload is None:
            return None
        try:
            return decode_result(payload, request_hash, self._load_equity_artifact, self._read_blob)
        except (OSError, TypeError, KeyError, ValueError, AttributeError) as exc:
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
