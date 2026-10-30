"""V3 immutable dependency publication, resume, registration and diagnosis."""
from dataclasses import replace
from datetime import date
import json

import pytest
from strategy_runtime import ExecutionResources
from strategy_manager import CandidateKey
from czsc_trader.application import (publish_evidence_many, publish_evidence, register_candidate,
    load_candidate, diagnose_accounts, CandidateRegistrationRequest, assemble_delivery, validate_delivery)
from czsc_trader.research_tools import (ResearchExecutionSession, ExecutionCheckpointRequest,
    CheckpointMode, EvaluationEvidenceWrite, MaterialEvidenceWrite, AccountRunRef, AccountDiagnosisRequest,
    EvaluationIdentity, EvaluationWindow)
from czsc_trader.research_tools.assessment import build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from equity_test_support import setup_v3


def run_accounts(context, request, *, paired=True, checkpoint=None):
    requests = (request, replace(request, candidate=replace(request.candidate, candidate_id='C0002'))) if paired else (request,)
    with ResearchExecutionSession(context, experiment=request.experiment, checkpoint=checkpoint) as execution:
        prepared = tuple(context.evaluation.prepare(value, execution=execution) for value in requests)
        results = context.evaluation.evaluate_many(prepared, execution=execution)
        assert all(value.status.value == 'SUCCEEDED' for value in results), [v.error for v in results]
        writes = tuple(EvaluationEvidenceWrite(request.experiment, f'account-{i}', p, value.result)
                       for i, (p, value) in enumerate(zip(prepared, results)))
        publications = publish_evidence_many(context, writes, execution=execution)
        assert all(p.status.value == 'PUBLISHED' for p in publications), [p.error for p in publications]
        facts = tuple(build_assessment_evidence(p, value.result, execution=execution)[0]
                      for p, value in zip(prepared, results))
        assert execution.equity_statistics.authenticated_accounts == len(requests) + 1
        yield execution, prepared, results, publications, facts


def test_v3_public_publish_register_diagnose_and_delivery(tmp_path):
    context, request, _, _ = setup_v3(tmp_path)
    for execution, prepared, results, publications, facts in run_accounts(context, request):
        detached = EvaluationEvidenceWrite(request.experiment, 'detached', prepared[0], results[0].result)
        refs = tuple(value.reference for value in publications)
        assert all((ref.schema, ref.schema_version) == ('equity_research', 3) for ref in refs)
        assert results[0].result.payload['benchmark_ref'] == results[1].result.payload['benchmark_ref']
        source = request.experiment.resolve(context.repository.root)
        asset_dir = refs[0].resolve(context.repository.root).parent
        assert len(list(asset_dir.glob('*.json'))) == 6  # shared input + baseline + two accounts + two results
        identities = []
        for result in results:
            value = dict(result.result.payload['evaluation_identity'])
            value['candidate'] = CandidateKey(**value['candidate'])
            identities.append(EvaluationIdentity(**value))
        diagnosis = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(refs[0], identities[0]), AccountRunRef(refs[1], identities[1]),
            EvaluationWindow('TEST', date(2026, 10, 1), date(2026, 10, 2))), execution=execution)
        assert diagnosis.status.value == 'COMPUTED', diagnosis.issues
        assert execution.equity_statistics.authenticated_accounts == 3
        record = register_candidate(context.repository,
            CandidateRegistrationRequest(request.candidate, request.experiment, (refs[0],), ()))
        assert load_candidate(context.repository, request.candidate.key).content_identity.content_sha256 == record.content_sha256
        material = publish_evidence(context, MaterialEvidenceWrite(request.experiment, 'definition',
            json.dumps(request.candidate.payload).encode(), 'application/json', 'json'))
        entry = d.PrototypeEntry('P1', d.CandidateIdentityRef(request.candidate.key, record.content_sha256),
            d.ExperimentDefinitionRef(material, 'strategy:step'), 'Synthetic v3 timing', (),
            (d.EvaluationEvidenceRef(refs[0], (facts[0].evaluation_id,)),), d.PrototypeDisposition.INVESTIGATE,
            'Contract exercise', ('Synthetic data',), 'Review', (material,))
        panel = d.PrototypePanel((entry,), (), (), 'Complete source closure')
        delivery = assemble_delivery(context.repository, d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 1, ()),
            d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report='# V3 fixture\n'))
        assert validate_delivery(context.repository, delivery.receipt.reference).status == 'PASS'
        assert source.is_dir()
        # A cached accounting certification cannot hide later dependency damage.
        dependency = asset_dir / (results[0].result.payload['input_ref']['sha256'] + '.json')
        dependency.write_bytes(b'{}')
        damaged = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(refs[0], identities[0]), None,
            EvaluationWindow('TEST', date(2026, 10, 1), date(2026, 10, 2))), execution=execution)
        assert damaged.status.value == 'INVALID_EVIDENCE'
        assert any('checksum differs' in issue for issue in damaged.issues)
        assert validate_delivery(context.repository, delivery.receipt.reference).status == 'PASS'
    # A real result cannot be published after its owning session has closed.
    with pytest.raises((TypeError, RuntimeError, ValueError), match='Session|session|active|execution'):
        publish_evidence(context, detached)


def test_v3_checkpoint_restores_results_and_publication_closure(tmp_path):
    context, request, _, _ = setup_v3(tmp_path)
    context.evaluation.resources = ExecutionResources(max_workers=2, native_threads_per_worker=1)
    for _, _, results, publications, _ in run_accounts(context, request,
            checkpoint=ExecutionCheckpointRequest('v3-checkpoint')):
        contents = tuple(value.result.content for value in results)
        refs = tuple(value.reference for value in publications)
    for execution, _, results, publications, _ in run_accounts(context, request,
            checkpoint=ExecutionCheckpointRequest('v3-checkpoint', CheckpointMode.RESUME)):
        assert tuple(value.result.content for value in results) == contents
        assert tuple(value.reference for value in publications) == refs
        assert execution.stats.reused_results == 2 and execution.stats.reused_publications == 2


@pytest.mark.parametrize('damage', ('missing', 'changed'))
def test_v3_delivery_cache_rechecks_each_packages_dependency_closure(tmp_path, monkeypatch, damage):
    from czsc_trader.application import delivery_service as service

    context, request, _, _ = setup_v3(tmp_path)
    for _, _, results, publications, facts in run_accounts(context, request, paired=False):
        ref = publications[0].reference
        record = register_candidate(context.repository,
            CandidateRegistrationRequest(request.candidate, request.experiment, (ref,), ()))
        material = publish_evidence(context, MaterialEvidenceWrite(request.experiment, 'definition',
            json.dumps(request.candidate.payload).encode(), 'application/json', 'json'))
        entry = d.PrototypeEntry('P1', d.CandidateIdentityRef(request.candidate.key, record.content_sha256),
            d.ExperimentDefinitionRef(material, 'strategy:step'), 'Synthetic v3 timing', (),
            (d.EvaluationEvidenceRef(ref, (facts[0].evaluation_id,)),), d.PrototypeDisposition.INVESTIGATE,
            'Contract exercise', ('Synthetic data',), 'Review', (material,))
        content = d.DeliveryContent(d.PrototypePanel((entry,), (), (), 'Complete source closure'),
            d.DeliveryStatus.COMPLETE, (), (), report='# V3 closure fixture\n')
        first = assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 1, ()), content)
        second = assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 2, (first.receipt.reference,)), content)

        certify = service._certify_account
        certifications = []

        def counted_certify(data, reference, root=None):
            certifications.append(reference.sha256)
            return certify(data, reference, root)

        monkeypatch.setattr(service, '_certify_account', counted_certify)
        checked = validate_delivery(context.repository, second.receipt.reference)
        assert checked.status == 'PASS', checked.issues
        assert certifications == [ref.sha256]  # Numerical certification is still shared.
        certifications.clear()

        root = service._delivery_path(context.repository, second.receipt.reference)
        dependency = root / 'evidence' / (results[0].result.payload['input_ref']['sha256'] + '.json')
        if damage == 'missing':
            dependency.unlink()
        else:
            dependency.write_bytes(b'{}')
        # Give the modified package a self-consistent receipt. It must fail
        # closure authentication, not an earlier manifest or public-copy check.
        files = service._manifest(root)
        revised = replace(second.receipt.reference, content_sha256=d._digest(files))
        receipt = replace(second.receipt, reference=revised, files=files)
        encoded = d._canonical(receipt)
        (root / 'receipt.json').write_bytes(encoded)
        (service._public_delivery_path(context.repository, revised) / 'receipt.json').write_bytes(encoded)
        assert service._manifest(root) == receipt.files
        service._validate_public_copy(context.repository, revised, root)
        damaged = validate_delivery(context.repository, revised)
        assert damaged.status == 'FAIL', damaged
        assert certifications == [ref.sha256]  # The valid predecessor populated the cache.
        assert all(issue.code not in ('DELIVERY_FILES', 'PUBLIC_DELIVERY', 'DELIVERY_IDENTITY')
                   for issue in damaged.issues)
        if damage == 'changed':
            assert any('checksum differs' in issue.message for issue in damaged.issues)
