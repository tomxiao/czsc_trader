"""Adapt archived equity/v2 facts to the shared, market-aware SE contracts."""

from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json

import pandas as pd
from dataflows import EquityDataRequest, EquityProduct, EquityQuery, SourceRef, TimeInterval
from dataflows.equity_data import sessions_from_metadata, validate_equity_frame
from dataflows.errors import DataflowError

from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, ClosedCycle, EquityAssessmentFacts, EvaluationScenarioContext, FillSide,
)
from strategy_evaluator.equity import audit_equity_account
from strategy_evaluator.equity_assessment import canonical_ledger, daily_points, session
from strategy_manager import CandidateDerivation, CandidateKey
from strategy_runtime import canonical_sha256
from strategy_runtime.equity import equity_hash
from strategy_runtime.equity_definition import EquityInputBinding, EquityStrategyDefinition

from ..backtesting.benchmark_contracts import EvaluationBenchmark, EquityBuyHold
from .evaluation import EvaluationIdentity
from .parameter_evaluation import ParameterEvaluationBinding


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decision_inputs(payload, definition, binding):
    """Authenticate declared context and recheck availability without strategy imports."""
    request, data = payload["request"], payload["data"]
    if dict(binding.expected_identities) != {key: value["content_sha256"] for key, value in data.items()}:
        raise ValueError("equity input binding differs from archived data")
    if tuple(item.input for item in binding.auxiliary_inputs) != definition.auxiliary_inputs:
        raise ValueError("equity auxiliary binding differs from definition")
    enabled = definition.auxiliary_inputs or definition.session_context
    records = payload["audit_inputs"].get("decision_inputs", {})
    expected = ({"sessions"} if definition.session_context else set()) | ({"auxiliary"} if definition.auxiliary_inputs else set())
    if type(records) is not dict or set(records) != expected:
        raise ValueError("equity decision input fields differ from declarations")
    if not enabled:
        return
    from strategy_runtime.equity import DecisionPoint, EquityPortfolio
    from strategy_runtime.equity_context import build_equity_decision_context

    def frame(rows):
        result = pd.DataFrame(rows)
        for column in ("Date", "BarStart", "AvailableDate"):
            if column in result:
                result[column] = pd.to_datetime(result[column], utc=True)
        return result

    start = date.fromisoformat(request["history_start"])
    end = pd.Timestamp(request["window"]["end"]).tz_convert(definition.instrument.timezone).date()
    kwargs = {}
    if definition.auxiliary_inputs:
        values = records["auxiliary"]
        if type(values) is not dict or set(values) != {item.name for item in definition.auxiliary_inputs}:
            raise ValueError("equity auxiliary facts differ from declarations")
        histories = {}
        for item in definition.auxiliary_inputs:
            if type(values[item.name]) is not dict or set(values[item.name]) != {"bars", "sessions"}:
                raise ValueError("equity auxiliary product facts differ")
            calendars = []
            for query in item.requests(start, end):
                product = query.parameters.query.product
                rows = frame(values[item.name][product.name.lower()])
                metadata = data[item.data_key(product)]["metadata"]
                validate_equity_frame(rows, query, metadata)
                calendars.append(metadata["sessions"])
                if product is EquityProduct.BARS:
                    histories[item.name] = rows
            if calendars[0] != calendars[1]:
                raise ValueError("equity auxiliary calendars differ within instrument")
        kwargs["auxiliary_histories"] = histories
    if definition.session_context:
        rows = frame(records["sessions"])
        query = EquityDataRequest(definition.instrument, SourceRef(**request["sources"]["sessions"]),
            EquityQuery(EquityProduct.SESSIONS, start, end, definition.execution_spec.decision_clock))
        metadata = data["sessions"]["metadata"]
        validate_equity_frame(rows, query, metadata)
        if metadata["sessions"] != data["bars"]["metadata"]["sessions"]:
            raise ValueError("equity main session calendar differs from bars")
        kwargs.update(sessions=rows, trading_sessions=sessions_from_metadata(metadata))
    history = frame(payload["audit_inputs"]["bars"])
    for row in payload["runs"]["candidate"]["decisions"]:
        if row.get("signal_status") == "SUPPRESSED_UNOBSERVED_BAR":
            continue
        point = DecisionPoint(datetime.fromisoformat(row["observed_through"]),
            datetime.fromisoformat(row["decision_at"]), TimeInterval(
                datetime.fromisoformat(row["execution_start"]), datetime.fromisoformat(row["execution_end"])))
        observed = history[(history.Date <= point.observed_through) & (history.AvailableDate + pd.Timedelta(
            seconds=definition.execution_spec.data_latency_seconds) <= point.decision_at)]
        if "BarStatus" in observed:
            observed = observed.loc[observed.BarStatus.eq("OBSERVED")].drop(columns=["BarStatus", "ExecutionBlocked"], errors="ignore")
        build_equity_decision_context(definition, observed,
            EquityPortfolio(float(request["initial_cash"]), 0, 0., 0), point, **kwargs)


def build_equity_assessment_payload(payload):
    """Authenticate serialized facts without reading mutable candidate sources."""
    if (type(payload) is not dict or payload.get("schema") != "equity-research/v2"
            or type(payload.get("schema_version")) is not int or payload["schema_version"] != 2):
        raise ValueError("formal equity assessment requires equity-research/v2")
    request = payload["request"]
    if request.get("schema") != "equity-research/v2" or equity_hash(request) != payload["request_hash"]:
        raise ValueError("equity assessment request hash differs")
    if set(payload["runs"]) != {"candidate", "buy_hold"}:
        raise ValueError("equity assessment requires candidate and benchmark")
    key = CandidateKey(request["experiment"]["strategy_id"], request["candidate_id"])
    content = request["candidate_identity"]["content_sha256"]
    if content != request["content_sha256"]:
        raise ValueError("equity candidate content identity differs")
    definition = EquityStrategyDefinition.from_dict(request["candidate_definition"])
    if (asdict(definition.content_identity) != request["candidate_identity"]
            or asdict(definition.instrument) != request["instrument"]
            or asdict(definition.execution_spec) != request["specification"]
            or definition.execution_spec.fingerprint != request["specification_hash"]
            or definition.warmup_bars != request["warmup_bars"]):
        raise ValueError("equity archived definition differs from declared identity or execution")
    identity_value = dict(payload["evaluation_identity"])
    identity_value["candidate"] = CandidateKey(**identity_value["candidate"])
    identity = EvaluationIdentity(**identity_value)
    if (identity.candidate != key or identity.content_sha256 != content
            or identity.evaluation_id != payload["evaluation_id"]
            or identity.input_sha256 != request["data_manifest"]
            or identity.protocol_sha256 != payload["request_hash"]
            or identity.environment_sha256 != canonical_sha256(request["engine_sources"])):
        raise ValueError("equity evaluation identity differs")
    benchmark = EvaluationBenchmark.from_dict(request["benchmark"])
    if (benchmark.fingerprint != request["benchmark_sha256"] or type(benchmark.execution) is not EquityBuyHold
            or benchmark.execution.execution_spec != definition.execution_spec):
        raise ValueError("equity benchmark fingerprint differs")
    instrument = request["instrument"]
    if instrument["market"] != "US":
        raise ValueError("equity assessment requires US market")
    inputs = payload["audit_inputs"]
    economic_fields = {"bars", "action_facts", "constraints", "specification", "initial_cash", "fee_rate"}
    input_fields = economic_fields | ({"decision_inputs"} if definition.auxiliary_inputs or definition.session_context else set())
    if type(inputs) is not dict or set(inputs) != input_fields:
        raise ValueError("equity audit input fields differ")
    if (inputs["specification"] != request["specification"]
            or inputs["initial_cash"] != request["initial_cash"] or inputs["fee_rate"] != request["fee_rate"]):
        raise ValueError("equity audit inputs differ from request")
    if equity_hash(inputs) != request["audit_inputs_sha256"]:
        raise ValueError("equity audit input fingerprint differs")
    binding = EquityInputBinding.from_dict(request["input_binding"])
    if (binding.prepared.manifest_sha256 != request["data_manifest"]
            or binding.instrument != definition.instrument
            or binding.specification_hash != definition.execution_spec.fingerprint
            or binding.warmup_bars != definition.warmup_bars):
        raise ValueError("equity input binding differs from archived data")
    try:
        _decision_inputs(payload, definition, binding)
    except DataflowError as exc:
        raise ValueError(f"equity archived decision inputs violate data contract: {exc}") from exc
    start, end = (datetime.fromisoformat(request["window"][key]) for key in ("start", "end"))
    expected_times = [row["Date"] for row in inputs["bars"]
                      if datetime.fromisoformat(row["BarStart"]) >= start and datetime.fromisoformat(row["Date"]) <= end]
    expected_time_set = set(expected_times)
    expected_bars = [row for row in inputs["bars"] if row["Date"] in expected_time_set]
    if (not expected_bars or datetime.fromisoformat(expected_bars[0]["BarStart"]) != start
            or datetime.fromisoformat(expected_bars[-1]["Date"]) != end):
        raise ValueError("equity evidence window does not align with source bars")
    ledgers = {}
    for name, run in payload["runs"].items():
        if [row["time"] for row in run["account_points"]] != expected_times:
            raise ValueError("equity account does not cover requested observation window")
        if name == "buy_hold" and any(row["target"] != 1.0 and row.get("signal_status") != "SUPPRESSED_UNOBSERVED_BAR"
                                      for row in run["decisions"]):
            raise ValueError("equity benchmark decisions differ from EquityBuyHold")
        ledger = {**{field: inputs[field] for field in economic_fields}, **{field: run[field] for field in (
            "decisions", "orders", "fills", "actions", "account_points", "trades")}}
        audit = audit_equity_account(**ledger, decision_contract="FORMAL_V2")
        if _canonical(asdict(audit)) != _canonical(run["metrics"]):
            raise ValueError("equity metrics differ from independently audited account")
        if list(daily_points(ledger)) != run["account_daily"]:
            raise ValueError("equity daily observations differ from account journal")
        from .equity_evaluation import _data_quality
        if run.get("data_quality") != _data_quality(inputs["bars"], run):
            raise ValueError("equity archived data quality differs from audited facts")
        ledgers[name] = ledger
    facts = EquityAssessmentFacts("US", "America/New_York", "USD", request["drawdown_basis"],
        request["concentration_basis"], canonical_ledger(ledgers["candidate"]), canonical_ledger(ledgers["buy_hold"]))
    run = payload["runs"]["candidate"]
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
            binding = ParameterEvaluationBinding.from_dict(lineage["parameter_binding"])
            point = binding.point
    version = f"equity-assessment-v2:{facts.drawdown_basis}:{facts.concentration_basis}"
    context = canonical_sha256({
        "instrument": instrument, "specification": inputs["specification"],
        "data": payload["data"], "sessions": [row.session for row in account],
        "window": request["window"], "history_start": request["history_start"],
        "initial_cash": request["initial_cash"], "benchmark": benchmark.fingerprint,
        "frequency_window_days": request["frequency_window_days"], "metric_version": version,
    })
    result_hash = sha256(_canonical(payload).encode()).hexdigest()
    behavior = canonical_sha256({name: run[name] for name in (
        "fills", "actions", "account_points", "trades")})
    return (AssessmentEvidence(
        AssessmentCandidate(f"{key.strategy_id}-{key.candidate_id}", content),
        request["experiment"]["experiment_id"], result_hash[:32], identity.evaluation_id,
        payload["request_hash"], result_hash, context, request["window_id"], request["scenario_id"], version,
        EvaluationScenarioContext(float(request["fee_rate"]), request["measurement_tier"],
            benchmark.benchmark_id, benchmark.kind, benchmark.fingerprint),
        float(request["initial_cash"]), float(request["initial_cash"]), 0,
        request["frequency_window_days"], account, fills, closed,
        tuple(float(r["equity"]) for r in payload["runs"]["buy_hold"]["account_daily"]),
        parent, derivation_hash, behavior, derivation_kind, point, facts),)


def build_equity_assessment_evidence(request, result):
    from .equity_evaluation import EquityEvaluationRequest, EquityEvaluationResult, _json_value
    if type(request) is not EquityEvaluationRequest or type(result) is not EquityEvaluationResult:
        raise TypeError("equity assessment requires typed request and result")
    payload = result.payload
    if request.prepared is None:
        raise ValueError("equity assessment requires the prepared request")
    expected = request.identity(request.candidate.definition.execution_spec)
    if _json_value(expected) != payload["request"]:
        raise ValueError("equity assessment request differs from result")
    evidence = build_equity_assessment_payload(payload)
    if any(item.result_sha256 != result.result_hash for item in evidence):
        raise ValueError("equity result bytes differ from canonical evidence")
    return evidence
