"""Project recorded V4 account observations into the shared SE contracts."""

from dataflows import AssetClass, InstrumentId, MarketId
from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, ClosedCycle, EquityAssessmentFacts, EvaluationScenarioContext, FillSide,
)
from strategy_evaluator.equity_assessment import canonical_observations, session
from strategy_manager import CandidateDerivation, CandidateKey
from strategy_runtime import canonical_sha256

from .parameter_evaluation import ParameterEvaluationBinding


def build_equity_assessment_payload(payload):
    """Adapt saved observations once; do not certify their source or recompute metrics."""
    from .equity_replay import MaterializedEquity, _read
    if type(payload) is not MaterializedEquity:
        raise TypeError("equity assessment requires the resolved immutable V4 closure")
    source_sha256 = payload.source_sha256
    header = _read(payload.source_content)
    request = header["request"]
    instrument = request["instrument"]
    instrument_id = InstrumentId(MarketId(instrument["market"]), AssetClass(instrument["asset_class"]), instrument["symbol"])
    key = CandidateKey(request["experiment"]["strategy_id"], request["candidate_id"])
    content = request["content_sha256"]
    artifacts = {item.sha256: item for item in payload.artifacts}
    runs = {}
    for name, field in (("candidate", "candidate_ref"), ("buy_hold", "benchmark_ref")):
        document = _read(artifacts[header[field]["sha256"]].content)
        if document.get("schema") != "equity-account/v1":
            raise ValueError("equity assessment requires saved account observations")
        owner = document["owner"]
        if name == "candidate":
            if (owner.get("kind") != "CANDIDATE" or owner.get("candidate") != header["evaluation_identity"]["candidate"]
                    or owner.get("content_sha256") != content or document["input_sha256"] != header["input_ref"]["sha256"]):
                raise ValueError("equity account does not identify the requested candidate and input")
        elif (owner.get("kind") != "BENCHMARK" or owner.get("run_identity") != header["benchmark_identity"]
              or document["input_sha256"] != header["benchmark_identity"]["input_snapshot_sha256"]):
            raise ValueError("equity account does not identify the requested benchmark and input")
        runs[name] = document["run"]
    run = runs["candidate"]
    def observations(value):
        return canonical_observations({"initial_cash": request["initial_cash"],
            "specification": request["specification"], "account_points": value["account_points"],
            "trades": value["trades"]})
    facts = EquityAssessmentFacts(instrument["market"], instrument_id.timezone, instrument_id.currency,
        request["drawdown_basis"], request["concentration_basis"],
        observations(run), observations(runs["buy_hold"]))
    account = tuple(AccountPoint(r["session"], float(r["cash"]), int(r["quantity"]), float(r["close"]), float(r["equity"]))
                    for r in run["account_daily"])
    fills = tuple(AssessmentFill(r["cycle_id"], session(r["interval_end"], facts.timezone), FillSide(r["side"]),
                                int(r["quantity"]), float(r["price"]), float(r["fees"])) for r in run["fills"])
    closed = tuple(ClosedCycle(r["cycle_id"], session(r["exit_at"], facts.timezone)) for r in run["trades"])
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
    version = f"equity-assessment-v4:{facts.drawdown_basis}:{facts.concentration_basis}"
    benchmark = request["benchmark"]
    comparison = {
        "instrument": instrument, "specification": request["specification"],
        "data": header["data"], "sessions": [row.session for row in account],
        "window": request["window"], "history_start": request["history_start"],
        "initial_cash": request["initial_cash"], "benchmark": request["benchmark_sha256"],
        "frequency_window_days": request["frequency_window_days"], "metric_version": version,
    }
    if "income_policy" in request:
        comparison["income_policy"] = request["income_policy"]
    context = canonical_sha256(comparison)
    behavior = canonical_sha256({name: run[name] for name in ("fills", "account_entries", "account_points", "trades")})
    return (AssessmentEvidence(
        AssessmentCandidate(f"{key.strategy_id}-{key.candidate_id}", content),
        request["experiment"]["experiment_id"], source_sha256[:32], header["evaluation_id"],
        header["request_hash"], source_sha256, context, request["window_id"], request["scenario_id"], version,
        EvaluationScenarioContext(float(request["fee_rate"]), request["measurement_tier"],
            benchmark["benchmark_id"], benchmark["kind"], request["benchmark_sha256"]),
        float(request["initial_cash"]), float(request["initial_cash"]), 0,
        request["frequency_window_days"], account, fills, closed,
        tuple(float(r["equity"]) for r in runs["buy_hold"]["account_daily"]),
        parent, derivation_hash, behavior, derivation_kind, point, facts),)
