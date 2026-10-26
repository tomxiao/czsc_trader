"""Verify installed identities and publish the seven RSCH upgrade conclusions."""
from hashlib import sha256
import json

import complete_upgrades as c
import upgrade_batch as v
from czsc_trader.application import publish_evidence, validate_release_package
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite, MaterialEvidenceWrite,
)
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyRuntime, StrategyRelease, load_strategy_deployment


SEMANTICS = {
    'S001-v1': 'others/S001-v1/audit_replay_v2/semantics.json',
    'S001-v2': 'others/S001-v2/audit_replay_v2/semantics.json',
    'S002-v1': 'others/S002-v1-observation-semantics.json',
    'S003-v1': 'others/explanation_semantics.json',
    'S007-v1': 'others/explanation_semantics.json',
    'S011-v1': 'others/observation_semantics_v2.json',
    'S015-v1': 'others/observation_semantics_v2.json',
}


def material(ctx, ex, path):
    return publish_evidence(ctx, MaterialEvidenceWrite(ex, path.stem, path.read_bytes(),
        'application/json' if path.suffix == '.json' else 'text/csv', path.suffix[1:]))


def verify(ref):
    item, ex, ctx, home, out = c.context(ref)
    child, original = c.candidate(ref)
    family, version = ref.split('-')
    stored = StrategyRegistry(ctx.repository.strategy_root).get_version(family, version)
    current = stored.to_dict()
    for field, value in item['original'].items():
        if field not in ('strategy_payload', 'release_hash'):
            assert current[field] == value, (ref, field)
    assert current['strategy_payload'] == json.loads(json.dumps(dict(child.payload), default=dict))
    manifest, binding, source = validate_release_package(ctx.repository, ref)
    deployment = load_strategy_deployment(ctx.repository.strategy_root, ref)
    assert deployment.release_hash == stored.release_hash
    assert deployment.package_hash == manifest['package_hash']
    for name in binding['source_files']:
        assert (source / name).read_bytes() == (child.source_root / name).read_bytes()
    definition = StrategyRuntime(ctx.repository.strategy_root).describe(StrategyRelease.from_mapping(current))
    assert definition.observation.signal_panel.explanation is not None
    assert definition.observation.sha256 == binding['observation_sha256']
    assert StrategyRegistry(ctx.repository.strategy_root).current_qualification(family, version).value == 'RESEARCH'
    archive = ctx.repository.strategy_root / 'revisions' / ref / original.release_hash
    receipt = v.read(archive / 'upgrade_receipt.json')
    assert receipt['status'] == 'COMMITTED' and receipt['production_writes'] == 0
    assert receipt['migrated']['release_hash'] == stored.release_hash
    assert receipt['migrated']['package_hash'] == manifest['package_hash']
    snapshot = v.read(archive / 'snapshot.json')
    actual = {p.relative_to(archive).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in archive.rglob('*') if p.is_file()}
    actual.pop('snapshot.json')
    actual.pop('upgrade_receipt.json')
    assert actual == snapshot['files']
    assert actual['upgrade_plan.json'] == receipt['plan_sha256']
    case = out / 'published_equivalence'
    result = v.read(case / 'result.json')
    assert result['status'] == 'PASS'
    assert result['old_release_hash'] == original.release_hash
    assert result['new_release_hash'] == stored.release_hash
    assert result['new_package_hash'] == manifest['package_hash']
    refs = []
    for artifact in result['artifacts']:
        path = case / artifact['path']
        assert sha256(path.read_bytes()).hexdigest() == artifact['sha256']
        refs.append(material(ctx, ex, path))
    refs += [material(ctx, ex, case / 'result.json'), material(ctx, ex, home / SEMANTICS[ref])]
    refs.append(c.publish(ctx, ex, ref + '_committed_upgrade_receipt', receipt))
    mode = result['modes']['WINDOW']
    days = next(x['rows'] for x in mode['checks'] if x['ledger'] == 'account_daily')
    row = {'reference': ref, 'status': 'COMMITTED', 'equivalence': 'PASS',
        'window': result['window'], 'account_sessions': days, 'fills': mode['fills'],
        'old_release_hash': original.release_hash, 'new_release_hash': stored.release_hash,
        'package_hash': manifest['package_hash'], 'source_hash': binding['implementation_sha256'],
        'selection_data_cutoff': stored.selection_data_cutoff, 'forward_start': stored.forward_start,
        'qualification': 'RESEARCH', 'production_writes': 0,
        'archive': archive.relative_to(v.ROOT).as_posix(),
        'equivalence_result': (case / 'result.json').relative_to(v.ROOT).as_posix()}
    v.save(out / 'final_verification.json', row)
    v.save(out / 'published_equivalence_refs.json', [x.to_dict() for x in refs])
    return row, refs


def main():
    rows, groups = [], {}
    for ref in v.ITEMS:
        row, refs = verify(ref)
        rows.append(row)
        family = ref.split('-')[0]
        groups.setdefault(family, {'rows': [], 'refs': []})
        groups[family]['rows'].append(row)
        groups[family]['refs'].extend(refs)
        print(ref, 'FINAL_IDENTITY_ARCHIVE_EQUIVALENCE_PASS', flush=True)
    summary = {'status': 'COMPLETED', 'versions': rows, 'new_market_data': False,
               'search_trials': 0, 'production_writes': 0,
               'responsibility': 'RSCH verification; TDR publication audit; PTE admission separate'}
    v.save(v.ROOT / 'research/S015/experiments/EX085_20261026/others/batch_summary.json', summary)
    for family, group in groups.items():
        ref = group['rows'][0]['reference']
        _, ex, ctx, home, _ = c.context(ref)
        lines = ['# 冻结策略信号解释原地升级', '', 'Status: COMPLETED', '',
            '已按用户授权完成本地发布包升级；由RSCH验证交易等价与解释语义，TDR记录升级审计。', '',
            '| 版本 | 原认证数据窗口 | 账户交易日 | 成交记录 | 最终发布包等价 |',
            '| --- | --- | ---: | ---: | --- |']
        report_rows = rows if family == 'S015' else group['rows']
        for row in report_rows:
            lines.append(f"| {row['reference']} | {row['window']['start']}～{row['window']['end']} | "
                         f"{row['account_sessions']} | {row['fills']} | PASS |")
        lines += ['', '## 验证与结果', '',
            '- 直接比较原归档发布包与最终安装发布包。CONTINUOUS与WINDOW两种历史模式下，交易信号、决策、订单、成交、账户和交易账本零容差一致；原series/facts保持一致。',
            '- 只归一化发布身份及面板明确声明的观察字段。相同真实历史输入、初始资金10万元及原费用、执行规则；未接新数据、未做参数搜索。',
            '- 信号解释已验证代表状态、阈值边界及不可用情形。该验证说明展示与被检验分支一致，不代表新增策略收益证据。',
            '- 版本号、父版本、选型截止日、前瞻起点及交易参数保持；旧包完整归档，新源码、发布清单、运行绑定和本地部署回执身份一致。', '',
            '## 证据与边界', '',
            '- 各版本others目录内的final_verification.json记录最终身份；published_equivalence/result.json及published_equivalence_refs.json保存最终包的直接回放结论、原始账本和正式证据引用。',
            '- 早期源码验证及技术检验阻塞材料保留。新审计API不要求技术检验PASS，但本次独立完成了RSCH等价性验证；未将原失败报告改写为通过。',
            '- 新身份资格为RESEARCH；本次未授予模拟交易资格、改绑PTE账户或写入生产环境。历史窗口内等价不替代未见市场或生产渠道验证。', '',
            '下一步：按单独授权为精确新发布身份准备PTE准入、账户改绑和生产发布。', '']
        if family == 'S015':
            lines += ['全批次摘要见others/batch_summary.json；其他批次的正式结论在各自本次实验report.md。', '']
            group['refs'].append(c.publish(ctx, ex, 'all_frozen_upgrade_summary', summary))
        (home / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
        previous = EvidenceRef.from_dict(v.read(home / 'report_ref.json')) if (home / 'report_ref.json').exists() else None
        publish_evidence(ctx, ExperimentReportWrite(ex, sha256((home / 'report.md').read_bytes()).hexdigest(),
            ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(group['refs'])), previous))
        print(family, 'REPORT_PUBLISHED', flush=True)


if __name__ == '__main__':
    main()
