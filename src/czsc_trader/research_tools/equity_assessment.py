"""Adapt immutable V4 equity facts to the shared, market-aware SE contracts."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json

import pandas as pd
from dataflows import EquityDataRequest, EquityProduct, EquityQuery, SourceRef
from dataflows.equity_data import sessions_from_metadata, validate_equity_frame
from dataflows.errors import DataflowError

from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, ClosedCycle, EquityAssessmentFacts, EvaluationScenarioContext, FillSide,
)
from strategy_evaluator.equity_assessment import canonical_ledger, daily_points, session, certify_equity_ledger
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
    records = payload["audit_inputs"].get("decision_inputs", {})
    expected = {"sessions"} | ({"auxiliary"} if definition.auxiliary_inputs else set())
    if definition.execution_input is not None:
        expected |= {'execution'}
        declared = definition.execution_input
        bound_execution = binding.execution_input
        if bound_execution is None or bound_execution.input != declared:
            raise ValueError('execution quote binding differs from definition')
        for query in declared.requests(pd.Timestamp(request['window']['start']).tz_convert(definition.instrument.timezone).date(),
                pd.Timestamp(request['window']['end']).tz_convert(definition.instrument.timezone).date()):
            product = query.parameters.query.product
            rows = pd.DataFrame(records['execution'][product.name.lower()])
            for field in ('Date', 'BarStart', 'AvailableDate'):
                if field in rows:
                    rows[field] = pd.to_datetime(rows[field], utc=True)
            validate_equity_frame(rows, query, data[declared.data_key(product)]['metadata'])
    elif binding.execution_input is not None:
        raise ValueError('undeclared execution quote input')
    if type(records) is not dict or set(records) != expected:
        raise ValueError("equity decision input fields differ from declarations")
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
    rows = frame(records["sessions"])
    query = EquityDataRequest(definition.instrument, SourceRef(**request["sources"]["sessions"]),
        EquityQuery(EquityProduct.SESSIONS, start, end, definition.execution_spec.decision_clock))
    metadata = data["sessions"]["metadata"]
    validate_equity_frame(rows, query, metadata)
    if metadata["sessions"] != data["bars"]["metadata"]["sessions"]:
        raise ValueError("equity main session calendar differs from bars")
    kwargs.update(sessions=rows, trading_sessions=sessions_from_metadata(metadata))
    _decision_availability(payload, definition, kwargs)


def _decision_availability(payload, definition, inputs):
    """Independent linear availability audit; never reconstruct full histories per bar."""
    latency = timedelta(seconds=definition.execution_spec.data_latency_seconds)
    frontiers = {}
    for declaration in definition.auxiliary_inputs:
        rows = inputs["auxiliary_histories"][declaration.name].to_dict("records")
        events = sorted(((max(row["Date"], row["AvailableDate"] + latency), index)
                         for index, row in enumerate(rows)))
        frontiers[declaration.name] = [rows, events, 0, -1, 0, False]
    intervals = {}
    rows = inputs["sessions"]
    calendar = inputs["trading_sessions"]
    if (tuple(rows.SessionDate) != tuple(item.session_date.isoformat() for item in calendar)
            or tuple(rows.Date) != tuple(item.segments[0].start for item in calendar)):
        raise ValueError("session table differs from calendar evidence")
    for trading_session, available in zip(calendar, rows.AvailableDate, strict=True):
        if trading_session.timezone != definition.instrument.timezone:
            raise ValueError("session timezone differs from instrument")
        for interval in trading_session.bars(definition.execution_spec.decision_clock):
            key = interval.start, interval.end
            if key in intervals:
                raise ValueError("current execution interval has no unique session")
            intervals[key] = available
    for row in sorted(payload["runs"]["candidate"]["decisions"], key=lambda item: item["decision_at"]):
        if row.get("signal_status") == "SUPPRESSED_UNOBSERVED_BAR":
            continue
        at = datetime.fromisoformat(row["decision_at"])
        for declaration in definition.auxiliary_inputs:
            state = frontiers[declaration.name]
            rows, events, cursor, latest, count, invalid = state
            while cursor < len(events) and events[cursor][0] <= at:
                index = events[cursor][1]
                latest = max(latest, index)
                source = rows[index]
                if source.get("BarStatus", "OBSERVED") == "OBSERVED":
                    count += 1
                    invalid |= float(source["Volume"]) <= 0
                cursor += 1
            state[2:] = cursor, latest, count, invalid
            if latest < 0 or rows[latest].get("BarStatus", "OBSERVED") != "OBSERVED" or invalid:
                raise ValueError("AUXILIARY_INPUT_UNAVAILABLE: " + declaration.name)
            if count < declaration.warmup_bars:
                raise ValueError("AUXILIARY_WARMUP_INSUFFICIENT: " + declaration.name)
            if (at - rows[latest]["Date"]).total_seconds() > declaration.max_age_seconds:
                raise ValueError("AUXILIARY_INPUT_STALE: " + declaration.name)
        key = datetime.fromisoformat(row["execution_start"]), datetime.fromisoformat(row["execution_end"])
        if key not in intervals:
            raise ValueError("current execution interval has no unique session")
        if intervals[key] > at:
            raise ValueError("CAUSAL_TIME_VIOLATION: session is not yet available")


def build_equity_assessment_payload(payload):
    """Authenticate serialized facts without reading mutable candidate sources."""
    from .equity_replay import MaterializedEquity
    if type(payload) is not MaterializedEquity:
        raise TypeError("equity assessment requires the resolved immutable V4 closure")
    source_sha256 = payload.source_sha256
    payload = payload.payload
    version = 4
    schema = "equity-research/v4"
    if (type(payload) is not dict or payload.get("schema") != schema
            or type(payload.get("schema_version")) is not int or payload["schema_version"] != 4):
        raise ValueError("equity assessment requires equity-research/v4")
    request = payload["request"]
    if request.get("candidate_definition", {}).get("contract_version") != version:
        raise ValueError("account evidence version differs from strategy contract")
    if request.get("schema") != schema or equity_hash(request) != payload["request_hash"]:
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
    if instrument["market"] not in {"US", "CN"}:
        raise ValueError("equity assessment requires a supported market")
    inputs = payload["audit_inputs"]
    economic_fields = {"bars", "action_facts", "constraints", "specification", "initial_cash", "fee_rate"}
    input_fields = economic_fields | {"decision_inputs"}
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
        ledger["account_contract"] = 4
        if name == 'candidate' and definition.execution_input is not None:
            ledger['execution_bars'] = inputs['decision_inputs']['execution']['bars']
        audit = certify_equity_ledger(ledger)
        if _canonical(asdict(audit)) != _canonical(run["metrics"]):
            raise ValueError("equity metrics differ from independently audited account")
        if list(daily_points(ledger)) != run["account_daily"]:
            raise ValueError("equity daily observations differ from account journal")
        from .equity_evaluation import _data_quality
        if run.get("data_quality") != _data_quality(inputs["bars"], run,
                timezone=definition.instrument.timezone, execution_bars=ledger.get("execution_bars")):
            raise ValueError("equity archived data quality differs from audited facts")
        ledgers[name] = ledger
    facts = EquityAssessmentFacts(instrument["market"], definition.instrument.timezone, definition.instrument.currency, request["drawdown_basis"],
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
    version = f"equity-assessment-v4:{facts.drawdown_basis}:{facts.concentration_basis}"
    context = canonical_sha256({
        "instrument": instrument, "specification": inputs["specification"],
        "data": payload["data"], "sessions": [row.session for row in account],
        "window": request["window"], "history_start": request["history_start"],
        "initial_cash": request["initial_cash"], "benchmark": benchmark.fingerprint,
        "frequency_window_days": request["frequency_window_days"], "metric_version": version,
    })
    result_hash = source_sha256 or sha256(_canonical(payload).encode()).hexdigest()
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
