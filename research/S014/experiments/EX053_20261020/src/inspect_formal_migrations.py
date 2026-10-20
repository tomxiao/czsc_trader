"""Inspect registered contract migrations and prepare plans; never freeze them."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import pickle
import traceback

from dataflows import ProviderConfig
from strategy_manager import CandidateEvidence, CandidateKey
from strategy_manager import freeze_contracts as f
from czsc_trader.application import (
    CandidateInspectionRequest, InspectionReplay, RepositoryContext,
    create_research_context, inspect_candidate, record_research_decision,
)
from czsc_trader.application.strategy_runtime_service import validate_release_package
from czsc_trader.research_tools import EvaluationResources, EvidenceRef, ExperimentRef, ResearchBatchRef
from czsc_trader.research_tools.delivery import EvaluationEvidenceRef


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUTPUT = EX / 'others/formal_migration_inspection'
REFERENCES = ('S001-v1', 'S001-v2', 'S002-v1', 'S007-v1', 'S011-v1', 'S003-v1')
CASES = {'S001-v1': 'S001-v1', 'S001-v2': 'S001-v2', 'S002-v1': 'S002-v1-common',
         'S007-v1': 'S007-v1-seed', 'S011-v1': 'S011-v1-common', 'S003-v1': 'S003-v1'}


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('immutable inspection receipt differs')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def engineering_proof(reference):
    publication = read(EX / 'others/market_acceptance_publication.json')
    manifest_ref = EvidenceRef.from_dict(publication['manifest'])
    manifest = read(manifest_ref.resolve(ROOT))
    case_path = (EX / 'others/market_equivalence' / CASES[reference] / 'result.json').relative_to(ROOT).as_posix()
    result_ref = EvidenceRef.from_dict(manifest['artifacts'][case_path])
    result_ref.resolve(ROOT)
    return tuple(f.ResearchEvidenceRef(
        f.ResearchEvidenceOwner(ref.experiment.strategy_id, ref.experiment.experiment_id),
        ref.evidence_id, ref.sha256) for ref in (manifest_ref, result_ref))


def run(reference, inplace, attempt):
    context = RepositoryContext.discover(ROOT)
    receipt = read(EX / 'others/formal_migration_registration' / f'{reference}.json')
    inventory = read(ROOT / '.tmp/window-contract-governance-inventory.json')
    row = next(item for item in inventory['releases'] if item['reference'] == reference)
    family, old_version = reference.split('-')
    candidate = CandidateKey(family, receipt['registration']['key']['candidate_id'])
    experiment = ExperimentRef.from_dict(receipt['experiment'])
    account = EvidenceRef.from_dict(receipt['account_evidence'])
    account.resolve(ROOT)
    output_root = OUTPUT / 'inplace' if inplace else OUTPUT
    if attempt != 1:
        output_root = output_root / f'attempt{attempt}'
    output = output_root / f'{reference}.json'
    if output.exists():
        previous = read(output)
        report = f.CandidateInspectionReport.from_dict(read(
            f.ResearchEvidenceRef.from_dict(previous['inspection_reference']).resolve(ROOT)))
        if report.sha256 != previous['report_sha256'] or report.origin.candidate != candidate:
            raise ValueError('existing inspection identity differs')
        print(json.dumps({'reference': reference, 'status': report.status.value, 'loaded_existing': True}), flush=True)
        return
    transport = receipt['bound_request_pickle']
    path = (ROOT / transport['path']).resolve()
    if not path.is_relative_to(ROOT / '.tmp') or digest(path) != transport['sha256']:
        raise ValueError('local bound request transport changed')
    request = pickle.loads(path.read_bytes())  # This turn's SHA-bound transport, not external input.
    manifest, binding, source = validate_release_package(context, reference)
    subject = f.FrozenMigrationSelectionSubject(
        f.FrozenVersionReference(family, old_version, row['release_hash'], manifest['package_hash']),
        candidate, receipt['registration']['content_sha256'], engineering_proof(reference))
    authority = EX / 'protocols' / ('inplace_migration_authorization.json' if inplace else 'migration_governance_authorization.json')
    target_version = old_version if inplace else row['proposed_freeze']['version']
    decision = record_research_decision(context, f.ResearchDecision(
        f'select_contract2_{family}_{old_version}_to_{target_version}',
        family, f.DecisionAction.APPROVE, subject,
        CandidateEvidence(authority.relative_to(ROOT).as_posix(), digest(authority)),
        '根据用户同意登记迁移并形成技术检验与冻结方案的授权，选择已核验等价迁移实现；不批准实际冻结、模拟交易资格或生产生效。'))
    # Preserve every original install-only file, including ordinary import packages.
    extras = tuple(f.FreezeFile(name, CandidateEvidence(
        (source / name).relative_to(ROOT).as_posix(), digest(source / name)))
        for name in binding['install_files'] if name not in binding['source_files'])
    research = create_research_context(context, ResearchBatchRef(family),
        resources=EvaluationResources(max_workers=1, native_threads_per_worker=1, random_seed=17),
        providers=ProviderConfig(env_file=ROOT / '.env'))
    risks = (
        '固定窗口工程迁移检验不形成新的策略收益优势或未见样本验收。',
        '原冻结版本未声明evaluation_scope；本次窗口不可追认为原研究范围。',
        '沿用原选择截止日和前瞻起点仅保存来源，不追认为新版本历史生效日。',
        '新版本冻结后默认RESEARCH；模拟交易资格和PTE切换须分别批准。',
    )
    if reference == 'S003-v1':
        risks += ('真实涨跌停规则会拒绝旧无规则回测曾接受的非法限价买单，改变成交及收益；同规则下策略前后等价，不表示新旧执行器经济等价。',)
    inspection = CandidateInspectionRequest(
        candidate=candidate, selection=decision,
        protocol=f.InspectionProtocol((f.InspectionCoordinate('full', 'baseline'),), tolerance=0.0),
        research=research, experiment=experiment,
        replays=(InspectionReplay(EvaluationEvidenceRef(account), request),),
        version=target_version, parent_version=read(context.strategy_root / family / 'versions' / f'{old_version}.json')['parent_version'] if inplace else old_version,
        change_summary='升级强类型历史窗口契约并显式声明MARKET_INTENT；保存原策略参数、指标与交易意图。',
        selection_data_cutoff=row['actual_selection_data_cutoff'], forward_start=row['forward_start'],
        additional_files=extras, remaining_risks=risks)
    dispatch = output_root / 'state' / f'{reference}-dispatch.json'
    if dispatch.exists():
        raise RuntimeError('inspection dispatched without durable receipt; inspect persisted reports before explicit recovery')
    write_once(dispatch, {'status': 'INSPECTION_DISPATCHED', 'selection': decision.to_dict(),
        'candidate': candidate.to_dict(), 'account_evidence': account.to_dict(),
        'target_version': inspection.version, 'strategy_computations': 2, 'benchmark_computations': 1})
    report = inspect_candidate(context, inspection)
    write_once(output, {'original_reference': reference, 'candidate': candidate.to_dict(),
        'status': report.status.value, 'inspection_reference': report.reference.to_dict(),
        'report_sha256': report.sha256, 'selection': decision.to_dict(),
        'plan_sha256': None if report.plan is None else report.plan.sha256,
        'plan': None if report.plan is None else report.plan.to_dict(),
        'checks': [item.to_dict() for item in report.checks],
        'remaining_risks': list(report.remaining_risks), 'freeze_executed': False,
        'paper_qualification_changed': False, 'production_writes': 0})
    print(json.dumps({'reference': reference, 'status': report.status.value,
        'plan_sha256': None if report.plan is None else report.plan.sha256,
        'checks': {item.check.value: item.status.value for item in report.checks}}, ensure_ascii=False), flush=True)
    if report.status is not f.InspectionStatus.PASS:
        raise RuntimeError('formal inspection did not pass; preserved report must be reviewed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--references', nargs='+', choices=REFERENCES, required=True)
    parser.add_argument('--inplace', action='store_true')
    parser.add_argument('--attempt', type=int, default=1)
    args = parser.parse_args()
    for reference in args.references:
        try:
            if args.attempt < 1:
                raise ValueError('attempt must be positive and explicitly selected')
            run(reference, args.inplace, args.attempt)
        except BaseException as error:
            directory = OUTPUT / 'failures' / reference
            number = len(tuple(directory.glob('*.json'))) + 1
            write_once(directory / f'{number:03}.json', {
                'error_type': type(error).__name__, 'error': str(error),
                'recorded_at': datetime.now(timezone.utc).isoformat(),
                'source_script_sha256': digest(Path(__file__)), 'automatic_rerun': False})
            traceback.print_exc()
            raise


if __name__ == '__main__':
    main()
