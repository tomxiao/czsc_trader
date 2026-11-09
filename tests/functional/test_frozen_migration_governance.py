# Risk ownership: TDR-24
"""Migration provenance is stricter than ordinary candidate admission.

Real frozen sources exercise reviewed conversion guards. Small ledger tables
exercise evidence tamper rejection; they are not market acceptance evidence.
"""

from dataclasses import replace
import json
import shutil
from uuid import uuid4

import pandas as pd
import pytest

from czsc_trader.application import validate_frozen_runtime_migration, validate_release_package
from czsc_trader.application.research_evidence import _migration_case, _migration_frame_equal
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyCandidate, implementation_sha256
from test_runtime_migration import preparations as preparations


def original(context, reference):
    manifest, _, _ = validate_release_package(context, reference)
    family, version = reference.split("-")
    return f.FrozenVersionReference(family, version, manifest["strategy_version_hash"], manifest["package_hash"])


@pytest.mark.release_acceptance
@pytest.mark.parametrize('change', ['extra_module'])
def test_rehashed_arbitrary_changes_cannot_use_migration_governance(preparations, change):
    context, results = preparations
    prepared = results["S007-v1"].candidate
    target = context.root / ".tmp" / ("migration_guard_" + uuid4().hex)
    shutil.copytree(prepared.source_root, target)
    payload = json.loads(json.dumps(dict(prepared.payload), default=dict))
    path = target / "strategies/s007_v1.py"
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
        validate_frozen_runtime_migration(context, original(context, "S007-v1"), candidate)


@pytest.mark.release_acceptance
@pytest.mark.parametrize('change', ['release_hash', 'family'], ids=['TDR-24-C05', 'TDR-24-C06'])
def test_frozen_source_hash_and_family_cannot_be_substituted(preparations, change):
    context, results = preparations
    if change == 'release_hash':
        source = replace(original(context, "S007-v1"), release_hash="a" * 64)
        error = 'release/package identity'
    else:
        source = original(context, "S001-v1")
        error = 'another family'
    with pytest.raises(ValueError, match=error):
        validate_frozen_runtime_migration(context, source, results["S007-v1"].candidate)


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
