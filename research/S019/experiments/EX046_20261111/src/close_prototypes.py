"""Selection-driven PROTOTYPES/3; no automatic stage or budget transition."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, assemble_delivery, validate_experiment, validate_delivery)
from dataflows import ProviderConfig

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
BATCH_ROOT = ROOT/'research/S019'
sys.path.insert(0,str(BATCH_ROOT/'experiments/EX013_20261110/src'))
from runner import read_account, metrics  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def local(name):
    path = (ROOT/name).resolve()
    assert path.is_relative_to(BATCH_ROOT.resolve()), name
    return path


def receipt(stage, revision):
    return d.DeliveryReference.from_dict(read(BATCH_ROOT/f'deliveries/{stage}/{revision}/receipt.json')['reference'])


def preflight(selection_path):
    selection = read(selection_path)
    assert selection['stage'] == 'STAGE_TWO'
    mandate, previous, assessment = (receipt(s,2) for s in ('MANDATE','PROTOTYPES','ASSESSMENT'))
    prior = read(BATCH_ROOT/'assets/deliveries/PROTOTYPES/2/delivery.json')['content']['payload']
    assert 'C0080' in {entry['prototype_id'] for entry in prior['prototypes']}
    payload = d.PrototypePanel(
        tuple(d.PrototypeEntry.from_dict(x) for x in selection['prototypes']),
        tuple(d.ComponentEntry.from_dict(x) for x in selection['components']),
        tuple(d.PrototypeComparison.from_dict(x) for x in selection['comparisons']),
        selection['conclusion'])
    assert any(p.identity.key.candidate_id == 'C0355' for p in payload.prototypes)
    assert all(p.sources and all(s.delivery == previous and s.prototype_id == 'C0080' for s in p.sources)
        for p in payload.prototypes)
    assert payload.comparisons, 'Keep explicit baseline/alternative/counterexample comparisons'
    repo = RepositoryContext.discover(ROOT)
    assert validate_delivery(repo,previous,scope=d.DeliveryValidationScope.INTEGRITY).status is d.ValidationStatus.PASS
    report_refs = []
    for experiment in selection['completed_experiments']:
        exp = d.ExperimentRef('S019',experiment)
        assert validate_experiment(repo,d.ExperimentValidationRequest(exp,
            d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
        report_refs.append(d.EvidenceRef.from_dict(read(BATCH_ROOT/f'experiments/{experiment}/report_ref.json')['report']))
    assert selection['owner_experiment'] in selection['completed_experiments']
    checks = []
    account_files = selection['account_reference_files']
    for entry in payload.prototypes:
        assert entry.evaluations, 'Selected complete prototypes require formal accounts'
        definition_raw = entry.definition.evidence.resolve(ROOT).read_bytes()
        assert sha256(definition_raw).hexdigest() == entry.definition.evidence.sha256
        definition = json.loads(definition_raw)
        for evaluation in entry.evaluations:
            ref_file = local(account_files[evaluation.evidence.sha256])
            assert read(ref_file) == evaluation.evidence.to_dict()
            ref, account = read_account(ref_file)
            header = read(ref.resolve(ROOT))
            request = header['request']
            assert request['candidate_id'] == entry.identity.key.candidate_id
            assert request['content_sha256'] == entry.identity.content_sha256
            assert request['candidate_definition'] == definition
            assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'
            assert request['window_id'] == 'FULL' and request['lineage'] is None
            assert set(evaluation.evaluation_ids) == {header['evaluation_id']}
            run, buy_hold = account['runs']['candidate'],account['runs']['buy_hold']
            result = metrics(run,buy_hold['metrics']['daily_max_drawdown'])
            checks.append({'prototype_id':entry.prototype_id,'candidate_id':entry.identity.key.candidate_id,
                'account_ref':ref.to_dict(),'evaluation_id':header['evaluation_id'],
                'center_metrics':result,'all_original_center_gates_pass':result['eligible'],
                'failed_original_center_gates':[k for k,v in result['gates'].items() if not v]})
    original_checks = read(BATCH_ROOT/'experiments/EX041_20261110/others/assessment_summary.json')
    assert all(x['acceptance_status']=='FAILED' for x in original_checks['candidates'])
    original_summary_sha = digest(BATCH_ROOT/'experiments/EX041_20261110/others/assessment_summary.json')
    assert original_summary_sha in {f['sha256'] for f in read(BATCH_ROOT/'deliveries/ASSESSMENT/2/receipt.json')['files']}
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage'] == 'STAGE_TWO'
    assert 'active_experiment' not in intent and 'active_round_budget' not in intent
    budget = intent['joint_search_budget']
    assert budget['authorized_rounds']==10 and 4 < budget['used_rounds'] <= 10
    assert budget['remaining_rounds']==10-budget['used_rounds']
    assert selection['completed_mechanism_experiments'] == [r['experiment'] for r in budget['rounds'] if r['round']>4]
    assert set(selection['completed_mechanism_experiments']) <= set(selection['completed_experiments'])
    review = {'selection_sha256':digest(selection_path),'template_sha256':digest(Path(__file__)),
        'measurement_helper_sha256':digest(BATCH_ROOT/'experiments/EX013_20261110/src/runner.py'),
        'mandate':mandate.to_dict(),'prototype_source':previous.to_dict(),'prior_assessment':assessment.to_dict(),
        'center_checks':checks,'prior_assessment_checks':original_checks['candidates'],
        'prior_assessment_summary_sha256':original_summary_sha,
        'budget_snapshot':budget,'report_refs':[r.to_dict() for r in report_refs],
        'new_account_replays':0,'automatic_stage_transition':'NONE','automatic_budget_mutation':'NONE'}
    return selection, payload, review, report_refs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('prepare','publish'))
    parser.add_argument('--selection',required=True,type=Path)
    parser.add_argument('--review',required=True,type=Path)
    args = parser.parse_args()
    selection_path = args.selection.resolve()
    review_path = args.review.resolve()
    assert selection_path.is_relative_to(BATCH_ROOT.resolve()) and review_path.is_relative_to(BATCH_ROOT.resolve())
    assert not (BATCH_ROOT/'deliveries/PROTOTYPES/3/receipt.json').exists(), 'Inspect existing delivery before retry'
    assert not review_path.with_name('prototype_publication.json').exists(), 'Inspect previous publication receipt before retry'
    selection,payload,review,reports = preflight(selection_path)
    report_path = local(selection['stage_report'])
    review['stage_report_sha256'] = digest(report_path)
    if args.action=='prepare':
        review_path.write_bytes((json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
        print('PROTOTYPES_REVIEW_READY',len(payload.prototypes),len(payload.comparisons),flush=True)
        return
    assert read(review_path)==review, 'Frozen selection, report, budget or account review changed'
    started = perf_counter()
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    context = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    exp = d.ExperimentRef('S019',selection['owner_experiment'])
    materials = []
    for i,path in enumerate((selection_path,review_path,Path(__file__),
            BATCH_ROOT/'experiments/EX041_20261110/others/assessment_summary.json',
            BATCH_ROOT/'deliveries/ASSESSMENT/2/receipt.json')):
        ext = path.suffix[1:]
        materials.append(publish_evidence(context,d.MaterialEvidenceWrite(exp,f'prototype-close-{i:02}',
            path.read_bytes(),{'py':'text/x-python','json':'application/json'}[ext],ext)))
    references = tuple(d.DeliveryReference.from_dict(review[key]) for key in ('mandate','prototype_source'))
    content = d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),
        report=report_path.read_text(encoding='utf-8'),evidence=tuple((*reports,*materials)))
    assembled = assemble_delivery(repo,d.DeliveryDefinition(batch,d.DeliveryStage.PROTOTYPES,3,references,
        schema_version=10),content)
    assert assembled.validation.status is d.ValidationStatus.PASS
    output = review_path.with_name('prototype_publication.json')
    assert not output.exists()
    output.write_bytes((json.dumps({'receipt':assembled.receipt.to_dict(),'validation':assembled.validation.to_dict(),
        'seconds':perf_counter()-started,'new_account_replays':0,'stage_transition':'NONE','budget_mutation':'NONE'},
        ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    print('PROTOTYPES_PUBLISHED',assembled.receipt.reference.content_sha256,flush=True)


if __name__=='__main__':
    main()
