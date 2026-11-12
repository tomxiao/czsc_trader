"""Call-scoped, streaming equity source reads for selection stability.

Shared byte budgets count serialized input/benchmark bytes, not Python memory.
Candidates are returned to the caller and never retained by this reader.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from time import perf_counter

from ..research_tools.evidence import EvidenceRef, managed_path
from ..research_tools.equity_evaluation import EQUITY_EVIDENCE_VERSIONS
from ..research_tools.equity_replay import (
    _read, decoded_equity_runs, equity_artifact_fields, primary_input_digest, validate_result_structure,
)


class SelectionSourceBudgetError(ValueError):
    """The complete requested source set exceeds an explicit byte budget."""


@dataclass(slots=True)
class SelectionSourceStatistics:
    # Actual read attempts / successfully read bytes and JSON decode attempts.
    read_count: int = 0
    source_bytes: int = 0
    decode_count: int = 0
    read_seconds: float = 0.
    decode_seconds: float = 0.
    # Serialized size of unique cached input/benchmark content, not resident memory.
    shared_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ResolvedSelectionSource:
    source: EvidenceRef
    header: dict
    inputs: dict
    candidate_run: dict
    benchmark_run: dict | None
    primary_input_sha256: str


class SelectionSourceReader:
    """Prepare all sources, then consume each unique source once.

    Decoded shared dictionaries are internal read-only views by convention: callers
    must project facts without modifying them. ``close`` ends their cache lifetime.
    Repeated sources must reuse projected facts in the caller, never reread ledgers.
    """

    def __init__(self, root: Path, *, max_source_bytes: int, max_shared_bytes: int):
        for value in (max_source_bytes, max_shared_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("selection source byte budgets must be positive integers")
        self.root = Path(root)
        self.max_source_bytes = max_source_bytes
        self.max_shared_bytes = max_shared_bytes
        self.stats = SelectionSourceStatistics()
        self._headers = {}
        self._failures = {}
        self._verified = {}
        self._shared = {}
        self._primary = {}
        self._consumed = set()
        self._prepared = False
        self._closed = False

    @staticmethod
    def _key(source):
        if type(source) is not EvidenceRef:
            raise TypeError("selection source requires EvidenceRef")
        return source.repository_path

    def _decode(self, content):
        start = perf_counter()
        self.stats.decode_count += 1
        try:
            result = _read(content)
            if type(result) is not dict:
                raise ValueError("equity source document must be an object")
            return result
        finally:
            self.stats.decode_seconds += perf_counter() - start

    @staticmethod
    def _require_mapping(value, name):
        if type(value) is not dict:
            raise ValueError(f"equity source {name} must be an object")

    def _header_shape(self, header):
        # Necessary access shapes only: no historical audit or numerical certification.
        for name in ("request", "evaluation_identity", "data"):
            self._require_mapping(header[name], name)
        self._require_mapping(header["request"]["candidate_definition"], "candidate_definition")
        if header["benchmark_identity"] is not None:
            self._require_mapping(header["benchmark_identity"], "benchmark_identity")
            self._require_mapping(header["benchmark_identity"]["definition"], "benchmark definition")

    def _read_file(self, relative, digest):
        path = managed_path(self.root, relative)
        key = str(path)
        if key in self._verified:
            known = self._verified[key]
            if isinstance(known, Exception):
                raise known
            if known != digest:
                raise ValueError("conflicting identity for the same equity source path")
            return None
        start = perf_counter()
        try:
            size = path.stat().st_size
            if self.stats.source_bytes + size > self.max_source_bytes:
                raise SelectionSourceBudgetError("selection source byte budget exceeded")
            self.stats.read_count += 1
            content = path.read_bytes()
            self.stats.source_bytes += len(content)
            if self.stats.source_bytes > self.max_source_bytes:
                raise SelectionSourceBudgetError("selection source byte budget exceeded")
            if sha256(content).hexdigest() != digest:
                raise ValueError("published equity source checksum differs")
            self._verified[key] = digest
            return content
        except Exception as error:
            self._verified[key] = error
            raise
        finally:
            self.stats.read_seconds += perf_counter() - start

    def prepare(self, sources: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
        if self._prepared or self._closed:
            raise RuntimeError("selection source reader is already prepared or closed")
        if type(sources) is not tuple or not sources:
            raise TypeError("selection source preparation requires a nonempty tuple")
        unique = {}
        for source in sources:
            key = self._key(source)
            if key in unique and unique[key].sha256 != source.sha256:
                raise ValueError("conflicting equity source identity")
            unique.setdefault(key, source)
        sizes = {}
        shared_sizes = {}
        # Metadata-only planning includes every readable dependency before ledgers load.
        for key, source in unique.items():
            try:
                if (source.schema != "equity_research" or source.schema_version not in EQUITY_EVIDENCE_VERSIONS
                        or source.media_type != "application/json"):
                    raise ValueError("selection source requires supported JSON equity evidence")
                path = managed_path(self.root, key)
                sizes[str(path)] = path.stat().st_size
                header = self._decode(self._read_file(key, source.sha256))
                self._header_shape(header)
                validate_result_structure(header)
                if header["schema_version"] != source.schema_version:
                    raise ValueError("selection account evidence version differs")
                self._headers[key] = header
                for name, _ in equity_artifact_fields(header):
                    digest = header[name]["sha256"]
                    relative = (PurePosixPath(key).parent / (digest + ".json")).as_posix()
                    dependency = managed_path(self.root, relative)
                    size = dependency.stat().st_size
                    sizes[str(dependency)] = size
                    if name != "candidate_ref":
                        shared_sizes[digest] = size
            except SelectionSourceBudgetError:
                raise
            except (OSError, ValueError, TypeError, KeyError) as error:
                self._failures[key] = error
        if sum(sizes.values()) > self.max_source_bytes:
            raise SelectionSourceBudgetError("selection source byte budget exceeded")
        if sum(shared_sizes.values()) > self.max_shared_bytes:
            raise SelectionSourceBudgetError("selection shared byte budget exceeded")
        self._prepared = True
        return tuple(unique.values())

    def _dependency(self, source, reference, *, shared):
        digest = reference["sha256"]
        relative = (PurePosixPath(source.repository_path).parent / (digest + ".json")).as_posix()
        content = self._read_file(relative, digest)
        if shared and digest in self._shared:
            return self._shared[digest]
        if content is None:
            raise ValueError("candidate source was already consumed; reuse its projected facts")
        if shared and self.stats.shared_bytes + len(content) > self.max_shared_bytes:
            raise SelectionSourceBudgetError("selection shared byte budget exceeded")
        value = self._decode(content)
        if shared:
            self._shared[digest] = value
            self.stats.shared_bytes += len(content)
        return value

    @property
    def unique_benchmark_count(self):
        """Known unique benchmark accounts plus one slot per failed header."""
        if not self._prepared or self._closed:
            raise RuntimeError("selection source reader must be prepared and open")
        known = {header["benchmark_ref"]["sha256"] for key, header in self._headers.items()
            if key not in self._failures and header["benchmark_ref"] is not None}
        return len(known) + len(self._failures)

    def read(self, source: EvidenceRef) -> ResolvedSelectionSource:
        if not self._prepared or self._closed:
            raise RuntimeError("selection source reader must be prepared and open")
        key = self._key(source)
        if key in self._consumed:
            raise ValueError("selection source already consumed; reuse its projected facts")
        self._consumed.add(key)
        if key in self._failures:
            raise self._failures[key]
        if key not in self._headers:
            raise ValueError("selection source was not prepared")
        header = self._headers[key]
        inputs = self._dependency(source, header["input_ref"], shared=True)
        benchmark_ref = header["benchmark_ref"]
        benchmark = None if benchmark_ref is None else self._dependency(source, benchmark_ref, shared=True)
        candidate = self._dependency(source, header["candidate_ref"], shared=False)
        for name in ("products", "data"):
            self._require_mapping(inputs[name], f"input {name}")
        for name, account in (("candidate", candidate), ("benchmark", benchmark)):
            if account is None:
                continue
            self._require_mapping(account["owner"], f"{name} owner")
            self._require_mapping(account["run"], f"{name} run")
        digest = header["input_ref"]["sha256"]
        if digest not in self._primary:
            self._primary[digest] = primary_input_digest(inputs)
        primary = self._primary[digest]
        runs = decoded_equity_runs(header, inputs, candidate, benchmark, primary_sha256=primary)
        return ResolvedSelectionSource(source, header, inputs, runs["candidate"], runs.get("buy_hold"), primary)

    def close(self):
        self._headers.clear()
        self._shared.clear()
        self._primary.clear()
        self._failures.clear()
        self._verified.clear()
        self._consumed.clear()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
