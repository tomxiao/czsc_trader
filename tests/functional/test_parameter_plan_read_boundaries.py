# Risk ownership: TDR-15
"""Parameter planning consumes declared links without certifying prior research."""
from dataclasses import replace

import pytest

from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools.evidence import EvidenceRef, managed_path
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan, _decode_parameter_plan
from equity_parameter_support import equity_plan


def test_TDR_15_C02_plan_read_verifies_selected_bytes_without_reading_upstream(tmp_path, monkeypatch):
    with equity_plan(tmp_path, applicable=False) as (context, _, plan, reference, _, _):
        root = context.repository.root
        for item in (plan.mapping_evidence, plan.feasibility_evidence):
            managed_path(root, item.repository_path).unlink(missing_ok=True)
        _decode_parameter_plan.cache_clear()
        calls = []
        original = EvidenceRef._read_verified

        def read_selected(self, repository_root):
            assert self == reference, "upstream evidence must remain a declaration"
            calls.append(self)
            return original(self, repository_root)

        monkeypatch.setattr(EvidenceRef, "_read_verified", read_selected)
        assert read_parameter_plan(reference, root) == plan
        assert len(calls) == 1


def test_TDR_15_C01_plan_creation_uses_declared_sources_and_owned_handles(tmp_path, monkeypatch):
    with equity_plan(tmp_path, applicable=False) as (context, center, plan, _, _, execution):
        def forbid_read(*args, **kwargs):
            raise AssertionError("plan creation must not authenticate source documents")

        monkeypatch.setattr(EvidenceRef, "_read_verified", forbid_read)
        kwargs = dict(mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
                      dataflows=context.data, execution=execution)
        assert ParameterEvaluationPlan.create(plan.design, center, (), **kwargs) == plan
        with pytest.raises(ValueError, match="not issued"):
            ParameterEvaluationPlan.create(plan.design, replace(center), (), **kwargs)


def test_TDR_15_C03_cached_decode_still_authenticates_selected_bytes(tmp_path, monkeypatch):
    with equity_plan(tmp_path, applicable=False) as (context, _, plan, reference, _, _):
        root = context.repository.root
        for item in (plan.mapping_evidence, plan.feasibility_evidence):
            managed_path(root, item.repository_path).unlink(missing_ok=True)
        _decode_parameter_plan.cache_clear()
        calls = []
        original = EvidenceRef._read_verified

        def read_selected(self, repository_root):
            assert self == reference, "upstream evidence must remain a declaration"
            calls.append(self)
            return original(self, repository_root)

        monkeypatch.setattr(EvidenceRef, "_read_verified", read_selected)
        assert read_parameter_plan(reference, root) == plan
        assert read_parameter_plan(reference, root) == plan
        assert len(calls) == 2
        assert _decode_parameter_plan.cache_info().hits == 1
        managed_path(root, reference.repository_path).write_bytes(b"changed")
        with pytest.raises(ValueError, match="content differs"):
            read_parameter_plan(reference, root)


def test_TDR_15_C04_same_hash_foreign_owner_cannot_reuse_verified_path(tmp_path):
    from czsc_trader.research_tools import ExperimentRef
    with equity_plan(tmp_path, applicable=False) as (context, _, plan, reference, _, _):
        root = context.repository.root
        assert read_parameter_plan(reference, root) == plan
        foreign = replace(reference, experiment=ExperimentRef('S901', reference.experiment.experiment_id))
        assert foreign.sha256 == reference.sha256
        with pytest.raises(FileNotFoundError):
            read_parameter_plan(foreign, root)
