"""Read-only S012 native stage-three draft builder; no registration/publication API.

prepare(root, config) authenticates the supplied files and completed REX traces,
recomputes the original three goals from serialized FULL ledgers, and constructs
public CandidateSet/ResearchDeliverable/registration-request values in memory.
Importing does no work. The caller explicitly persists the returned audit and
later calls the platform's registration/publication APIs in its own workflow.

The companion config.example.json describes required inputs. FULL metadata is a
list of real trial rows, including all terminal failures. Screening search.json
must contain every submitted proposal, its declared domains and exact scope.
No legacy helper, experiment number, parameter-only coverage or old gate is used.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
from typing import Mapping

from dataflows import Dataset

from czsc_trader.application import CandidateRegistrationRequest
from czsc_trader.research_tools import (
    CandidateEntry, CandidateIdentityRef, CandidateSet, CategoricalParameterDomain,
    DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage,
    DeliveryStatus, EvaluationEvidenceRef, EvidenceFile, EvidenceRef,
    ExperimentEvidenceRef, ExperimentEvidenceUse, ExperimentOwner, Explanation,
    ExplanationKind, FactStatus, FactValue, NumericParameterDomain, ParameterScale,
    ParameterValue, ReproductionSpec, ResearchDeliverable, SearchRecord, SearchTrial,
    SearchTrialStatus,
)
from research_experiment import EvaluationRecord, load_experiment, load_experiment_input
from strategy_manager import CandidateEvidence, CandidateKey, CandidateRegistrationOrigin
from strategy_runtime import (
    ImplementationDependency, StrategyCandidate, StrategyRuntime, canonical_sha256,
)


FAMILY = "S012"
SCOPE_FIELDS = (
    "implementation_sha256", "feature_sha256", "execution_data_fingerprint",
    "execution_policy_sha256", "economic_protocol_sha256", "gate_sha256",
)
EXPECTED_COMPONENT = {
    "type": "DeliveryReference",
    "owner": {"type": "ExperimentOwner", "strategy_id": FAMILY,
              "experiment_id": "EX041_20261006"},
    "stage": "COMPONENTS", "revision": 1,
    "content_sha256": "42f663cfa2299b78792ea3eb73a32ee478215de164356da0b56947d305471bf4",
}
EXPECTED_MANDATE = "6e2f856f79f4211f0f6532b3349b33a2f35cd881fd8c4a687d020dff5bb46435"


def require(value, message):
    if not value:
        raise ValueError(message)


def plain(value):
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def digest(value):
    return sha256(json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def scoped(root, relative, *, directory=False):
    """Disallow accidentally reading another batch or production from config."""
    require(isinstance(relative, str) and "\\" not in relative,
            "Use repository-relative POSIX paths")
    path = (root / relative).resolve()
    path.relative_to(root)
    normalized = path.relative_to(root).as_posix()
    require(any(normalized.startswith(prefix) for prefix in (
        "research/S012/", "experiments/S012/", ".tmp/s012-stage3-native-20261006/",
    )), f"Out-of-scope evidence: {relative}")
    require(path.is_dir() if directory else path.is_file(), f"Missing path: {relative}")
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def checked(root, reference, checks):
    require(set(reference) == {"path", "sha256"}, "File reference requires path and sha256")
    path = scoped(root, reference["path"])
    require(file_sha(path) == reference["sha256"], f"File hash differs: {reference['path']}")
    checks[reference["path"]] = reference["sha256"]
    return path


def scalar_parameters(raw):
    require(isinstance(raw, dict) and raw, "Declared scalar parameters are required")
    require(all(type(value) in (str, int, float, bool) for value in raw.values()),
            "Search parameters must be public scalar values")
    require(all(not isinstance(value, float) or isfinite(value) for value in raw.values()),
            "Nonfinite search parameter")
    return raw


def scope_key(scope, parameters):
    require(set(scope) == set(SCOPE_FIELDS), "Scope must contain exactly six identity fields")
    for name in SCOPE_FIELDS:
        value = scope[name]
        require((name == "gate_sha256" and value is None)
                or (isinstance(value, str) and len(value) == 64
                    and all(char in "0123456789abcdef" for char in value)),
                f"Invalid scope identity: {name}")
    return digest({"scope": scope, "parameters": scalar_parameters(parameters)})


def protocol(result, run):
    """Comparable economic protocol; preserve actual FULL mode in result separately."""
    request = result["request_identity"]
    window = next(item for item in request["windows"] if item["window_id"] == run["window_id"])
    cost = next(item for item in request["costs"] if item["scenario_id"] == run["scenario_id"])
    return {"symbol": request["symbol"], "asset_type": request["asset_type"],
            "window": window, "data_cutoff": request["data_cutoff"],
            "initial_cash": request["initial_cash"], "cost": cost,
            "benchmark": request["benchmark"],
            "frequency_window_days": request["frequency_window_days"],
            "frequency_denominator": 1535,
            "metric_semantics_version": request["metric_semantics_version"]}


def derive_formal_scope(root, row, *, gate_sha256=None, window_id="DEVELOPMENT", scenario_id="BASE"):
    """Derive scope from actual successful FULL evidence; no prepare or writes.

    For failed attempts, preserve declared request scope separately: there is no
    successful input/result identity to derive. First prototype FULL can use a
    null gate; selected screening validation must explicitly link its new gate.
    """
    root = Path(root).resolve()
    record = EvaluationRecord.from_dict(row["record"])
    require(record.status.value == "SUCCEEDED", "Scope derivation requires successful real FULL")
    candidate = StrategyCandidate(FAMILY, row["candidate_id"].removeprefix(FAMILY + "-"),
                                  row["payload"], scoped(root, row["source_root"], directory=True))
    loaded = load_experiment(root / "experiments/S012" / record.experiment_id)
    dependencies = tuple(ImplementationDependency(item.name, item.version)
                         for item in loaded.definition.dependencies)
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=dependencies)
    require(identity.content_sha256 == record.content_sha256, "Candidate implementation differs")
    result_path = scoped(root, f"experiments/S012/{record.experiment_id}/artifacts/rex/{record.result_artifact.path}")
    require(file_sha(result_path) == record.result_artifact.sha256, "Formal result bytes differ")
    result = read(result_path)
    run = next(item for item in result["runs"] if item["window_id"] == window_id
               and item["scenario_id"] == scenario_id)
    return {"implementation_sha256": identity.source_sha256,
            "feature_sha256": candidate.payload["parameters"]["rule"]["data_source"]["sha256"],
            "execution_data_fingerprint": result["request_identity"]["data_identity"],
            "execution_policy_sha256": digest(runtime.describe(candidate).execution),
            "economic_protocol_sha256": digest(protocol(result, run)), "gate_sha256": gate_sha256}


def gate_scope_base_sha256(scope):
    return digest({name: scope[name] for name in SCOPE_FIELDS
                   if name not in {"gate_sha256", "execution_policy_sha256"}})


def search_domain_sha256(raw):
    return digest([domain.to_dict() for domain in domains(raw)])


def table_rows(value):
    require(isinstance(value, dict) and isinstance(value.get("data"), list),
            "Expected schema-v4 embedded ledger table; supply an adapter for other schemas")
    return value["data"]


def account_metrics(rows, initial_cash):
    require(len(rows) == 1534, "FULL account must preserve 1534 actual evaluation sessions")
    dates = [str(row["date"])[:10] for row in rows]
    require(dates == sorted(set(dates)) and dates[0] == "2020-06-08"
            and dates[-1] == "2026-09-30", "Unexpected account interval")
    equity = [float(row["equity"]) for row in rows]
    require(all(isfinite(value) and value > 0 for value in equity), "Invalid account equity")
    peak, drawdown = float(initial_cash), 0.0
    for value in equity:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return {"net_cagr": (equity[-1] / initial_cash) ** (252 / len(rows)) - 1,
            "max_drawdown": drawdown, "sessions": len(rows), "dates": dates}


def qualification(result, run):
    contract = protocol(result, run)
    require(contract["symbol"] == "518850.SH" and contract["asset_type"] == "etf",
            "Unexpected instrument")
    require(contract["initial_cash"] == 100000 and contract["cost"]["one_way_cost"] == .001
            and contract["cost"]["measurement_tier"] == "FORMAL"
            and contract["frequency_window_days"] == 60,
            "Original account cost/cash/frequency contract differs")
    require(contract["benchmark"]["execution"] == {"type": "NextOpenBuyHold", "lot_size": 100},
            "Original BuyHold execution differs")
    require(contract["window"]["start"] == "2020-06-08"
            and contract["window"]["end"] == "2026-09-30"
            and contract["data_cutoff"] == "2026-09-30", "Full pool contract differs")
    account = account_metrics(table_rows(run["ledgers"]["account_daily"]), 100000.)
    benchmark = account_metrics(table_rows(run["buyhold"]["account_daily"]), 100000.)
    require(account.pop("dates") == benchmark.pop("dates"), "Strategy/BH sessions differ")
    trades = table_rows(run["ledgers"]["trades"])
    closed = sum(trade["status"] == "CLOSED" for trade in trades)
    frequency = closed * 60 / 1535
    goals = (account["net_cagr"] >= benchmark["net_cagr"] * 1.5,
             abs(account["max_drawdown"]) < abs(benchmark["max_drawdown"]),
             frequency >= 5)
    return {"account": account, "benchmark": benchmark, "closed_cycles": closed,
            "frequency": frequency, "frequency_denominator": 1535,
            "goals": list(goals), "passed_all": all(goals)}


def domains(raw):
    require(isinstance(raw, (list, dict)) and raw, "Predeclared domains required")
    values = raw if isinstance(raw, list) else [dict(value, name=name) for name, value in raw.items()]
    result = []
    for value in values:
        if value.get("type") == "NumericParameterDomain":
            result.append(NumericParameterDomain.from_dict(value))
        elif value.get("type") == "CategoricalParameterDomain":
            result.append(CategoricalParameterDomain.from_dict(value))
        elif "choices" in value:
            result.append(CategoricalParameterDomain(value["name"], tuple(value["choices"])))
        else:
            result.append(NumericParameterDomain(
                value["name"], float(value["lower"]), float(value["upper"]),
                ParameterScale(value.get("scale", "LINEAR")),
                None if value.get("step") is None else float(value["step"]),
                value.get("integer", False)))
    return tuple(result)


def receipt_closure(root, current, checks):
    references, attempts, documents = {}, {}, {}

    def visit(eid, expected=None):
        require(eid.startswith("EX") and "/" not in eid and "\\" not in eid,
                "Invalid S012 experiment ID")
        if eid in references:
            require(expected is None or references[eid].receipt_sha256 == expected,
                    "Predecessor receipt differs")
            return
        workspace = scoped(root, f"experiments/S012/{eid}/artifacts/rex", directory=True)
        receipt = read(workspace / "execution_receipt.json")
        sha = receipt["receipt_sha256"]
        require(expected is None or sha == expected, "Predecessor receipt differs")
        # Public read-only loader authenticates complete REX artifact closure.
        load_experiment_input(workspace, expected_receipt_sha256=sha)
        require(receipt["experiment_id"] == eid, "Receipt experiment differs")
        documents[eid] = receipt
        references[eid] = ExperimentEvidenceRef(
            eid, workspace.relative_to(root).as_posix(), sha,
            ExperimentEvidenceUse.CURRENT_EVALUATION if eid in current
            else ExperimentEvidenceUse.HISTORICAL_REFERENCE)
        if eid in current:
            for raw in receipt["trace"]["evaluations"]:
                record = EvaluationRecord.from_dict(raw)
                key = (eid, record.attempt_id)
                require(key not in attempts and record.status.value != "STARTED", "Nonterminal/duplicate attempt")
                attempts[key] = record
        for predecessor, predecessor_sha in receipt["predecessor_receipts"].items():
            visit(predecessor, predecessor_sha)

    for eid in sorted(current):
        visit(eid)
    return tuple(references[eid] for eid in sorted(references)), attempts, documents


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


def prepare(root, config):
    """Return (typed draft, audit dict); never mutate governance or the filesystem."""
    root = Path(root).resolve()
    config = read(scoped(root, config)) if isinstance(config, str) else dict(config)
    checks = {}
    component = read(checked(root, config["component_receipt"], checks))
    component_ref = DeliveryReference.from_dict(component["reference"])
    require(component_ref.to_dict() == EXPECTED_COMPONENT, "Latest authorized EX041 COMPONENTS differs")
    component_root = Path(config["component_receipt"]["path"]).parent
    for item in component["files"]:
        checked(root, {"path": (component_root / item["path"]).as_posix(),
                       "sha256": item["sha256"]}, checks)
    require(read(scoped(root, (component_root / "delivery.json").as_posix()))["content"]["status"] == "COMPLETE",
            "Actual latest COMPONENTS is incomplete")
    auth = read(checked(root, config["authorization_review"], checks))
    require(auth["stage2_reference"] == EXPECTED_COMPONENT and auth.get("user_instruction"),
            "Native-resume authorization differs")
    decision_ref = read(checked(root, config["authorization_decision_reference"], checks))
    decision_file = {"path": "research/S012/" + decision_ref["evidence"]["path"],
                     "sha256": decision_ref["evidence"]["sha256"]}
    decision = read(checked(root, decision_file, checks))
    require(decision["action"] == "APPROVE" and decision["subject"]["target_stage"] == "CANDIDATES"
            and decision["decision_id"] == decision_ref["decision_id"]
            and decision["subject"]["delivery"] == {
                "type": "CandidateEvidence", **config["component_receipt"]},
            "Approval subject differs from real latest component receipt")
    confirmation = decision["confirmation_source"]
    confirmation_path = checked(root, {"path": "research/S012/" + confirmation["path"],
                                       "sha256": confirmation["sha256"]}, checks)
    require(read(confirmation_path) == auth, "Approval confirmation differs from actual native-resume review")
    start = read(checked(root, config["authorization_start"], checks))
    intent = start["result"]["family"]["research_intent"]
    require(start["status"] == "PASS" and intent["stage"] == "CANDIDATES"
            and config["authorization_review"]["path"] in intent["confirmation_sources"],
            "Native-resume intent evidence differs")
    mandate = read(checked(root, config["mandate_receipt"], checks))
    mandate_ref = DeliveryReference.from_dict(mandate["reference"])
    require(mandate_ref.content_sha256 == EXPECTED_MANDATE, "Original mandate differs")
    mandate_root = Path(config["mandate_receipt"]["path"]).parent
    for item in mandate["files"]:
        checked(root, {"path": (mandate_root / item["path"]).as_posix(),
                       "sha256": item["sha256"]}, checks)

    closure = read(checked(root, config["closure_review"], checks))
    require(closure.get("decision_statement"), "Explicit research closure judgment required")
    complete = closure["status"] == "COMPLETE"
    require(closure["status"] in {"COMPLETE", "PARTIAL", "BLOCKED"}, "Invalid closure status")
    for reference in closure["evidence_files"]:
        checked(root, reference, checks)
    if complete:
        require(all(closure.get(name) is True for name in (
            "search_completed", "equivalence_completed", "boundary_review_completed",
            "selection_history_disclosed")), "Initial FULL trials alone cannot close stage three")
        require(bool(closure["evidence_files"]), "Complete closure needs supporting evidence")

    owner = config["owner_experiment_id"]
    current = set(config["current_experiments"])
    require(owner in current, "Final owner must have real current REX receipt")
    refs, attempts, receipts = receipt_closure(root, current, checks)
    audit_input = read(checked(root, config["independent_account_audit"], checks))
    require(audit_input["status"] == "PASS" and not audit_input["errors"], "Independent account audit failed")
    require(set(audit_input["experiments"]) == current, "Independent audit does not cover exact current set")
    for eid in current:
        require(audit_input["verified_receipt_hashes"][eid] == receipts[eid]["receipt_sha256"],
                "Independent audit receipt differs")

    rows, entries, registrations, grouped = [], [], [], defaultdict(list)
    gates = {reference["sha256"]: read(checked(root, reference, checks))
             for reference in config["gates"]}
    for gate in gates.values():
        require(gate["status"] == "PASS" and gate.get("comparison_summary")
                and gate.get("evidence_files") and gate.get("full_reference_attempts"),
                "A gate must retain actual comparison evidence and successful FULL references")
        for reference in gate["evidence_files"]:
            checked(root, reference, checks)
        for reference in gate["full_reference_attempts"]:
            record = attempts.get((reference["experiment_id"], reference["attempt_id"]))
            require(record is not None and record.status.value == "SUCCEEDED"
                    and tuple(reference["evaluation_ids"]) == record.evaluation_ids,
                    "Gate reference is not a real successful FULL attempt")
    metadata_attempts, successful_keys, formal_trials = set(), set(), []
    candidate_objects, candidate_hashes, judgments = {}, {}, {}
    for reference in config["full_trials"]:
        raw = read(checked(root, reference, checks))
        rows.extend(raw if isinstance(raw, list) else raw["records"])
    for row in rows:
        record = EvaluationRecord.from_dict(row["record"])
        attempt_key = (record.experiment_id, record.attempt_id)
        require(attempt_key not in metadata_attempts and attempts.get(attempt_key) == record,
                "FULL metadata differs from receipted real attempt")
        metadata_attempts.add(attempt_key)
        candidate_id = row["candidate_id"].removeprefix(FAMILY + "-")
        require(record.candidate_id == f"{FAMILY}-{candidate_id}", "Candidate ID differs")
        parameters = scalar_parameters(row["parameters"])
        source_root = scoped(root, row["source_root"], directory=True)
        candidate = StrategyCandidate(FAMILY, candidate_id, row["payload"], source_root)
        loaded = load_experiment(root / "experiments/S012" / record.experiment_id)
        dependencies = tuple(ImplementationDependency(item.name, item.version)
                             for item in loaded.definition.dependencies)
        runtime = StrategyRuntime()
        identity = runtime.identify(candidate, dependencies=dependencies)
        require(identity.content_sha256 == record.content_sha256, "Actual candidate source/content differs")
        descriptor = candidate.payload["runtime"]
        require(descriptor["source_sha256"] == identity.source_sha256, "Implementation closure differs")
        for name in descriptor["source_files"]:
            path = (source_root / name).resolve()
            path.relative_to(source_root)
            checked(root, {"path": path.relative_to(root).as_posix(), "sha256": file_sha(path)}, checks)
        payload_parameters = {key: value for key, value in candidate.payload["parameters"].items() if key != "rule"}
        require(digest(payload_parameters) == digest(parameters), "Search/payload parameters differ")
        scope = row.get("scope")
        if scope is None:
            scope = config["scope_by_attempt"][f"{record.experiment_id}:{record.attempt_id}"]
        composite = scope_key(scope, parameters)
        if scope["gate_sha256"] is not None:
            gate = gates.get(scope["gate_sha256"])
            require(gate is not None and gate["status"] == "PASS"
                    and gate["scope_base_sha256"] == gate_scope_base_sha256(scope),
                    "Formal gate not supplied/authenticated for this source/input/protocol")
        require(scope["implementation_sha256"] == identity.source_sha256, "Scope implementation differs")
        feature = candidate.payload["parameters"]["rule"]["data_source"]
        require(feature["package"] == "strategy_runtime", "Expected immutable local feature resource")
        feature_path = (source_root / feature["path"]).resolve()
        feature_path.relative_to(source_root)
        require(feature["path"] in descriptor["source_files"], "Feature excluded from source closure")
        require(file_sha(feature_path) == feature["sha256"] == scope["feature_sha256"], "New feature bytes differ")
        definition = runtime.describe(candidate)
        require(digest(definition.execution) == scope["execution_policy_sha256"], "Execution policy scope differs")
        policy = definition.execution.settings
        require(definition.execution.policy_type == "FROZEN_RULE"
                and policy["entry"]["order_type"] == "LIMIT"
                and policy["exit"]["order_type"] == "MARKET"
                and policy["instrument"]["lot_size"] == 100
                and policy["capital"]["fee_rate"] == .001
                and 0 < policy["capital"]["allocation_fraction"] <= 1,
                "Original execution constraints differ")
        key = CandidateKey(FAMILY, candidate_id)
        require(candidate_hashes.setdefault(key, record.content_sha256) == record.content_sha256,
                "Candidate key assigned conflicting implementation")
        candidate_objects[key] = (candidate, dependencies, loaded, row)
        grouped[key].append(record)
        judgments.setdefault(key, row.get("judgment", row["hypothesis"]))
        qualified, metrics = False, None
        if record.status.value == "SUCCEEDED":
            artifact = record.result_artifact
            result_file = {"path": f"experiments/S012/{record.experiment_id}/artifacts/rex/{artifact.path}",
                           "sha256": artifact.sha256}
            result = read(checked(root, result_file, checks))
            request = result["request_identity"]
            require(request["execution_mode"] == "FULL" and request["content_sha256"] == record.content_sha256
                    and result["request_hash"] == record.request_hash
                    and result["result_hash"] == record.result_hash, "FULL result identity differs")
            require(request["data_identity"] == scope["execution_data_fingerprint"], "Market input scope differs")
            ids = tuple(canonical_sha256(run["identity"]) for run in result["runs"])
            require(ids == record.evaluation_ids, "Evaluation IDs differ from actual result identities")
            for run in result["runs"]:
                require(run["identity"]["content_sha256"] == record.content_sha256,
                        "Run implementation differs")
                require(run["identity"]["candidate"] == key.to_dict(), "Run candidate key differs")
                require(run["identity"]["input_sha256"] == canonical_sha256({
                    "execution": request["data_identity"], "signal": run["signal_data_identity"]}),
                    "Run actual signal/execution input identity differs")
                binding = result["input_bindings"][run["window_id"]]
                feature_requests = [request for request in binding["plan"]["requests"].values()
                                    if request["dataset"] == Dataset.STRATEGY_FEATURE_EVIDENCE.value]
                require(len(feature_requests) == 1 and feature_requests[0]["parameters"]["source_sha256"]
                        == scope["feature_sha256"], "Prepared feature identity differs")
            coordinate = config["qualification_coordinate"]
            selected = [run for run in result["runs"] if run["window_id"] == coordinate["window_id"]
                        and run["scenario_id"] == coordinate["scenario_id"]]
            require(len(selected) == 1, "Exactly one real qualification coordinate required")
            require(digest(protocol(result, selected[0])) == scope["economic_protocol_sha256"],
                    "Economic protocol scope differs")
            metrics = qualification(result, selected[0])
            audit_rows = [item for item in audit_input["rows"]
                          if item["experiment_id"] == record.experiment_id
                          and item["candidate_id"].removeprefix(FAMILY + "-") == candidate_id
                          and item.get("window_id") == coordinate["window_id"]
                          and item.get("scenario_id") == coordinate["scenario_id"]]
            require(len(audit_rows) == 1 and audit_rows[0]["status"] == "PASS", "Independent audit coordinate missing/ambiguous")
            independent = audit_rows[0]
            require(independent["goals"] == metrics["goals"]
                    and independent["passed_all"] == metrics["passed_all"], "Independent economic judgment differs")
            for field in ("net_cagr", "max_drawdown"):
                require(isclose(float(independent["metrics"][field]), metrics["account"][field],
                                rel_tol=1e-10, abs_tol=1e-12), f"Independent {field} differs")
            qualified = metrics["passed_all"]
            successful_keys.add(composite)
        require(type(row["passed_all"]) is bool and row["passed_all"] == qualified,
                "Caller qualification differs from real FULL account")
        state = SearchTrialStatus.COMPLETE if record.status.value == "SUCCEEDED" else (
            SearchTrialStatus.CANCELLED if record.status.value == "CANCELLED" else SearchTrialStatus.FAILED)
        formal_trials.append(SearchTrial(
            f"FULL:{record.experiment_id}:{record.attempt_id}",
            tuple(ParameterValue(name, value) for name, value in parameters.items()), state,
            f"Real FULL attempt status={record.status.value}; qualified={qualified}; scope_key={composite}",
            CandidateIdentityRef(key, record.content_sha256),
            (EvaluationEvidenceRef(record.experiment_id, record.attempt_id, record.evaluation_ids),)))
        row["_audit"] = {"scope_key": composite, "qualified": qualified, "metrics": metrics}
        if record.status.value == "SUCCEEDED":
            row["_authenticated"] = {
                "scope": dict(scope), "parameters": dict(payload_parameters),
                "payload_parameters_sha256": digest(candidate.payload["parameters"]),
                "public_content_sha256": identity.content_sha256,
                "execution_policy_sha256": digest(definition.execution),
            }
    require(metadata_attempts == set(attempts), "FULL metadata must cover every current terminal attempt")
    scope_by_attempt = {(row["record"]["experiment_id"], row["record"]["attempt_id"]):
        row["_authenticated"]["scope"] for row in rows if "_authenticated" in row}
    for gate in gates.values():
        for reference in gate["full_reference_attempts"]:
            scope = scope_by_attempt[(reference["experiment_id"], reference["attempt_id"])]
            require(gate_scope_base_sha256(scope) == gate["scope_base_sha256"],
                    "Gate FULL comparison used a different implementation/input/protocol")

    qualified_keys = {CandidateKey(FAMILY, row["candidate_id"].removeprefix(FAMILY + "-"))
                      for row in rows if row["_audit"]["qualified"]}
    for key in sorted(grouped, key=lambda item: item.candidate_id):
        candidate, dependencies, loaded, metadata = candidate_objects[key]
        entries.append(CandidateEntry(
            CandidateIdentityRef(key, candidate_hashes[key]), metadata["hypothesis"], judgments[key],
            tuple(EvaluationEvidenceRef(record.experiment_id, record.attempt_id, record.evaluation_ids)
                  for record in grouped[key])))
        if key in qualified_keys:
            eligible = next(row for row in rows if row["candidate_id"].removeprefix(FAMILY + "-") == key.candidate_id
                            and row["_audit"]["qualified"])
            origin_eid = eligible["record"]["experiment_id"]
            origin_loaded = load_experiment(root / "experiments/S012" / origin_eid)
            candidate = StrategyCandidate(FAMILY, key.candidate_id, eligible["payload"],
                scoped(root, eligible["source_root"], directory=True))
            dependencies = tuple(ImplementationDependency(item.name, item.version)
                                 for item in origin_loaded.definition.dependencies)
            preflight = scoped(root, eligible["preflight_path"])
            require(read(preflight)["status"] == "PASS", "Registration preflight failed")
            registrations.append(CandidateRegistrationRequest(
                candidate,
                CandidateRegistrationOrigin(origin_eid, origin_loaded.definition.sha256,
                    file_sha(origin_loaded.root / "experiment_binding.json"),
                    CandidateEvidence(preflight.relative_to(root).as_posix(), file_sha(preflight))),
                dependencies))

    compatible_coverage = []
    if config.get("compatible_gate_coverage") is not None:
        from compatible_gate_coverage import check_sidecar
        additional_keys, compatible_coverage = check_sidecar(
            root, config["compatible_gate_coverage"], rows, gates, config["searches"], checks)
        successful_keys.update(additional_keys)

    searches, screening_audits = [], []
    for reference in config["searches"]:
        search = read(checked(root, reference, checks))
        declared_domains = domains(search["domains"])
        proposals = search["proposals"]
        # An annotated selection view must retain the original immutable search
        # and sidecar, and may not remove/change an original proposal field.
        raw_search = read(checked(root, search["raw_search_evidence"], checks))
        selection = read(checked(root, search["selection_evidence"], checks))
        originals = raw_search["proposals"]
        require(len(originals) == len(proposals), "Selection view omitted/added search proposals")
        for original, proposal in zip(originals, proposals):
            require(all(proposal.get(name) == value for name, value in original.items()),
                    "Annotated selection changed immutable original proposal")
        require(selection["raw_search_sha256"] == search["raw_search_evidence"]["sha256"],
                "Selection belongs to a different original search")
        selected_ids = set(selection["selected_proposal_ids"])
        require(selection.get("selection_reason"), "Selection/frontier reasoning required")
        require(selected_ids == {proposal["proposal_id"] for proposal in proposals
                                 if proposal["selected_for_full"]}, "Selection sidecar differs")
        require(type(search["declared_budget"]) in (int, type(None)), "Budget is a declared integer or null")
        require(search["stop_reason"].strip(), "Search stopping evidence required")
        trials, required_full, states = [], set(), Counter()
        for proposal in proposals:
            parameters = scalar_parameters(proposal["parameters"])
            scope = proposal.get("scope", search.get("scope"))
            composite = scope_key(scope, parameters)
            require(scope["gate_sha256"] is not None, "Screening requires a new scoped equivalence gate")
            gate = read(checked(root, proposal.get("gate_evidence", search.get("gate_evidence")), checks))
            gate_reference = proposal.get("gate_evidence", search.get("gate_evidence"))
            require(gate_reference["sha256"] == scope["gate_sha256"] and gate["status"] == "PASS",
                    "Equivalence gate differs/failed")
            require(gate["scope_base_sha256"] == gate_scope_base_sha256(scope), "Gate belongs to different source/input/protocol")
            require(gate["covered_domains_sha256"] == digest([domain.to_dict() for domain in declared_domains]),
                    "Gate does not cover declared search parameter/policy domain")
            raw_state = proposal["status"].upper()
            state = SearchTrialStatus("FAILED" if raw_state == "FAIL" else raw_state)
            require(type(proposal["passed_all"]) is bool and type(proposal["selected_for_full"]) is bool,
                    "Explicit screening judgment and FULL selection required for every proposal")
            require(not proposal["passed_all"] or state is SearchTrialStatus.COMPLETE,
                    "Only completed screening can qualify for FULL")
            if proposal["passed_all"] or proposal["selected_for_full"]:
                required_full.add(composite)
            states[state.value] += 1
            reason = f"SCREENING; scope_key={composite}; passed={proposal['passed_all']}; selected={proposal['selected_for_full']}; {proposal['reason']}"
            trials.append(SearchTrial(proposal["proposal_id"],
                tuple(ParameterValue(name, value) for name, value in parameters.items()), state,
                reason, None, (), proposal.get("predecessor_proposal_id")))
        record = SearchRecord(search["search_id"], declared_domains, search["method"], search["method_version"],
            search["seed"], search["scheduling"], search["declared_budget"], tuple(trials), search["stop_reason"])
        missing = sorted(required_full - successful_keys)
        if complete:
            require(not missing, "Selected/passing screening lacks same-scope successful FULL coverage")
        screening_audits.append({"search_id": search["search_id"], "states": dict(states),
                                "required_full_scope_keys": sorted(required_full), "missing_full": missing})
        searches.append(record)
    if complete:
        require(bool(searches), "Initial prototype FULL set alone cannot close the optimizer/search delivery")

    choices = defaultdict(dict)
    for row in rows:
        for name, value in row["parameters"].items():
            choices[name][digest(value)] = value
    formal_config = config["formal_search"]
    searches.append(SearchRecord(formal_config["search_id"],
        tuple(CategoricalParameterDomain(name, tuple(values[key] for key in sorted(values)))
              for name, values in sorted(choices.items())),
        "Actual finite selected FULL verification set", "1", None,
        formal_config["scheduling"], formal_config["declared_budget"],
        tuple(formal_trials), formal_config["stop_reason"]))
    handoff = tuple(sorted(qualified_keys, key=lambda key: key.candidate_id))
    if "expected_handoff" in config:
        require(set(config["expected_handoff"]) == {key.candidate_id for key in handoff},
                "Expected handoff must equal ALL formally qualified candidates")
    candidate_set = CandidateSet(tuple(entries), handoff, tuple(searches), config["conclusion"])
    CandidateSet.from_dict(candidate_set.to_dict())
    for reference in config["attachments"]:
        checked(root, reference, checks)
    for name in ("summary", "report", "candidate_inputs"):
        checked(root, config[name], checks)
    summary_path = config["summary"]["path"]
    summary = read(scoped(root, summary_path))
    require(summary["formal_candidate_count"] == len(entries)
            and summary["formal_attempt_count"] == len(rows)
            and set(summary["handoff"]) == {key.candidate_id for key in handoff},
            "Machine summary differs from complete FULL/qualification audit")
    summary_ref = EvidenceRef("attachments/" + summary_path, checks[summary_path], "application/json")
    facts = {"formal_candidate_count": len(entries), "formal_attempt_count": len(rows),
             "handoff_count": len(handoff), "all_qualified_handoff": True,
             "all_terminal_attempts_covered": True, "scope_aware_full_coverage":
             all(not audit["missing_full"] for audit in screening_audits),
             "original_frequency_denominator": 1535,
             "independent_holdout": False, "closure_authorized_by_explicit_review": complete}
    attachments = tuple(EvidenceFile(path, EvidenceRef("attachments/" + path, sha,
        "application/json" if path.endswith(".json") else "text/markdown" if path.endswith(".md")
        else "application/octet-stream")) for path, sha in sorted(checks.items()))
    incomplete = tuple(closure.get("incomplete_items", ()))
    if not complete and not incomplete:
        incomplete = (closure["decision_statement"],)
    content = DeliveryContent(candidate_set, DeliveryStatus(closure["status"]),
        tuple(FactValue(name, value, "research_fact", FactStatus.AVAILABLE, (summary_ref,))
              for name, value in facts.items()),
        (Explanation(ExplanationKind.RESEARCH_JUDGMENT, closure["decision_statement"]),),
        ReproductionSpec(config["reproduction"], (summary_ref,),
            "Original S012 whole listing development pool; real FULL identities and ledger artifacts.",
            "Pinned source/input/policy/protocol/gate; every observed search proposal disclosed."),
        incomplete, attachments)
    draft = Draft(DeliveryDefinition(ExperimentOwner(FAMILY, owner), DeliveryStage.CANDIDATES,
        config.get("revision", 1), (component_ref, mandate_ref), refs), content, tuple(registrations))
    audit = {"status": "PASS", "delivery_status": closure["status"], "owner": owner,
        "component_reference": component_ref.to_dict(), "mandate_reference": mandate_ref.to_dict(),
        "current_experiments": sorted(current), "formal_attempt_count": len(rows),
        "formal_candidate_count": len(entries), "handoff": [key.candidate_id for key in handoff],
        "screening": screening_audits, "files": checks,
        "compatible_gate_coverage": compatible_coverage,
        "authenticated_full_sources": [{"record": row["record"], "_authenticated": row["_authenticated"]}
            for row in rows if "_authenticated" in row],
        "qualification": [{"experiment_id": row["record"]["experiment_id"],
            "attempt_id": row["record"]["attempt_id"], "candidate_id": row["candidate_id"],
            **row["_audit"]} for row in rows],
        "limits": ["No governance writes performed by this builder.",
            "Empty qualified set never determines research closure.",
            "Equivalence proof and search closure truth remain researcher-owned evidence.",
            "This builder reads prior independent managed-input/account audit; it does not rerun it.",
            "Failed attempts preserve declared scope; they have no successful result/input identity."]}
    return draft, audit
