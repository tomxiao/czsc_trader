"""Public parameter plan, account and immutable delivery business contracts."""

from dataclasses import replace
from importlib.metadata import version
import json
import shutil

import pytest
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind, ParameterDesignRequest, ParameterPerturbationProtocol,
    ParameterSpace, build_parameter_perturbation_design, assess_candidates, compare_candidates,
    PerturbationLink,
)
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency, canonical_sha256

from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import (
    ParameterEvaluationPlan, EvaluationLineage, MaterialEvidenceWrite, EvaluationEvidenceWrite,
    build_assessment_evidence,
)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from test_assessment_delivery import fresh_completed as fresh_completed, prepare, assessment_request, comparison_request
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_research_delivery import attachment, published


def parameter_plan(research, request, *, child_parameters=None):
    request = research.evaluation.prepare(request)
    mapping = attachment(research, "parameter-map", {"parameter": "threshold", "unit": "fraction"})
    feasible = attachment(research, "parameter-constraint", {"constraint": "domain"})
    center = AssessmentCandidate(request.strategy.reference_id,
        StrategyRuntime().identify(request.strategy, dependencies=request.dependencies).content_sha256)
    protocol = ParameterPerturbationProtocol(point_count=2)
    space = ParameterSpace((ParameterCoordinate("threshold", .5, 0., 1., ParameterCoordinateKind.CONTINUOUS),),
                           mapping.sha256, feasible.sha256)
    design = build_parameter_perturbation_design(ParameterDesignRequest(center, protocol, space),
                                               feasibility=lambda coordinates: True).design
    children = []
    for point in design.points:
        parameters = {**request.strategy.payload["parameters"], "threshold": point.coordinates[0]}
        if child_parameters is not None:
            parameters.update(child_parameters(point))
        payload = {"runtime": dict(request.strategy.payload["runtime"]), "parameters": parameters}
        candidate = StrategyCandidate("S900", f"C{point.index + 2:04}", payload, request.strategy.source_root)
        child = replace(request, strategy=candidate, runtime_binding={**request.runtime_binding,
                        "candidate_id": candidate.reference_id}, input_bindings={})
        children.append(research.evaluation.prepare(child))
    plan = ParameterEvaluationPlan.create(design, request, tuple(children), mapping_evidence=mapping,
                                         feasibility_evidence=feasible, dataflows=research.data)
    reference = publish_evidence(research, MaterialEvidenceWrite(ExperimentRef("S900", request.experiment_id),
        "parameter-plan", json.dumps(plan.to_dict(), ensure_ascii=False).encode(), "application/json", "json"))
    bound = []
    for index, child in enumerate(children):
        derivation = CandidateDerivation(CandidateKey("S900", "C0001"), center.content_sha256,
            CandidateKey("S900", child.strategy.candidate_id), plan.children[index].candidate.content_sha256,
            CandidateDerivationKind.PARAMETERS, {"threshold": design.points[index].coordinates[0]},
            design.protocol.sha256, CandidateEvidence(reference.repository_path, reference.sha256))
        binding = plan.bind_point(reference, index, repository_root=request.repository_root)
        bound.append(replace(child, lineage=EvaluationLineage(derivation, binding)))
    return request, plan, reference, tuple(bound)


def test_published_parameter_point_reaches_authenticated_account_and_se(managed_evaluation):
    research, request = managed_evaluation
    request = replace(request, dependencies=(ImplementationDependency("numpy", version("numpy")),))
    center, plan, reference, children = parameter_plan(research, request)
    result = research.evaluation.evaluate(children[0])
    evidence = build_assessment_evidence(children[0], result)
    assert evidence[0].parameter_point == plan.design.bind_point(0)
    saved = serialize_evaluation_evidence(children[0], result)
    validate_evaluation_evidence(json.loads(json.dumps(saved)))
    assert saved["schema_version"] == 6
    assert saved["request_identity"]["parameter_binding"]["plan"]["sha256"] == reference.sha256
    assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises(ValueError, match="nonparameter context"):
        research.evaluation.prepare(replace(children[0], initial_cash=center.initial_cash + 1))
    with pytest.raises(ValueError, match="actual child content"):
        research.evaluation.prepare(replace(children[0], strategy=children[1].strategy,
            runtime_binding=children[1].runtime_binding, input_bindings=children[1].input_bindings))
    with pytest.raises(ValueError, match="content differs"):
        reference.resolve(request.repository_root).write_bytes(b"corrupt")
        research.evaluation.prepare(children[0])


def test_parameter_plan_rejects_missing_publication_and_collapsed_payloads(managed_evaluation):
    research, request = managed_evaluation
    center, plan, reference, children = parameter_plan(research, request)
    with pytest.raises(ValueError, match="duplicate parameter child candidate"):
        replace(plan, children=(plan.children[0], plan.children[0]))
    with pytest.raises(ValueError, match="duplicate parameter candidate payload"):
        replace(plan, children=(plan.children[0], replace(plan.children[1], payload_json=plan.children[0].payload_json)))
    with pytest.raises(ValueError, match="evidence differs"):
        replace(plan, mapping_evidence=plan.feasibility_evidence)
    reference.resolve(request.repository_root).unlink()
    with pytest.raises(FileNotFoundError, match="published evidence"):
        research.evaluation.prepare(children[0])


def test_parameter_assessment_delivery_replays_plan_after_source_cleanup(fresh_completed):
    context, research, request, center_result, _ = fresh_completed
    definition, content = prepare(fresh_completed)
    center, plan, reference, children = parameter_plan(research, request)
    center_evidence = build_assessment_evidence(center, center_result)
    accounts, links = [], []
    for child in children:
        result = research.evaluation.evaluate(child)
        accounts.extend(build_assessment_evidence(child, result))
        published_account = publish_evidence(research, EvaluationEvidenceWrite(
            ExperimentRef("S900", request.experiment_id), child.strategy.candidate_id, child, result))
        links.append(PerturbationLink(plan.design.center, accounts[-1].candidate, 1.,
            canonical_sha256(child.lineage.derivation.to_dict()), child.lineage.parameter_binding.point))
        content = replace(content, evidence=(*content.evidence, published_account))
    assessment = assessment_request(center_evidence)
    assessment = replace(assessment, protocol=replace(assessment.protocol, parameter_protocol=plan.design.protocol),
                         perturbations=tuple(links), evidence=(*center_evidence, *accounts),
                         parameter_designs=(plan.design,))
    panel = assess_candidates(assessment)
    comparison = comparison_request(panel)
    payload = replace(content.payload, assessment_request=assessment, assessment=panel,
                      comparison_request=comparison, comparison=compare_candidates(comparison), parameter_plans=(reference,))
    false_center = replace(plan, center_request_sha256="f" * 64)
    false_reference = publish_evidence(research, MaterialEvidenceWrite(ExperimentRef("S900", request.experiment_id),
        "false-parameter-center", json.dumps(false_center.to_dict()).encode(), "application/json", "json"))
    with pytest.raises(ValueError, match="planned center differs"):
        assemble_delivery(context, definition,
                          replace(content, payload=replace(payload, parameter_plans=(false_reference,))))
    receipt = assemble_delivery(context, definition, replace(content, payload=payload))
    shutil.rmtree(request.strategy.source_root)
    for material in (reference, plan.mapping_evidence, plan.feasibility_evidence):
        material.resolve(context.root).unlink()
    assert validate_delivery(context, receipt.reference).status.value == "PASS"
    saved = published(context, receipt)
    assert (saved / plan.mapping_evidence.path).is_file()
    assert (saved / plan.feasibility_evidence.path).is_file()


def test_adapter_rejects_altered_raw_input_binding(managed_evaluation):
    research, request = managed_evaluation
    request = research.evaluation.prepare(request)
    result = research.evaluation.evaluate(request)
    run = result.runs[0]
    changed = replace(result, runs=(replace(run, signals=replace(run.signals,
        support_data={**run.signals.support_data, "input_binding": {}})),))
    with pytest.raises(ValueError, match="input binding differs"):
        build_assessment_evidence(request, changed)


def test_parameter_plan_rejects_parameter_driven_execution_switch(managed_evaluation):
    research, request = managed_evaluation
    with pytest.raises(ValueError, match="SRT execution contract differs"):
        parameter_plan(research, request, child_parameters=lambda point: {"entry_order_type": "MARKET"})


def test_parameter_plan_allows_genuine_lookback_extension(managed_evaluation):
    from datetime import date
    from strategy_runtime.implementation_identity import implementation_sha256

    research, request = managed_evaluation
    source = request.strategy.source_root / "strategies/candidate_fixture.py"
    text = source.read_text(encoding="utf-8")
    old = '"daily",\n                1,\n                CutoffRule.SIGNAL_SESSION'
    assert old in text
    source.write_text(text.replace(old, '"daily",\n                int(parameters.values.get("lookback", 1)),\n                CutoffRule.SIGNAL_SESSION', 1), encoding="utf-8")
    source_hash = implementation_sha256(("strategies/candidate_fixture.py",), source_root=request.strategy.source_root)
    payload = {"runtime": {**request.strategy.payload["runtime"], "source_sha256": source_hash},
               "parameters": {"threshold": .5, "lookback": 1}}
    request = replace(request, strategy=replace(request.strategy, payload=payload),
                      runtime_binding={**request.runtime_binding, "implementation_sha256": source_hash},
                      windows=(replace(request.windows[0], start=date(2026, 9, 16)),))
    center, plan, _, children = parameter_plan(research, request,
        child_parameters=lambda point: {"lookback": 2 if point.coordinates[0] > .5 else 1})
    central_start = center.input_bindings["full"].plan.requests["flow"].start
    assert any(x.input_bindings["full"].plan.requests["flow"].start < central_start for x in children)
    assert all(research.evaluation.prepare(x).lineage.parameter_binding for x in children)
    assert len(plan.children) == 2


@pytest.mark.parametrize("failure", ["source_contract", "raw_values"])
def test_parameter_plan_rejects_changed_raw_signal_inputs(managed_evaluation, monkeypatch, failure):
    from dataflows import Dataflows, Dataset, PreparePolicy, ProviderBinding, ProviderConfig

    research, request = managed_evaluation
    center, plan, _, children = parameter_plan(research, request)
    child = children[0]
    if failure == "source_contract":
        original = child.input_bindings["full"]
        requests = dict(original.plan.requests)
        requests["flow"] = replace(requests["flow"], symbol="510500.SH")
        changed = replace(original, plan=replace(original.plan, requests=requests))
        child = replace(child, input_bindings={"full": changed})
        with pytest.raises(ValueError, match="raw input source contract differs"):
            research.evaluation.prepare(child)
    else:
        original = child.input_bindings["full"]

        def changed_source(source_request):
            pinned = research.data.fetch(source_request, prepared=original.prepared)
            assert pinned.ready
            frame = pinned.dataframe.copy()
            if str(source_request.dataset) == Dataset.ETF_SHARE_SIZE.value:
                frame["Flow"] += 1
                frame["TotalShare"] += 1
            return frame, dict(pinned.identity.metadata)

        flows = Dataflows(base_dir=research.data.binding.base_dir, space=research.data.binding.space,
            providers=ProviderConfig(bindings={value.dataset: ProviderBinding("synthetic", "v1", changed_source)
                for value in original.plan.requests.values()}))
        prepared = flows.prepare(tuple(original.plan.requests.values()), policy=PreparePolicy.REFRESH)
        assert prepared.ready and prepared.reference != original.prepared
        child = replace(child, input_bindings={"full": replace(original, prepared=prepared.reference)})
        fetch = research.data.fetch
        calls = []

        def tracked(source_request, *, prepared):
            calls.append((source_request.dataset, prepared))
            return fetch(source_request, prepared=prepared)

        monkeypatch.setattr(research.data, "fetch", tracked)
        with pytest.raises(ValueError, match="raw input source or values differ"):
            research.evaluation.prepare(child)
        flow_reads = [reference for dataset, reference in calls if str(dataset) == Dataset.ETF_SHARE_SIZE.value]
        assert flow_reads == [center.input_bindings["full"].prepared, prepared.reference]


def test_equal_pinned_inputs_read_once_per_role_and_again_for_each_preparation(managed_evaluation, monkeypatch):
    research, request = managed_evaluation
    center, _, _, children = parameter_plan(research, request)
    original = center.input_bindings["full"]
    assert all(child.input_bindings["full"].prepared == original.prepared for child in children)
    fetch = research.data.fetch
    calls = []

    def tracked(source_request, *, prepared):
        calls.append((source_request, prepared))
        return fetch(source_request, prepared=prepared)

    monkeypatch.setattr(research.data, "fetch", tracked)
    for index, child in enumerate((children[0], children[0], children[1]), start=1):
        assert research.evaluation.prepare(child) is child
        assert len(calls) == index * len(original.plan.requests)
        assert all(reference == original.prepared for _, reference in calls)
    assert sorted(source_request.dataset for source_request, _ in calls) == sorted([
        source_request.dataset for source_request in original.plan.requests.values()
    ] * 3)


def test_equal_pinned_inputs_reject_corrupted_asset_after_success(managed_evaluation):
    import sqlite3

    research, request = managed_evaluation
    center, _, _, children = parameter_plan(research, request)
    original = center.input_bindings["full"]
    assert children[0].input_bindings["full"].prepared == original.prepared
    assert research.evaluation.prepare(children[0]) is children[0]
    # Fault injection affects only this synthetic fixture's managed store.
    path = research.data.binding.base_dir / research.data.binding.space.path / "assets.sqlite3"
    with sqlite3.connect(path) as connection:
        manifest = connection.execute("SELECT manifest FROM preparations WHERE preparation_id=?",
                                      (str(original.prepared.preparation_id),)).fetchone()[0]
        entries = json.loads(manifest)
        connection.execute("UPDATE assets SET payload=? WHERE asset_id=?", (b"corrupt", entries[0]["asset_id"]))
    raw = research.data.fetch(next(iter(original.plan.requests.values())), prepared=original.prepared)
    assert not raw.ready and raw.error.code == "ASSET_CORRUPT"
    with pytest.raises(ValueError, match="complete pinned inputs"):
        research.evaluation.prepare(children[0])


def test_unprepared_adapter_uses_authenticated_binding_after_source_cleanup(managed_evaluation):
    research, request = managed_evaluation
    assert not request.input_bindings
    result = research.evaluation.evaluate(request)
    shutil.rmtree(request.strategy.source_root)
    evidence = build_assessment_evidence(request, result)
    assert evidence[0].request_sha256 == result.request_hash


def test_parameter_plan_reuses_decoding_but_rechecks_all_published_bytes(managed_evaluation, monkeypatch):
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan, _decode_parameter_plan

    research, request = managed_evaluation
    _, plan, reference, _ = parameter_plan(research, request)
    _decode_parameter_plan.cache_clear()
    original = ParameterEvaluationPlan.from_dict
    calls = []

    def decode(cls, value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(ParameterEvaluationPlan, "from_dict", classmethod(decode))
    assert read_parameter_plan(reference, request.repository_root) == plan
    assert read_parameter_plan(reference, request.repository_root) == plan
    assert len(calls) == 1
    for item in (plan.mapping_evidence, plan.feasibility_evidence, reference):
        path = item.resolve(request.repository_root)
        data = path.read_bytes()
        path.write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="content differs"):
            read_parameter_plan(reference, request.repository_root)
        path.write_bytes(data)
    _decode_parameter_plan.cache_clear()


def test_bound_preparation_checks_calendars_without_copying_frame_metadata(managed_evaluation, monkeypatch):
    import pandas.core.generic as generic

    research, request = managed_evaluation
    bound = research.evaluation.prepare(request)
    frames = (bound.execution_data.adjusted_daily, bound.execution_data.execution_daily)
    originals = tuple(frame.attrs for frame in frames)
    copies = []
    original = generic.deepcopy

    def tracked(value, *args, **kwargs):
        if any(value is metadata for metadata in originals):
            copies.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(generic, "deepcopy", tracked)
    assert research.evaluation.prepare(bound) is bound
    assert copies == []
    assert all(frame.attrs is metadata for frame, metadata in zip(frames, originals, strict=True))
