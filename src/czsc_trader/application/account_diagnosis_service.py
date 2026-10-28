"""Read-only authentication and adaptation for numerical account diagnosis."""

import json
import math

from strategy_evaluator.account_diagnosis import (
    DIAGNOSIS_PROTOCOL,
    AccountDiagnosisStatus,
    DecisionCoverage,
    PopulationCoverageSummary,
    diagnose_account_replays,
)
from strategy_evaluator.replay_audit import ReplayEvidence

from .context import RepositoryContext
from ..research_tools.account_diagnosis import (
    AccountDiagnosisRequest,
    AccountDiagnosisResult,
    DiagnosisReconciliation,
)
from ..research_tools.evaluation import validate_evaluation_evidence


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(
        data,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON number: {value}")
        ),
    )


def _load(repository, run):
    ref = run.evidence
    if (ref.schema != "account_evaluation" or ref.schema_version not in (7, 8)
            or ref.media_type != "application/json"):
        raise ValueError("account diagnosis requires account_evaluation schema 7 or 8")
    value = _json(ref._read_verified(repository.root)[1])
    if value.get("schema_version") != ref.schema_version:
        raise ValueError("account evidence schema differs from reference")
    validate_evaluation_evidence(value)
    request = value["request_identity"]
    if request["experiment_id"] != ref.experiment.experiment_id:
        raise ValueError("account evidence experiment origin differs from reference")
    if run.identity.candidate.strategy_id != ref.experiment.strategy_id:
        raise ValueError("account evaluation batch differs from evidence origin")
    selected = [item for item in value["runs"] if item["identity"] == run.identity.to_dict()]
    if len(selected) != 1:
        raise ValueError("account identity does not select exactly one retained evaluation")
    selected = selected[0]
    return request, selected, ReplayEvidence.from_dict(selected["replay_evidence"])


def _comparison_context(request, run):
    # Candidate implementation and derived input features can differ. Market data,
    # units, benchmark, fees, sessions and initial account remain comparable.
    return {
        key: request[key]
        for key in (
            "symbol",
            "asset_type",
            "data_identity",
            "initial_cash",
            "pricing",
            "benchmark",
            "execution_mode",
            "market_rules",
        )
    } | {"cost": next(c for c in request["costs"] if c["scenario_id"] == run["scenario_id"])}


def _coverage(repository, populations, loaded, window):
    by_id = {reference.identity.evaluation_id: replay for reference, _, _, replay in loaded}
    seen = set()
    result = []
    for ref in populations:
        payload = _json(ref.evidence._read_verified(repository.root)[1])
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "population_id", "evaluation_id", "memberships"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
        ):
            raise ValueError("decision population requires schema 1 and exact fields")
        if payload["population_id"] != ref.population_id:
            raise ValueError("population identity differs from its reference")
        evaluation = payload["evaluation_id"]
        if evaluation not in by_id or (evaluation, ref.population_id) in seen:
            raise ValueError("population evaluation is absent or duplicated")
        seen.add((evaluation, ref.population_id))
        replay = by_id[evaluation]
        decision_ids = {d["decision_id"] for d in replay.decisions}
        members = {}
        if not isinstance(payload["memberships"], list):
            raise ValueError("population memberships must be an array")
        for member in payload["memberships"]:
            if not isinstance(member, dict) or set(member) != {"decision_id", "member"}:
                raise ValueError("population membership requires exact decision_id/member fields")
            decision = member["decision_id"]
            if (
                decision not in decision_ids
                or decision in members
                or (member["member"] is not None and type(member["member"]) is not bool)
            ):
                raise ValueError("population contains unknown, duplicate or invalid membership")
            members[decision] = member["member"]
        buys = {o["decision_id"] for o in replay.orders if o["side"] == "BUY"}
        filled = {f["decision_id"] for f in replay.fills if f["side"] == "BUY"}
        accounts = {str(r["date"])[:10]: r for r in replay.account_daily}
        for decision in replay.decisions:
            session = str(decision["valid_session"])[:10]
            if not window.start.isoformat() <= session <= window.end.isoformat():
                continue
            key = decision["decision_id"]
            quantity = int(accounts[session]["quantity_before"])
            target = float(decision["target_position"])
            holding = quantity > 0 and target == 1.0
            result.append(
                DecisionCoverage(
                    evaluation,
                    ref.population_id,
                    key,
                    session,
                    members.get(key),
                    key in buys,
                    key in filled,
                    holding,
                )
            )
    return tuple(result)


def _summarize(coverage):
    summaries = []
    for evaluation, population in sorted({(r.evaluation_id, r.population_id) for r in coverage}):
        rows = [
            r for r in coverage if (r.evaluation_id, r.population_id) == (evaluation, population)
        ]
        for category in ("buy_intent", "buy_fill", "holding_decision"):
            selected = [r for r in rows if getattr(r, category)]
            members = sum(r.member is True for r in selected)
            nonmembers = sum(r.member is False for r in selected)
            unknown = sum(r.member is None for r in selected)
            summaries.append(
                PopulationCoverageSummary(
                    evaluation,
                    population,
                    category,
                    len(selected),
                    members,
                    nonmembers,
                    unknown,
                    members / len(selected) if selected and not unknown else None,
                )
            )
    return tuple(summaries)


def diagnose_accounts(
    repository: RepositoryContext, request: AccountDiagnosisRequest
) -> AccountDiagnosisResult:
    """Diagnose retained account facts without preparing data or replaying a strategy."""
    if type(repository) is not RepositoryContext or type(request) is not AccountDiagnosisRequest:
        raise TypeError("account diagnosis requires RepositoryContext and AccountDiagnosisRequest")
    if request.baseline.evidence.schema == "equity_research" or (
            request.alternative is not None and request.alternative.evidence.schema == "equity_research"):
        from .equity_account_diagnosis import diagnose_equity_evidence
        return diagnose_equity_evidence(repository, request)
    refs = (request.baseline,) + (() if request.alternative is None else (request.alternative,))
    sources = tuple(r.evidence for r in refs) + tuple(p.evidence for p in request.populations)

    def failure(status, message):
        return AccountDiagnosisResult(status, DIAGNOSIS_PROTOCOL, (message,), sources)

    try:
        loaded = tuple((ref, *_load(repository, ref)) for ref in refs)
        coverage = _coverage(repository, request.populations, loaded, request.window)
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return failure(AccountDiagnosisStatus.INVALID_EVIDENCE, str(exc))
    baseline, left_request, left_run, left = loaded[0]
    for _, _, _, replay in loaded:
        if (
            request.window.start.isoformat() < str(replay.account_daily[0]["date"])[:10]
            or request.window.end.isoformat() > str(replay.account_daily[-1]["date"])[:10]
        ):
            return failure(
                AccountDiagnosisStatus.INCOMPARABLE,
                "diagnostic window exceeds retained account coverage",
            )
    right = None
    if len(loaded) == 2:
        _, right_request, right_run, right = loaded[1]
        if (
            _comparison_context(left_request, left_run)
            != _comparison_context(right_request, right_run)
            or left.evaluation_sessions != right.evaluation_sessions
        ):
            return failure(
                AccountDiagnosisStatus.INCOMPARABLE,
                "market, execution, units, cost or session context differs",
            )
    calculation = diagnose_account_replays(
        left,
        baseline.identity.evaluation_id,
        request.window.start,
        request.window.end,
        symbol=left_request["symbol"],
        alternative=right,
        alternative_id=None
        if request.alternative is None
        else request.alternative.identity.evaluation_id,
    )
    reconciliation = tuple(
        DiagnosisReconciliation(
            p.evaluation_id,
            p.daily[0].opening_equity,
            p.daily[-1].closing_equity,
            p.daily[-1].closing_equity - p.daily[0].opening_equity,
            math.fsum(d.entry + d.holding + d.exit + d.fees for d in p.daily),
            p.daily[-1].closing_equity
            - p.daily[0].opening_equity
            - math.fsum(d.entry + d.holding + d.exit + d.fees for d in p.daily),
        )
        for p in calculation.pnl_breakdown
    )
    return AccountDiagnosisResult(
        calculation.status,
        calculation.protocol,
        calculation.issues,
        sources,
        calculation.pnl_breakdown,
        coverage if calculation.status is AccountDiagnosisStatus.COMPUTED else (),
        calculation.path_comparison,
        calculation.daily_paths,
        reconciliation,
        _summarize(coverage) if calculation.status is AccountDiagnosisStatus.COMPUTED else (),
    )
