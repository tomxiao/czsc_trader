"""Read retained batch facts without strategy replay or semantic research decisions."""

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json

from strategy_manager import CandidateKey, CandidateRegistration, StrategyFamily

from .context import RepositoryContext
from ..research_tools import delivery as d
from ..research_tools.context import ExperimentRef, ResearchBatchRef
from ..research_tools.evidence import EvidenceRef, managed_path
from ..research_tools.experiment_artifacts import ExperimentReportSnapshot
from ..research_tools.evaluation import EvaluationIdentity
from ..research_tools.overview import (
    CandidateHandoffOverview, CandidateOverview, ComponentPanelOverview, CountBasis,
    DeliveryOverview, ExperimentOverview, ExperimentReportState, OverviewLimitation,
    ResearchCount, ResearchCountKind, ResearchOverview, ResearchOverviewError,
    ResearchSnapshot, ResearchSourceKind, ResearchSourceRef, SearchOverview,
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

    def authenticate(self, relative, expected_sha256):
        """Reuse a path observation; finish reauthenticates every observed path.

        Repeated references must agree on the expected identity. Keep hashes,
        rather than large evidence bodies, for the duration of this request.
        """
        if relative not in self.files:
            self.read(relative)
        observation = self.files[relative]
        if observation is None or observation[0] != expected_sha256:
            raise ValueError(f"referenced file hash differs: {relative}")

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
        return tuple(self.source(name) for name in sorted(self.files.keys() | self.directories.keys()))


def _walk(value):
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk(item)


def _evidence(reader, batch, reference):
    if reference.experiment.strategy_id != batch.strategy_id:
        raise ValueError("reference belongs to another batch")
    data = reader.read(reference.repository_path)
    if sha256(data).hexdigest() != reference.sha256:
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
            for source in saved.evidence:
                _evidence(reader, batch, source)
            if saved.previous is not None:
                _evidence(reader, batch, saved.previous)
            outcome = saved.outcome
            state = ExperimentReportState.PUBLISHED if report == saved.report.encode("utf-8") else ExperimentReportState.UNPUBLISHED_CHANGES
        result.append(ExperimentOverview(reference, state, published, outcome, reader.source(metadata)))
    return tuple(result)


def _deliveries(reader, batch, limitations):
    result = []
    parent = f"research/{batch.strategy_id}/assets/deliveries"
    # A retained public receipt cannot silently disappear from the overview
    # merely because its complete package directory was removed.
    public_parent = f"research/{batch.strategy_id}/deliveries"
    for stage_name, directory in reader.listing(public_parent):
        d.DeliveryStage(stage_name)
        if not directory:
            raise ValueError("public delivery stage must be a directory")
        for revision, revision_dir in reader.listing(f"{public_parent}/{stage_name}"):
            if not revision_dir or not revision.isdecimal() or str(int(revision)) != revision or int(revision) < 1:
                raise ValueError("invalid public delivery revision")
            reader.read(f"{parent}/{stage_name}/{revision}/delivery.json")
    for stage_name, is_dir in reader.listing(parent):
        stage = d.DeliveryStage(stage_name)
        if not is_dir:
            raise ValueError("delivery stage must be a directory")
        for revision_name, revision_dir in reader.listing(f"{parent}/{stage_name}"):
            if not revision_dir or not revision_name.isdecimal() or str(int(revision_name)) != revision_name or int(revision_name) < 1:
                raise ValueError("delivery revision requires a positive canonical integer")
            path = f"{parent}/{stage_name}/{revision_name}"
            value = _json(reader.read(f"{path}/delivery.json"))
            if type(value) is not dict or type(value.get("schema_version")) is not int:
                raise ValueError("invalid delivery envelope")
            if value["schema_version"] != 7:
                limitations.append(OverviewLimitation("UNSUPPORTED_DELIVERY_SCHEMA", path, "Retained delivery is not schema 7; no compatibility interpretation was performed."))
                continue
            if set(value) != {"schema_version", "definition", "content"}:
                raise ValueError("delivery envelope fields differ")
            definition = d.DeliveryDefinition.from_dict(value["definition"])
            content = d.DeliveryContent.from_dict(value["content"])
            expected_payload = {
                d.DeliveryStage.MANDATE: d.ResearchMandate,
                d.DeliveryStage.COMPONENTS: d.ComponentPanel,
                d.DeliveryStage.CANDIDATES: d.CandidateSet,
                d.DeliveryStage.ASSESSMENT: d.CandidateAssessmentDelivery,
                d.DeliveryStage.INSPECTION: d.CandidateInspectionDelivery,
            }
            if type(content.payload) is not expected_payload[stage]:
                raise ValueError("delivery stage and payload differ")
            if (definition.batch, definition.stage, definition.revision) != (batch, stage, int(revision_name)):
                raise ValueError("delivery directory and identity differ")
            receipt_path = f"{path}/receipt.json"
            receipt = d.DeliveryReceipt.from_dict(_json(reader.read(receipt_path)))
            reference = receipt.reference
            if (reference.batch, reference.stage, reference.revision) != (batch, stage, definition.revision) or d._digest(receipt.files) != reference.content_sha256:
                raise ValueError("delivery receipt identity differs")
            expected = {entry.path for entry in receipt.files} | {"receipt.json"}
            def scan(relative, prefix=""):
                paths = set()
                for name, directory in reader.listing(relative):
                    paths |= scan(f"{relative}/{name}", f"{prefix}{name}/") if directory else {prefix + name}
                return paths
            if scan(path) != expected:
                raise ValueError("delivery file manifest differs")
            for entry in receipt.files:
                reader.authenticate(f"{path}/{entry.path}", entry.sha256)
            if reader.read(f"{path}/report.md") != content.report.encode("utf-8"):
                raise ValueError("delivery report differs")
            public = f"research/{batch.strategy_id}/deliveries/{stage_name}/{revision_name}"
            if {name for name, _ in reader.listing(public)} != {"receipt.json", "report.md"}:
                raise ValueError("public delivery layout differs")
            for name in ("receipt.json", "report.md"):
                if reader.read(f"{public}/{name}") != reader.read(f"{path}/{name}"):
                    raise ValueError("public delivery copy differs")
            for ref in _walk(content):
                if isinstance(ref, EvidenceRef):
                    if ref.experiment.strategy_id != batch.strategy_id:
                        raise ValueError("delivery evidence belongs to another batch")
                    reader.authenticate(f"{path}/{ref.path}", ref.sha256)
            for previous in definition.predecessors:
                predecessor = f"{parent}/{previous.stage.value}/{previous.revision}/receipt.json"
                saved = d.DeliveryReceipt.from_dict(_json(reader.read(predecessor)))
                if saved.reference != previous:
                    raise ValueError("predecessor reference differs")
            result.append((DeliveryOverview(reference, content.status, definition.predecessors, reader.source(receipt_path)), content))
    return result


def _candidates(reader, batch, limitations):
    parent = f"research/registrations/{batch.strategy_id}/candidates"
    result = []
    for name, is_dir in reader.listing(parent):
        if is_dir or not name.endswith(".json"):
            raise ValueError("invalid candidate registry entry")
        path = f"{parent}/{name}"
        value = _json(reader.read(path))
        if type(value) is not dict or set(value) != {"record", "record_sha256"}:
            raise ValueError("invalid candidate registration envelope")
        raw = value["record"]
        if type(raw) is not dict or type(raw.get("schema_version")) is not int:
            raise ValueError("invalid candidate record")
        if raw["schema_version"] != 3 or raw.get("identity_schema_version") != 2:
            limitations.append(OverviewLimitation("UNSUPPORTED_CANDIDATE_SCHEMA", path, "Retained registration uses an unsupported schema; not included in authenticated candidate counts."))
            continue
        record = CandidateRegistration.from_dict(raw)
        if record.key.strategy_id != batch.strategy_id or name != f"{record.key.candidate_id}.json" or record.record_sha256 != value["record_sha256"]:
            raise ValueError("candidate registration identity differs")
        for ref in (record.payload, *record.source_files, *record.origin.evidence, *((record.derivation.evidence,) if record.derivation else ())):
            reader.authenticate(f"research/{batch.strategy_id}/{ref.path}", ref.sha256)
        result.append(CandidateOverview(record.key, record.content_sha256, record.record_sha256, record.origin.experiment_id, reader.source(path)))
    return tuple(result)


def _accounts(reader, batch, limitations):
    """Count retained identity declarations; no ledger semantic validation is implied."""
    parent = f"research/{batch.strategy_id}/assets/evidence"
    identities = set()
    sources = []
    for experiment, is_dir in reader.listing(parent):
        if not is_dir:
            raise ValueError("invalid evidence owner directory")
        ExperimentRef(batch.strategy_id, experiment)
        for name, directory in reader.listing(f"{parent}/{experiment}"):
            if directory:
                raise ValueError("published evidence must be files")
            if not name.endswith(".json"):
                continue
            path = f"{parent}/{experiment}/{name}"
            data = reader.read(path)
            if name != f"{sha256(data).hexdigest()}.json":
                raise ValueError("published evidence filename differs from content hash")
            try:
                value = _json(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Generic material is allowed to carry arbitrary original bytes;
                # a .json suffix is not an account schema declaration.
                continue
            if type(value) is not dict or value.get("source_kind") != "published_result":
                continue
            if value.get("schema_version") != 7:
                limitations.append(OverviewLimitation("UNSUPPORTED_ACCOUNT_SCHEMA", path, "Published account declaration is not schema 7; excluded from retained identity counts."))
                continue
            request = value["request_identity"]
            if request["experiment_id"] != experiment or not request["strategy_reference"].startswith(batch.strategy_id + "-"):
                raise ValueError("account declaration belongs to another experiment or batch")
            projected = value["assessment_evidence"]
            runs = value["runs"]
            if type(projected) is not list or not projected or type(runs) is not list or len(runs) != len(projected):
                raise ValueError("account identity declarations are missing")
            for item, run in zip(projected, runs, strict=True):
                identifier = item["evaluation_id"]
                d._hash(identifier)
                raw = run["identity"]
                identity = EvaluationIdentity(CandidateKey(**raw["candidate"]), **{key: raw[key] for key in (
                    "content_sha256", "input_sha256", "protocol_sha256", "environment_sha256")})
                if identity.to_dict() != raw or identifier != identity.evaluation_id or identity.candidate.strategy_id != batch.strategy_id or item["experiment_id"] != experiment:
                    raise ValueError("retained account evaluation identity differs")
                identities.add(identifier)
            sources.append(reader.source(path))
    return len(identities), tuple(sources) or (reader.source(parent),)


def get_research_overview(repository: RepositoryContext, batch: ResearchBatchRef) -> ResearchOverview:
    """Authenticate retained metadata and file hashes, never judge research quality.

    The returned counts cover retained records only. Account ledger semantics,
    candidate runtime identity, SE assessment recomputation and authorization are
    deliberately outside this metadata snapshot's authentication scope.
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
        limitations = [OverviewLimitation("METADATA_AUTHENTICATION_ONLY", path,
            "Retained metadata and referenced file hashes are checked; ledger semantics, runtime identities, assessment recomputation, authorization and unrecorded searches are not certified.")]
        experiments = _experiments(reader, batch)
        retained = _deliveries(reader, batch, limitations)
        candidates = _candidates(reader, batch, limitations)
        account_count, account_sources = _accounts(reader, batch, limitations)
        latest = {}
        search_records = {}
        components = []
        handoffs = []
        for item, content in retained:
            stage = item.reference.stage
            if stage not in latest or latest[stage].reference.revision < item.reference.revision:
                latest[stage] = item
            if isinstance(content.payload, d.ComponentPanel):
                components.append(ComponentPanelOverview(item.reference, content.payload.components))
            if isinstance(content.payload, d.CandidateSet):
                handoffs.append(CandidateHandoffOverview(item.reference, content.payload.handoff))
                for search in content.payload.searches:
                    # Identity includes the complete declaration; repeated revisions
                    # do not add trials. Different declarations are never summed.
                    key = d._digest(search)
                    entry = search_records.setdefault(key, [search, []])
                    entry[1].append(item.reference)
        searches = tuple(SearchOverview(value[0], tuple(value[1])) for _, value in sorted(search_records.items()))
        # Never present an older readable revision as the current latest when a
        # higher retained revision exists in an unsupported format.
        for limitation in limitations:
            if limitation.code == "UNSUPPORTED_DELIVERY_SCHEMA":
                parts = limitation.repository_path.split("/")
                stage, revision = d.DeliveryStage(parts[-2]), int(parts[-1])
                if stage in latest and latest[stage].reference.revision < revision:
                    del latest[stage]
        search_sources = tuple(dict.fromkeys(item.source for item, content in retained if isinstance(content.payload, d.CandidateSet)))
        candidate_sources = tuple(item.source for item in candidates) or (reader.source(f"research/registrations/{batch.strategy_id}/candidates"),)
        unsupported_candidates = any(x.code == "UNSUPPORTED_CANDIDATE_SCHEMA" for x in limitations)
        counts = [ResearchCount(ResearchCountKind.REGISTERED_CANDIDATES,
            None if unsupported_candidates else len(candidates), CountBasis.UNKNOWN if unsupported_candidates else CountBasis.VERIFIED,
            candidate_sources, "Unsupported retained registrations prevent a complete count." if unsupported_candidates else "Authenticated retained registration identities only."),
            ResearchCount(ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS,
                None if any(x.code == "UNSUPPORTED_ACCOUNT_SCHEMA" for x in limitations) else account_count,
                CountBasis.UNKNOWN if any(x.code == "UNSUPPORTED_ACCOUNT_SCHEMA" for x in limitations) else CountBasis.DECLARED,
                account_sources, "Distinct supported retained evaluation ID declarations; not ledger certification or a complete exploration count. Unsupported schemas prevent a complete total.")]
        for kind, field in ((ResearchCountKind.SEARCH_EVALUATIONS, "evaluations"), (ResearchCountKind.DISTINCT_CONFIGURATIONS, "unique_configurations")):
            known = len(searches) == 1
            counts.append(ResearchCount(kind, getattr(searches[0].summary, field) if known else None,
                CountBasis.DECLARED if known else CountBasis.UNKNOWN, search_sources,
                "Single retained search declaration; does not certify complete history." if known else "No unique nonoverlapping total can be established from retained search declarations."))
        counts.append(ResearchCount(ResearchCountKind.ECONOMIC_PATH_GROUPS, None, CountBasis.UNKNOWN, (),
                                   "No typed retained economic-path grouping declaration is available; no grouping is inferred."))
        if len(searches) > 1:
            limitations.append(OverviewLimitation("SEARCH_OVERLAP_UNKNOWN", path, "Multiple search declarations may overlap; their counts were not added."))
        sources = reader.finish()
        snapshot = ResearchSnapshot(d._digest(sources), datetime.now(timezone.utc).isoformat(), sources)
        return ResearchOverview(batch, snapshot, family.research_state,
            tuple(latest[stage] for stage in sorted(latest)), experiments, tuple(components), candidates,
            tuple(handoffs), searches, tuple(counts), tuple(limitations))
    except ResearchOverviewError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ResearchOverviewError("INVALID_RETAINED_RECORD", path, str(exc)) from exc
