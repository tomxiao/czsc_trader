"""Project recorded V4 account observations into the shared SE contracts."""

from enum import StrEnum

from dataflows import AssetClass, InstrumentId, MarketId
from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, ClosedCycle, EquityAssessmentFacts, EvaluationScenarioContext, FillSide,
    ParameterPerformanceEvidence, PerformanceFacts,
)
from strategy_evaluator.equity_assessment import canonical_observations, session
from strategy_manager import CandidateDerivation, CandidateKey
from strategy_runtime import canonical_sha256

from .parameter_evaluation import ParameterEvaluationBinding


class AssessmentProjection(StrEnum):
    FULL = "FULL"
    PARAMETER_PERFORMANCE = "PARAMETER_PERFORMANCE"


def build_equity_assessment_payload(payload, *, projection: AssessmentProjection = AssessmentProjection.FULL
        ) -> tuple[AssessmentEvidence, ...] | tuple[ParameterPerformanceEvidence, ...]:
    """Adapt saved observations once; do not certify their source or recompute metrics."""
    from .equity_replay import MaterializedEquity
    if type(payload) is not MaterializedEquity:
        raise TypeError("equity assessment requires the resolved immutable V4 closure")
    if type(projection) is not AssessmentProjection:
        raise TypeError("assessment projection requires AssessmentProjection")
    source_sha256 = payload.source_sha256
    header, runs = payload._account_facts()
    request = header["request"]
    instrument = request["instrument"]
    instrument_id = InstrumentId(MarketId(instrument["market"]), AssetClass(instrument["asset_class"]), instrument["symbol"])
    key = CandidateKey(request["experiment"]["strategy_id"], request["candidate_id"])
    content = request["content_sha256"]
    run = runs["candidate"]
    def observations(value):
        return canonical_observations({"initial_cash": request["initial_cash"],
            "specification": request["specification"], "account_points": value["account_points"],
            "trades": value["trades"]})
    parent, derivation_hash, derivation_kind, point = None, None, None, None
    lineage = request.get("lineage")
    if lineage is not None:
        derivation = CandidateDerivation.from_dict(lineage["derivation"])
        if derivation.child != key or derivation.child_content_sha256 != content:
            raise ValueError("equity lineage does not identify evaluated child")
        parent = AssessmentCandidate(f"{derivation.parent.strategy_id}-{derivation.parent.candidate_id}",
                                     derivation.parent_content_sha256)
        derivation_hash = canonical_sha256(derivation.to_dict())
        derivation_kind = AssessmentDerivationKind(derivation.kind.value)
        if lineage.get("parameter_binding") is not None:
            point = ParameterEvaluationBinding.from_dict(lineage["parameter_binding"]).point
    version = f"equity-assessment-v4:{request['drawdown_basis']}:{request['concentration_basis']}"
    benchmark = request["benchmark"]
    comparison = {
        "instrument": instrument, "specification": request["specification"],
        "data": header["data"], "sessions": [row["session"] for row in run["account_daily"]],
        "window": request["window"], "history_start": request["history_start"],
        "initial_cash": request["initial_cash"], "benchmark": request["benchmark_sha256"],
        "frequency_window_days": request["frequency_window_days"], "metric_version": version,
    }
    if "income_policy" in request:
        comparison["income_policy"] = request["income_policy"]
    context = canonical_sha256(comparison)
    candidate = AssessmentCandidate(f"{key.strategy_id}-{key.candidate_id}", content)
    scenario = EvaluationScenarioContext(float(request["fee_rate"]), request["measurement_tier"],
        benchmark["benchmark_id"], benchmark["kind"], request["benchmark_sha256"])
    if projection is AssessmentProjection.PARAMETER_PERFORMANCE:
        if (parent is None or derivation_kind is not AssessmentDerivationKind.PARAMETERS or point is None):
            raise ValueError("parameter performance projection requires a bound parameter derivation")
        from strategy_evaluator import equity_benchmark_fingerprint
        basis = request["drawdown_basis"]
        if basis not in {"SESSION_CLOSE", "BAR_CLOSE"}:
            raise ValueError("parameter performance requires an explicit drawdown basis")
        field = "daily_max_drawdown" if basis == "SESSION_CLOSE" else "bar_max_drawdown"
        own, reference = run["metrics"], runs["buy_hold"]["metrics"]
        performance = PerformanceFacts(candidate, header["evaluation_id"], scenario,
            float(own["annualized_return"]), float(own[field]),
            float(reference["annualized_return"]), float(reference[field]), point.point_index)
        fingerprint = equity_benchmark_fingerprint(
            initial_cash=float(request["initial_cash"]),
            sessions=tuple(row["session"] for row in run["account_daily"]),
            benchmark_equity=tuple(float(row["equity"]) for row in runs["buy_hold"]["account_daily"]),
            market=instrument["market"], timezone=instrument_id.timezone,
            currency=instrument_id.currency, drawdown_basis=basis,
            benchmark_ledger=observations(runs["buy_hold"]))
        return (ParameterPerformanceEvidence(performance, request["experiment"]["experiment_id"],
            source_sha256[:32], header["request_hash"], source_sha256, context,
            request["window_id"], request["scenario_id"], version,
            float(request["initial_cash"]), request["frequency_window_days"], fingerprint,
            parent, derivation_hash, derivation_kind, point),)
    facts = EquityAssessmentFacts(instrument["market"], instrument_id.timezone, instrument_id.currency,
        request["drawdown_basis"], request["concentration_basis"],
        observations(run), observations(runs["buy_hold"]))
    account = tuple(AccountPoint(r["session"], float(r["cash"]), int(r["quantity"]), float(r["close"]), float(r["equity"]))
                    for r in run["account_daily"])
    fills = tuple(AssessmentFill(r["cycle_id"], session(r["interval_end"], facts.timezone), FillSide(r["side"]),
                                int(r["quantity"]), float(r["price"]), float(r["fees"])) for r in run["fills"])
    closed = tuple(ClosedCycle(r["cycle_id"], session(r["exit_at"], facts.timezone)) for r in run["trades"])
    behavior = canonical_sha256({name: run[name] for name in ("fills", "account_entries", "account_points", "trades")})
    return (AssessmentEvidence(
        candidate,
        request["experiment"]["experiment_id"], source_sha256[:32], header["evaluation_id"],
        header["request_hash"], source_sha256, context, request["window_id"], request["scenario_id"], version,
        scenario,
        float(request["initial_cash"]), float(request["initial_cash"]), 0,
        request["frequency_window_days"], account, fills, closed,
        tuple(float(r["equity"]) for r in runs["buy_hold"]["account_daily"]),
        parent, derivation_hash, behavior, derivation_kind, point, facts),)
