"""Publish existing results and migration preparations; never run accounts."""

from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence,
)
from czsc_trader.research_tools import (
    ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef,
)


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def main():
    destination = EX / 'others/publication.json'
    if destination.exists():
        raise FileExistsError('retain the completed publication receipt')
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))
    owner = ExperimentRef('S014', EX.name)

    def publish(name, data, suffix, media='application/json'):
        return publish_evidence(context, MaterialEvidenceWrite(owner, name, data, media, suffix))

    receipt = json.loads((EX / 'others/c9523_independent_backtest.json').read_bytes())
    assert receipt['status'] == 'PASS'
    review_path = EX / 'others/final_account_review.json'
    assert json.loads(review_path.read_bytes())['blocking_findings'] == []
    files = {}
    for name, relative in receipt['artifacts'].items():
        path = ROOT / relative
        suffix = path.suffix.removeprefix('.')
        media = {'csv': 'text/csv', 'html': 'text/html', 'md': 'text/markdown'}.get(suffix, 'application/json')
        ref = publish('c9523-window-' + name.replace('.', '-'), path.read_bytes(), suffix, media)
        files[name] = {'source_path': relative, 'evidence': ref.to_dict()}
    for name in ('c9523_full_control.json', 'c9523_independent_backtest.json', 'final_account_review.json'):
        ref = publish('c9523-' + name.replace('.', '-'), (EX / 'others' / name).read_bytes(), 'json')
        files[name] = {'source_path': (EX / 'others' / name).relative_to(ROOT).as_posix(), 'evidence': ref.to_dict()}

    validation = {}
    for name in ('window-contract-integrated-tests.log', 'pte-feedback-cross-contract-tests.log',
                 'window-adapter-final-tests.log', 'window-contract-final-migration-tests.log',
                 'window-contract-final-srt-tests.log'):
        data = (ROOT / '.tmp' / name).read_bytes()
        assert b' passed' in data
        ref = publish(name.replace('.', '-'), data, 'log', 'text/plain')
        validation[name] = ref.to_dict()

    migration_root = ROOT / '.tmp/window-contract-final-migrations'
    summary = json.loads((migration_root / 'summary.json').read_bytes())
    migrations = []
    for record in summary['records']:
        folder = (ROOT / record['metadata_path']).parent
        metadata = json.loads((folder / 'migration.json').read_bytes())
        entry = {'original_reference': metadata['original_reference'], 'files': {}}
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            if not path.read_bytes():
                entry['files'][path.relative_to(folder).as_posix()] = {
                    'empty_file': True, 'sha256': sha256(b'').hexdigest(),
                }
                continue
            suffix = path.suffix.removeprefix('.')
            ref = publish('migration-' + folder.name + '-' + sha256(path.relative_to(folder).as_posix().encode()).hexdigest()[:12],
                          path.read_bytes(), suffix, 'text/x-python' if suffix == 'py' else 'application/json')
            entry['files'][path.relative_to(folder).as_posix()] = ref.to_dict()
        migrations.append(entry)

    baseline = json.loads((ROOT / '.tmp/srt_window_contract_review_baseline.json').read_bytes())
    changed = [name for name, digest in baseline['hashes'].items()
               if sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    assert not changed, changed
    protected = {'status': 'PASS', 'protected_files': len(baseline['hashes']),
                 'sha256_by_repository_path': baseline['hashes'], 'changed': changed,
                 'scope': 'repository frozen originals; no production inspection or write'}
    protected_data = (json.dumps(protected, ensure_ascii=False, indent=2) + '\n').encode()
    protected_ref = publish('frozen-original-integrity', protected_data, 'json')
    manifest = {'status': 'PUBLISHED', 'account_files': files,
                'engineering_validation': validation,
                'migration_summary': summary, 'migration_files': migrations,
                'protected_originals': protected_ref.to_dict(),
                'candidate_registration_performed': False,
                'freeze_performed': False, 'deployment_performed': False,
                'research_stage_changed': False}
    manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    manifest_ref = publish('window-contract-result-manifest', manifest_data, 'json')
    (EX / 'others/result_manifest.json').write_bytes(manifest_data)

    account_refs = files
    chart = account_refs['chart.html']['evidence']['evidence_id']
    account_report = account_refs['report.md']['evidence']['evidence_id']
    assets = '../../../assets/evidence/' + EX.name + '/'
    report = f'''# C9521 窗口契约适配与独立回测结论

执行窗口为 2026-06-01 至 2026-10-19，标的 600722.SH，初始资金 100,000 元、空仓，单边费用 0.1%，最小交易单位 100 股。94 个交易日，信号日期为 2026-05-29 至 2026-10-16；预热历史只供指标计算。

| 账户 | 窗口收益 | 最大回撤幅度 | 完整交易 |
| --- | ---: | ---: | ---: |
| C9521 的契约适配版 C9523 | 22.84% | 13.52% | 5 |
| 买入持有 | 28.22% | 33.47% | 0（期末仍持有） |
| MA5/MA20 | 62.87% | 21.88% | 1 |

期末权益 122,844.562 元、0 股。策略比买入持有少赚 5.38 个百分点，同时最大回撤减少 19.95 个百分点。五次交易中两次盈利，主要利润来自八月底至九月上旬的一次上涨。这个窗口显示了控制回撤的作用，也显示了错过部分上涨的代价；五次交易不足以说明其优势稳定。

## 等价性与候选身份

原 C9521 已登记内容、资格及阶段三交付保持原样。C9522 为首次技术适配草稿；C9523 在同一经济规则与源码上补充 SIMULATED_FILL_FEEDBACK 声明，使用新的内容身份；两者均未登记为正式候选。没有新增策略机制、调参、冻结或推进阶段。

使用原认证离线数据，对原完整窗口 2020-01-02 至 2026-10-15 复核：C9522、C9523 各自 1,642 个信号及账户日、184 笔成交、187 张订单、92 次闭合交易，与原 C9521 的业务字段逐项精确相同。比较保留身份字段之间的对应关系，没有用宽松数值容差掩盖差异。

C9523 使用内部模拟成交反馈，尚未实现由 PTE 实际成交回报驱动的决策状态。当前 PTE 明确拒绝这类策略，且其股票交易能力也不在本次扩展范围。本次结果证明既定历史执行口径下的等价性，不证明真实成交反馈等价。

## 契约及迁移实施

契约 2 通过强类型上下文和一个必实现的计算入口明确窗口、信号日和计算历史，禁止依赖父类默认回退。独立窗口重建账户相关状态，市场指标及按 HistoryPolicy 定义的市场意图仍可利用此前历史。S007 的市场分数滞后状态据此保留原语义。

已为 S001-v1、S001-v2、S002-v1、S003-v1、S007-v1、S011-v1 生成新的契约 2 准备包。测试覆盖市场信号和实际策略政策经 SRT 计划、TXE 成交后的订单、费用、现金、持仓及周期；这些为合成输入工程测试，不替代逐策略真实市场复验。准备包状态仍为待数值验收，尚未生成新冻结版本。

PTE 本地实现支持显式目标版本，要求账户暂停、没有未完成订单，批量准备成功后才切换数据库绑定；现金、持仓和历史账本保留。失败时回滚数据库及数据准备的 current 指针。该保证不等于跨文件系统和数据库的断电原子性。

新登记、检查和新冻结要求契约 2 及明确反馈声明；既有冻结的幂等查询保留。PTE 跨版本拒绝模拟或确认成交反馈声明，契约 2 仅接受市场意图；既有契约 1 未声明发布仍可读取，等待迁移。原冻结发布的 {len(baseline['hashes'])} 个受保护文件字节未变。

## 判断与下一步

本次完成平台本地实现及所请求的独立账户回测。独立账户意味着窗口内从新资金起算；窗口的大部分日期已被前期研究使用，因此不属于未见样本检验。没有生产变更、远端推送或正式冻结。

建议下一步对六个准备包执行有明确窗口和非零持仓场景的真实市场等价性验收，再评审具体冻结版本和 PTE 切换。C9523 如需进入 PTE，应先设计并验证真实成交回报契约。

- [主策略交互图表]({assets}{chart})
- [TDR 原始回测报告]({assets}{account_report})（模板中的“冻结执行规则”指所使用的执行规则，C9523 本身尚未冻结）
- [完整证据与迁移文件索引]({assets}{manifest_ref.evidence_id})
'''
    report_data = report.encode('utf-8')
    report_ref = publish('window-contract-final-report', report_data, 'md', 'text/markdown')
    copy_path = EX / 'others/report.md'
    copy_path.write_bytes(report_data)
    assert copy_path.read_bytes() == report_ref.resolve(ROOT).read_bytes()
    verification = {'status': 'PASS_BYTE_EXACT', 'copy_path': copy_path.relative_to(ROOT).as_posix(),
                    'report': report_ref.to_dict(), 'sha256': sha256(report_data).hexdigest()}
    (EX / 'protocols/report_copy_verification.json').write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    destination.write_text(json.dumps({'status': 'PUBLISHED', 'manifest': manifest_ref.to_dict(),
                                     'report': report_ref.to_dict()}, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PUBLISHED', 'report': report_ref.to_dict(),
                      'artifacts': len(files), 'migrations': len(migrations)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
