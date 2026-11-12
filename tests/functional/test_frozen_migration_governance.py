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
from test_runtime_migration import isolated_migration_preparations


@pytest.fixture(scope="module")
def migration_guard_inputs(frozen_seed_root):
    # Only S007 supplies the candidate. S001 is the independent wrong-family reference.
    with isolated_migration_preparations(
        frozen_seed_root, releases=("S007-v1", "S001-v1"), conversions=("S007-v1",)
    ) as (context, results):
        yield context, results["S007-v1"].candidate


def original(context, reference):
    manifest, _, _ = validate_release_package(context, reference)
    family, version = reference.split("-")
    return f.FrozenVersionReference(family, version, manifest["strategy_version_hash"], manifest["package_hash"])


@pytest.mark.release_acceptance
def test_rehashed_extra_module_cannot_use_migration_governance(migration_guard_inputs):
    context, prepared = migration_guard_inputs
    target = context.root / ".tmp" / ("migration_guard_" + uuid4().hex)
    shutil.copytree(prepared.source_root, target)
    payload = json.loads(json.dumps(dict(prepared.payload), default=dict))
    (target / "strategies/extra.py").write_text("raise RuntimeError('new code')\n", encoding="utf-8")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=target)
    candidate = StrategyCandidate(prepared.strategy_family_id, prepared.candidate_id, payload, target)
    with pytest.raises(ValueError, match="migration source differs from the reviewed conversion"):
        validate_frozen_runtime_migration(context, original(context, "S007-v1"), candidate)


@pytest.mark.release_acceptance
@pytest.mark.parametrize('change', ['release_hash', 'family'], ids=['TDR-24-C05', 'TDR-24-C06'])
def test_frozen_source_hash_and_family_cannot_be_substituted(migration_guard_inputs, change):
    context, candidate = migration_guard_inputs
    if change == 'release_hash':
        source = replace(original(context, "S007-v1"), release_hash="a" * 64)
        error = 'release/package identity'
    else:
        source = original(context, "S001-v1")
        error = 'another family'
    with pytest.raises(ValueError, match=error):
        validate_frozen_runtime_migration(context, source, candidate)


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
