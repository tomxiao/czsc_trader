"""User-authorized local S018-v1 replacement with retained migration evidence."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from czsc_trader.application import (RepositoryContext, create_research_context,
    load_candidate, publish_evidence, validate_release_package,
    FrozenRuntimeUpgradeRequest, prepare_frozen_runtime_upgrade, apply_frozen_runtime_upgrade)
from czsc_trader.application.runtime_migration import PreparedFrozenRuntimeUpgrade
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_manager.freeze_contracts import FrozenVersionReference, ResearchEvidenceRef, ResearchEvidenceOwner
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, StrategyRuntime
from strategy_runtime.deployment import validate_release_integrity
from dataflows import ProviderConfig
from czsc_trader.application.research_evidence import validate_inspection
from strategy_manager.freeze_contracts import InspectionStatus

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
EXPERIMENT = ExperimentRef('S018','EX070_20261108')
EXP = EXPERIMENT.resolve(ROOT)
EXPECTED_CONTENT = '94bbd13ea036128a0ce31c183b34da8fedfa742cb686132c85c0edb437bfd23b'
EXPECTED_REPORT = 'd0985f1b2b4024606f1666309d7fbe2ba216a835629a121112757c9c853da049'
EXPECTED_RELEASE = '75e84399dc535f98b42ed7a186c6b2ed56c1d8c85397e28152f243fc8f0bae4a'
EXPECTED_PACKAGE = '283e6044a6911cc7c7a518aa1fe85e282ec1d138fdf21f09ef740c043b823e41'
sys.dont_write_bytecode = True


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')


def evidence(context, name, value):
    content = (json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n').encode()
    ref = publish_evidence(context,MaterialEvidenceWrite(EXPERIMENT,name,content,'application/json','json'))
    return ResearchEvidenceRef(ResearchEvidenceOwner('S018',EXPERIMENT.experiment_id),ref.evidence_id,ref.sha256)


def check_package(repository, candidate):
    manifest, _, source = validate_release_package(repository,'S018-v1')
    version = StrategyRegistry(repository.strategy_root).get_version('S018','v1')
    assert manifest['runtime_candidate_id'] == 'C9396'
    frozen = EquityStrategyCandidate('S018','C9396',
        EquityStrategyDefinition.from_dict(dict(version.strategy_payload['equity_definition'])),source)
    assert frozen.content_identity == candidate.content_identity
    assert frozen.definition.to_dict() == candidate.definition.to_dict()
    for name in candidate.definition.source_files:
        assert (source/name).read_bytes() == (candidate.source_root/name).read_bytes()
    StrategyRuntime().describe(frozen)
    return manifest, version


def main(mode):
    repository = RepositoryContext.discover(ROOT)
    candidate = load_candidate(repository,CandidateKey('S018','C9396'))
    assert candidate.content_identity.content_sha256 == EXPECTED_CONTENT
    context = create_research_context(repository,ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={},equity_bindings={}),execution_spec=candidate.definition.execution_spec)
    if mode == 'prepare':
        assert not (HERE/'prepared.json').exists(), 'Preparation already retained; use the existing exact plan'
        report_ref = EvidenceRef.from_dict(read(EXP/'report_ref.json')['report'])
        assert report_ref.sha256 == EXPECTED_REPORT
        report_ref.resolve(ROOT)
        inspection_ref = ResearchEvidenceRef.from_dict(read(EXP/'others/attempt01/reference.json'))
        inspection = validate_inspection(ROOT,inspection_ref)
        assert inspection.status is InspectionStatus.PASS
        assert inspection.origin.content_sha256 == EXPECTED_CONTENT
        verified_old = validate_release_integrity(repository.strategy_root,'S018-v1')
        old = StrategyRegistry(repository.strategy_root).get_version('S018','v1')
        original = FrozenVersionReference('S018','v1',old.release_hash,verified_old.package_sha256)
        authorization = {
            'recorded_at':datetime.now(timezone.utc).isoformat(), 'actor':'RSCH',
            'user_instruction':'同意',
            'approved_proposal':'DEV修复已完成；下一步建议切回RSCH，完成已授权的S018-v1原地升级。',
            'prior_user_instruction':'可以重新冻结并保持版本号不变',
            'context':'User approved the same-version S018-v1 upgrade after EX070 formal-component verification and DEV c4ac86237 isolated transaction/rollback verification.',
            'candidate':'S018-C9396','content_sha256':EXPECTED_CONTENT,'original':original.to_dict(),
            'version':'v1','scope':'Local same-version frozen package replacement using EX069 adaptation and EX070 formal technical evidence.',
            'expected_release_hash':EXPECTED_RELEASE,'expected_package_hash':EXPECTED_PACKAGE,
            'stage_four_rerun':False,'formal_stage_five_rerun':False,
            'excluded':['qualification grant','PTE production deployment or rebinding','merge','tag','push'],
        }
        confirmation = evidence(context,'c9396-same-version-user-authorization',authorization)
        review = {'candidate':'S018-C9396','content_sha256':EXPECTED_CONTENT,
            'report':report_ref.to_dict(),'report_publication_status':'PASS',
            'inspection':inspection_ref.to_dict(),'technical_summary':read(EXP/'others/technical_summary.json'),
            'financial_predicate_points':961,'financial_predicate_differences':0,
            'isolated_pte_sessions':58,'platform_fix_commit':'c4ac86237',
            'new_account_completed':True,
            'account_ref':read(ROOT/'research/S018/experiments/EX069_20261108/others/account_reference.json'),
            'limits':['No old/new economic equivalence claim','No inherited stage-four or stage-five acceptance',
                      'EX070 uses formal PTE components with recorded broker facts, not live trading',
                      'EX070 preview package and the history-preserving upgrade package have distinct release identities; runtime content equality is checked separately'],
            'authorization_decision':'Proceed with expressly authorized same-version replacement; no additional economic search.'}
        review_ref = evidence(context,'c9396-same-version-rsch-review',review)
        report_material = ResearchEvidenceRef(ResearchEvidenceOwner('S018',EXPERIMENT.experiment_id),
            report_ref.evidence_id,report_ref.sha256)
        prepared = prepare_frozen_runtime_upgrade(repository,FrozenRuntimeUpgradeRequest(
            original,candidate,confirmation,
            '保持S018-v1版本号，原地替换为C9396：策略只使用HFQ行情并输出当前账户权益目标比例，EC尽力执行。金融参数及谓词保持；再平衡、目标提升和退出状态语义变化及验证边界见EX069。',
            'RSCH',(review_ref,report_material,inspection_ref),ROOT/'.tmp/s018-c9396-same-version/prepared'))
        staged = replace(repository,strategy_root=prepared.plan_path.parent/'staged')
        new_manifest, new = check_package(staged,candidate)
        assert prepared.migrated.release_hash == EXPECTED_RELEASE
        assert prepared.migrated.package_hash == EXPECTED_PACKAGE
        for name in ('strategy_id','version','parent_version','source_candidate','source_experiment','selection_data_cutoff','forward_start'):
            assert getattr(old,name) == getattr(new,name)
        value = {'plan_path':prepared.plan_path.relative_to(ROOT).as_posix(),
            'plan_sha256':prepared.plan_sha256,'original':original.to_dict(),'migrated':prepared.migrated.to_dict(),
            'candidate_content_sha256':EXPECTED_CONTENT,'authorization':confirmation.to_dict(),
            'review':review_ref.to_dict(),'inspection':inspection_ref.to_dict(),
            'checks':{'same_version':True,'same_candidate_bytes':True,
                'runtime_load':True,'historical_fields_preserved':True},
            'plan':read(prepared.plan_path)}
        save('prepared.json',value)
        print(json.dumps({'status':'PREPARED','migrated':prepared.migrated.to_dict(),'checks':value['checks']},ensure_ascii=False))
        return
    value = read(HERE/'prepared.json')
    prepared = PreparedFrozenRuntimeUpgrade(ROOT/value['plan_path'],value['plan_sha256'],
        FrozenVersionReference.from_dict(value['original']),FrozenVersionReference.from_dict(value['migrated']))
    receipt = apply_frozen_runtime_upgrade(repository,prepared)
    manifest, version = check_package(repository,candidate)
    assert manifest['package_hash'] == receipt.migrated.package_hash
    assert version.release_hash == receipt.migrated.release_hash
    assert version.release_hash == EXPECTED_RELEASE and manifest['package_hash'] == EXPECTED_PACKAGE
    archived = replace(repository,strategy_root=receipt.archive_path/'strategies')
    old = StrategyRegistry(archived.strategy_root).get_version('S018','v1')
    assert validate_release_integrity(archived.strategy_root,'S018-v1').package_sha256 == prepared.original.package_hash
    for name in ('strategy_id','version','parent_version','source_candidate','source_experiment','selection_data_cutoff','forward_start'):
        assert getattr(old,name) == getattr(version,name)
    # The idempotent path authenticates the old archive, audit copies and current package.
    assert apply_frozen_runtime_upgrade(repository,prepared) == receipt
    qualification = StrategyRegistry(repository.strategy_root).current_qualification('S018','v1')
    result = {'status':receipt.status.value,'reference':'S018-v1','runtime_candidate':'C9396',
        'qualification':qualification.value,'original':receipt.original.to_dict(),'migrated':receipt.migrated.to_dict(),
        'archive_path':receipt.archive_path.relative_to(ROOT).as_posix(),
        'receipt_path':receipt.receipt_path.relative_to(ROOT).as_posix(),
        'candidate_content_sha256':EXPECTED_CONTENT,
        'inspection':value['inspection'],'historical_source_candidate':version.source_candidate,
        'checks':{'package_valid':True,'candidate_content_equal':True,'runtime_load':True,
                  'archive_and_idempotent_receipt_valid':True,'version_unchanged':True,
                  'historical_fields_preserved':True},
        'production_writes':0,'qualification_grant':False}
    assert qualification.value == 'RESEARCH'
    published = evidence(context,'c9396-same-version-committed',result)
    result['evidence'] = published.to_dict()
    save('result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode',choices=('prepare','apply'))
    main(parser.parse_args().mode)
