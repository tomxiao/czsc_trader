"""Publish completed read-only PTE observation verification; never run strategies."""
from collections import Counter
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

from strategy_manager import StrategyRegistry
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_release_package
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/pte-window-replay-20261020'
PREFIX = 'pte_observation_replay_20261020'


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def put_once(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('completed verification material differs')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def main():
    publication = EX / 'others' / f'{PREFIX}_publication.json'
    if publication.exists():
        raise FileExistsError('verification already published')
    report_path = EX / 'others' / f'{PREFIX}_report.md'
    summary_path = EX / 'others' / f'{PREFIX}_summary.json'
    results_path = EX / 'others' / f'{PREFIX}_results.json'
    review_path = EX / 'others' / f'{PREFIX}_review.json'
    summary, results = read(WORK / 'final_summary.json'), read(WORK / 'final_results.json')
    reviews = {name: read(WORK / name) for name in ('independent_review.json', 'component_independent_review.json')}
    assert all(value['status'] == 'PASS' for value in reviews.values())
    assert len(results) == len({(row['account_id'], row['decision_id']) for row in results}) == 125
    assert Counter(row['verification_status'] for row in results) == {
        'FULL_PATH_BUSINESS_MATCH': 35, 'COMPONENT_BUSINESS_MATCH': 52, 'NOT_VERIFIABLE_FULL_REPLAY': 38}
    assert not any(row.get('difference_paths') for row in results)
    for name, expected in summary['helper_sha256'].items():
        assert digest(WORK / name) == expected, name
    windows = {row['account_id']: row for row in read(WORK / 'history_extract/summary.json')}
    actual_ids = set(windows)
    assert actual_ids == {'s001-v1', 's001-v2', 's003-v1', 's007-v1', 's011-v1'}
    assert {row['account_id'] for row in results} == actual_ids
    runtime_snapshot = read(WORK / 'snapshot/snapshot_manifest.json')
    dfls_snapshot = read(WORK / 'dfls/market/snapshot_manifest.json')
    assert digest(WORK / 'snapshot/runtime.db') == runtime_snapshot['sha256']
    assert digest(WORK / 'dfls/market/assets.sqlite3') == dfls_snapshot['sha256']
    protocol_path = EX / 'protocols' / f'{PREFIX}.json'
    protocol = read(protocol_path)
    context = RepositoryContext.discover(ROOT)
    registry = StrategyRegistry(context.strategy_root)
    for target in protocol['targets']:
        family, version = target['strategy_version'].split('-')
        manifest, _, _ = validate_release_package(context, target['strategy_version'])
        assert manifest['strategy_version_hash'] == target['new_release_hash']
        assert manifest['package_hash'] == target['new_package_hash']
        assert registry.current_qualification(family, version).value == 'PAPER_READY'
    summary = {**summary, 'overall_full_window_strict_verdict': 'NOT_PROVEN',
        'observed_business_mismatches': 0, 'windows': [{
            'account_id': aid, 'signal_start': windows[aid]['decision_signal_window'][0],
            'signal_end': windows[aid]['decision_signal_window'][1],
            'execution_start': windows[aid]['decision_execution_window'][0],
            'execution_end': windows[aid]['decision_execution_window'][1],
            'last_settlement_session': windows[aid]['last_settlement_session'],
            'signal_days': windows[aid]['distinct_signal_days']} for aid in sorted(actual_ids)],
        'historical_lifecycle_counts': dict(Counter(row['historical_status'] for row in results)),
        'component_signal_evidence': {'stored_strategy_output_exact_match': 43,
            'historical_strategy_output_missing': 9, 'observation_series_facts_replayed': False},
        'remaining_38': {'legacy_data_identity_only_no_complete_context': 6,
                         'incomplete_original_input_evidence': 32},
        'runtime_snapshot_sha256': runtime_snapshot['sha256'],
        'dfls_snapshot_sha256': dfls_snapshot['sha256'],
        'production_release': protocol['production_application_release'],
        'targets': protocol['targets'], 'production_writes': 0, 'pte_accounts_changed': 0,
        'new_market_acquisitions': 0, 'strategy_or_sm_changes': 0,
        'source_commit': '59388b89',
        'scope_limit': 'Replay decisions against actual historical account feedback; not an autonomous account backtest or equivalence of broker fills/returns.'}
    put_once(summary_path, encoded(summary))
    put_once(results_path, (WORK / 'final_results.json').read_bytes())
    put_once(review_path, encoded({'status': 'PASS', 'reviews': reviews,
        'scope': 'Independent evidence/method review; does not convert missing history or component matches into full-path acceptance.'}))
    table = []
    for row in summary['accounts']:
        aid, counts = row['account_id'], row['status_counts']
        window = windows[aid]['decision_signal_window']
        table.append(f'| {aid} | {window[0][5:]}—{window[1][5:]} | {row["rows"]} | '
                     f'{counts.get("FULL_PATH_BUSINESS_MATCH", 0)} | '
                     f'{counts.get("COMPONENT_BUSINESS_MATCH", 0)} | '
                     f'{counts.get("NOT_VERIFIABLE_FULL_REPLAY", 0)} |')
    report = f'''# PTE五账户观察窗口回放验证

**已验证的87条记录未发现业务决策差异；不能宣称五个账户完整观察窗口均已严格一致。** 其中35条通过完整调用链回放，52条仅通过历史输入的策略组件核验，另外38条缺乏完成严格回放所需的原始证据。

生产应用为v0.6.16。本轮从运行中的PTE只读取得一致性数据库快照和DFLS数据空间快照，在本地离线执行。五个账户绑定原版本号，回放使用当前已批准PAPER_READY的新发布哈希。S002-v1已退役，渠道平账账户不纳入。本次未取新行情、未改策略或SM、未驱动订单、未更换PTE绑定、未启停服务。

| 账户 | 信号观察窗口（2026） | 历史决策 | 全链严格一致 | 组件业务一致 | 无法完整回放 |
| --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(table)}
| 合计 | | 125 | 35 | 52 | 38 |

信号窗口截止10月19日，对应末次执行日为10月20日，最后结算快照截至10月19日。125条包括121条COMPLETED、2条INCOMPLETE及2条SUPERSEDED，未删去被替代或未完成记录；合计103个账户信号日。

35条完整链路覆盖每户10月9日、12日、13日、14日、15日、16日、19日七个信号日。使用当时的原始准备引用、逐角色内容身份、真实账户资金/持仓和独立还原的cycle状态，经当前SRT准备和PTE决策接口重算，递归比较业务字段，零数值容差。包括买入、卖出、持有、等待和S003双腿轮转，并非只比较无交易的日子。发布哈希及由其派生的决策、信号、计划和数据身份单列保留，未作为业务差异。

另外52条保留了真实原始输入，但当前DFLS要求的历史契约证据不齐。42条来自完整旧版准备上下文，10条持有原准备引用但被当前数据契约拒绝；没有补造字段或冒充当前准入通过。本轮直接以经认证的新实现、原输入表和共享执行计划组件比较已记录的买卖方向、数量、价格、费用、资金、订单及执行腿，全部一致。其中43条原有strategy_output也严格匹配，另外9条原记录缺该字段；没有重建完整观察图series/facts。这52条不计为完整SRT/PTE调用链通过。

其余38条中，6条仅找回旧publication的输入身份补证，缺完整计算上下文；32条缺完整原输入，不能以后来的行情替代。因此本轮结论是：**可核验范围内没有发现新实现造成的决策偏移，完整窗口严格等价仍未得到证明。** 历史证据缺口不是新策略差异，也不能当作验证成功。本轮使用真实账户反馈，不声称模拟成交或收益能复刻券商成交。

独立复核核对了125条ID与生命周期、87条状态revision、314个组件输入角色身份及254份唯一原始CSV文件哈希。初轮数据身份校验脚本问题、旧数据契约拒绝和S011组件角色映射问题均留有原始记录；组件角色修正按真实dataset声明执行，没有修改策略。

详细内容见[逐条结果]({results_path.name})、[汇总与版本哈希]({summary_path.name})、[独立复核]({review_path.name})。归档原始抽取、旧输入及逐决策比较材料的不可变证据引用见发布回执。

下一步可将本轮结果作为PTE同版本替换的补充依据；如要求整个观察窗逐条可证明，仍需先找回38条缺失的原始上下文。本报告不设置新的策略资格门槛，也不授权生产替换。
'''
    put_once(report_path, report.encode('utf-8'))
    # Seal only the five-account extraction and replay evidence. Full production
    # databases stay local; their immutable refs and snapshot hashes are retained.
    files = []
    for folder in ('history_extract', 'early_provenance', 'replay', 'component_replay'):
        files.extend(path for path in (WORK / folder).rglob('*') if path.is_file())
    files.extend(path for path in WORK.iterdir() if path.is_file() and path.suffix in ('.py', '.json', '.log'))
    files.extend((WORK / 'snapshot/snapshot_manifest.json', WORK / 'dfls/market/snapshot_manifest.json'))
    files = sorted(set(files))
    index = {path.relative_to(WORK).as_posix(): {'sha256': digest(path), 'bytes': path.stat().st_size}
             for path in files}
    bundle = WORK / 'sealed_verification_evidence.tar.gz'
    if bundle.exists():
        raise FileExistsError('sealed evidence bundle already exists')
    with tarfile.open(bundle, 'w:gz') as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(WORK).as_posix(), recursive=False)
        data = encoded({'scope': 'Five-account evidence; database snapshot hashes and original data preparation refs, not copied full production DBs.', 'files': index})
        info = tarfile.TarInfo('sealed_evidence_manifest.json')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with tarfile.open(bundle, 'r:gz') as archive:
        for name, record in index.items():
            assert sha256(archive.extractfile(name).read()).hexdigest() == record['sha256'], name
    research = create_research_context(context, ResearchBatchRef('S014'))
    owner = ExperimentRef('S014', EX.name)

    def publish(path, name, media, suffix):
        ref = publish_evidence(research, MaterialEvidenceWrite(owner, name, path.read_bytes(), media, suffix))
        assert digest(ref.resolve(ROOT)) == digest(path)
        return ref.to_dict()

    refs = {'report': publish(report_path, 'pte-observation-replay-report', 'text/markdown', 'md'),
        'summary': publish(summary_path, 'pte-observation-replay-summary', 'application/json', 'json'),
        'results': publish(results_path, 'pte-observation-replay-results', 'application/json', 'json'),
        'review': publish(review_path, 'pte-observation-replay-review', 'application/json', 'json'),
        'protocol': publish(protocol_path, 'pte-observation-replay-protocol', 'application/json', 'json'),
        'evidence_bundle': publish(bundle, 'pte-observation-replay-sealed-evidence', 'application/gzip', 'gz')}
    put_once(publication, encoded({'status': 'PUBLISHED', 'references': refs, 'sealed_files': len(index),
        'bundle_bytes': bundle.stat().st_size, 'full_window_strict_verdict': 'NOT_PROVEN',
        'full_path_matches': 35, 'component_matches': 52, 'unverifiable': 38,
        'business_mismatches_observed': 0, 'production_writes': 0}))
    print(json.dumps({'status': 'PUBLISHED', 'full_path_matches': 35, 'component_matches': 52,
                      'unverifiable': 38, 'sealed_files': len(index), 'bundle_bytes': bundle.stat().st_size}))


if __name__ == '__main__':
    main()
