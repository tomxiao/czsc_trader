"""Publish completed real-market engineering checks without running accounts."""

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def main():
    receipt_path = EX / 'others/market_acceptance_publication.json'
    if receipt_path.exists():
        raise FileExistsError('retain the completed publication')
    review_path = EX / 'others/market_equivalence_independent_review.json'
    review = read(review_path)
    assert review['status'] == 'PASS' and review['blocking_findings'] == []
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))
    owner = ExperimentRef('S014', EX.name)

    def publish(name, data, suffix, media='application/json'):
        return publish_evidence(context, MaterialEvidenceWrite(owner, name, data, media, suffix))

    def file_ref(path, name):
        suffix = path.suffix.removeprefix('.')
        media = {'csv': 'text/csv', 'py': 'text/x-python', 'md': 'text/markdown',
                 'log': 'text/plain', 'gz': 'application/gzip'}.get(suffix, 'application/json')
        data = path.read_bytes()
        if not data:
            return {'empty_file': True, 'sha256': sha256(data).hexdigest()}
        return publish(name, data, suffix, media).to_dict()

    config_path = EX / 'protocols/market_equivalence_cases.json'
    config = read(config_path)
    driver_used = ROOT / '.tmp/market-driver-executed-20261020.py'
    driver_sha = sha256(driver_used.read_bytes()).hexdigest()
    records, reference_coverage, artifacts = [], {}, {}
    for case in config['cases']:
        case_id = case['case_id']
        folder = EX / 'others/market_equivalence' / case_id
        result = read(folder / 'result.json')
        assert result['status'] in ('PASS', 'COVERAGE_INSUFFICIENT'), result
        assert result['config_sha256'] == sha256(config_path.read_bytes()).hexdigest()
        assert result['driver_sha256'] == driver_sha
        for item in result['artifacts']:
            assert sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256']
        for path in sorted(folder.iterdir()):
            if path.is_file():
                name = 'market-' + sha256(path.relative_to(EX).as_posix().encode()).hexdigest()[:24]
                artifacts[path.relative_to(ROOT).as_posix()] = file_ref(path, name)
        record = {'case_id': case_id, 'reference': case['reference'], 'status': result['status'],
                  'window': result['window'], 'modes': {}}
        coverage = reference_coverage.setdefault(case['reference'], {})
        for mode, outcome in result['modes'].items():
            assert outcome['status'] in ('PASS', 'COVERAGE_INSUFFICIENT'), outcome
            trades = pd.read_csv(folder / f'new_{mode}_trades.csv', float_precision='round_trip')
            fills = pd.read_csv(folder / f'new_{mode}_fills.csv', float_precision='round_trip')
            account = pd.read_csv(folder / f'new_{mode}_account_daily.csv', float_precision='round_trip')
            closed = int(trades.status.eq('CLOSED').sum())
            opened = int(trades.status.eq('OPEN').sum())
            actual = {'status': outcome['status'], 'sessions': len(account), 'fills': len(fills),
                      'closed_trades': closed, 'open_trades': opened,
                      'complete_cycle_coverage': outcome['status'] == 'PASS' and len(fills) > 0 and closed > 0,
                      'fees': float(fills.fees.sum()), 'ending_cash': float(account.cash.iloc[-1]),
                      'ending_quantity': int(account.quantity.iloc[-1]),
                      'ending_equity': float(account.equity.iloc[-1]),
                      'nonzero_plan_coverage': outcome['nonzero_plans']}
            record['modes'][mode] = actual
            coverage[mode] = coverage.get(mode, False) or (
                outcome['status'] == 'PASS' and len(fills) > 0 and closed > 0)
        record['cycle_coverage_status'] = ('PASS' if all(item['complete_cycle_coverage']
            for item in record['modes'].values()) else 'COVERAGE_INSUFFICIENT')
        records.append(record)
    assert len(reference_coverage) == 6
    assert all(set(modes) == {'WINDOW', 'CONTINUOUS'} and all(modes.values())
               for modes in reference_coverage.values()), reference_coverage

    baseline = read(ROOT / '.tmp/srt_window_contract_review_baseline.json')
    assert all(sha256((ROOT / path).read_bytes()).hexdigest() == digest
               for path, digest in baseline['hashes'].items())
    for path, name in ((config_path, 'real-market-case-config'), (driver_used, 'real-market-executed-driver'),
                       (review_path, 'real-market-independent-review'),
                       (EX / 'others/market_review_attempt1.json', 'real-market-review-attempt1'),
                       (ROOT / '.tmp/window-real-market-final-tests.log', 'real-market-focused-tests')):
        artifacts[path.relative_to(ROOT).as_posix()] = file_ref(path, name)
    for version in ('v1', 'v2'):
        folder = ROOT / f'.tmp/s002_real_edge_{version}'
        for path in sorted(folder.iterdir()):
            if path.is_file():
                artifacts[path.relative_to(ROOT).as_posix()] = file_ref(path, 's002-edge-' + version + '-' + path.stem)

    selected = read(ROOT / '.tmp/window-contract-final-migrations/summary.json')['records']
    selected_files = {}
    for item in selected:
        folder = (ROOT / item['metadata_path']).parent
        if item['reference'] == 'S002-v1':
            folder = ROOT / '.tmp/window-contract-real-market-r2/S002-v1-C9902'
        metadata = read(folder / 'migration.json')
        entry = {'candidate_id': metadata['candidate_id'], 'candidate_identity': metadata['candidate_identity'],
                 'files': {}}
        for path in sorted(folder.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                relative = path.relative_to(folder).as_posix()
                entry['files'][relative] = file_ref(path, 'market-selected-' + item['reference'] + '-' +
                                                  sha256(relative.encode()).hexdigest()[:16])
        selected_files[item['reference']] = entry

    summary = {'status': 'PASS_ON_DECLARED_REAL_WINDOWS', 'versions': 6, 'cases': len(records),
               'mode_comparisons': len(records) * 2, 'executed_accounts': len(records) * 4,
               'reference_coverage': reference_coverage, 'records': records,
               'raw_counter_correction': 'Executed driver field closed_trades counted all trade rows, including OPEN. '
                                         'This summary counts only CSV status=CLOSED; original results are preserved. '
                                         'Comparison and coverage statuses never depended on that raw counter.',
               'protected_frozen_files': len(baseline['hashes']), 'frozen_files_unchanged': True,
               'candidate_registration_performed': False, 'freeze_performed': False,
               'production_access_performed': False}
    summary_data = encoded(summary)
    summary_ref = publish('real-market-equivalence-summary', summary_data, 'json')
    (EX / 'others/market_acceptance_summary.json').write_bytes(summary_data)
    manifest = {'summary': summary_ref.to_dict(), 'artifacts': artifacts, 'selected_migrations': selected_files}
    manifest_ref = publish('real-market-acceptance-artifact-index', encoded(manifest), 'json')

    lines = []
    common = {record['reference']: record for record in records
              if record['case_id'] in ('S001-v1', 'S001-v2', 'S002-v1-common', 'S003-v1',
                                       'S007-v1-seed', 'S011-v1-common')}
    for reference, record in sorted(common.items()):
        window, continuous = record['modes']['WINDOW'], record['modes']['CONTINUOUS']
        lines.append(f"| {reference} | {window['fills']} / {continuous['fills']} | "
                     f"{window['closed_trades']} / {continuous['closed_trades']} | 精确一致 |")
    assets = '../../../assets/evidence/' + EX.name + '/'
    report = '''# 六个冻结版本的真实行情等价验收

六个版本在本次声明窗口内全部通过迁移等价验收。共9个窗口案例、18组模式对照、36个独立账户；比较信号及订单、成交、费用、现金、持仓、净值、交易周期，数值不设置宽松容差。内容身份发生变化的关联编号只允许双射对应，不删除账本关联。

## 实际覆盖

以下主窗口均为2026-06-01至2026-09-02。数字顺序为“独立窗口模式 / 连续历史模式”，成交和闭合周期均取每组中的一个账户，旧版与新版完全相同。

| 原冻结版本 | 成交笔数 | 闭合周期 | 旧版与迁移版 |
| --- | ---: | ---: | --- |
''' + '\n'.join(lines) + f'''

额外窗口包括S002的2026-08-06至08-14左边界、S007的09-03至09-30增量输入、S011的10-08至10-15短窗口。S002边界的独立模式没有交易，保留COVERAGE_INSUFFICIENT，不能单独用作成交验收；连续模式有实际买卖，主窗口则覆盖两种模式。S011短窗只在末日买入，仍为OPEN；完整进出场覆盖来自主窗口。

S003的闭合周期统计日内叠加交易，期末仍保留{common['S003-v1']['modes']['WINDOW']['ending_quantity']}股底仓，没有强制平仓。

## 本次发现并修复的问题

原S002迁移草稿在连续模式下过早裁剪历史，丢失窗口前刚产生的持有意图。在08-06起的真实边界窗口，旧版仍应持有，新版却可能发出卖出计划。已保留首次失败结果，后继技术候选改为S002-C9902，先从完整预热数据重建市场意图，再选取输出日。独立模式继续从窗口起点初始化；旧冻结发布未修改。

修复后，S002的两种模式、空仓及非零持仓计划均精确一致。所有六版还通过了实际plan_at的非零账户检查，包括600股、200股、不同现金、周期目标量保留，以及S003核心仓不足时的明确拒绝。

## 证据及适用范围

所有输入均由DFLS公开prepare/fetch及明确PreparedDataRef认证，旧新版共享实际数据版本，分别推导身份绑定。S001、S007增量及S011扩展窗口仅在新的本地工程空间准备，未修改旧缓存。S003/S007的预计算种子按已冻结资源哈希认证；S007另验实际增量输入，未把旧缓存缺少契约版本的条目当作可用数据。

FROZEN_RULE账户使用真实未复权日线/分钟线及逐日涨跌停契约。S003按原INTRADAY_OVERLAY执行路径使用真实5分钟检查点；现有TXE该路径不接受MarketExecutionRules，本次没有扩展这一能力。验收覆盖本次窗口和既有策略能力，不代表全部历史日期或所有市场条件。

本次没有连接Futu、切换真实PTE账户、冻结发布或推送。离线plan_at与PTE采用同样的连续历史语义，但交易渠道回报、运行部署及生产切换仍需单独验收。此次是工程等价验证，不是新增收益研究或未见样本检验。

聚焦回归58项通过，Ruff及差异检查通过。原冻结的{len(baseline['hashes'])}个受保护文件字节未变。原驱动把交易记录行数标为closed_trades；本报告按CSV中status=CLOSED重新统计完整周期，OPEN不计闭合，原执行材料保留并绑定实际使用的驱动源码。

## 建议

在本次窗口范围内，六个版本均可继续准备新契约的正式技术检验及冻结方案。S002应采用修复后的C9902，旧草稿不再作为迁移对象。正式冻结版本和PTE生产切换应按各自授权步骤执行，并保留现有账户现金、持仓及历史账本。

- [独立复核及全部原始证据索引]({assets}{manifest_ref.evidence_id})
- [窗口、成交和闭合周期汇总]({assets}{summary_ref.evidence_id})
'''
    data = report.encode('utf-8')
    report_ref = publish('real-market-acceptance-report', data, 'md', 'text/markdown')
    copy_path = EX / 'others/market_acceptance_report.md'
    copy_path.write_bytes(data)
    assert report_ref.resolve(ROOT).read_bytes() == copy_path.read_bytes()
    (EX / 'protocols/market_report_copy_verification.json').write_bytes(encoded({
        'status': 'PASS_BYTE_EXACT', 'report': report_ref.to_dict(),
        'copy_path': copy_path.relative_to(ROOT).as_posix()}))
    receipt_path.write_bytes(encoded({'status': 'PUBLISHED', 'report': report_ref.to_dict(),
        'summary': summary_ref.to_dict(), 'manifest': manifest_ref.to_dict()}))
    print(json.dumps({'status': 'PUBLISHED', 'versions': 6, 'cases': len(records),
                      'report': report_ref.to_dict()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
