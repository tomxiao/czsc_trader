"""Navigate retained research metadata without expanding evidence payloads."""
from datetime import datetime, timezone
from hashlib import sha256
import json

from strategy_manager import StrategyFamily
from .context import RepositoryContext
from ..research_tools import delivery as d
from ..research_tools.context import ExperimentRef, ResearchBatchRef
from ..research_tools.evidence import EvidenceRef, managed_path
from ..research_tools.experiment_artifacts import ExperimentReportSnapshot
from ..research_tools.overview import (
    DeliveryMetadataState, DeliveryOverview, ExperimentOverview, ExperimentReportState,
    OverviewLimitation, ResearchOverview, ResearchOverviewError,
    ResearchSnapshot, ResearchSourceKind, ResearchSourceRef,
)


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


class _ReadSnapshot:
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.directories = {}

    def read(self, relative, *, optional=False):
        path = managed_path(self.root, relative)
        if path.exists() and not path.is_file():
            raise ValueError(f"expected a file: {relative}")
        data = path.read_bytes() if path.exists() else None
        if data is None and not optional:
            raise FileNotFoundError(relative)
        observation = None if data is None else (sha256(data).hexdigest(), len(data))
        if relative in self.files and self.files[relative] != observation:
            raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "file changed during overview")
        self.files[relative] = observation
        return data

    def listing(self, relative):
        path = managed_path(self.root, relative)
        if path.exists() and not path.is_dir():
            raise ValueError(f"expected a directory: {relative}")
        result = tuple(sorted((child.name, child.is_dir()) for child in path.iterdir())) if path.exists() else None
        if relative in self.directories and self.directories[relative] != result:
            raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "directory changed during overview")
        self.directories[relative] = result
        for name, _ in result or ():
            managed_path(self.root, f"{relative}/{name}")
        return result or ()

    def source(self, relative):
        if relative in self.files:
            observation = self.files[relative]
            digest = sha256(b"").hexdigest() if observation is None else observation[0]
            return ResearchSourceRef(relative, digest, ResearchSourceKind.FILE, observation is not None)
        return ResearchSourceRef(relative, d._digest(self.directories[relative]), ResearchSourceKind.DIRECTORY, self.directories[relative] is not None)

    def finish(self):
        for relative, expected in self.files.items():
            path = managed_path(self.root, relative)
            if path.exists() and not path.is_file():
                raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "file kind changed during overview")
            actual = None
            if path.is_file():
                digest = sha256()
                size = 0
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                actual = (digest.hexdigest(), size)
            if actual != expected:
                raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "file changed during overview")
        for relative, expected in self.directories.items():
            path = managed_path(self.root, relative)
            if path.exists() and not path.is_dir():
                raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "directory kind changed during overview")
            actual = tuple(sorted((x.name, x.is_dir()) for x in path.iterdir())) if path.is_dir() else None
            if actual != expected:
                raise ResearchOverviewError("CONCURRENT_CHANGE", relative, "directory changed during overview")
            for name, _ in actual or ():
                # Unread navigation targets (e.g. a delivery report) can become
                # links without changing the observed name/is_dir pair.
                child = f"{relative}/{name}"
                try:
                    managed_path(self.root, child)
                except ValueError as exc:
                    raise ResearchOverviewError("CONCURRENT_CHANGE", child, "directory entry became unsafe") from exc
        return tuple(self.source(name) for name in sorted(self.files.keys() | self.directories.keys()))


def _evidence(reader, batch, reference):
    if reference.experiment.strategy_id != batch.strategy_id:
        raise ValueError("reference belongs to another batch")
    data = reader.read(reference.repository_path)
    # read() already hashed these exact bytes; no second hash or payload traversal.
    if reader.source(reference.repository_path).sha256 != reference.sha256:
        raise ValueError(f"evidence hash differs: {reference.repository_path}")
    return data


def _experiments(reader, batch):
    result = []
    parent = f"research/{batch.strategy_id}/experiments"
    for name, is_dir in reader.listing(parent):
        if not is_dir:
            raise ValueError(f"unexpected experiment entry: {name}")
        reference = ExperimentRef(batch.strategy_id, name)
        metadata = f"{reference.repository_path}/experiment.json"
        if ExperimentRef.from_dict(_json(reader.read(metadata))) != reference:
            raise ValueError("experiment identity differs from directory")
        report = reader.read(f"{reference.repository_path}/report.md", optional=True)
        pointer = reader.read(f"{reference.repository_path}/report_ref.json", optional=True)
        published = None
        outcome = None
        state = ExperimentReportState.MISSING if report is None else ExperimentReportState.DRAFT
        if pointer is not None:
            value = _json(pointer)
            if type(value) is not dict or set(value) != {"schema_version", "report"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError("unsupported experiment report pointer schema")
            published = EvidenceRef.from_dict(value["report"])
            if published.experiment != reference or (published.schema, published.schema_version) != ("experiment_report", 1):
                raise ValueError("report pointer identity differs")
            saved = ExperimentReportSnapshot.from_dict(_json(_evidence(reader, batch, published)))
            if saved.experiment != reference:
                raise ValueError("report snapshot experiment differs")
            outcome = saved.outcome
            state = ExperimentReportState.PUBLISHED if report == saved.report.encode("utf-8") else ExperimentReportState.UNPUBLISHED_CHANGES
        result.append(ExperimentOverview(reference, state, published, outcome, reader.source(metadata)))
    return tuple(result)


def _delivery_revisions(reader, parent):
    result = {}
    for name, directory in reader.listing(parent):
        stage = d.DeliveryStage(name)
        if not directory:
            raise ValueError("delivery stage must be a directory")
        revisions = set()
        for revision, is_dir in reader.listing(f"{parent}/{name}"):
            if not is_dir or not revision.isdecimal() or str(int(revision)) != revision or int(revision) < 1:
                raise ValueError("invalid delivery revision")
            revisions.add(int(revision))
        result[stage] = revisions
    return result


def _deliveries(reader, batch, limitations):
    public_parent = f"research/{batch.strategy_id}/deliveries"
    retained_parent = f"research/{batch.strategy_id}/assets/deliveries"
    public = _delivery_revisions(reader, public_parent)
    retained = _delivery_revisions(reader, retained_parent)
    result = []
    for stage in sorted(public.keys() | retained.keys()):
        revisions = public.get(stage, set()) | retained.get(stage, set())
        if not revisions:
            continue
        revision = max(revisions)
        public_path = f"{public_parent}/{stage.value}/{revision}"
        retained_path = f"{retained_parent}/{stage.value}/{revision}"
        public_receipt = f"{public_path}/receipt.json"
        data = reader.read(public_receipt)
        if data != reader.read(f"{retained_path}/receipt.json"):
            raise ValueError("public delivery receipt differs")
        raw = _json(data)
        if type(raw) is not dict or type(raw.get("schema_version")) is not int:
            raise ValueError("delivery receipt requires an explicit schema version")
        reference = None
        state = DeliveryMetadataState.UNSUPPORTED
        if raw["schema_version"] not in d._readable_schema_versions(stage):
            limitations.append(OverviewLimitation("UNSUPPORTED_DELIVERY_SCHEMA", public_receipt,
                "Latest receipt schema is unsupported; no older revision is substituted and no payload is inspected."))
        else:
            receipt = d.DeliveryReceipt.from_dict(raw)
            reference = receipt.reference
            if (reference.batch, reference.stage, reference.revision) != (batch, stage, revision):
                raise ValueError("delivery receipt directory identity differs")
            if d._digest(receipt.files) != reference.content_sha256:
                raise ValueError("delivery receipt manifest identity differs")
            for entry in receipt.files:
                d._path(entry.path)
                d._hash(entry.sha256)
            required = {"delivery.json", "report.md"}
            if not required <= {entry.path for entry in receipt.files}:
                raise ValueError("delivery receipt lacks required file declarations")
            state = DeliveryMetadataState.READABLE
        # Observe the report's directory entry, not its content. Integrity belongs
        # to validate_delivery, including delivery.json and all declared files.
        if set(reader.listing(public_path)) != {("receipt.json", False), ("report.md", False)}:
            raise ValueError("public delivery navigation files differ")
        result.append(DeliveryOverview(stage, revision, reference, f"{public_path}/report.md",
                                       state, reader.source(public_receipt)))
    return tuple(result)


def get_research_overview(repository: RepositoryContext, batch: ResearchBatchRef) -> ResearchOverview:
    """Read current task sources, report metadata and latest delivery receipts.

    Only the returned metadata source set is authenticated. Evidence payloads,
    historical delivery contents, accounts and candidate registries are not read.
    This is not report/phase acceptance, authorization or runtime certification.
    """
    if type(repository) is not RepositoryContext or type(batch) is not ResearchBatchRef:
        raise TypeError("overview requires RepositoryContext and ResearchBatchRef")
    reader = _ReadSnapshot(repository.root)
    path = f"research/{batch.strategy_id}/batch.json"
    try:
        if ResearchBatchRef.from_dict(_json(reader.read(path))) != batch:
            raise ValueError("batch identity differs")
        family_path = f"research/registrations/{batch.strategy_id}/family.json"
        family = StrategyFamily.from_dict(_json(reader.read(family_path)))
        if family.strategy_id != batch.strategy_id:
            raise ValueError("family identity differs")
        handoff_path = f"research/{batch.strategy_id}/HANDOFF.md"
        reader.read(handoff_path, optional=True)
        task_sources = (reader.source(family_path), reader.source(handoff_path))
        limitations = [OverviewLimitation("METADATA_ONLY", path,
            "Only listed metadata is checked. Report status describes its own publication snapshot; linked evidence, delivery contents, accounts, candidates and authorization are not certified.")]
        experiments = _experiments(reader, batch)
        deliveries = _deliveries(reader, batch, limitations)
        sources = reader.finish()
        snapshot = ResearchSnapshot(d._digest(sources), datetime.now(timezone.utc).isoformat(), sources)
        return ResearchOverview(batch, snapshot, family.research_state, task_sources,
                                deliveries, experiments, tuple(limitations))
    except ResearchOverviewError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ResearchOverviewError("INVALID_RETAINED_RECORD", path, str(exc)) from exc
