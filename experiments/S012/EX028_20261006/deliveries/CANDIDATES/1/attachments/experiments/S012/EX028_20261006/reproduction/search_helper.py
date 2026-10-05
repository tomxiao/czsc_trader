"""Read-only S012 search serialization and screening/FULL coverage auditing.

assemble_searches(screening_path, formal_records, metadata=None) returns
(tuple[SearchRecord, ...], audit_dict). Importing never writes or publishes.

The original search.json and audit dict must be retained as delivery attachments.
Screening COMPLETE means completed research calculation, never a FULL evaluation.
FULL verification domains below describe the actual selected finite verification
set; they are explicitly not inferred optimizer bounds or expansion evidence.
"""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import (
    CandidateIdentityRef, CategoricalParameterDomain, EvaluationEvidenceRef,
    NumericParameterDomain, ParameterScale, ParameterValue, SearchRecord,
    SearchTrial, SearchTrialStatus,
)
from research_experiment import EvaluationRecord
from strategy_manager import CandidateKey


def _load(value):
    if isinstance(value, (str, Path)):
        return json.loads(Path(value).read_text(encoding="utf-8"))
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parameter_sha256(parameters):
    """Hash exact declared parameter values, including type, without candidate ID."""
    return sha256(_json(parameters).encode("utf-8")).hexdigest()


def _parameters(value):
    if isinstance(value, dict):
        values = value
    else:
        values = {x["name"]: x["value"] for x in value}
        if len(values) != len(value):
            raise ValueError("Duplicate parameter names")
    if any(type(x) not in (str, int, float, bool) for x in values.values()):
        raise TypeError("Public SearchRecord parameters must be scalar values")
    return values


def _domain(name, raw):
    if isinstance(raw, (NumericParameterDomain, CategoricalParameterDomain)):
        return raw
    if "type" in raw:
        cls = {"NumericParameterDomain": NumericParameterDomain,
               "CategoricalParameterDomain": CategoricalParameterDomain}.get(raw["type"])
        if cls is not None:
            return cls.from_dict(raw)
    if "choices" in raw:
        return CategoricalParameterDomain(name, tuple(raw["choices"]))
    lower, upper = raw.get("lower", raw.get("low")), raw.get("upper", raw.get("high"))
    if lower is None or upper is None:
        raise ValueError(f"Missing declared domain bounds: {name}")
    scale = raw.get("scale", "LOG" if raw.get("log", False) else "LINEAR")
    step = raw.get("step")
    integer = raw.get("integer", str(raw.get("kind", "")).upper() in {"INT", "INTEGER"})
    return NumericParameterDomain(name, float(lower), float(upper), ParameterScale(scale),
                                  None if step is None else float(step), bool(integer))


def _domains(raw):
    if isinstance(raw, dict):
        return tuple(_domain(name, value) for name, value in raw.items())
    return tuple(_domain(value.name if isinstance(value, (NumericParameterDomain, CategoricalParameterDomain))
                         else value["name"], value) for value in raw)


def _state(raw, *, screening):
    state = str(getattr(raw, "value", raw)).upper()
    state = state.rsplit(".", 1)[-1]
    aliases = {"FAIL": "FAILED", "SUCCEEDED": "COMPLETE"}
    if not screening and state == "UNKNOWN":
        # SearchTrial has no UNKNOWN member. The real UNKNOWN remains in the
        # EvaluationRecord, evidence closure and explicit trial reason.
        return SearchTrialStatus.FAILED
    return SearchTrialStatus(aliases.get(state, state))


def screening_record(search, *, metadata=None):
    """Use exact declared domains and every submitted proposal; infer no bounds."""
    search = _load(search)
    meta = dict(metadata or {})
    if isinstance(search, dict):
        meta.update(search)
        proposals = meta.get("proposals", meta.get("trials"))
    else:
        proposals = search
    if proposals is None:
        raise ValueError("Search input requires all proposals/trials")
    required = ("search_id", "domains", "method", "method_version", "seed",
                "scheduling", "declared_budget", "stop_reason")
    if any(name not in meta for name in required):
        raise ValueError("Missing declared search metadata: " + ", ".join(x for x in required if x not in meta))
    if not str(meta["stop_reason"]).strip():
        raise ValueError("Search closure requires an explicit evidence-based stop reason")
    trials = []
    for row in proposals:
        parameters = _parameters(row.get("parameters", row.get("params", {})))
        proposal = row.get("proposal_id")
        if proposal is None:
            number = row.get("trial_number", row.get("number"))
            if number is None:
                raise ValueError("Each submitted proposal requires a stable ID or trial number")
            proposal = f"{meta['search_id']}:trial:{number}"
        state = _state(row.get("status", row.get("state")), screening=True)
        if type(row.get("passed_all", False)) is not bool:
            raise TypeError("passed_all must be a boolean")
        reason = row.get("reason")
        if not reason:
            raise ValueError(f"Missing proposal reason: {proposal}")
        reason = f"SCREENING研究计算，未认证为FULL；{reason}；screening_passed_all={row.get('passed_all', False)}"
        trials.append(SearchTrial(str(proposal), tuple(ParameterValue(k, v) for k, v in parameters.items()),
                                  state, reason, None, (), row.get("predecessor_proposal_id")))
    record = SearchRecord(meta["search_id"], _domains(meta["domains"]), meta["method"],
                          meta["method_version"], meta["seed"], meta["scheduling"],
                          meta["declared_budget"], tuple(trials), meta["stop_reason"])
    SearchRecord.from_dict(record.to_dict())
    return record, tuple(proposals)


def _formal_rows(inputs):
    rows = _load(inputs)
    if isinstance(rows, dict):
        rows = rows["records"]
    return tuple(rows)


def formal_record(records, *, search_id="S012_STAGE3_FULL_VERIFICATION", stop_reason,
                  declared_budget=None):
    """Describe every actual formal attempt, including unsuccessful evaluations."""
    records = _formal_rows(records)
    values, rows = {}, []
    attempts = set()
    for row in records:
        raw = row["record"]
        attempt = raw if isinstance(raw, EvaluationRecord) else EvaluationRecord.from_dict(raw)
        if attempt.attempt_id in attempts:
            raise ValueError("Duplicate formal attempt metadata")
        attempts.add(attempt.attempt_id)
        if attempt.status.value == "STARTED":
            raise ValueError("Cannot close search with unterminated formal attempt")
        parameters = _parameters(row["parameters"])
        for name, value in parameters.items():
            values.setdefault(name, {})[_json(value)] = value
        key = CandidateKey("S012", attempt.candidate_id.removeprefix("S012-"))
        declared = row.get("candidate_id", key.candidate_id).removeprefix("S012-")
        if declared != key.candidate_id:
            raise ValueError("Formal metadata candidate differs from evaluator record")
        identity = CandidateIdentityRef(key, attempt.content_sha256)
        evidence = (EvaluationEvidenceRef(attempt.experiment_id, attempt.attempt_id, attempt.evaluation_ids),)
        reason = (f"真实FULL尝试状态={attempt.status.value}；经济目标passed_all={row.get('passed_all', False)}；"
                  + row.get("judgment", row.get("hypothesis", "正式完整账户验证")))
        if attempt.error_code:
            reason += f"；{attempt.error_code}: {attempt.error_message}"
        rows.append(SearchTrial(f"FULL:{attempt.experiment_id}:{attempt.attempt_id}",
                                tuple(ParameterValue(k, v) for k, v in parameters.items()),
                                _state(attempt.status, screening=False), reason, identity, evidence))
    domains = tuple(CategoricalParameterDomain(name, tuple(choices[k] for k in sorted(choices)))
                    for name, choices in sorted(values.items()))
    return SearchRecord(search_id, domains, "Explicit selected finite FULL verification set", "1", None,
                        "Managed evaluator requests; actual scheduling and resources in experiment receipts",
                        declared_budget, tuple(rows), stop_reason)


def coverage_audit(proposals, formal_records):
    """Check every unique screening pass received successful exact-parameter FULL evidence."""
    formal_records = _formal_rows(formal_records)
    formal_all, formal_success = set(), set()
    formal_ids, hashes, formal_states = set(), {}, Counter()
    formal_passed = set()
    for row in formal_records:
        raw = row["record"]
        record = raw if isinstance(raw, EvaluationRecord) else EvaluationRecord.from_dict(raw)
        params_hash = parameter_sha256(_parameters(row["parameters"]))
        formal_all.add(params_hash)
        formal_states[record.status.value] += 1
        formal_ids.add(record.candidate_id)
        prior = hashes.setdefault(record.candidate_id, record.content_sha256)
        if prior != record.content_sha256:
            raise ValueError("One formal candidate ID has conflicting executable content")
        if record.status.value == "SUCCEEDED":
            formal_success.add(params_hash)
            if row.get("passed_all", False):
                formal_passed.add(record.candidate_id)
        elif row.get("passed_all", False):
            raise ValueError("Failed/UNKNOWN attempt cannot pass economic targets")
    passing, selected, all_parameters, behavior = set(), set(), set(), set()
    screening_states = Counter()
    proposal_ids = set()
    for row in proposals:
        params = _parameters(row.get("parameters", row.get("params", {})))
        params_hash = parameter_sha256(params)
        all_parameters.add(params_hash)
        state = _state(row.get("status", row.get("state")), screening=True)
        screening_states[state.value] += 1
        proposal_ids.add(row.get("proposal_id", row.get("trial_number", row.get("number"))))
        if row.get("behavior_sha256"):
            behavior.add(row["behavior_sha256"])
        if row.get("selected_for_full", False):
            if state is not SearchTrialStatus.COMPLETE:
                raise ValueError("A non-completed screening proposal cannot be selected as a finished frontier point")
            selected.add(params_hash)
        if row.get("passed_all", False):
            if state is not SearchTrialStatus.COMPLETE:
                raise ValueError("PRUNED/FAILED screening proposal cannot be a completed pass")
            passing.add(params_hash)
    missing = passing - formal_success
    missing_selected = selected - formal_success
    return {
        "screening_proposal_count": len(proposals),
        "screening_unique_parameter_count": len(all_parameters),
        "screening_unique_reported_behavior_count": len(behavior),
        "screening_states": dict(screening_states),
        "screening_unique_pass_count": len(passing),
        "screening_explicit_full_selected_count": len(selected),
        "formal_attempt_count": len(formal_records),
        "formal_unique_candidate_count": len(formal_ids),
        "formal_unique_parameter_count": len(formal_all),
        "formal_states": dict(formal_states),
        "formal_passed_candidate_ids": sorted(formal_passed),
        "screening_pass_missing_successful_full_parameter_hashes": sorted(missing),
        "screening_all_passes_successful_full_verified": not missing,
        "screening_selected_missing_successful_full_parameter_hashes": sorted(missing_selected),
        "screening_all_selected_successful_full_verified": not missing_selected,
        "no_pass_frontier_selection_declared": bool(selected) if not passing else None,
        "limits": [
            "参数匹配使用本工具规范化哈希；原文件parameter_sha256保留，不强制假定同一编码。",
            "同参数FULL成功尚需同实现、输入及经济账本等价证据，当前参数覆盖检查不认证等价。",
            "域边界性质、扩边/旧域对照、停止充分性及失败实验闭包须作为原始附件人工核验。",
        ],
    }


def assemble_searches(screening_path, formal_records, *, metadata=None,
                      formal_search_id="S012_STAGE3_FULL_VERIFICATION",
                      formal_stop_reason, formal_declared_budget=None, require_pass_coverage=True):
    """Read-only typed searches and coverage; unresolved screening passes reject closure."""
    screening, proposals = screening_record(screening_path, metadata=metadata)
    formal = formal_record(formal_records, search_id=formal_search_id, stop_reason=formal_stop_reason,
                           declared_budget=formal_declared_budget)
    audit = coverage_audit(proposals, formal_records)
    if require_pass_coverage:
        missing = (set(audit["screening_pass_missing_successful_full_parameter_hashes"])
                   | set(audit["screening_selected_missing_successful_full_parameter_hashes"]))
        if missing:
            raise ValueError("Some screening passes/selected frontier points lack successful exact-parameter FULL verification: "
                             + ", ".join(sorted(missing)))
    return (screening, formal), audit


def assemble_multiple_searches(screening_paths, formal_records, *, formal_stop_reason,
                              formal_search_id="S012_STAGE3_FULL_VERIFICATION",
                              formal_declared_budget=None, require_pass_coverage=True):
    """Combine intact screening histories with one actual formal verification set.

    The caller supplies augmented selection copies as immutable attachments and
    retains originals plus their byte hashes. This helper edits none of them.
    """
    records, proposals, per_search = [], [], {}
    for path in screening_paths:
        record, rows = screening_record(path)
        if record.search_id in per_search:
            raise ValueError("Each screening history requires its original unique search ID")
        records.append(record)
        proposals.extend(rows)
        per_search[record.search_id] = coverage_audit(rows, formal_records)
    formal = formal_record(formal_records, search_id=formal_search_id,
                           stop_reason=formal_stop_reason, declared_budget=formal_declared_budget)
    if formal.search_id in per_search:
        raise ValueError("Formal verification search ID conflicts with screening")
    audit = coverage_audit(tuple(proposals), formal_records)
    audit["per_screening_search"] = per_search
    if require_pass_coverage:
        missing = (set(audit["screening_pass_missing_successful_full_parameter_hashes"])
                   | set(audit["screening_selected_missing_successful_full_parameter_hashes"]))
        if missing:
            raise ValueError("Some screening passes/selected frontier points lack successful FULL verification: "
                             + ", ".join(sorted(missing)))
    return (*records, formal), audit
