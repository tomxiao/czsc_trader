"""Commit the user's approved exact C9380 package; never deploy it."""
from pathlib import Path
from hashlib import sha256
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]
TEMP = ROOT / '.tmp/s018-c9380-stage5'
TEMP.mkdir(exist_ok=True, parents=True)
os.environ.update(TEMP=str(TEMP), TMP=str(TEMP), PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode = True

# ruff: noqa: E402 -- Configure local temporary storage before platform imports.
from czsc_trader.application import RepositoryContext, record_research_decision, freeze_candidate, get_freeze_result
from strategy_manager import CandidateEvidence, freeze_contracts as f
from strategy_runtime.deployment import validate_release_package


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_new(path, value):
    raw = (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError('existing freeze evidence differs: '+str(path.relative_to(ROOT)))
    else:
        path.write_bytes(raw)
    return path


def main():
    repo=RepositoryContext.discover(ROOT)
    review=read(EXP/'protocols/freeze_approval_plan.json')
    report=f.CandidateInspectionReport.from_dict(read(EXP/'others/inspection_report.json'))
    subject=f.FreezeSubject.from_dict(review['subject'])
    assert subject.content_sha256=='186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    assert subject.inspection.sha256=='db4744d3c893c2570a211e16c398394bda693d3481f6996984286cbd6633b41c'
    assert subject.plan_sha256=='2b1a664203176f58f82dd4c106ef90c08fe6f3a8dce4aaae5e855819c8ae7030'
    assert report.plan.sha256==subject.plan_sha256 and report.reference==subject.inspection
    assert report.status is f.InspectionStatus.PASS and subject.version=='v1'
    assert review['plan']==report.plan.to_dict() and review['release']==report.release.to_dict()
    assert report.release.package_sha256=='994d23f4a7c12f1963c0d006c3f92f8062bd9b3ab5f25bbda860aa8c47f28e7e'
    approval_file=save_new(EXP/'protocols/freeze_01/user_approval.json',{
        'user_quote':'同意冻结','recorded_on':'2026-11-05',
        'approved_proposal':'按已呈现的精确冻结计划将C9380首次冻结为S018-v1；不部署。',
        'subject':subject.to_dict(), 'release_sha256':report.release.release_sha256,
        'package_sha256':report.release.package_sha256,
        'reviewed_plan':'research/S018/experiments/EX068_20261105/protocols/freeze_approval_plan.json',
        'reviewed_plan_file_sha256':sha256((EXP/'protocols/freeze_approval_plan.json').read_bytes()).hexdigest(),
        'scope':'提交已检验的同一版本及发布字节，核对COMMITTED并完成阶段五交付；不部署、不重绑、不改生产。'})
    approval=record_research_decision(repo,f.ResearchDecision('S018-C9380-v1-freeze-approval-20261105',
        'S018',f.DecisionAction.APPROVE,subject,
        CandidateEvidence(approval_file.relative_to(ROOT).as_posix(),sha256(approval_file.read_bytes()).hexdigest()),
        '用户在精确计划及技术报告呈现后明确同意冻结S018-v1。'))
    save_new(EXP/'others/freeze_01/approval_reference.json',approval.to_dict())
    request=f.FreezeCandidateRequest(f.FreezeRequestId('S018','S018-C9380-v1-native-20261105'),report.reference,approval)
    save_new(EXP/'others/freeze_01/request.json',request.to_dict())
    initial=get_freeze_result(repo,request.request_id)
    if initial.status is f.FreezeStatus.NOT_FOUND:
        try:
            receipt=freeze_candidate(repo,request)
        except Exception:
            observed=get_freeze_result(repo,request.request_id)
            save_new(EXP/'others/freeze_01/interrupted_result.json',observed.to_dict())
            raise
    else:
        receipt=initial
    save_new(EXP/'others/freeze_01/receipt.json',receipt.to_dict())
    observed=get_freeze_result(repo,request.request_id)
    assert observed==receipt and receipt.status is f.FreezeStatus.COMMITTED,receipt.to_dict()
    assert receipt.request_sha256==request.sha256
    assert receipt.version.release_hash==report.release.release_sha256
    assert receipt.version.package_hash==report.release.package_sha256
    package=validate_release_package(repo.strategy_root,'S018-v1')
    assert package.package_sha256==receipt.version.package_hash
    assert package.release.release_hash==receipt.version.release_hash
    assert package.release.payload['runtime']['kind']=='ACCOUNT_REPLAY'
    assert package.release.payload['runtime']['contract_version']==4
    save_new(EXP/'others/freeze_01/verification.json',{
        'status':'PASS','receipt':observed.to_dict(),
        'plan_sha256':subject.plan_sha256,'inspected_package_matches_frozen':True,
        'release_sha256':package.release.release_hash,'package_sha256':package.package_sha256,
        'qualification':'RESEARCH','production':'NOT_TOUCHED','deployment':'NOT_EXECUTED'})
    print(json.dumps({'status':receipt.status.value,'version':receipt.version.to_dict()},ensure_ascii=True),flush=True)


if __name__=='__main__':
    main()
