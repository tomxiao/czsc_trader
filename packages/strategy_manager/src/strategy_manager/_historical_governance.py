"""Read-only decoders for sealed historical governance evidence.

These types are not research inputs and have no execution or write entry point.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, ClassVar
from .errors import ValidationError
from .models import canonical_sha256, _enum_dict
from .validation import (
    require_date,
    require_exact_fields,
    require_identifier,
    require_schema_version,
    require_sha256,
    require_strategy_id,
    require_string,
    require_timestamp,
)


@dataclass(frozen=True)
class CandidateSnapshot:
    schema_version: int
    strategy_id: str
    candidate_id: str
    source_experiment: str
    strategy_payload: dict[str, Any]
    data_contract: dict[str, Any]
    execution_policy: dict[str, Any]
    research_claims: dict[str, Any]
    candidate_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "strategy_id",
        "candidate_id",
        "source_experiment",
        "strategy_payload",
        "data_contract",
        "execution_policy",
        "research_claims",
        "candidate_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CandidateSnapshot:
        require_exact_fields(value, cls.FIELDS)
        for field in (
            "strategy_payload",
            "data_contract",
            "execution_policy",
            "research_claims",
        ):
            if not isinstance(value[field], dict) or not value[field]:
                raise ValidationError(f"{field} must be a nonempty JSON object")
        instance = cls(
            schema_version=require_schema_version(value["schema_version"]),
            strategy_id=require_strategy_id(value["strategy_id"]),
            candidate_id=require_identifier(value["candidate_id"], "candidate_id"),
            source_experiment=require_string(value["source_experiment"], "source_experiment"),
            strategy_payload=dict(value["strategy_payload"]),
            data_contract=dict(value["data_contract"]),
            execution_policy=dict(value["execution_policy"]),
            research_claims=dict(value["research_claims"]),
            candidate_hash=require_sha256(value["candidate_hash"], "candidate_hash"),
        )
        if instance.candidate_hash != canonical_sha256(instance.hash_payload()):
            raise ValidationError("candidate_hash does not match the candidate snapshot")
        return instance

    def hash_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("candidate_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


@dataclass(frozen=True)
class EvaluationMandate:
    schema_version: int
    mandate_id: str
    strategy_id: str
    candidate_id: str
    development_cutoff: str
    forward_start: str
    evaluation_windows: dict[str, Any]
    benchmark: dict[str, Any]
    objectives: list[dict[str, Any]]
    cost_policy: dict[str, Any]
    frequency_policy: dict[str, Any]
    audit_requirements: dict[str, Any]
    required_audits: list[str]
    evidence_seen_through: str
    finalized_at: str
    finalized_by: str
    mandate_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "mandate_id",
        "strategy_id",
        "candidate_id",
        "development_cutoff",
        "forward_start",
        "evaluation_windows",
        "benchmark",
        "objectives",
        "cost_policy",
        "frequency_policy",
        "audit_requirements",
        "required_audits",
        "evidence_seen_through",
        "finalized_at",
        "finalized_by",
        "mandate_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluationMandate:
        require_exact_fields(value, cls.FIELDS)
        for field in (
            "evaluation_windows",
            "benchmark",
            "cost_policy",
            "frequency_policy",
            "audit_requirements",
        ):
            if not isinstance(value[field], dict) or not value[field]:
                raise ValidationError(f"{field} must be a nonempty JSON object")
        objectives = value["objectives"]
        if (
            not isinstance(objectives, list)
            or not objectives
            or any(not isinstance(item, dict) or not item for item in objectives)
        ):
            raise ValidationError("objectives must be a nonempty list of JSON objects")
        required_audits = value["required_audits"]
        if (
            not isinstance(required_audits, list)
            or not required_audits
            or any(not isinstance(item, str) or not item.strip() for item in required_audits)
        ):
            raise ValidationError("required_audits must be a nonempty list of names")
        if len(set(required_audits)) != len(required_audits):
            raise ValidationError("required_audits must not contain duplicates")
        instance = cls(
            schema_version=require_schema_version(value["schema_version"]),
            mandate_id=require_identifier(value["mandate_id"], "mandate_id"),
            strategy_id=require_strategy_id(value["strategy_id"]),
            candidate_id=require_identifier(value["candidate_id"], "candidate_id"),
            development_cutoff=require_date(value["development_cutoff"], "development_cutoff"),
            forward_start=require_date(value["forward_start"], "forward_start"),
            evaluation_windows=dict(value["evaluation_windows"]),
            benchmark=dict(value["benchmark"]),
            objectives=[dict(item) for item in objectives],
            cost_policy=dict(value["cost_policy"]),
            frequency_policy=dict(value["frequency_policy"]),
            audit_requirements=dict(value["audit_requirements"]),
            required_audits=[item.strip() for item in required_audits],
            evidence_seen_through=require_date(
                value["evidence_seen_through"], "evidence_seen_through"
            ),
            finalized_at=require_timestamp(value["finalized_at"], "finalized_at"),
            finalized_by=require_string(value["finalized_by"], "finalized_by"),
            mandate_hash=require_sha256(value["mandate_hash"], "mandate_hash"),
        )
        if instance.mandate_hash != canonical_sha256(instance.hash_payload()):
            raise ValidationError("mandate_hash does not match the evaluation mandate")
        if instance.forward_start <= instance.development_cutoff:
            raise ValidationError("forward_start must be after development_cutoff")
        if instance.evidence_seen_through > instance.development_cutoff:
            raise ValidationError("evidence_seen_through must not exceed development_cutoff")
        return instance

    def hash_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("mandate_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)


@dataclass(frozen=True)
class AdjudicationReport:
    schema_version: int
    report_id: str
    review_id: str
    strategy_id: str
    candidate_id: str
    candidate_hash: str
    evaluation_mandate_hash: str
    audit_policy_hash: str
    claim_checks: list[dict[str, Any]]
    audit_results: dict[str, dict[str, Any]]
    machine_verdict: str
    risk_label: str
    blocking_findings: list[str]
    reservations: list[str]
    generated_at: str
    report_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "report_id",
        "review_id",
        "strategy_id",
        "candidate_id",
        "candidate_hash",
        "evaluation_mandate_hash",
        "audit_policy_hash",
        "claim_checks",
        "audit_results",
        "machine_verdict",
        "risk_label",
        "blocking_findings",
        "reservations",
        "generated_at",
        "report_hash",
    )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AdjudicationReport:
        require_exact_fields(value, cls.FIELDS)
        checks = value["claim_checks"]
        audits = value["audit_results"]
        if not isinstance(checks, list) or any(not isinstance(item, dict) for item in checks):
            raise ValidationError("claim_checks must be a list of JSON objects")
        if not isinstance(audits, dict) or any(
            not isinstance(name, str) or not isinstance(item, dict) for name, item in audits.items()
        ):
            raise ValidationError("audit_results must map names to JSON objects")
        findings = value["blocking_findings"]
        reservations = value["reservations"]
        if any(
            not isinstance(items, list)
            or any(not isinstance(item, str) or not item for item in items)
            for items in (findings, reservations)
        ):
            raise ValidationError("findings and reservations must be lists of strings")
        verdict = require_identifier(value["machine_verdict"], "machine_verdict")
        if verdict not in {"ELIGIBLE_FOR_FREEZE_REVIEW", "INCOMPLETE", "REJECTED"}:
            raise ValidationError("machine_verdict has unsupported value")
        instance = cls(
            schema_version=require_schema_version(value["schema_version"]),
            report_id=require_identifier(value["report_id"], "report_id"),
            review_id=require_identifier(value["review_id"], "review_id"),
            strategy_id=require_strategy_id(value["strategy_id"]),
            candidate_id=require_identifier(value["candidate_id"], "candidate_id"),
            candidate_hash=require_sha256(value["candidate_hash"], "candidate_hash"),
            evaluation_mandate_hash=require_sha256(
                value["evaluation_mandate_hash"], "evaluation_mandate_hash"
            ),
            audit_policy_hash=require_sha256(value["audit_policy_hash"], "audit_policy_hash"),
            claim_checks=[dict(item) for item in checks],
            audit_results={str(name): dict(item) for name, item in audits.items()},
            machine_verdict=verdict,
            risk_label=require_identifier(value["risk_label"], "risk_label"),
            blocking_findings=list(findings),
            reservations=list(reservations),
            generated_at=require_timestamp(value["generated_at"], "generated_at"),
            report_hash=require_sha256(value["report_hash"], "report_hash"),
        )
        if instance.report_hash != canonical_sha256(instance.hash_payload()):
            raise ValidationError("report_hash does not match the adjudication report")
        return instance

    def hash_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("report_hash")
        return value

    def to_dict(self) -> dict[str, Any]:
        return _enum_dict(self)
