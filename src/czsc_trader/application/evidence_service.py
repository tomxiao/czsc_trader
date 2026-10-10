"""Atomic, explicit publication of research result evidence."""

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.evidence import (
    EvidenceRef, EvidenceWriteRequest, EvaluationEvidenceWrite, MaterialEvidenceWrite, managed_path,
)


def _publish_bytes(repository_root: Path, target: Path, data: bytes) -> None:
    root = Path(repository_root).resolve()
    relative = Path(target).relative_to(root).as_posix()
    target = managed_path(root, relative)
    if not relative.startswith("research/"):
        raise ValueError("research evidence must stay within the research directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = managed_path(root, ".tmp/evidence-publication")
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = temporary_root / f"{uuid4().hex}.part"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != data:
                raise ValueError("published evidence cannot be overwritten") from None
    finally:
        temporary.unlink(missing_ok=True)


def publish_evidence(context: ResearchContext, request: EvidenceWriteRequest) -> EvidenceRef:
    if type(context) is not ResearchContext or type(request) not in (
        MaterialEvidenceWrite, EvaluationEvidenceWrite,
    ):
        raise TypeError("publication requires a research context and typed evidence request")
    if request.experiment.strategy_id != context.strategy_id:
        raise ValueError("evidence experiment belongs to another research batch")
    root = context.repository.root
    experiment = request.experiment.resolve(root)
    if not (experiment / "experiment.json").is_file():
        raise ValueError("evidence must belong to a platform-allocated experiment")
    recorded = ExperimentRef.from_dict(json.loads((experiment / "experiment.json").read_text(encoding="utf-8")))
    if recorded != request.experiment:
        raise ValueError("experiment identity differs from the allocated reference")
    if isinstance(request, EvaluationEvidenceWrite):
        from ..research_tools.evaluation import serialize_evaluation_evidence

        if request.request.experiment_id != request.experiment.experiment_id:
            raise ValueError("evaluation request belongs to another experiment")
        if request.request.strategy.strategy_family_id != context.strategy_id:
            raise ValueError("evaluation belongs to another research batch")
        if request.request.execution_data is None or request.request.execution_data.prepared.space_id != context.data.binding.space_id:
            raise ValueError("evaluation must bind the batch data space")
        if any(binding.prepared.space_id != context.data.binding.space_id for binding in request.request.input_bindings.values()):
            raise ValueError("evaluation input belongs to another data space")
        value = serialize_evaluation_evidence(request.request, request.result)
        data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
        media_type, suffix, schema, version = "application/json", "json", "account_evaluation", 6
    else:
        data = request.content
        media_type, suffix = request.media_type, request.suffix
        schema, version = None, None
    digest = sha256(data).hexdigest()
    reference = EvidenceRef(request.experiment, f"{digest}.{suffix}", digest,
                            media_type, request.name, schema, version)
    _publish_bytes(root, managed_path(root, reference.repository_path), data)
    return reference


def resolve_evidence(repository_root: Path, reference: EvidenceRef) -> Path:
    if type(reference) is not EvidenceRef:
        raise TypeError("reference requires EvidenceRef")
    return reference.resolve(repository_root)
