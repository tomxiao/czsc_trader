"""Reuse authenticated S014 account evidence for report-only family diagnostics.

No account execution, market request, registry mutation, or cross-batch access.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from czsc_trader.research_tools import EvidenceRef
from strategy_evaluator import AssessmentEvidence, FamilyReturnEvidence

ROOT = Path(__file__).resolve().parents[5]
BATCH = ROOT / "research/S014"
EX = Path(__file__).resolve().parents[1]
ORIGINAL_SHA = "e5005956b926d2062a1a0d040e1387dd30f32e64692480e055597473f153d8e2"
ORIGINAL_PATH = BATCH / f"assets/evidence/EX052_20261020/{ORIGINAL_SHA}.json"
_CACHE = None


def _read(path):
    return json.loads(path.read_bytes())


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _public_ref(path, digest):
    relative = path.relative_to(BATCH)
    if relative.parts[:2] != ("assets", "evidence"):
        raise ValueError("Only S014 public account evidence is accepted")
    return EvidenceRef.from_dict({
        "type": "EvidenceRef", "experiment": {
            "type": "ExperimentRef", "strategy_id": "S014",
            "experiment_id": relative.parts[2]},
        "evidence_id": relative.name, "sha256": digest,
        "media_type": "application/json", "name": "stage4-historical-family-account",
        "schema": "account_evaluation", "schema_version": 7})


def _context(evidence):
    return (evidence.context_sha256, evidence.metric_version,
            evidence.scenario_context, evidence.window_id, evidence.scenario_id,
            evidence.initial_cash, evidence.opening_cash, evidence.opening_quantity,
            tuple(x.session for x in evidence.account))


def _economic_hash(evidence):
    # Full funded-account path, rather than rounded returns or headline metrics.
    return sha256(json.dumps([x.to_dict() for x in evidence.account],
                             sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _load_inventory():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    original_bytes = ORIGINAL_PATH.read_bytes()
    if sha256(original_bytes).hexdigest() != ORIGINAL_SHA:
        raise ValueError("Original C9521 public evidence hash mismatch")
    original_raw = json.loads(original_bytes)
    original = AssessmentEvidence.from_dict(original_raw["assessment_evidence"][0])
    if original.candidate.candidate_id != "S014-C9521":
        raise ValueError("Original C9521 evidence identity mismatch")
    refs = {ORIGINAL_SHA: _public_ref(ORIGINAL_PATH, ORIGINAL_SHA)}
    registered = {}
    sources = {}
    for path in sorted((ROOT / "research/registrations/S014/candidates").glob("*.json")):
        record = _read(path)["record"]
        # A concurrently registered EX054 technical successor is the supplied
        # center, never an extra historical selection-family attempt.
        if record["origin"]["experiment_id"] >= "EX054":
            continue
        candidate = "S014-" + record["key"]["candidate_id"]
        registered[candidate] = record["content_sha256"]
        for ref in record["origin"]["evidence"]:
            public = BATCH / ref["path"]
            refs[ref["sha256"]] = _public_ref(public, ref["sha256"])
            sources.setdefault(ref["sha256"], []).append(str(path.relative_to(ROOT)))
    dispatches = []
    source_paths = []
    metadata_bytes = 0
    for experiment in sorted((BATCH / "experiments").iterdir()):
        if not experiment.is_dir() or experiment.name >= "EX054":
            continue
        others = experiment / "others"
        for path in sorted(others.glob("*.json")):
            # Select indexes, avoiding large duplicated accounts and unrelated
            # technical PTE/frozen replay publications in EX053.
            if experiment.name.startswith("EX053"):
                if path.name not in ("full_control.json", "c9523_full_control.json"):
                    continue
            if path.stat().st_size > 500_000:
                continue
            metadata_bytes += path.stat().st_size
            value = _read(path)
            if any(item.get("type") == "EvidenceRef" and item.get("schema") == "account_evaluation"
                   for item in _walk(value)):
                source_paths.append(str(path.relative_to(ROOT)))
            if path.name in ("account_results.json", "accounts_index.json"):
                for row in value.get("records", []):
                    dispatches.append({
                        "experiment_id": experiment.name,
                        "candidate": row.get("candidate"), "status": row.get("status"),
                        "index": row.get("index"),
                        "evidence_sha256": (row.get("evidence") or {}).get("sha256"),
                        "error": row.get("error"),
                    })
            for item in _walk(value):
                if item.get("type") != "EvidenceRef" or item.get("schema") != "account_evaluation":
                    continue
                if item["experiment"]["strategy_id"] != "S014":
                    raise ValueError("Cross-batch account reference in S014 family indexes")
                ref = EvidenceRef.from_dict(item)
                refs[ref.sha256] = ref
                sources.setdefault(ref.sha256, []).append(str(path.relative_to(ROOT)))
        # EX035 fixed-node diagnostics used individual run receipts, not an
        # accounts_index/account_results document. They are real research trials.
        if experiment.name.startswith("EX035"):
            for path in sorted((others / "accounts").glob("run-*.json")):
                row = _read(path)
                dispatches.append({
                    "experiment_id": experiment.name, "candidate": row.get("candidate"),
                    "status": row.get("status"), "index": row.get("index"),
                    "evidence_sha256": (row.get("evidence") or {}).get("sha256"),
                    "error": row.get("error")})
                source_paths.append(str(path.relative_to(ROOT)))
    delivery_path = BATCH / "assets/deliveries/CANDIDATES/14/delivery.json"
    receipt_path = BATCH / "assets/deliveries/CANDIDATES/14/receipt.json"
    delivery_bytes = delivery_path.read_bytes()
    delivery_digest = sha256(delivery_bytes).hexdigest()
    declared = next(x["sha256"] for x in _read(receipt_path)["files"] if x["path"] == "delivery.json")
    if delivery_digest != declared:
        raise ValueError("CANDIDATES/14 published delivery hash mismatch")
    search_summaries = [x for x in _walk(json.loads(delivery_bytes)) if x.get("type") == "SearchSummary"]
    loaded = []
    inventory = {
        "scope": "S014 public registered origins plus first-level historical account result indexes EX001-EX053; no assets scan",
        "original_account_ref": refs[ORIGINAL_SHA].to_dict(),
        "registered_count": len(registered), "metadata_bytes_read": metadata_bytes,
        "source_paths": sorted(set(source_paths + [
            str(delivery_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))
        ] + [path for paths in sources.values() for path in paths])),
        "search_summary_source": {"path": str(delivery_path.relative_to(ROOT)),
                                  "sha256": delivery_digest},
        "search_summaries": search_summaries,
        "search_summary_evaluations_sum_includes_reused_baselines": sum(x["evaluations"] for x in search_summaries),
        "search_summary_unique_configurations_sum_not_additive": sum(x["unique_configurations"] for x in search_summaries),
        "referenced_account_count": len(refs),
        "dispatch_status_counts": dict(Counter(x["status"] for x in dispatches)),
        "dispatches": dispatches, "accounts": [],
    }
    total_bytes = 0
    for digest, ref in refs.items():
        path = ref.resolve(ROOT)
        raw_bytes = path.read_bytes()
        total_bytes += len(raw_bytes)
        if sha256(raw_bytes).hexdigest() != digest:
            raise ValueError(f"Historical account hash mismatch: {ref.evidence_id}")
        value = json.loads(raw_bytes)
        row = {"ref": ref.to_dict(), "bytes": len(raw_bytes),
               "sources": sorted(set(sources.get(digest, []))),
               "schema_version": value.get("schema_version"), "projections": []}
        for raw in value.get("assessment_evidence", []):
            evidence = AssessmentEvidence.from_dict(raw)
            same = _context(evidence) == _context(original)
            item = {"candidate": evidence.candidate.to_dict(),
                    "experiment_id": evidence.experiment_id,
                    "evaluation_id": evidence.evaluation_id,
                    "window_id": evidence.window_id, "scenario_id": evidence.scenario_id,
                    "context_sha256": evidence.context_sha256,
                    "metric_version": evidence.metric_version,
                    "session_count": len(evidence.account),
                    "registered": registered.get(evidence.candidate.candidate_id) == evidence.candidate.content_sha256,
                    "same_original_context": same,
                    "economic_path_sha256": _economic_hash(evidence),
                    "rejection": None if same else "CONTEXT_METRIC_SCENARIO_OR_CALENDAR_DIFFERENT"}
            row["projections"].append(item)
            if same:
                loaded.append((evidence, ref, item))
        if not row["projections"]:
            row["rejection"] = "NO_SCHEMA7_ASSESSMENT_PROJECTION"
        inventory["accounts"].append(row)
    inventory["account_bytes_authenticated"] = total_bytes
    inventory["same_context_projection_count"] = len(loaded)
    inventory["limitations"] = [
        "All 2020-2026 history was repeatedly seen; this is not unseen validation.",
        "Only recoverable, published S014 accounts with exactly equal context, metric, scenario and calendar enter the matrix; incompatible or older projections are explicitly excluded.",
        "Technical reproductions and duplicate funded-account paths are collapsed; matrix width does not count them as independent mechanisms.",
        "PBO/DSR are descriptive after adaptive mechanism discovery, not proof that selection bias has been removed.",
        "Indexes record account dispatches; failed accounts have no return column. Missing historical attempts are not reconstructed by new runs.",
        "Four early observation-contract failed account dispatches enter the conservative raw trial count; one input-preparation failure was not an account dispatch and remains separately disclosed.",
    ]
    _CACHE = (original, loaded, inventory)
    return _CACHE


def build_family(center_evidence):
    """Return family evidence, account projections, public refs, and audit inventory."""
    original, loaded, source_inventory = _load_inventory()
    if _context(center_evidence) != _context(original):
        raise ValueError("Actual new center must retain original C9521 comparison context")
    if _economic_hash(center_evidence) != _economic_hash(original):
        raise ValueError("New center must exactly reproduce original C9521 funded path")
    inventory = json.loads(json.dumps(source_inventory))
    chosen = [center_evidence]
    chosen_hashes = {_economic_hash(center_evidence): center_evidence.candidate.candidate_id}
    candidate_ids = {center_evidence.candidate.candidate_id}
    supporting_refs = {}
    duplicates = []
    for evidence, ref, item in loaded:
        economic_hash = item["economic_path_sha256"]
        if economic_hash in chosen_hashes:
            duplicates.append({"candidate": evidence.candidate.candidate_id,
                               "evaluation_id": evidence.evaluation_id,
                               "representative": chosen_hashes[economic_hash],
                               "economic_path_sha256": economic_hash})
            continue
        if evidence.candidate.candidate_id in candidate_ids:
            raise ValueError("Different economic paths reuse a family candidate ID")
        chosen.append(evidence)
        candidate_ids.add(evidence.candidate.candidate_id)
        chosen_hashes[economic_hash] = evidence.candidate.candidate_id
        supporting_refs[ref.sha256] = ref
    arrays = []
    for evidence in chosen:
        equity = np.asarray([x.equity for x in evidence.account], dtype=float)
        arrays.append(equity / np.r_[evidence.initial_cash, equity[:-1]] - 1)
    family = FamilyReturnEvidence(
        candidates=tuple(x.candidate for x in chosen),
        sessions=tuple(x.session for x in center_evidence.account),
        returns=tuple(tuple(float(x) for x in row) for row in np.column_stack(arrays)),
        selected=center_evidence.candidate,
        raw_trial_count=178,
        limitations=tuple(inventory["limitations"]))
    inventory["selected"] = center_evidence.candidate.to_dict()
    inventory["selected_replaces_original_C9521_economic_path"] = True
    inventory["unique_funded_paths"] = len(chosen)
    inventory["raw_trial_count"] = 178
    inventory["raw_trial_count_definition"] = "66 cumulative early unique accounts + 69 EX035 diagnostic accounts + 38 EX040-EX052 successful accounts + 1 EX040 failed dispatch + 4 early observation-contract failed account dispatches = 178 recovered research attempts. Two EX053 technical reproductions and the equivalent EX054 center/perturbations do not add original selection-family trials. Retained reused controls make this conservative, not independent. This does not claim all unpublished exploration is recovered."
    inventory["raw_trial_count_scope"] = {"early_registered_complete_accounts": 66,
        "EX035_fixed_E9_node_complete_accounts": 69,
        "EX040_EX052_complete_accounts": 38, "EX040_failed_dispatches": 1,
        "EX053_technical_reproductions_excluded": 2,
        "early_observation_contract_failed_account_dispatches_included": 4,
        "early_input_preparation_failure_disclosed_separately": 1,
        "unseen_validation_samples": 0}
    inventory["collapsed_duplicate_accounts"] = duplicates
    inventory["matrix_candidates"] = [x.candidate.to_dict() for x in chosen]
    inventory["supporting_refs"] = [x.to_dict() for x in supporting_refs.values()]
    return family, tuple(chosen), tuple(supporting_refs.values()), inventory


if __name__ == "__main__":
    original, _, _ = _load_inventory()
    family, _, _, inventory = build_family(original)
    output = EX / "others/family_inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: inventory[k] for k in (
        "registered_count", "referenced_account_count", "account_bytes_authenticated",
        "same_context_projection_count", "unique_funded_paths", "dispatch_status_counts")}))
