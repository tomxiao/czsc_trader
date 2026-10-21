"""Request-local graph reuse retains authentication and mutation detection."""
from dataclasses import replace
from pathlib import Path

import pytest

from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.application import delivery_service as service
from czsc_trader.research_tools import delivery as d
from test_research_delivery import content, context as context


def graph(research):
    references = []
    for revision, predecessors in ((1, ()), (2, (1,)), (3, (1,)), (4, (2, 3))):
        receipt = assemble_delivery(
            research.repository,
            d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, revision,
                                 tuple(references[index - 1] for index in predecessors)),
            content(report=f"Declared graph node {revision}"),
        )
        references.append(receipt.reference)
    return references


def test_diamond_reuses_semantics_but_reauthenticates_every_call(context):
    references = graph(context)
    result = validate_delivery(context.repository, references[-1])
    assert result.status is d.ValidationStatus.PASS
    assert result.stats.unique_deliveries == 4
    assert result.stats.reference_visits == 5
    assert result.stats.recursive_expansions == 4
    assert result.stats.semantic_reuses == 1
    assert result.stats.files_hashed > 0 and result.stats.bytes_hashed > 0
    assert result.stats.elapsed_seconds >= 0
    assert d.DeliveryValidation.from_dict(result.to_dict()).to_dict() == result.to_dict()
    repeated = validate_delivery(context.repository, references[-1])
    assert repeated.stats.recursive_expansions == 4
    leaf = service._delivery_path(context.repository, references[0])
    (leaf / "report.md").write_bytes(b"tampered")
    failed = validate_delivery(context.repository, references[-1])
    assert failed.status is d.ValidationStatus.FAIL
    assert failed.stats is not None


def test_descendant_change_after_reuse_is_detected_at_completion(context, monkeypatch):
    references = graph(context)
    leaf = service._delivery_path(context.repository, references[0])
    original = service._validate_content

    def mutate_after_descendants(definition, *args, **kwargs):
        original(definition, *args, **kwargs)
        if definition.revision == 4:
            (leaf / "report.md").write_bytes(b"changed after descendant validation")

    monkeypatch.setattr(service, "_validate_content", mutate_after_descendants)
    result = validate_delivery(context.repository, references[-1])
    assert result.status is d.ValidationStatus.FAIL
    assert result.issues[0].code == "SOURCE_CHANGED"


def test_reuse_never_hides_public_copy_corruption(context):
    references = graph(context)
    public = service._public_delivery_path(context.repository, references[0])
    (public / "report.md").write_bytes(b"changed public report")
    result = validate_delivery(context.repository, references[-1])
    assert result.status is d.ValidationStatus.FAIL
    assert result.issues[0].code == "PUBLIC_DELIVERY"


def test_publication_rechecks_predecessors_after_installation(context, monkeypatch):
    parent = graph(context)[0]
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 5, (parent,))
    destination = service._delivery_path(context.repository, definition)
    public = service._public_delivery_path(context.repository, definition)
    leaf = service._delivery_path(context.repository, parent)
    rename = Path.rename

    def mutate_during_commit(source, target):
        result = rename(source, target)
        if target == public:
            (leaf / "report.md").write_bytes(b"predecessor changed while installing")
        return result

    monkeypatch.setattr(Path, "rename", mutate_during_commit)
    with pytest.raises(d.DeliveryValidationError, match="changed during validation"):
        assemble_delivery(context.repository, definition, content())
    assert not destination.exists() and not public.exists()


def test_active_path_cycle_is_checked_before_a_reuse_hit(context):
    reference = graph(context)[0]
    identity = (reference.batch, reference.stage, reference.revision)
    session = service._ValidationSession()
    token = service._validation_session.set(session)
    try:
        root = service._delivery_path(context.repository, reference)
        service._read_delivery(context.repository, reference, root, set())
        with pytest.raises(d.DeliveryValidationError, match="cyclic"):
            service._read_delivery(context.repository, reference, root, {identity})
    finally:
        service._validation_session.reset(token)


@pytest.mark.parametrize("field,value", [("files_hashed", -1), ("bytes_hashed", True),
                                        ("elapsed_seconds", float("nan"))])
def test_validation_stats_reject_invalid_numbers(field, value):
    stats = d.DeliveryValidationStats(0, 0, 0, 0, 0, 0, 0.0)
    with pytest.raises((ValueError, TypeError)):
        replace(stats, **{field: value})
