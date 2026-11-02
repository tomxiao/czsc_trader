"""Caller-supplied performance projections, not account-journal certification."""

from dataclasses import dataclass

from . import research_models as m


def assessment_benchmark_fingerprint(evidence: m.AssessmentEvidence) -> str | None:
    """Identify the actual benchmark input, including intraday equity journals.

    This is a deterministic fingerprint of supplied facts, not an audit receipt.
    Callers sourcing projections independently must establish their provenance.
    """
    if type(evidence) is not m.AssessmentEvidence:
        raise TypeError("benchmark fingerprint requires AssessmentEvidence")
    if not evidence.benchmark_equity:
        return None
    equity = evidence.equity
    return m.digest({
        "initial_cash": evidence.initial_cash,
        "sessions": tuple(x.session for x in evidence.account),
        "benchmark_equity": evidence.benchmark_equity,
        "equity_contract": None if equity is None else {
            "market": equity.market, "timezone": equity.timezone,
            "currency": equity.currency, "drawdown_basis": equity.drawdown_basis,
            "benchmark_ledger": equity.benchmark_ledger,
        },
    })


@dataclass(frozen=True)
class ParameterPerformanceEvidence(m.ResearchRecord):
    """Numeric parameter facts and caller-asserted source/comparison identities."""

    performance: m.PerformanceFacts
    experiment_id: str
    attempt_id: str
    request_sha256: str
    result_sha256: str
    context_sha256: str
    window_id: str
    scenario_id: str
    metric_version: str
    initial_cash: float
    frequency_window_days: int
    benchmark_equity_sha256: str | None
    parent: m.AssessmentCandidate
    derivation_sha256: str
    derivation_kind: m.AssessmentDerivationKind
    parameter_point: m.ParameterNeighborhoodBinding

    @property
    def candidate(self):
        return self.performance.candidate

    @property
    def evaluation_id(self):
        return self.performance.evaluation_id

    @property
    def scenario_context(self):
        return self.performance.scenario

    def validate(self):
        import re
        m.require(re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is not None, "invalid attempt_id")
        m.require(self.initial_cash > 0 and self.frequency_window_days > 0,
                  "invalid performance opening/frequency contract")
        m.require(self.parent != self.candidate, "candidate cannot derive from itself")
        m.require(self.derivation_kind is m.AssessmentDerivationKind.PARAMETERS,
                  "numeric parameter input requires parameter-only derivation")
        m.require(self.parameter_point.point_index == self.performance.point_index,
                  "performance point differs from binding")
        m.require((self.benchmark_equity_sha256 is None)
                  == (self.performance.benchmark_return is None),
                  "benchmark fingerprint/performance presence differs")


@dataclass(frozen=True)
class CandidatePerformanceAssessmentRequest(m.ResearchRecord):
    """Center journals plus numeric neighbors; never a full-journal FULL audit.

    Source authenticity is the caller's responsibility. This request validates
    declared identities and deterministically computes numerical diagnostics.
    """

    baseline_request: m.CandidateAssessmentRequest
    parameter_evidence: tuple[ParameterPerformanceEvidence, ...]

    def validate(self):
        base = self.baseline_request
        m.require(type(base.protocol) is m.CalmarSelfCheckProtocol,
                  "performance input requires CalmarSelfCheckProtocol")
        m.require(base.protocol.parameter_protocol.version == "parameter-cartesian-neighborhood-v2",
                  "performance input requires current neighborhood protocol")
        m.require(all(x.candidate in base.centers and x.parameter_point is None for x in base.evidence),
                  "baseline request accepts only center account evidence")
        m.unique((x.evaluation_id for x in (*base.evidence, *self.parameter_evidence)), "evaluation ID")
        m.unique(((x.candidate.candidate_id, x.window_id, x.scenario_id)
                  for x in (*base.evidence, *self.parameter_evidence)), "evaluation coordinate")
        m.unique(((x.parent, x.parameter_point.point_index) for x in self.parameter_evidence),
                 "performance point")
        designs = {x.center: x for x in base.parameter_designs}
        links = {(x.parent, x.child): x for x in base.perturbations}
        identities = {x.candidate_id: x.content_sha256 for x in (
            *base.centers, *(x.child for x in base.perturbations), *(x.candidate for x in base.evidence))}
        for item in self.parameter_evidence:
            m.require(identities.get(item.candidate.candidate_id) == item.candidate.content_sha256,
                      "performance candidate content identity conflict")
            design = designs.get(item.parent)
            m.require(isinstance(design, m.ParameterNeighborhoodDesign),
                      "performance parent requires a neighborhood design")
            m.require(item.parameter_point == design.bind_point(item.parameter_point.point_index),
                      "performance point differs from design")
            link = links.get((item.parent, item.candidate))
            m.require(link is not None and link.derivation_sha256 == item.derivation_sha256
                      and link.parameter_point == item.parameter_point,
                      "performance parent/derivation/binding differs from link")
        executed = {(x.candidate, x.window_id, x.scenario_id) for x in self.parameter_evidence}
        m.require(all(x.status is not m.IncompleteEvaluationStatus.NOT_RUN
                      or (x.candidate, x.window_id, x.scenario_id) not in executed for x in base.incomplete),
                  "NOT_RUN conflicts with completed performance evidence")


def project_parameter_performance(evidence: m.AssessmentEvidence) -> ParameterPerformanceEvidence:
    """Project supplied account facts using the same performance calculation.

    The projection preserves declared source identities; it does not certify
    publication, origin, or a TDR FULL validation.
    """
    if type(evidence) is not m.AssessmentEvidence:
        raise TypeError("performance projection requires AssessmentEvidence")
    m.require(evidence.parent is not None
              and evidence.derivation_kind is m.AssessmentDerivationKind.PARAMETERS
              and isinstance(evidence.parameter_point, m.ParameterNeighborhoodBinding),
              "performance projection requires a bound parameter derivation")
    from .research_assessment import _performance_facts
    return ParameterPerformanceEvidence(
        _performance_facts(evidence), evidence.experiment_id, evidence.attempt_id,
        evidence.request_sha256, evidence.result_sha256, evidence.context_sha256,
        evidence.window_id, evidence.scenario_id, evidence.metric_version,
        evidence.initial_cash, evidence.frequency_window_days,
        assessment_benchmark_fingerprint(evidence), evidence.parent,
        evidence.derivation_sha256, evidence.derivation_kind, evidence.parameter_point,
    )
