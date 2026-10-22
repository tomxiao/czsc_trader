"""Migration provenance is stricter than ordinary candidate admission.

Real frozen sources exercise reviewed conversion guards. Small ledger tables
exercise evidence tamper rejection; they are not market acceptance evidence.
"""

from dataclasses import replace
from hashlib import sha256
import json
import shutil
from uuid import uuid4

import pandas as pd
import pytest

from czsc_trader.application import validate_frozen_runtime_migration, validate_release_package
from czsc_trader.application.research_evidence import _migration_case, _migration_frame_equal
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyCandidate, implementation_sha256
from test_runtime_migration import REFERENCES, preparations as preparations


def original(context, reference):
    manifest, _, _ = validate_release_package(context, reference)
    family, version = reference.split("-")
    return f.FrozenVersionReference(family, version, manifest["strategy_version_hash"], manifest["package_hash"])


@pytest.mark.release_acceptance
@pytest.mark.parametrize("reference", REFERENCES)
def test_reviewed_six_frozen_conversions_revalidate_without_writing(preparations, reference):
    context, results = preparations
    result = results[reference]
    before = {path: sha256(path.read_bytes()).hexdigest()
              for path in result.candidate.source_root.rglob("*") if path.is_file()}
    definition = validate_frozen_runtime_migration(context, original(context, reference), result.candidate)
    assert definition.implementation.contract_version == 2
    assert before == {path: sha256(path.read_bytes()).hexdigest()
                      for path in result.candidate.source_root.rglob("*") if path.is_file()}


@pytest.mark.release_acceptance
@pytest.mark.parametrize("change", ["algorithm", "extra_module", "initializer", "parameters", "feedback", "missing_source"])
def test_rehashed_arbitrary_changes_cannot_use_migration_governance(preparations, change):
    context, results = preparations
    prepared = results["S002-v1"].candidate
    target = context.root / ".tmp" / ("migration_guard_" + uuid4().hex)
    shutil.copytree(prepared.source_root, target)
    payload = json.loads(json.dumps(dict(prepared.payload), default=dict))
    path = target / "strategies/s002_v1.py"
    if change == "algorithm":
        path.write_bytes(path.read_bytes() + b"\n# arbitrary new source, even if hash is updated\n")
    elif change == "extra_module":
        (target / "strategies/extra.py").write_text("raise RuntimeError('new code')\n", encoding="utf-8")
    elif change == "initializer":
        (target / "strategies/__init__.py").write_text("raise RuntimeError('changed import')\n", encoding="utf-8")
    elif change == "parameters":
        payload["parameters"]["unauthorized_parameter"] = 1
    elif change == "feedback":
        payload["decision_feedback"] = "SIMULATED_FILL_FEEDBACK"
    else:
        path.unlink()
    if change != "missing_source":
        payload["runtime"]["source_sha256"] = implementation_sha256(
            tuple(payload["runtime"]["source_files"]), source_root=target)
    candidate = StrategyCandidate(prepared.strategy_family_id, prepared.candidate_id, payload, target)
    with pytest.raises(ValueError, match="reviewed conversion|reviewed contracts|required files"):
        validate_frozen_runtime_migration(context, original(context, "S002-v1"), candidate)


@pytest.mark.release_acceptance
def test_frozen_source_hash_and_family_cannot_be_substituted(preparations):
    context, results = preparations
    source = original(context, "S002-v1")
    for changed in (replace(source, release_hash="a" * 64), replace(source, package_hash="b" * 64)):
        with pytest.raises(ValueError, match="release/package identity"):
            validate_frozen_runtime_migration(context, changed, results["S002-v1"].candidate)
    with pytest.raises(ValueError, match="another family"):
        validate_frozen_runtime_migration(context, original(context, "S001-v1"), results["S002-v1"].candidate)


def test_migration_selection_roundtrip_is_distinct_from_alpha_selection():
    evidence = f.ResearchEvidenceRef(f.ResearchEvidenceOwner("S014", "EX053_20261020"), "a" * 64 + ".json", "a" * 64)
    subject = f.FrozenMigrationSelectionSubject(f.FrozenVersionReference("S002", "v1", "b" * 64, "c" * 64),
        f.CandidateKey("S002", "C9902"), "d" * 64, (evidence,))
    decision = f.ResearchDecision("migration_test", "S002", f.DecisionAction.APPROVE, subject,
                                 evidence, "Technical conversion only")
    assert f.ResearchDecision.from_dict(decision.to_dict()) == decision
    assert not isinstance(subject, f.CandidateSelectionSubject)
    for values in ((), (evidence, evidence)):
        with pytest.raises(ValueError, match="unique equivalence"):
            replace(subject, equivalence_evidence=values)
    with pytest.raises(ValueError, match="family differ"):
        replace(subject, candidate=f.CandidateKey("S001", "C9902"))


def test_equivalence_rejects_economic_difference_and_broken_cross_ledger_linkage():
    identities = {}
    _migration_frame_equal(pd.DataFrame({"order_id": ["old1"], "cash": [100.0]}),
                           pd.DataFrame({"order_id": ["new1"], "cash": [100.0]}), identities)
    with pytest.raises(ValueError, match="linkage differs"):
        _migration_frame_equal(pd.DataFrame({"order_id": ["old1"]}),
                               pd.DataFrame({"order_id": ["new2"]}), identities)
    with pytest.raises(ValueError, match="values differ"):
        _migration_frame_equal(pd.DataFrame({"cash": [100.0]}), pd.DataFrame({"cash": [99.99]}), {})
    with pytest.raises(ValueError, match="missing values differ"):
        _migration_frame_equal(pd.DataFrame({"cash": [float("nan")]}), pd.DataFrame({"cash": [100.0]}), {})


def test_pass_label_alone_is_not_real_equivalence_evidence():
    with pytest.raises(ValueError, match="complete real-market"):
        _migration_case(None, {"status": "PASS"}, None, None, None)
