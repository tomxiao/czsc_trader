# Risk ownership: E2E-02 TDR-09
"""V4 immutable dependency publication, resume, registration and diagnosis."""
from dataclasses import replace
import json

import pytest
from strategy_manager import CandidateKey
from czsc_trader.application import (publish_evidence_many, publish_evidence, register_candidate,
    load_candidate, diagnose_accounts, CandidateRegistrationRequest, assemble_delivery, validate_delivery)
from czsc_trader.research_tools import (ResearchExecutionSession, CheckpointMode, EvaluationEvidenceWrite, MaterialEvidenceWrite, AccountRunRef, AccountDiagnosisRequest,
    EvaluationIdentity, EvaluationWindow)
from czsc_trader.research_tools.assessment import build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from account_parity_support import setup_account
from dataflows import MarketId, BarFrequency


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
        restored = checkpoint is not None and checkpoint.mode is CheckpointMode.RESUME
        assert execution.equity_statistics.candidate_runs == (0 if restored else len(requests))
        assert execution.equity_statistics.benchmark_runs == (0 if restored else 1)
        yield execution, prepared, results, publications, facts


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US], ids=['E2E-02-C01', 'E2E-02-C02'])
def test_v4_public_publish_register_diagnose_and_delivery(tmp_path, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    window = EvaluationWindow('TEST', request.window.start.date(), request.window.end.date())
    for execution, prepared, results, publications, facts in run_accounts(context, request):
        detached = EvaluationEvidenceWrite(request.experiment, 'detached', prepared[0], results[0].result)
        refs = tuple(value.reference for value in publications)
        assert all((ref.schema, ref.schema_version) == ('equity_research', 4) for ref in refs)
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
            window), execution=execution)
        assert diagnosis.status.value == 'COMPUTED', diagnosis.issues
        assert execution.equity_statistics.candidate_runs == 2
        assert execution.equity_statistics.benchmark_runs == 1
        record = register_candidate(context.repository,
            CandidateRegistrationRequest(request.candidate, request.experiment, (refs[0],), ()))
        assert load_candidate(context.repository, request.candidate.key).content_identity.content_sha256 == record.content_sha256
        material = publish_evidence(context, MaterialEvidenceWrite(request.experiment, 'definition',
            json.dumps(request.candidate.payload).encode(), 'application/json', 'json'), execution=execution)
        entry = d.PrototypeEntry('P1', d.CandidateIdentityRef(request.candidate.key, record.content_sha256),
            d.ExperimentDefinitionRef(material, 'strategy:step'), 'Synthetic v4 timing', (),
            (d.EvaluationEvidenceRef(refs[0], (facts[0].evaluation_id,)),), d.PrototypeDisposition.INVESTIGATE,
            'Contract exercise', ('Synthetic data',), 'Review', (material,))
        panel = d.PrototypePanel((entry,), (), (), 'Complete source closure')
        delivery = assemble_delivery(context.repository, d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 1, ()),
            d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report='# V4 fixture\n'))
        assert validate_delivery(context.repository, delivery.receipt.reference).status == 'PASS'
        assert source.is_dir()
        # A cached accounting certification cannot hide later dependency damage.
        dependency = asset_dir / (results[0].result.payload['input_ref']['sha256'] + '.json')
        dependency.write_bytes(b'{}')
        damaged = diagnose_accounts(context.repository, AccountDiagnosisRequest(
            AccountRunRef(refs[0], identities[0]), None,
            window), execution=execution)
        assert damaged.status.value == 'INVALID_EVIDENCE'
        assert any('artifact content digest differs' in issue for issue in damaged.issues)
        assert validate_delivery(context.repository, delivery.receipt.reference).status == 'PASS'
    # A real result cannot be published after its owning session has closed.
    with pytest.raises((TypeError, RuntimeError, ValueError), match='Session|session|active|execution'):
        publish_evidence(context, detached)
