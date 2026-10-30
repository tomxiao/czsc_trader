"""Public parameter plan, account and immutable delivery business contracts."""
from evaluation_seed_support import prepare_request

from dataclasses import replace
from importlib.metadata import version
import json
import pickle
import shutil

import pytest
from strategy_evaluator import (
    AssessmentCandidate, assess_candidates, compare_candidates,
    PerturbationLink,
)
from strategy_evaluator.parameter_neighborhood import (
    ParameterAxis, RealDomain, RealSetDomain, IntegerDomain, BoundedLocalStep, AbsoluteChangeLimit,
    RelativeChangeLimit,
    ParameterNeighborhoodSpace, ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
    build_parameter_neighborhood_design,
)
from strategy_evaluator import research_models as m
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


def parameter_plan(research, request, *, child_parameters=None, vary_lookback=False, not_applicable=False):
    request = prepare_request(research, request)
    mapping = attachment(research, "parameter-map", {"parameter": "threshold", "unit": "fraction"})
    feasible = attachment(research, "parameter-constraint", {"constraint": "domain"})
    center = AssessmentCandidate(request.strategy.reference_id,
        StrategyRuntime().identify(request.strategy, dependencies=request.dependencies).content_sha256)
    protocol = ParameterNeighborhoodProtocol()
    axes = (ParameterAxis("threshold", .5, RealDomain(0., 1.), BoundedLocalStep(AbsoluteChangeLimit(.05)),
                          ("threshold",), "fraction"),)
    if not_applicable:
        axes = (ParameterAxis("threshold", .5, RealSetDomain((0., .5, 1.)),
                              BoundedLocalStep(RelativeChangeLimit(.05)), ("threshold",), "fraction"),)
    if vary_lookback:
        axes += (ParameterAxis("lookback", 1, IntegerDomain(1, 10), BoundedLocalStep(AbsoluteChangeLimit(1.)),
                               ("lookback",), "sessions"),)
    space = ParameterNeighborhoodSpace(axes, mapping.sha256, feasible.sha256)
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(center, protocol, space),
                                                 feasibility=lambda values: True).design
    children = []
    for point in design.points:
        parameters = {**request.strategy.payload["parameters"], **{x.name: x.value for x in point.values}}
        if child_parameters is not None:
            parameters.update(child_parameters(point))
        payload = {**request.strategy.payload, "parameters": parameters}
        candidate = StrategyCandidate("S900", f"C{point.index + 2:04}", payload, request.strategy.source_root)
        child = replace(request, strategy=candidate, runtime_binding={**request.runtime_binding,
                        "candidate_id": candidate.reference_id}, input_bindings={})
        children.append(prepare_request(research, child))
    from czsc_trader.research_tools import ResearchExecutionSession
    with ResearchExecutionSession(research, experiment=ExperimentRef("S900", request.experiment_id)) as execution:
        center_handle = research.evaluation.prepare(request, execution=execution)
        child_handles = tuple(research.evaluation.prepare(child, execution=execution) for child in children)
        plan = ParameterEvaluationPlan.create(design, center_handle, child_handles, mapping_evidence=mapping,
            feasibility_evidence=feasible, dataflows=research.data, execution=execution)
    reference = publish_evidence(research, MaterialEvidenceWrite(ExperimentRef("S900", request.experiment_id),
        "parameter-plan", json.dumps(plan.to_dict(), ensure_ascii=False).encode(), "application/json", "json"))
    bound = []
    for index, child in enumerate(children):
        derivation = CandidateDerivation(CandidateKey("S900", "C0001"), center.content_sha256,
            CandidateKey("S900", child.strategy.candidate_id), plan.children[index].candidate.content_sha256,
            CandidateDerivationKind.PARAMETERS, {x.name: x.value for x in design.points[index].values},
            design.protocol.sha256, CandidateEvidence(reference.repository_path, reference.sha256))
        binding = plan.bind_point(reference, index, repository_root=request.repository_root)
        bound.append(replace(child, lineage=EvaluationLineage(derivation, binding)))
    return request, plan, reference, tuple(bound)


@pytest.fixture
def prepared_parameter_plan(request, tmp_path, frozen_seed_root):
    """Build the real plan once; each fault gets private files, frames and bindings."""
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import relocate_request, restored_context

    seed = frozen_seed_root / "parameter-plan-input"
    data = frozen_seed_root / "parameter-plan-input.pkl"
    if not seed.exists():
        research, evaluation = request.getfixturevalue("managed_evaluation")
        prepared = parameter_plan(research, evaluation)
        data.write_bytes(pack(prepared))
        shutil.copytree(research.repository.root, seed)
    root = tmp_path / "parameter-plan-repo"
    shutil.copytree(seed, root)
    center, plan, reference, children = pickle.loads(data.read_bytes())
    return (restored_context(root), relocate_request(center, root), plan, reference,
            tuple(relocate_request(child, root) for child in children))


def test_published_parameter_point_reaches_authenticated_account_and_se(managed_evaluation):
    research, request = managed_evaluation
    request = replace(request, dependencies=(ImplementationDependency("numpy", version("numpy")),))
    center, plan, reference, children = parameter_plan(research, request)
    result = research.evaluation.evaluate(children[0])
    evidence = build_assessment_evidence(children[0], result)
    assert evidence[0].parameter_point == plan.design.bind_point(0)
    saved = serialize_evaluation_evidence(children[0], result)
    validate_evaluation_evidence(json.loads(json.dumps(saved)))
    assert saved["schema_version"] == 8
    assert saved["request_identity"]["parameter_binding"]["plan"]["sha256"] == reference.sha256
    assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises(ValueError, match="nonparameter context"):
        prepare_request(research, replace(children[0], initial_cash=center.initial_cash + 1))
    with pytest.raises(ValueError, match="actual child content"):
        prepare_request(research, replace(children[0], strategy=children[1].strategy,
            runtime_binding=children[1].runtime_binding, input_bindings=children[1].input_bindings))
    with pytest.raises(ValueError, match="content differs"):
        reference.resolve(request.repository_root).write_bytes(b"corrupt")
        prepare_request(research, children[0])


def test_parameter_plan_rejects_missing_publication_and_collapsed_payloads(prepared_parameter_plan):
    research, center, plan, reference, children = prepared_parameter_plan
    with pytest.raises(ValueError, match="duplicate parameter child candidate"):
        replace(plan, children=(plan.children[0], plan.children[0]))
    with pytest.raises(ValueError, match="duplicate parameter candidate payload"):
        replace(plan, children=(plan.children[0], replace(plan.children[1], payload_json=plan.children[0].payload_json)))
    with pytest.raises(ValueError, match="evidence differs"):
        replace(plan, mapping_evidence=plan.feasibility_evidence)
    reference.resolve(center.repository_root).unlink()
    with pytest.raises(FileNotFoundError, match="published evidence"):
        prepare_request(research, children[0])


@pytest.mark.parametrize("acceptance_target", [True, False], ids=["acceptance", "diagnostic-only"])
def test_parameter_assessment_delivery_replays_plan_after_source_cleanup(fresh_completed, acceptance_target):
    context, research, request, center_result, _ = fresh_completed
    group = m.ParameterNeighborhoodTarget("point-economics", 1, 1,
        (m.ResearchTarget("point-return", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(-1.0, True)),),
        (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                         upper=m.ConstantBound(1.0, True)),))
    definition, content = prepare(fresh_completed, (group,) if acceptance_target else None)
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
    protocol = m.NeighborhoodSelfCheckProtocol(
        **{name: getattr(assessment.protocol, name) for name in (
            "version", "baseline_window", "standard_scenario", "stress_scenario",
            "rolling_window_days", "rolling_step_days", "quantile_method", "minimum_rolling_windows",
            "bootstrap_repetitions", "bootstrap_block_length", "seed", "reconciliation_tolerance", "pbo_blocks")},
        parameter_protocol=plan.design.protocol,
    )
    assessment = replace(assessment, protocol=protocol,
                         perturbations=tuple(links), evidence=(*center_evidence, *accounts),
                         parameter_designs=(plan.design,))
    panel = assess_candidates(assessment)
    comparison = replace(comparison_request(panel), targets=content.payload.comparison_request.targets)
    payload = replace(content.payload, assessment_request=assessment, assessment=panel,
                      comparison_request=comparison, comparison=compare_candidates(comparison), parameter_plans=(reference,))
    checked = payload.comparison.rows[0].target_checks[0]
    if acceptance_target:
        assert (checked.valid_points, checked.joint_passes) == (2, 2)
    else:
        assert not any(isinstance(target, m.ParameterNeighborhoodTarget)
                       for target in comparison.targets.requirements)
        for metric in (m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90):
            diagnostic = next(item for item in panel.rows[0].diagnostics if item.metric is metric)
            assert diagnostic.value is not None
    assert checked.status is m.TargetCheckStatus.PASSED
    false_center = replace(plan, center_request_sha256="f" * 64)
    false_reference = publish_evidence(research, MaterialEvidenceWrite(ExperimentRef("S900", request.experiment_id),
        "false-parameter-center", json.dumps(false_center.to_dict()).encode(), "application/json", "json"))
    with pytest.raises(ValueError, match="planned center differs"):
        assemble_delivery(context, definition,
                          replace(content, payload=replace(payload, parameter_plans=(false_reference,)))).receipt
    from strategy_runtime.resources import ExecutionResources
    progress = []
    assembled = assemble_delivery(context, definition, replace(content, payload=payload),
                                  resources=ExecutionResources(max_workers=2), on_progress=progress.append)
    receipt = assembled.receipt
    assert assembled.validation.stats.accounts_authenticated == 3
    assert any(event.phase.value == "AUTHENTICATION" and event.completed == event.total == 2
               for event in progress)
    parallel = validate_delivery(context, receipt.reference, resources=ExecutionResources(max_workers=2))
    serial = validate_delivery(context, receipt.reference, resources=ExecutionResources(max_workers=1))
    assert parallel == serial == assembled.validation
    assert parallel.stats.accounts_authenticated == serial.stats.accounts_authenticated == 3
    shutil.rmtree(request.strategy.source_root)
    for material in (reference, plan.mapping_evidence, plan.feasibility_evidence):
        material.resolve(context.root).unlink()
    assert validate_delivery(context, receipt.reference).status.value == "PASS"
    saved = published(context, receipt)
    assert (saved / plan.mapping_evidence.path).is_file()
    assert (saved / plan.feasibility_evidence.path).is_file()


def test_adapter_rejects_altered_raw_input_binding(managed_evaluation):
    research, request = managed_evaluation
    request = prepare_request(research, request)
    result = research.evaluation.evaluate(request)
    run = result.runs[0]
    changed = replace(result, runs=(replace(run, signals=replace(run.signals,
        support_data={**run.signals.support_data, "input_binding": {}})),))
    with pytest.raises(ValueError, match="input binding differs"):
        build_assessment_evidence(request, changed)


def test_not_applicable_plan_and_delivery_retain_authenticated_center_without_child_accounts(fresh_completed):
    """A zero-point plan is evidence-backed NA, not missing or a fabricated account."""
    from czsc_trader.research_tools import delivery as d
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan, _payload_json

    context, research, request, center_result, _ = fresh_completed
    group = m.ParameterNeighborhoodTarget("point-economics", 13, 16,
        (m.ResearchTarget("point-return", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(-1.0, True)),),
        (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                         upper=m.ConstantBound(.25, True)),))
    center_target = m.ResearchTarget("center-return", m.ResearchMetric.NET_ANNUAL_RETURN,
                                    lower=m.ConstantBound(-1.0, True))
    definition, content = prepare(fresh_completed, (center_target, group))
    center, plan, reference, children = parameter_plan(research, request, not_applicable=True)
    assert plan.schema_version == 3 and children == plan.children == ()
    assert not plan.design.is_applicable
    assert read_parameter_plan(reference, context.root) == plan
    with pytest.raises(ValueError, match="no point to bind"):
        plan.bind_point(reference, 0, repository_root=context.root)
    bad_payload = json.loads(plan.center.payload_json)
    bad_payload["parameters"]["threshold"] = .4
    with pytest.raises(ValueError, match="center payload differs"):
        replace(plan, center=replace(plan.center, payload_json=_payload_json(bad_payload)))
    empty_design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        plan.design.center, plan.design.protocol, replace(plan.design.space, axes=())),
        feasibility=lambda values: True).design
    assert not replace(plan, design=empty_design).design.is_applicable
    malformed = json.loads(plan.center.payload_json)
    malformed["parameters"] = None
    with pytest.raises(ValueError, match="explicit parameter object"):
        replace(plan, design=empty_design,
                center=replace(plan.center, payload_json=_payload_json(malformed)))

    assessment = replace(assessment_request(build_assessment_evidence(center, center_result)),
                         parameter_designs=(plan.design,))
    panel = assess_candidates(assessment)
    comparison = replace(comparison_request(panel), targets=content.payload.comparison_request.targets)
    compared = compare_candidates(comparison)
    checked = compared.rows[0].target_checks[1]
    assert checked.status is m.TargetCheckStatus.NOT_APPLICABLE
    assert compared.rows[0].acceptance_status is m.TargetCheckStatus.PASSED
    for metric in (m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90):
        diagnostic = next(x for x in panel.rows[0].diagnostics if x.metric is metric)
        assert diagnostic.status is m.DiagnosticStatus.NOT_APPLICABLE and diagnostic.value is None
    payload = replace(content.payload, assessment_request=assessment, assessment=panel,
                      comparison_request=comparison, comparison=compared, parameter_plans=(reference,))
    forged_center_payload = json.loads(plan.center.payload_json)
    forged_center_payload["parameters"] = {}
    forged = replace(plan, design=empty_design,
                     center=replace(plan.center, payload_json=_payload_json(forged_center_payload)))
    forged_ref = publish_evidence(research, MaterialEvidenceWrite(reference.experiment,
        "forged-empty-parameters", json.dumps(forged.to_dict()).encode(), "application/json", "json"))
    forged_request = replace(assessment, parameter_designs=(empty_design,))
    forged_panel = assess_candidates(forged_request)
    forged_comparison = replace(comparison, panel=forged_panel)
    forged_payload = replace(payload, assessment_request=forged_request, assessment=forged_panel,
        comparison_request=forged_comparison, comparison=compare_candidates(forged_comparison),
        parameter_plans=(forged_ref,))
    with pytest.raises(d.DeliveryValidationError, match="payload runtime identity differs"):
        assemble_delivery(context, definition, replace(content, payload=forged_payload))
    assembled = assemble_delivery(context, definition, replace(content, payload=payload))
    assert assembled.receipt.schema_version == 12
    assert assembled.validation.status is d.ValidationStatus.PASS
    assert assembled.validation.stats.accounts_authenticated == 1
    assert validate_delivery(context, assembled.receipt.reference).status is d.ValidationStatus.PASS
    assert d.DeliveryContent.from_dict(replace(content, payload=payload).to_dict()).payload == payload


@pytest.mark.parametrize("applicable", [False, True])
def test_parameter_plan_checks_declared_scope_and_preserves_unmapped_fields(managed_evaluation, applicable):
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan

    research, request = managed_evaluation
    parameters = {**request.strategy.payload["parameters"],
                  "config": {"labels": ["a", "b"], "optional": None, "fixed": 20}}
    request = replace(request, strategy=replace(request.strategy,
        payload={**request.strategy.payload, "parameters": parameters}))
    _, plan, reference, _ = parameter_plan(research, request, not_applicable=not applicable)
    assert plan.design.is_applicable is applicable
    assert read_parameter_plan(reference, research.repository.root) == plan
    assert json.loads(plan.center.payload_json)["parameters"] == parameters
    for child in plan.children:
        assert json.loads(child.payload_json)["parameters"]["config"] == parameters["config"]
    axis = plan.design.space.axes[0]
    bad_space = replace(plan.design.space, axes=(replace(axis, payload_path=("absent",)),))
    bad_design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        plan.design.center, plan.design.protocol, bad_space), feasibility=lambda values: True).design
    with pytest.raises(ValueError, match="path does not exist"):
        replace(plan, design=bad_design)


def test_parameter_plan_rejects_undeclared_configuration_change(managed_evaluation):
    research, request = managed_evaluation
    with pytest.raises(ValueError, match="undeclared changes are forbidden"):
        parameter_plan(research, request, child_parameters=lambda point: {"unmapped": [1, None]})


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
    center, plan, _, children = parameter_plan(research, request, vary_lookback=True)
    central_start = center.input_bindings["full"].plan.requests["flow"].start
    assert any(x.input_bindings["full"].plan.requests["flow"].start < central_start for x in children)
    assert all(prepare_request(research, x).lineage.parameter_binding for x in children)
    assert len(plan.children) == 5


@pytest.mark.parametrize("failure", ["source_contract", "raw_values"])
def test_parameter_plan_rejects_changed_raw_signal_inputs(prepared_parameter_plan, monkeypatch, failure):
    from dataflows import Dataflows, Dataset, PreparePolicy, ProviderBinding, ProviderConfig

    research, center, _, _, children = prepared_parameter_plan
    child = children[0]
    if failure == "source_contract":
        original = child.input_bindings["full"]
        requests = dict(original.plan.requests)
        requests["flow"] = replace(requests["flow"], symbol="510500.SH")
        changed = replace(original, plan=replace(original.plan, requests=requests))
        child = replace(child, input_bindings={"full": changed})
        with pytest.raises(ValueError, match="raw input source contract differs"):
            prepare_request(research, child)
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
            prepare_request(research, child)
        flow_reads = [reference for dataset, reference in calls if str(dataset) == Dataset.ETF_SHARE_SIZE.value]
        assert flow_reads == [center.input_bindings["full"].prepared, prepared.reference]


def test_equal_pinned_inputs_read_once_per_role_and_again_for_each_preparation(prepared_parameter_plan, monkeypatch):
    research, center, _, _, children = prepared_parameter_plan
    original = center.input_bindings["full"]
    assert all(child.input_bindings["full"].prepared == original.prepared for child in children)
    fetch = research.data.fetch
    calls = []

    def tracked(source_request, *, prepared):
        calls.append((source_request, prepared))
        return fetch(source_request, prepared=prepared)

    monkeypatch.setattr(research.data, "fetch", tracked)
    for index, child in enumerate((children[0], children[0], children[1]), start=1):
        assert prepare_request(research, child) is child
        assert len(calls) == index * len(original.plan.requests)
        assert all(reference == original.prepared for _, reference in calls)
    assert sorted(source_request.dataset for source_request, _ in calls) == sorted([
        source_request.dataset for source_request in original.plan.requests.values()
    ] * 3)


def test_equal_pinned_inputs_reject_corrupted_asset_after_success(prepared_parameter_plan):
    import sqlite3

    research, center, _, _, children = prepared_parameter_plan
    original = center.input_bindings["full"]
    assert children[0].input_bindings["full"].prepared == original.prepared
    assert prepare_request(research, children[0]) is children[0]
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
        prepare_request(research, children[0])


def test_unprepared_adapter_uses_authenticated_binding_after_source_cleanup(managed_evaluation):
    research, request = managed_evaluation
    assert not request.input_bindings
    result = research.evaluation.evaluate(request)
    shutil.rmtree(request.strategy.source_root)
    evidence = build_assessment_evidence(request, result)
    assert evidence[0].request_sha256 == result.request_hash


def test_parameter_plan_reuses_decoding_but_rechecks_all_published_bytes(prepared_parameter_plan, monkeypatch):
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan, _decode_parameter_plan

    _, request, plan, reference, _ = prepared_parameter_plan
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
    bound = prepare_request(research, request)
    frames = (bound.execution_data.adjusted_daily, bound.execution_data.execution_daily)
    originals = tuple(frame.attrs for frame in frames)
    copies = []
    original = generic.deepcopy

    def tracked(value, *args, **kwargs):
        if any(value is metadata for metadata in originals):
            copies.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(generic, "deepcopy", tracked)
    assert prepare_request(research, bound) is bound
    assert copies == []
    assert all(frame.attrs is metadata for frame, metadata in zip(frames, originals, strict=True))


@pytest.mark.parametrize("extend_history", [False, True])
def test_live_parameter_handles_use_certified_facts_without_source_or_data_reads(managed_evaluation, monkeypatch, extend_history):
    from datetime import date
    from strategy_runtime.implementation_identity import implementation_sha256
    from czsc_trader.research_tools import ResearchExecutionSession
    from czsc_trader.research_tools.parameter_evaluation import validate_parameter_request
    research, request = managed_evaluation
    if extend_history:
        source = request.strategy.source_root / "strategies/candidate_fixture.py"
        text = source.read_text(encoding="utf-8")
        old = '\"daily\",\n                1,\n                CutoffRule.SIGNAL_SESSION'
        assert old in text
        source.write_text(text.replace(old, '\"daily\",\n                int(parameters.values.get(\"lookback\", 1)),\n                CutoffRule.SIGNAL_SESSION', 1), encoding="utf-8", newline="\n")
        source_hash = implementation_sha256(("strategies/candidate_fixture.py",), source_root=request.strategy.source_root)
        payload = {"runtime": {**request.strategy.payload["runtime"], "source_sha256": source_hash},
                   "parameters": {"threshold": .5, "lookback": 1}}
        request = replace(request, strategy=replace(request.strategy, payload=payload),
            runtime_binding={**request.runtime_binding, "implementation_sha256": source_hash},
            windows=(replace(request.windows[0], start=date(2026, 9, 16)),))
    center, plan, _, children = parameter_plan(research, request, vary_lookback=extend_history)
    experiment = ExperimentRef("S900", request.experiment_id)
    with ResearchExecutionSession(research, experiment=experiment) as execution:
        center_handle = research.evaluation.prepare(center, execution=execution)
        child_handles = tuple(research.evaluation.prepare(replace(child, lineage=None), execution=execution)
                              for child in children)
        bound_handles = tuple(research.evaluation.prepare(child, execution=execution) for child in children)
        def forbidden(*args, **kwargs):
            pytest.fail("parameter handle operations must consume certified facts without source or data reads")
        monkeypatch.setattr(research.data, "fetch", forbidden)
        monkeypatch.setattr(StrategyRuntime, "describe", forbidden)
        monkeypatch.setattr(StrategyRuntime, "identify", forbidden)
        recreated = ParameterEvaluationPlan.create(plan.design, center_handle, child_handles,
            mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
            dataflows=research.data, execution=execution)
        assert recreated == plan
        for child in bound_handles:
            validate_parameter_request(child, research.data, execution=execution)
        with pytest.raises(ValueError, match="not issued"):
            ParameterEvaluationPlan.create(plan.design, replace(center_handle), child_handles,
                mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
                dataflows=research.data, execution=execution)
