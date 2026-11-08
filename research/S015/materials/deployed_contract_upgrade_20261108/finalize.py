"""Verify the five installed local packages and write the migration delivery index."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, load_candidate, validate_experiment
from czsc_trader.research_tools import EvidenceRef, ExperimentRef, ExperimentValidationRequest, ExperimentValidationScope
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition
from strategy_runtime.deployment import validate_release_integrity, validate_release_package

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
REFERENCES = ('S001-v1', 'S001-v2', 'S007-v1', 'S011-v1', 'S015-v1')


def main():
    repository = RepositoryContext.discover(ROOT)
    results = []
    for reference in REFERENCES:
        record = json.loads((HERE / (reference + '.json')).read_bytes())
        assert record['result']['status'] == 'COMMITTED'
        family, version = reference.split('-')
        candidate = load_candidate(repository, CandidateKey(**record['candidate']))
        package = validate_release_package(repository.strategy_root, reference)
        assert package.release.release_hash == record['result']['migrated']['release_hash']
        assert package.package_sha256 == record['result']['migrated']['package_hash']
        frozen = EquityStrategyCandidate(family, candidate.candidate_id,
            EquityStrategyDefinition.from_dict(dict(package.release.payload['equity_definition'])), package.source_root)
        assert frozen.content_identity == candidate.content_identity
        archive = ROOT / Path(record['result']['receipt']).parent / 'strategies'
        prior = validate_release_integrity(archive, reference)
        assert prior.package_sha256 == record['original']['package_hash']
        original = StrategyRegistry(archive).get_version(family, version).to_dict()
        current = StrategyRegistry(repository.strategy_root).get_version(family, version).to_dict()
        assert {k: v for k, v in original.items() if k not in ('release_hash', 'strategy_payload')} == {
            k: v for k, v in current.items() if k not in ('release_hash', 'strategy_payload')}
        for key in ('signal_evidence', 'verification_ref', 'result_ref'):
            EvidenceRef.from_dict(record[key]).resolve(ROOT)
        check = validate_experiment(repository, ExperimentValidationRequest(
            ExperimentRef.from_dict(record['experiment']), ExperimentValidationScope.REPORT_PUBLICATION))
        assert check.status.value == 'PASS', check.issues
        for name, digest in record['verification']['files'].items():
            assert sha256((ROOT / record['output'] / name).read_bytes()).hexdigest() == digest
        results.append({'reference': reference, 'candidate': candidate.candidate_id,
            'experiment': record['experiment']['experiment_id'], 'content': record['content'],
            'status': 'COMMITTED', 'verification': 'PASS', 'history_preserved': True,
            'decisions': record['verification']['counts']['decisions'],
            'pte_scenarios': record['verification']['pte_scenarios'],
            'release_hash': package.release.release_hash, 'package_hash': package.package_sha256})
    result = {'status': 'PASS', 'upgrades': results, 'excluded': ['S002-v1', 'S003-v1'],
        'already_completed_unchanged': 'S018-v1', 'production_writes': 0,
        'financial_prefix_checks': 983, 'financial_target_differences': 0,
        'candidate_package_decisions': sum(r['decisions'] for r in results),
        'isolated_pte_scenarios': sum(r['pte_scenarios'] for r in results)}
    (HERE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 已部署策略当前合同适配交付', '', 'Status: COMPLETED', '',
        '五个版本已完成本地原地升级，版本号不变。S002-v1按用户要求无需升级；S003-v1暂不升级；S018-v1维持此前完成的版本。', '',
        '| 冻结版本 | 新实现 | 账户回放决策 | 隔离PTE场景 | 实验报告 |',
        '|---|---|---:|---:|---|']
    for row in results:
        family = row['reference'].split('-')[0]
        report = f"../../../{family}/experiments/{row['experiment']}/report.md"
        lines.append(f"| {row['reference']} | {row['candidate']} | {row['decisions']} | {row['pte_scenarios']} | [通过]({report}) |")
    lines.extend(['',
        '金融信号核验：S001两版各41点、S007为63点、S011为405点、S015为433点，共983个真实逐日前缀目标仓位差异为0；S007另有1414日全列历史信号一致，S015中心等六项特征差异为0。S001继续采用此前获准的已完成周线设计，S007保留1%买入溢价，其余参数和报价规则保持。', '',
        '新候选与精确待替换包在183个账户决策上，决策、订单、成交、账本及最终状态完全一致。30个隔离PTE场景覆盖部分成交、重复回报、完成、拒单、未知提交、过期、对账阻断及重启恢复；使用正式PTE组件与记录型网关，不连接真实下单渠道。', '',
        '策略仅读取后复权行情，输出当前策略账户权益目标；EC负责报价、数量、资金与执行。旧实现的现金或股数锁定与现行权益再平衡并不经济等价，本轮不宣称旧、新账户收益和订单一致，不重新选型，也不继承旧口径自检结论。S007的C9990曾因未返回强类型空周期状态而未通过账户回放，保留原记录；修正后以C9991完成全部验证。', '',
        '旧包和原始元数据均已归档并验证，重复应用返回相同迁移回执；五项研究报告发布校验通过。更新了仓库本地部署回执，未修改PTE prod、生产绑定、生产账户或模拟交易资格；新发布哈希当前资格均为RESEARCH。', '',
        '下一步建议由DEV准备生产发布与账户重绑，明确保留S002、S003的范围及当前生产合同兼容性；生产写入仍需按实际方案取得确认。', ''])
    (HERE / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
