"""Audit and publish completed same-version repository upgrades without trading."""
from hashlib import sha256
import json
from pathlib import Path

from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRelease, StrategyRuntime, load_strategy_deployment
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_release_package
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
REFERENCES = ('S001-v1', 'S001-v2', 'S002-v1', 'S003-v1', 'S007-v1', 'S011-v1')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def write_once(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('immutable publication differs')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def main():
    output = EX / 'others/inplace_upgrade_publication.json'
    if output.exists():
        raise FileExistsError('completed publication already exists')
    context = RepositoryContext.discover(ROOT)
    registry = StrategyRegistry(context.strategy_root)
    baseline = read(ROOT / '.tmp/srt_window_contract_review_baseline.json')
    rows, archives = [], {}
    for reference in REFERENCES:
        applied = read(EX / 'others/inplace_upgrade/applied' / f'{reference}.json')
        assert applied['status'] == 'COMMITTED'
        family, number = reference.split('-')
        archive = ROOT / applied['archive_path']
        archives[reference] = archive
        old = read(archive / 'strategies' / family / 'versions' / f'{number}.json')
        new = registry.get_version(family, number)
        current = new.to_dict()
        assert {key: value for key, value in old.items() if key not in ('strategy_payload', 'release_hash')} == {
            key: value for key, value in current.items() if key not in ('strategy_payload', 'release_hash')}
        assert (new.version, new.release_id) == (number, reference)
        assert new.strategy_payload['runtime']['contract_version'] == 2
        assert new.strategy_payload['decision_feedback'] == 'MARKET_INTENT'
        report_dir = EX / 'others/formal_migration_inspection/inplace'
        if reference == 'S011-v1':
            report_dir = report_dir / 'attempt2'
        inspection = read(report_dir / f'{reference}.json')
        report = validate_inspection(ROOT, f.ResearchEvidenceRef.from_dict(inspection['inspection_reference']))
        assert report.status is f.InspectionStatus.PASS and len(report.checks) == 8
        manifest, _, _ = validate_release_package(context, reference)
        installed = load_strategy_deployment(context.strategy_root, reference)
        definition = StrategyRuntime().describe(StrategyRelease.from_mapping(current),
            source_root=installed.source_root, runtime_binding=installed.binding)
        assert definition.release_hash == new.release_hash == applied['migrated']['release_hash']
        assert manifest['package_hash'] == installed.package_hash == applied['migrated']['package_hash']
        assert registry.current_qualification(family, number).value == 'RESEARCH'
        registered = read(EX / 'others/formal_migration_registration' / f'{reference}.json')
        rows.append({'reference': reference, 'candidate': registered['registration']['key'],
            'original': applied['original'], 'migrated': applied['migrated'],
            'archive': applied['archive_path'], 'technical_inspection': inspection['inspection_reference'],
            'inspection_status': report.status.value, 'checks_passed': len(report.checks),
            'original_qualification': next(item['qualification'] for item in read(
                ROOT / '.tmp/window-contract-governance-inventory.json')['releases'] if item['reference'] == reference),
            'current_qualification': 'RESEARCH', 'version_and_provenance_unchanged': True})
    checked, archived = 0, 0
    for name, expected in baseline['hashes'].items():
        path = Path(name)
        if path.parts[1] == 'deployments':
            reference = path.stem
        elif len(path.parts) > 2 and path.parts[2] == 'versions':
            reference = f'{path.parts[1]}-{path.stem}'
        elif len(path.parts) > 3 and path.parts[2] == 'releases':
            reference = f'{path.parts[1]}-{path.parts[3]}'
        else:
            assert digest(ROOT / path) == expected, name
            checked += 1
            continue
        assert digest(archives[reference] / path) == expected, name
        archived += 1
        checked += 1
    assert checked == 70
    dependency = read(ROOT / '.tmp/window-contract-in-place-dependencies.json')
    for item in dependency['references']:
        for journal in item['matching_journals']:
            for name, expected in journal['request_files'].items():
                assert digest(ROOT / name) == expected
    review = read(EX / 'others/inplace_upgrade/staged_independent_review.json')
    assert review['status'] == 'PASS', review
    summary = {'status': 'COMPLETED_LOCAL_SAME_VERSION_UPGRADE', 'references': rows,
        'original_baseline_files_preserved_byte_exact': checked,
        'original_release_files_archived_byte_exact': archived, 'new_versions_created': 0,
        'formal_candidates_registered': 6, 'formal_inspections_passed': 6,
        'formal_checks_passed': 48, 'production_writes': 0, 'pte_accounts_changed': 0,
        'paper_qualification_events_added': 0,
        'qualification_policy': 'Historical approvals remain bound to old hashes. All new hashes are RESEARCH; subsequent PTE replacement requires explicit eligibility approval and production confirmation.',
        's003_execution_boundary': 'Same actual market rules: old/new strategy exact. Legacy without rules accepted BUY9.254 above true upper9.090 on2026-07-15; revised execution rejects it, 37 versus39 fills. This is an execution correction, not alpha.',
        'historical_journal_boundary': 'S011 legacy journal was UNKNOWN before this work; original bytes retained. This task does not repair that earlier mismatch.'}
    summary_path = EX / 'others/inplace_upgrade_summary.json'
    write_once(summary_path, encoded(summary))
    table = '\n'.join(f'| {row["reference"]} | {row["candidate"]["candidate_id"]} | 不变 | 8/8 PASS | RESEARCH |'
                      for row in rows)
    report = f'''# 同版本原地升级交付

六个现有策略已在仓库内完成强类型历史窗口契约升级，**版本号全部不变**。未创建 v2/v3/v4 替代版本；先前新增版本方案已撤销，其技术检查及失败记录保留。

| 策略 | 迁移候选 | 版本号 | 正式技术检查 | 新内容哈希资格 |
| --- | --- | --- | --- | --- |
{table}

原版本的参数、指标、交易意图、研究来源、parent、选择截止日和前瞻起点保持。源码、运行绑定、发布清单、版本内容哈希和仓库内部署回执同步重签。70项原基线逐字节核验，其中{archived}份原发布、版本和部署文件归档于各自 `strategies/revisions/<策略版本>/<旧哈希>/`，其余治理原件保持。原批准与历史账户证据不改写。

六份正式账户均经 schema7 发布；六份同版本技术报告各八项检查通过。原地升级入口先校验暂存包和明确旧身份，写锁内比较后替换，失败恢复原文件；显式旧哈希仍可通过已提交归档验证历史报告。具体哈希、报告引用和归档路径见 [机器清单](inplace_upgrade_summary.json)。

S003 必须单独说明：2026-07-15 真实涨停价9.090，策略原买入限价9.254越界。旧无规则回测接受了它，真实规则正确拒绝，成交从39笔变37笔，账户结果随之变化。旧策略与升级策略在相同真实规则下五本账完全相同；不能据此声称旧无规则执行器经济等价。见 [差异证据](s003_market_rule_execution_difference.json)。

S007 的独立审计已修复浮点减一个报价单位后的规范问题：合法2.01通过，2.009和2.011拒绝，零容差未放宽。旧失败及本轮S011准备阶段的终态识别失败均保留。

PTE 同版本替换的六项聚焦测试通过，包含非零持仓、现金和cycle_target保留，以及未完订单阻断和失败回滚。**生产PTE尚未替换、账户绑定未改变、服务未重启。** 新哈希按现有精确身份规则处于RESEARCH；后续应针对这些精确哈希确认模拟交易资格，再按受控流程替换PTE。S002原先也为RESEARCH，不提升其资格。

S011早前冻结journal在本轮开始前已为UNKNOWN，本轮保存原字节并明确区分已终结历史事务与待处理事务，未追改历史记录。此次工程验证不构成新的收益优势或未见样本验收；未运行仓库全量回归。
'''
    report_path = EX / 'others/inplace_upgrade_report.md'
    write_once(report_path, report.encode('utf-8'))
    research = create_research_context(context, ResearchBatchRef('S014'))
    owner = ExperimentRef('S014', EX.name)
    artifacts = {}

    def publish(path):
        data = path.read_bytes()
        if not data:
            return {'empty_file': True, 'sha256': sha256(data).hexdigest()}
        suffix = path.suffix.removeprefix('.') or 'json'
        media = {'md': 'text/markdown', 'py': 'text/x-python', 'csv': 'text/csv', 'log': 'text/plain'}.get(suffix, 'application/json')
        ref = publish_evidence(research, MaterialEvidenceWrite(owner,
            'inplace-' + sha256(path.relative_to(ROOT).as_posix().encode()).hexdigest()[:24], data, media, suffix))
        assert ref.resolve(ROOT).read_bytes() == data
        return ref.to_dict()

    selected_paths = [summary_path, report_path, EX / 'others/version_bump_plan_withdrawal.json',
        EX / 'protocols/inplace_migration_authorization.json',
        EX / 'others/s003_market_rule_execution_difference.json',
        EX / 'others/s003_market_rule_audit_chain_review.json',
        ROOT / '.tmp/window-contract-in-place-dependencies.json',
        ROOT / '.tmp/inspect_formal_migrations.version-bump.executed.py']
    selected_paths.extend(ROOT / '.tmp' / name for name in (
        'inplace-upgrade-focused-tests.log', 'inplace-upgrade-postapply-tests.log',
        'inplace-frozen-import-tests.log', 'inplace-upgrade-apply.log',
        'inplace-upgrade-publish.log'))
    selected_paths.extend(path for path in (ROOT / '.tmp/s003-overlay-market-rules-real-v3').rglob('*')
                          if path.is_file() and path.suffix in ('.json', '.csv'))
    for folder in ('others/formal_migration_registration', 'others/formal_migration_inspection', 'others/inplace_upgrade'):
        selected_paths.extend(path for path in (EX / folder).rglob('*') if path.is_file())
    for archive in archives.values():
        selected_paths.extend(path for path in archive.rglob('*') if path.is_file())
    selected_paths.extend((EX / 'src').glob('*.py'))
    for path in sorted(set(selected_paths)):
        artifacts[path.relative_to(ROOT).as_posix()] = publish(path)
    manifest = {'status': 'PUBLISHED', 'summary': summary, 'artifacts': artifacts}
    manifest_ref = publish_evidence(research, MaterialEvidenceWrite(owner,
        'inplace-upgrade-artifact-manifest', encoded(manifest), 'application/json', 'json'))
    write_once(output, encoded({'status': 'PUBLISHED',
        'report': artifacts[report_path.relative_to(ROOT).as_posix()],
        'summary': artifacts[summary_path.relative_to(ROOT).as_posix()],
        'manifest': manifest_ref.to_dict(), 'artifact_count': len(artifacts)}))
    print(json.dumps({'status': 'PUBLISHED', 'versions_unchanged': 6,
                      'preserved_baseline_files': checked, 'archived_release_files': archived,
                      'artifacts': len(artifacts)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
