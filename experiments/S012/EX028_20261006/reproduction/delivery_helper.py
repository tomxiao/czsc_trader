"""S012 stage-three publication helper. Importing and prepare() are read-only.

Input schema:
  exp: owner experiment ID or Path; owner must be bound and not sealed.
  summary: conclusion, summary_path, report_path, candidate_inputs_path,
    current_experiments (optional), artifacts (optional relative paths),
    facts (optional scalar map), explanations/reproduction (optional).
  records: one metadata dict per formally attempted candidate. Keys:
    candidate_id, hypothesis, judgment, passed_all (bool), and for handoff
    candidate (StrategyCandidate) OR payload/payload_path + source_root,
    origin_experiment_id, preflight_path. Additional metrics are caller-owned.
    All attempts are read from CURRENT_EVALUATION execution receipts, not
    synthesized from these metadata dicts. Failure/UNKNOWN attempts stay visible.
  search_records: SearchRecord objects or their exact typed to_dict() values.

Call prepare(...) to inspect the draft, then publish(...) explicitly. Before
calling, persist the complete payloads, sources and dependencies of all trial
objects to candidate_inputs_path and experiment artifacts. The caller owns
economic target verification, exhaustive search selection and manifest sealing.
"""

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    CandidateRegistrationRequest, RepositoryContext, assemble_delivery,
    load_candidate, register_candidate, validate_delivery,
)
from czsc_trader.research_tools import (
    CandidateEntry, CandidateIdentityRef, CandidateSet, DeliveryContent,
    DeliveryDefinition, DeliveryReference, DeliveryStage, DeliveryStatus,
    DeliveryValidationScope, EvaluationEvidenceRef, EvidenceFile, EvidenceRef,
    ExperimentEvidenceRef, ExperimentEvidenceUse, ExperimentOwner, Explanation,
    ExplanationKind, FactStatus, FactValue, ReproductionSpec, ResearchDeliverable,
    SearchRecord,
)
from research_experiment import EvaluationRecord, load_experiment
from strategy_manager import CandidateEvidence, CandidateKey, CandidateRegistrationOrigin
from strategy_runtime import ImplementationDependency, StrategyCandidate, StrategyRuntime


APPROVED_COMPONENT_HASH = "d5ed294ec2f3e585c5cd0a56f2dd6b5c08b4531c6e18689d2d59c793c9a65c57"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _relative(root, value):
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Evidence file missing or outside repository: {value}")
    return path.relative_to(root).as_posix()


def _owner(exp):
    return Path(exp).name


def _origin(item, default):
    record = item.get("record", {})
    recorded = record.experiment_id if isinstance(record, EvaluationRecord) else record.get("experiment_id", default)
    return item.get("origin_experiment_id", recorded)


def _closure(root, current):
    refs, traces = {}, {}

    def visit(eid):
        if eid in refs:
            return
        workspace = f"experiments/S012/{eid}/artifacts/rex"
        receipt = _read(root / workspace / "execution_receipt.json")
        refs[eid] = ExperimentEvidenceRef(
            eid, workspace, receipt["receipt_sha256"],
            ExperimentEvidenceUse.CURRENT_EVALUATION if eid in current
            else ExperimentEvidenceUse.HISTORICAL_REFERENCE,
        )
        if eid in current:
            traces[eid] = tuple(EvaluationRecord.from_dict(x)
                                for x in receipt["trace"]["evaluations"])
        for predecessor, expected in receipt["predecessor_receipts"].items():
            visit(predecessor)
            if refs[predecessor].receipt_sha256 != expected:
                raise ValueError(f"Predecessor receipt differs: {predecessor}")

    for eid in sorted(current):
        visit(eid)
    return tuple(refs[eid] for eid in sorted(refs)), traces


@dataclass
class Draft(ResearchDeliverable):
    _definition: DeliveryDefinition
    content: DeliveryContent
    registration_requests: tuple[CandidateRegistrationRequest, ...]

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


def prepare(root, exp, summary, records, search_records):
    """Build and inspect the typed draft; never register, publish or write files."""
    root = Path(root).resolve()
    owner = _owner(exp)
    if not owner.startswith("EX"):
        raise ValueError("Use a scoped S012 experiment ID")
    loaded_owner = load_experiment(root / "experiments/S012" / owner)
    if loaded_owner.definition.strategy_id != "S012":
        raise ValueError("Owner is not S012")
    metadata = {}
    for item in records:
        key = CandidateKey("S012", item["candidate_id"].removeprefix("S012-"))
        if key in metadata:
            raise ValueError(f"Duplicate candidate metadata: {key}")
        if type(item["passed_all"]) is not bool:
            raise TypeError("passed_all must be a boolean from the economic target audit")
        metadata[key] = item
    inferred = {_origin(item, owner) for item in metadata.values()}
    current = set(summary.get("current_experiments", inferred)) | {owner}
    refs, traces = _closure(root, current)
    grouped = defaultdict(list)
    for eid, attempts in traces.items():
        for attempt in attempts:
            if attempt.status.value == "STARTED":
                raise ValueError("Stage delivery cannot contain unterminated attempts")
            key = CandidateKey("S012", attempt.candidate_id.removeprefix("S012-"))
            grouped[key].append(attempt)
    if set(metadata) != set(grouped):
        raise ValueError("Candidate metadata must cover exactly every formal attempted identity")

    entries, registrations, handoff = [], [], []
    for key in sorted(grouped, key=lambda x: x.candidate_id):
        item, attempts = metadata[key], grouped[key]
        hashes = {attempt.content_sha256 for attempt in attempts}
        if len(hashes) != 1:
            raise ValueError(f"Conflicting content hashes for {key}")
        content_hash = next(iter(hashes))
        identity = CandidateIdentityRef(key, content_hash)
        evidence = tuple(EvaluationEvidenceRef(x.experiment_id, x.attempt_id, x.evaluation_ids)
                         for x in attempts)
        raw_record = item.get("record")
        if raw_record is not None:
            declared_record = (raw_record if isinstance(raw_record, EvaluationRecord)
                               else EvaluationRecord.from_dict(raw_record))
            if declared_record not in attempts:
                raise ValueError(f"Metadata record is absent from receipted attempts: {key}")
        judgment = item.get("judgment", "三项原始目标同时通过，进入交接全集。" if item["passed_all"]
                            else "未同时满足三项原始目标；保留完整评价及反证，不进入交接全集。")
        entries.append(CandidateEntry(identity, item["hypothesis"], judgment, evidence))
        if not item["passed_all"]:
            continue
        if not any(x.status.value == "SUCCEEDED" for x in attempts):
            raise ValueError(f"Passing candidate has no successful formal attempt: {key}")
        origin_eid = _origin(item, owner)
        if origin_eid not in current:
            raise ValueError("Registration origin must be a current evaluation experiment")
        loaded = load_experiment(root / "experiments/S012" / origin_eid)
        dependencies = tuple(ImplementationDependency(x.name, x.version)
                             for x in loaded.definition.dependencies)
        candidate = item.get("candidate")
        if candidate is None:
            payload = item.get("payload")
            if payload is None:
                payload = _read(root / _relative(root, item["payload_path"]))
            source = Path(item["source_root"])
            source = source if source.is_absolute() else root / source
            candidate = StrategyCandidate("S012", key.candidate_id, payload, source)
        if (candidate.strategy_family_id, candidate.candidate_id) != ("S012", key.candidate_id):
            raise ValueError("Registration candidate key differs")
        if StrategyRuntime().identify(candidate, dependencies=dependencies).content_sha256 != content_hash:
            raise ValueError(f"Registration source/payload differs from formal attempt: {key}")
        preflight = _relative(root, item["preflight_path"])
        origin = CandidateRegistrationOrigin(
            origin_eid, loaded.definition.sha256,
            _hash(loaded.root / "experiment_binding.json"),
            CandidateEvidence(preflight, _hash(root / preflight)),
        )
        registrations.append(CandidateRegistrationRequest(candidate, origin, dependencies))
        handoff.append(key)

    searches = tuple(x if isinstance(x, SearchRecord) else SearchRecord.from_dict(x)
                     for x in search_records)
    candidate_set = CandidateSet(tuple(entries), tuple(handoff), searches, summary["conclusion"])
    paths = [summary["summary_path"], summary["report_path"], summary["candidate_inputs_path"]]
    paths.extend(summary.get("artifacts", ()))
    attachments, seen = [], set()
    for value in paths:
        relative = _relative(root, value)
        if relative in seen:
            continue
        seen.add(relative)
        suffix = Path(relative).suffix.lower()
        media = {".json": "application/json", ".md": "text/markdown", ".py": "text/x-python"}.get(
            suffix, "application/octet-stream")
        attachments.append(EvidenceFile(relative, EvidenceRef(
            "attachments/" + relative, _hash(root / relative), media)))
    summary_ref = next(x.reference for x in attachments
                       if x.source_path == _relative(root, summary["summary_path"]))
    facts = {
        **summary.get("facts", {}),
        "formal_candidate_count": len(entries),
        "formal_attempt_count": sum(len(x) for x in grouped.values()),
        "handoff_count": len(handoff),
        "full_history_frequency_denominator": 1535,
        "all_formal_attempts_covered": True,
    }
    typed_facts = tuple(FactValue(name, value, "research_fact", FactStatus.AVAILABLE, (summary_ref,))
                        for name, value in facts.items())
    explanations = tuple(Explanation(ExplanationKind.RESEARCH_JUDGMENT, text)
                         for text in summary.get("explanations", (summary["conclusion"],)))
    reproduction = ReproductionSpec(
        summary.get("reproduction", "按归属实验设计、完整搜索记录和正式评价请求复算；保留参数、源码与依赖。"),
        (summary_ref,),
        "S012授权DFLS开发池；正式输入身份见受管评价和执行回执。",
        summary.get("determinism", "固定种子、绑定实现及输入；开发池已全部观察，披露选择历史。"),
    )
    status = DeliveryStatus(summary.get("status", "COMPLETE"))
    content = DeliveryContent(candidate_set, status, typed_facts, explanations, reproduction,
                              tuple(summary.get("incomplete_items", ())), tuple(attachments))
    predecessor = DeliveryReference.from_dict(_read(root /
        "experiments/S012/EX019_20261005/deliveries/COMPONENTS/1/receipt.json")["reference"])
    if predecessor.content_sha256 != APPROVED_COMPONENT_HASH:
        raise ValueError("Approved stage-two component content differs")
    definition = DeliveryDefinition(ExperimentOwner("S012", owner), DeliveryStage.CANDIDATES,
                                    summary.get("revision", 1), (predecessor,), refs)
    return Draft(definition, content, tuple(registrations))


def publish(root, exp, summary, records, search_records):
    """Explicit publication only; caller subsequently seals the owner experiment."""
    root = Path(root).resolve()
    draft = prepare(root, exp, summary, records, search_records)
    context = RepositoryContext.discover(root)
    if (root / "experiments/S012" / _owner(exp) / "experiment_manifest.json").exists():
        raise ValueError("Publish before sealing the owner experiment")
    for request in draft.registration_requests:
        registration = register_candidate(context, request)
        loaded = load_candidate(context, registration.key)
        content = StrategyRuntime().identify(loaded, dependencies=request.dependencies).content_sha256
        if content != registration.content_sha256:
            raise ValueError("Registered candidate failed loading identity verification")
    receipt = assemble_delivery(context, draft)
    validation = validate_delivery(context, receipt.reference, scope=DeliveryValidationScope.FULL)
    if validation.status.value != "PASS":
        raise ValueError(f"Published delivery FULL validation failed: {validation.issues}")
    return receipt, validation
