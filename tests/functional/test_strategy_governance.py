# Risk ownership: TDR-01
from datetime import date

import pytest
from dataflows import ProviderConfig
from strategy_manager import StrategyRegistry
from czsc_trader.application import (
    RepositoryContext, ValidationError, ResearchBatchRequest, ExperimentRequest, create_research_batch, create_research_context, create_experiment,
)


def batch(**changes):
    return ResearchBatchRequest("S910", "public research identity", ("588080.SH",),
                                {"objective": "synthetic"}, **changes)


def files(context):
    return {p.relative_to(context.research_root): p.read_bytes()
            for p in context.research_root.rglob("*") if p.is_file()}


def test_TDR_01_C01_research_identity_credentials_context_and_editable_experiments(minimal_repo):
    repository = RepositoryContext.discover(minimal_repo)
    first = create_research_batch(repository, batch(), actor="test", reason="立项")
    research = create_research_context(repository, first, providers=ProviderConfig(bindings={}))
    assert research.data.binding.space_id == research.evaluation.data.binding.space_id
    assert research.data.binding.space.path.as_posix() == "research/S910/assets/data"


@pytest.mark.parametrize('operation', ['create_family'])
def test_TDR_01_C03_research_document_rolls_back_when_registration_fails(minimal_repo, monkeypatch, operation):
    context = RepositoryContext.discover(minimal_repo)
    request = batch()
    if operation == "start_research_batch":
        create_research_batch(context, request, actor="test", reason="initial")
        request = batch(credential_id="SGC-S910-002")
    before = files(context)
    def fail(*args, **kwargs):
        raise OSError("injected registration failure")
    monkeypatch.setattr(StrategyRegistry, operation, fail)
    with pytest.raises(ValidationError):
        create_research_batch(context, request, actor="test", reason="failure")
    assert files(context) == before


@pytest.mark.parametrize('changes', [{'name': 'changed'}])
def test_TDR_01_C02_conflicting_batch_rejected_without_writes(minimal_repo, changes):
    context = RepositoryContext.discover(minimal_repo)
    create_research_batch(context, batch(), actor="test", reason="initial")
    before = files(context)
    values = {"strategy_id": "S910", "name": "public research identity", "scope": ("588080.SH",),
              "research_intent": {"objective": "synthetic"}, "credential_id": "SGC-S910-002", **changes}
    with pytest.raises(ValidationError):
        create_research_batch(context, ResearchBatchRequest(**values), actor="test", reason="conflict")
    assert files(context) == before


@pytest.mark.parametrize('credential', ['../escape'])
def test_TDR_01_C04_invalid_credential_is_blocked_before_io(credential):
    with pytest.raises(ValueError):
        batch(credential_id=credential)


def test_TDR_01_C05_allocation_reserves_legacy_ids_by_name_only(minimal_repo):
    repository = RepositoryContext.discover(minimal_repo)
    reference = create_research_batch(repository, batch(), actor="test", reason="initial")
    legacy = repository.root / "experiments/S910/EX005_20261001"
    legacy.mkdir(parents=True)
    (legacy / "sealed.json").write_text("unread legacy content")
    research = create_research_context(repository, reference, providers=ProviderConfig(bindings={}))
    experiment = create_experiment(research, ExperimentRequest("new", "new", date(2026, 10, 7)))
    assert experiment.experiment_id == "EX006_20261007"
    assert (legacy / "sealed.json").read_text(encoding="utf-8") == "unread legacy content"


def test_TDR_01_C06_context_rejects_mixed_batch_and_evaluation_capabilities(minimal_repo):
    from dataclasses import replace
    from czsc_trader.research_tools import ResearchBatchRef
    repository = RepositoryContext.discover(minimal_repo)
    reference = create_research_batch(repository, batch(), actor="test", reason="initial")
    context = create_research_context(repository, reference, providers=ProviderConfig(bindings={}))
    with pytest.raises(ValueError, match="batch-owned"):
        replace(context, batch=ResearchBatchRef("S911"))


def test_TDR_01_C07_context_rejects_foreign_evaluation(minimal_repo):
    from dataclasses import replace
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    repository = RepositoryContext.discover(minimal_repo)
    reference = create_research_batch(repository, batch(), actor="test", reason="initial")
    context = create_research_context(repository, reference, providers=ProviderConfig(bindings={}))
    with pytest.raises(ValueError, match="same batch"):
        replace(context, evaluation=EvaluationAccess(dataflows=context.data, strategy_id="S911"))
