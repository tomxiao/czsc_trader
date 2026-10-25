"""Freeze the exact inspected C9700 package under the user's approval."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from czsc_trader.application import (  # noqa: E402
    RepositoryContext, assemble_delivery, freeze_candidate, get_freeze_result,
    record_research_decision,
)
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources  # noqa: E402
from czsc_trader.research_tools import delivery as d  # noqa: E402
from strategy_manager import CandidateEvidence, StrategyRegistry  # noqa: E402
from strategy_manager import freeze_contracts as f  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
OUT = HOME / 'others/freeze'
REPORT_HASH = '10ddf0ff6f3e246cbff071ea94a63a784bec36c6f0855598f1bb5ffb690feefa'
PLAN_HASH = '18ce3226e5ab7ff637d926e7d755546f850884ffe73d21c2309fb7e6971fe73c'
RELEASE_HASH = '13eba2fcbf0da0df6fa4422e723086a2cd4e087616f09a626a07a9a999ede53b'
PACKAGE_HASH = 'a34f673d05d816128ae2b6c9c458a8f83baca234889d22e55e0331f18560b0ef'
CONTENT_HASH = '3f92791519e1f9422fef11bb5c9177db4d9d83e628ea5f5cba0ec684b9530d5f'
REQUEST_ID = f.FreezeRequestId('S015', 'S015-C9700-v1-approved-20261025')


def read(path):
    return json.loads(path.read_bytes())


def save_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        assert path.read_bytes() == raw, f'Existing evidence differs: {path}'
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'execute'))
    args = parser.parse_args()
    context = RepositoryContext.discover(ROOT)
    report = f.CandidateInspectionReport.from_dict(read(HOME / 'others/inspection_report.json'))
    assert report == f.CandidateInspectionReport.from_dict(read(report.reference.resolve(ROOT)))
    assert report.sha256 == REPORT_HASH and report.status is f.InspectionStatus.PASS
    assert report.plan.sha256 == PLAN_HASH and report.plan.version == 'v1'
    assert report.origin.candidate.candidate_id == 'C9700' and report.origin.content_sha256 == CONTENT_HASH
    assert report.release.release_sha256 == RELEASE_HASH and report.release.package_sha256 == PACKAGE_HASH
    for item in report.release.files:
        assert sha256(item.source.resolve(ROOT).read_bytes()).hexdigest() == item.source.sha256
    assert b'"limit_parameter": 0.01' in (HOME / 'src/strategy_runtime/strategies/price_process.py').read_bytes()
    existing = get_freeze_result(context, REQUEST_ID)
    assert existing.status in {f.FreezeStatus.NOT_FOUND, f.FreezeStatus.COMMITTED}, existing
    if existing.status is f.FreezeStatus.NOT_FOUND:
        assert not (context.strategy_root / 'S015/versions/v1.json').exists()
    if args.mode == 'check':
        print(json.dumps({'status': 'READY', 'inspection': REPORT_HASH, 'plan': PLAN_HASH,
                          'release': RELEASE_HASH, 'transaction': existing.status.value}))
        return
    approval_source = OUT / 'user_approval.json'
    save_once(approval_source, {
        'source': 'Direct user message in the current conversation',
        'date': '2026-10-25',
        'message': '只要参与了模型训练的过程就好，同意冻结C9700为S015-v1',
        'scope': 'Freeze the previously inspected exact C9700 package as S015-v1; no deployment or production operations.',
        'clarification': 'The fixed 1% buy premium participated in all execution and performance calculations; it was not searched or perturbed.',
        'content_sha256': CONTENT_HASH, 'inspection_sha256': REPORT_HASH,
        'plan_sha256': PLAN_HASH, 'release_sha256': RELEASE_HASH, 'package_sha256': PACKAGE_HASH,
    })
    approval = record_research_decision(context, f.ResearchDecision(
        'S015-approve-C9700-v1-20261025', 'S015', f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, CONTENT_HASH, report.reference, PLAN_HASH, 'v1'),
        CandidateEvidence(approval_source.relative_to(ROOT).as_posix(), sha256(approval_source.read_bytes()).hexdigest()),
        '用户在确认1%固定限价参与历史执行和评价但未搜索或扰动后，明确批准按既有精确计划冻结C9700为S015-v1。',
    ))
    save_once(OUT / 'approval_ref.json', approval.to_dict())
    request = f.FreezeCandidateRequest(REQUEST_ID, report.reference, approval)
    save_once(OUT / 'request.json', request.to_dict())
    receipt = freeze_candidate(context, request)
    save_once(OUT / 'receipt.json', receipt.to_dict())
    assert receipt.status is f.FreezeStatus.COMMITTED, receipt
    assert get_freeze_result(context, REQUEST_ID) == receipt
    version = StrategyRegistry(context.strategy_root).get_version('S015', 'v1')
    assert version.release_hash == RELEASE_HASH
    assert receipt.version.package_hash == PACKAGE_HASH
    target = context.strategy_root / 'S015/releases/v1'
    assert read(context.strategy_root / 'S015/versions/v1.json') == read(report.release.version_record.resolve(ROOT))
    assert (target / 'release_manifest.json').read_bytes() == report.release.manifest.resolve(ROOT).read_bytes()
    files = []
    for item in report.release.files:
        frozen = target / item.path
        assert frozen.read_bytes() == item.source.resolve(ROOT).read_bytes(), item.path
        files.append({'path': frozen.relative_to(ROOT).as_posix(), 'sha256': sha256(frozen.read_bytes()).hexdigest()})
    save_once(OUT / 'verification.json', {'status': 'PASS', 'freeze_status': receipt.status.value,
        'query_matches_receipt': True, 'version_and_manifest_match_inspected': True, 'files': files,
        'fixed_entry_premium': 0.01, 'deployment': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED'})
    text = '\n'.join([
        '# S015-v1：C9700获批冻结完成', '',
        'Status: COMPLETED', '',
        '用户明确批准冻结C9700为S015-v1。公共冻结事务已COMMITTED，并经get_freeze_result复核。',
        '版本记录、manifest及全部发布文件与阶段五受检包逐字节一致；金融逻辑、全部参数和1%限价不变。',
        '1%限价参与全部历史成交、仓位与收益评价，但未参与阶段三搜索及阶段四扰动；冻结不增加该参数的稳健性证据。', '',
        f'- 候选内容：`{CONTENT_HASH}`', f'- 检验报告：`{REPORT_HASH}`',
        f'- 冻结计划：`{PLAN_HASH}`', f'- 发布版本：`{RELEASE_HASH}`', f'- 发布包：`{PACKAGE_HASH}`', '',
        '选择数据截止2026-10-21；前瞻起点元数据为2026-10-26，不表示该日期已启用账户。',
        '初始资格为RESEARCH。未授予PTE资格、部署、创建账户或执行任何生产变更。',
        '既有阶段四及阶段五风险、已见数据和检验覆盖边界保持；原INSPECTION/4及EX082原报告保留。', '',
        '下一步由用户决定是否申请模拟交易资格并开展部署准备；实际生产生效另行授权。',
    ]) + '\n'
    local_report = HOME / 'freeze_report.md'
    if local_report.exists():
        assert local_report.read_text(encoding='utf-8') == text
    else:
        local_report.write_text(text, encoding='utf-8')
    assert not (ROOT / 'research/S015/deliveries/INSPECTION/5').exists(), 'Do not replace published delivery'
    assembled = assemble_delivery(context,
        d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.INSPECTION, 5),
        d.DeliveryContent(d.CandidateInspectionDelivery(report.reference, (report.selection, approval), receipt, ()),
                          d.DeliveryStatus.COMPLETE, (), (), report=text),
        resources=ExecutionResources(1, 1, 13))
    save_once(OUT / 'publication_receipt.json', assembled.to_dict())
    assert assembled.validation.status is d.ValidationStatus.PASS, assembled.validation
    assert assembled.validation.scope is d.DeliveryValidationScope.FULL
    print(json.dumps({'freeze': receipt.status.value, 'release': RELEASE_HASH,
                      'file_count': len(files), 'delivery': assembled.receipt.reference.to_dict(),
                      'validation': 'FULL_PASS', 'production': 'NOT_TOUCHED'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
