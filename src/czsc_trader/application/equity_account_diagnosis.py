"""Authenticate V4 retained evidence before pure continuous-account diagnosis."""
import math
from strategy_evaluator.account_diagnosis import AccountDiagnosisStatus, DecisionCoverage
from strategy_evaluator.equity_assessment import read_ledger, session
from strategy_evaluator.equity_diagnosis import diagnose_equity_accounts, PROTOCOL
from ..research_tools.account_diagnosis import AccountDiagnosisResult, DiagnosisReconciliation


def diagnose_equity_evidence(repository, request, *, execution=None):
    from .account_diagnosis_service import _json, _summarize
    refs = (request.baseline,) + (() if request.alternative is None else (request.alternative,))
    sources = tuple(x.evidence for x in refs) + tuple(x.evidence for x in request.populations)
    def fail(status, message):
        return AccountDiagnosisResult(status, PROTOCOL, (message,), sources)
    if any(r.evidence.schema != 'equity_research' or r.evidence.schema_version != 4 for r in refs):
        return fail(AccountDiagnosisStatus.INCOMPARABLE, "diagnosis requires the same explicit equity evidence contract")
    try:
        loaded = []
        from strategy_evaluator.equity_assessment import EquityCertificationScope
        from ..research_tools.equity_replay import build_equity_assessment
        from .equity_evidence_io import materialize_equity_document
        if execution is None:
            certification = EquityCertificationScope()
        else:
            from ..research_tools.equity_replay import _state
            if execution.context.repository.root != repository.root:
                raise ValueError('diagnosis session belongs to another repository')
            certification = _state(execution.context.evaluation, execution).certification
        for ref in refs:
            value = _json(ref.evidence._read_verified(repository.root)[1])
            if (value.get("schema_version") != ref.evidence.schema_version or value["request"]["experiment"] != {
                    "strategy_id": ref.evidence.experiment.strategy_id, "experiment_id": ref.evidence.experiment.experiment_id}
                    or value["evaluation_identity"] != ref.identity.to_dict()):
                raise ValueError("equity account identity or origin differs")
            view = materialize_equity_document(repository.root, ref.evidence.repository_path, value)
            facts = build_equity_assessment(view, scope=certification)[0]
            value = view.payload
            loaded.append((value, read_ledger(facts.equity.candidate_ledger)))
        def comparable(value):
            r = value["request"]
            return {k: r[k] for k in ("instrument", "specification", "initial_cash", "fee_rate", "window", "benchmark",
                                       "drawdown_basis", "concentration_basis")} | {
                "data": {key: value["data"][key] for key in ("bars", "sessions", "actions", "constraints")},
                "execution_data": {k: v for k, v in value["data"].items() if k.startswith("execution:")}}
        if len(loaded) == 2 and comparable(loaded[0][0]) != comparable(loaded[1][0]):
            return fail(AccountDiagnosisStatus.INCOMPARABLE, "equity market, data, execution, cost or window differs")
        for _, ledger in loaded:
            if (request.window.start.isoformat() < ledger["account_points"][0]["session"]
                    or request.window.end.isoformat() > ledger["account_points"][-1]["session"]):
                return fail(AccountDiagnosisStatus.INCOMPARABLE, "diagnostic window exceeds retained coverage")
        calculation = diagnose_equity_accounts(loaded[0][1], refs[0].identity.evaluation_id,
            request.window.start, request.window.end, symbol=loaded[0][0]["request"]["instrument"]["symbol"],
            alternative=None if len(loaded) == 1 else loaded[1][1],
            alternative_id=None if len(refs) == 1 else refs[1].identity.evaluation_id)
        coverage = []
        by_id = {ref.identity.evaluation_id: ledger for ref, (_, ledger) in zip(refs, loaded)}
        seen = set()
        for ref in request.populations:
            value = _json(ref.evidence._read_verified(repository.root)[1])
            if (type(value) is not dict or set(value) != {"schema_version", "population_id", "evaluation_id", "memberships"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or value["population_id"] != ref.population_id or type(value["memberships"]) is not list):
                raise ValueError("decision population requires exact schema 1")
            identity = value["evaluation_id"]
            if identity not in by_id or (identity, ref.population_id) in seen:
                raise ValueError("population evaluation absent or duplicated")
            seen.add((identity, ref.population_id))
            ledger = by_id[identity]
            ids = {r["decision_id"] for r in ledger["decisions"]}
            members = {}
            for member in value["memberships"]:
                if (type(member) is not dict or set(member) != {"decision_id", "member"}
                        or member["decision_id"] not in ids or member["decision_id"] in members
                        or (member["member"] is not None and type(member["member"]) is not bool)):
                    raise ValueError("invalid or duplicate decision population membership")
                members[member["decision_id"]] = member["member"]
            buys = {r["order_id"]: r["decision_id"] for r in ledger["orders"] if r["side"] == "BUY"}
            buy_decisions = set(buys.values())
            filled = {buys[r["order_id"]] for r in ledger["fills"] if r["side"] == "BUY"}
            for decision in ledger["decisions"]:
                zone = "Asia/Shanghai" if ledger["specification"]["market"]["rule_version"] == "CN_EQUITY_V1" else "America/New_York"
                day = session(decision["execution_start"], zone)
                if request.window.start.isoformat() <= day <= request.window.end.isoformat():
                    key = decision["decision_id"]
                    coverage.append(DecisionCoverage(identity, ref.population_id, key, day, members.get(key),
                        key in buy_decisions, key in filled,
                        decision['target_quantity'] > 0 and not decision['plan']['orders'] and not decision['plan']['legs']))
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return fail(AccountDiagnosisStatus.INVALID_EVIDENCE, str(exc))
    reconciliation = tuple(DiagnosisReconciliation(p.evaluation_id, p.daily[0].opening_equity,
        p.daily[-1].closing_equity, p.daily[-1].closing_equity - p.daily[0].opening_equity,
        math.fsum(d.entry + d.holding + d.exit + d.fees for d in p.daily),
        math.fsum(d.residual for d in p.daily)) for p in calculation.pnl_breakdown)
    return AccountDiagnosisResult(calculation.status, calculation.protocol, calculation.issues, sources,
        calculation.pnl_breakdown, tuple(coverage), calculation.path_comparison, calculation.daily_paths,
        reconciliation, _summarize(tuple(coverage)))
