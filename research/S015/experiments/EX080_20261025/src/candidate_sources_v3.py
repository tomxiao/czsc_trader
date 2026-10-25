"""Publish a candidate-source revision after exact center-request replays.

prepare: authenticate unchanged economic facts, write a draft report and panel.
check: bind the reviewed report/materials and print an input digest.
publish: explicitly publish CANDIDATES/10, retaining CANDIDATES/9 as predecessor.
No strategy accounts, registration, selection or platform code are changed.
"""
from __future__ import annotations
# ruff: noqa: E402 -- native thread limits precede numerical imports

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from stage4 import ROOT, HOME, OUT, EX, BATCH, ctx, read, save, assert_protocol, predecessor
from czsc_trader.application import RepositoryContext, publish_evidence, assemble_delivery
from czsc_trader.research_tools import EvidenceRef, ExecutionResources, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import research_models as m

WORK = HOME / 'candidate_sources_v3'
SOURCE_HASH = '31272c048a128a7f0bbbadb784baa500d45120ed215ac738c59044e6eef5698b'
MIME = {'.py': 'text/x-python', '.json': 'application/json', '.md': 'text/markdown'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def original():
    ref, raw = predecessor('CANDIDATES', 9, SOURCE_HASH)
    payload = d.CandidateSet.from_dict(raw)
    require(len(payload.candidates) == 39 and len(payload.handoff) == 29,
            'Original registered and handoff scope changed')
    return ref, payload


def account(raw_ref):
    ref = EvidenceRef.from_dict(raw_ref)
    require(ref.experiment.strategy_id == 'S015', 'Account outside approved batch')
    raw = read(ref.resolve(ROOT))
    validate_evaluation_evidence(raw)
    return ref, raw


def revised_panel(prior, rows):
    replays = {x['candidate_id']: x for x in rows}
    require(len(replays) == len(rows) == 29
            and set(replays) == {x.candidate_id for x in prior.handoff}, 'Replay scope changed')
    entries = []
    for entry in prior.candidates:
        cid = entry.identity.key.candidate_id
        if cid not in replays:
            entries.append(entry)
            continue
        row = replays[cid]
        old = EvidenceRef.from_dict(row['old_evidence'])
        new = EvidenceRef.from_dict(row['evidence'])
        require(sum(x.evidence == old for x in entry.evaluations) == 1,
                f'Original center account not unique: {cid}')
        require(row['content_sha256'] == entry.identity.content_sha256,
                f'Candidate content changed: {cid}')
        # Keep any existing pressure references. The old two-window standard
        # account is retained as supporting evidence, not a current evaluation.
        evaluations = tuple(d.EvaluationEvidenceRef(new, (row['evaluation_id'],))
                            if x.evidence == old else x for x in entry.evaluations)
        entries.append(replace(entry, evaluations=evaluations))
    panel = replace(prior, candidates=tuple(entries))
    require(replace(panel, candidates=prior.candidates) == prior,
            'Only candidate evaluation-source fields may change')
    require(all(replace(new, evaluations=old.evaluations) == old
                for old, new in zip(prior.candidates, panel.candidates, strict=True)),
            'Candidate identity, hypothesis or judgment changed')
    return panel


def prepare():
    assert_protocol()
    require(not WORK.exists(), 'Preserve prepared candidate revision; review it in place')
    previous, prior = original()
    replay_document = read(OUT / 'center_replays.json')
    require(replay_document['status'] == 'PASS' and replay_document['new_accounts'] == 29,
            'Completed exact-request center replays required')
    rows = replay_document['rows']
    panel = revised_panel(prior, rows)
    common = {x['candidate_id']: x for x in read(OUT / 'common_415_checks.json')}
    plans = {x['candidate_id']: x['plan'] for x in read(OUT / 'plan_refs.json')}
    checks = []
    for number, row in enumerate(rows, 1):
        cid = row['candidate_id']
        old_ref, old = account(row['old_evidence'])
        new_ref, new = account(row['evidence'])
        old_full = next(m.AssessmentEvidence.from_dict(x) for x in old['assessment_evidence']
                        if x['window_id'] == 'full')
        old_common = next(m.AssessmentEvidence.from_dict(x) for x in old['assessment_evidence']
                          if x['window_id'] == 's011_common')
        require(len(new['runs']) == len(new['assessment_evidence']) == 1,
                'New center source must have exactly one standard full-window account')
        current = m.AssessmentEvidence.from_dict(new['assessment_evidence'][0])
        require(current.window_id == 'full' and current.scenario_id == 'standard'
                and current.parent is None and current.parameter_point is None,
                'Center source cannot be a pressure account or parameter point')
        require(current.candidate == old_full.candidate
                and current.candidate.content_sha256 == row['content_sha256'], 'Center identity changed')
        require(new['request_hash'] == row['request_hash'] == plans[cid]['center_request_sha256']
                and new['result_hash'] == row['result_hash'], 'Exact plan request was not replayed')
        old_run = next(x for x in old['runs'] if x['window_id'] == 'full')
        new_run, = new['runs']
        require(old_run['ledgers'] == new_run['ledgers'] and old_run['signals'] == new_run['signals'],
                'Economic ledgers or signals changed')
        ignored = {'experiment_id', 'attempt_id', 'request_sha256', 'result_sha256', 'evaluation_id'}
        require({k: v for k, v in current.to_dict().items() if k not in ignored}
                == {k: v for k, v in old_full.to_dict().items() if k not in ignored},
                'Economic projection changed')
        require(old_common.evaluation_id == common[cid]['evaluation_id']
                and common[cid]['passed'] and len(old_common.account) == 415,
                'Historical common-window source or check changed')
        checks.append({'candidate_id': cid, 'content_sha256': row['content_sha256'],
                       'old_standard_and_415': old_ref.to_dict(), 'new_standard': new_ref.to_dict(),
                       'new_evaluation_id': current.evaluation_id,
                       'new_request_sha256': current.request_sha256,
                       'common_415_evaluation_id': old_common.evaluation_id,
                       'common_415_check': common[cid], 'economic_projection_equal': True,
                       'five_ledgers_and_signals_equal': True})
        print('CANDIDATE_SOURCE_CHECK', number, 29, cid, flush=True)
    save(WORK / 'panel.json', panel.to_dict())
    inputs = (OUT / 'center_replays.json', OUT / 'common_415_checks.json', OUT / 'plan_refs.json')
    save(WORK / 'source_checks.json', {'status': 'PASS', 'predecessor': previous.to_dict(),
         'candidate_count': 39, 'handoff_count': 29, 'source_rebindings': 29,
         'new_accounts': 0, 'new_configurations': 0, 'candidate_content_changed': False,
         'selection_history_changed': False, 'checks': checks,
         'source_inputs': {p.relative_to(ROOT).as_posix(): file_hash(p) for p in inputs}})
    report = '''# S015 候选交付修订：阶段四中心请求来源对齐

本修订已完成候选评价来源的技术对齐。39个已登记候选、29个阶段四交接对象、全部参数与实现身份、阶段三判断及9项搜索声明均保持原样；没有新增策略、搜索、账户或资格结论。

## 修订原因与范围

阶段四参数计划绑定了EX080单窗口full请求。29个确切请求复算与历史双窗口账户的full部分，在信号、五张经济账本和非来源字段上完全一致，但请求身份不同。原CANDIDATES/9继续把历史双窗口源作为当前评价来源，会与阶段四所需的新请求来源发生冲突。

本修订仅将29个中心在`CandidateEntry.evaluations`中的标准双窗口源替换为真实EX080单窗口full复算源；已有关联的费用压力源以及其余10个候选评价完全保留。候选内容、handoff顺序、假设、判断、搜索声明和阶段三结论均未改变。

## 415日证据仍完整保留

原双窗口账户没有拆分、重签或改写，其415日比较原件继续作为本修订的显式支持证据，并由CANDIDATES/9前驱保留。29项415日双优结果及精确评价身份见[来源对照](source_checks.json)和[既有415日检查](../others/common_415_checks.json)。

标准旧源不再放入当前`CandidateEntry.evaluations`：平台读取该字段时会导入源文件中的全部窗口，即使指定415日评价ID，也会同时导入旧full请求。支持证据保存是明确的角色调整，不是删除415日结果或降低验收要求。

## 验证与边界

- 逐项认证29组新旧公开账户，核对候选内容身份、既有参数计划请求、信号、五表经济账本和完整经济投影。
- 39候选身份与29交接身份完全相同；只改变29项标准评价引用。新复算已经计入EX080的29个中心账户，本修订不重复计为新试验。
- 415日来源及门槛结果原样保存；已见样本、选择历史和统计局限不改变。
- 本修订不宣布阶段四完成、选型或冻结。阶段四资格与建议以随后成功发布的ASSESSMENT交付为准。

证据：[CANDIDATES/9历史报告](../../../deliveries/CANDIDATES/9/report.md)、[确切请求复算](../others/center_replays.json)、[来源核对](source_checks.json)。下一步由阶段四使用本修订作为候选来源，继续公开FULL校验；阶段五及冻结仍须单独批准。
'''
    (WORK / 'report.md').write_text(report, encoding='utf-8')
    print('CANDIDATES10_DRAFT_READY', flush=True)


def reviewed_inputs():
    assert_protocol()
    previous, prior = original()
    checks = read(WORK / 'source_checks.json')
    require(checks['status'] == 'PASS' and checks['predecessor'] == previous.to_dict(),
            'Completed source verification differs')
    for path, expected in checks['source_inputs'].items():
        require(file_hash(ROOT / path) == expected, 'Authenticated source inputs changed')
    rows = read(OUT / 'center_replays.json')['rows']
    panel = d.CandidateSet.from_dict(read(WORK / 'panel.json'))
    require(panel == revised_panel(prior, rows), 'Prepared candidate source mapping changed')
    paths = (Path(__file__), WORK / 'panel.json', WORK / 'source_checks.json', WORK / 'report.md',
             OUT / 'center_replays.json', OUT / 'common_415_checks.json')
    manifest = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths}
    digest = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    report = (WORK / 'report.md').read_text(encoding='utf-8')
    destination = ROOT / 'research/S015/deliveries/CANDIDATES/10'

    def rebase(match):
        target = match.group(1)
        if '://' in target or target.startswith('#'):
            return match.group(0)
        resolved = (WORK / target).resolve()
        require(resolved.is_relative_to(ROOT) and resolved.exists(), f'Invalid report link: {target}')
        return '](' + Path(os.path.relpath(resolved, destination)).as_posix() + ')'

    report = re.sub(r'\]\(([^)]+)\)', rebase, report)
    refs, writes = [], []
    for path in paths:
        raw, suffix = path.read_bytes(), path.suffix
        relative = path.relative_to(ROOT).as_posix()
        require(sha256(raw).hexdigest() == manifest[relative], 'Reviewed material changed')
        ref = EvidenceRef(EX, f'{manifest[relative]}{suffix}', manifest[relative], MIME[suffix], path.stem)
        refs.append(ref)
        writes.append((relative, MaterialEvidenceWrite(EX, path.stem, raw, MIME[suffix], suffix[1:]), ref))
    # Supporting evidence retains 415-day original accounts outside the current
    # evaluation role. The original full+415 source also remains in predecessor C9.
    refs.extend(EvidenceRef.from_dict(row['old_evidence']) for row in rows)
    refs = tuple(dict.fromkeys(refs))
    content = d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=refs)
    definition = d.DeliveryDefinition(BATCH, d.DeliveryStage.CANDIDATES, 10, (previous,))
    return manifest, digest, writes, definition, content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'check', 'publish'))
    parser.add_argument('--reviewed-input-sha')
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare()
        return
    manifest, digest, writes, definition, content = reviewed_inputs()
    if args.mode == 'check':
        print(json.dumps({'status': 'CANDIDATES10_READY_FOR_REVIEW', 'input_sha256': digest,
                          'candidates': 39, 'handoff': 29, 'standard_source_rebindings': 29,
                          'new_accounts': 0, 'new_configurations': 0}, ensure_ascii=False), flush=True)
        return
    require(args.reviewed_input_sha == digest, 'Review digest missing or inputs changed')
    receipt_path = WORK / 'publication_receipt.json'
    require(not receipt_path.exists() and not (ROOT / 'research/S015/deliveries/CANDIDATES/10').exists(),
            'Preserve existing candidate delivery and receipt')
    context = ctx(8)
    for relative, write, expected in writes:
        require(file_hash(ROOT / relative) == manifest[relative], 'Reviewed material changed')
        require(publish_evidence(context, write) == expected, 'Published material identity differs')

    last = [None, 0.]

    def progress(event):
        if event.phase != last[0] or event.elapsed_seconds - last[1] >= 30 or event.completed == event.total:
            print('CANDIDATES10_VALIDATION', event.phase.value, event.completed, event.total, flush=True)
            last[:] = [event.phase, event.elapsed_seconds]

    result = assemble_delivery(RepositoryContext.discover(ROOT), definition, content,
                               resources=ExecutionResources(8, 1, 13), on_progress=progress)
    require(result.validation.status is d.ValidationStatus.PASS
            and result.validation.scope is d.DeliveryValidationScope.FULL, 'Candidate FULL validation failed')
    save(receipt_path, {'status': 'CANDIDATES10_FULL_PASS', 'input_sha256': digest,
                        'assembly': result.to_dict(), 'new_accounts': 0, 'new_configurations': 0})
    print('CANDIDATES10_FULL_PASS', result.receipt.reference.content_sha256, flush=True)


if __name__ == '__main__':
    main()
