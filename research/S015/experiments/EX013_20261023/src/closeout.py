"""Authenticate retained accounts and publish the explicit dual-window decision."""
# ruff: noqa: E402
import argparse
from hashlib import sha256
from types import SimpleNamespace
import os

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import numpy as np
import pandas as pd
from fixed_comparison import (
    ROOT, EROOT, EX, read, save, context, material, archived, stats,
    authenticated_delivery, candidate, candidate_hash,
)
from czsc_trader.application import (
    RepositoryContext, publish_evidence, validate_experiment, update_research_intent,
    ResearchIntentUpdate, get_research_overview,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite, ExperimentValidationRequest,
    ExperimentValidationScope, ResearchBatchRef,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence


def frames(payload):
    return SimpleNamespace(**{name: pd.DataFrame(table['data'])
                             for name, table in payload['runs'][0]['ledgers'].items()})


def analyze():
    protocol = read(EROOT / 'protocols/fixed_set.json')
    precheck = read(EROOT / 'others/precheck.json')
    historical = read(EROOT / 'others/historical_integrity.json')
    # Independent current integrity authentication is a prerequisite for reuse.
    status_values = [historical.get('status'), historical.get('validation', {}).get('status')]
    assert 'PASS' in status_values, list(historical)
    old, oldref = authenticated_delivery('ASSESSMENT', 1)
    assert oldref == protocol['source_assessment']
    old_rows = {r['candidate']['candidate_id'].removeprefix('S015-'): r
                for r in old['content']['payload']['comparison']['rows']}
    baseline, c_old = archived('S011-v1'), archived('C0031')
    pinned = protocol['gate']['baseline_reference']
    assert baseline['manifest']['strategy']['reference'] == pinned['release_id']
    assert baseline['manifest']['strategy']['source_hash'] == pinned['release_hash']
    assert baseline['manifest']['request'] == c_old['manifest']['request']
    assert baseline['manifest']['execution_data'] == c_old['manifest']['execution_data']
    assert baseline['manifest']['execution_data']['fingerprint'] == protocol['gate']['baseline_reference']['execution_fingerprint']
    base_stats = stats(SimpleNamespace(**{k: v for k, v in baseline.items() if k != 'manifest'}))
    gate = protocol['gate']['conditions']
    assert abs(base_stats['net_return'] - gate[0]['baseline_value']) < 1e-14
    assert abs(base_stats['maximum_drawdown'] - gate[1]['baseline_value']) < 1e-14
    rows, groups, account_refs = [], {}, []
    repeated = read(EvidenceRef.from_dict(precheck['repeat_reference']).resolve(ROOT))
    binding_audit = {}
    for cid, payload_hash in protocol['candidates'].items():
        assert candidate_hash(candidate(cid)) == payload_hash
        source = precheck if cid == 'C0031' else read(EROOT / 'others/results' / (cid + '.json'))
        ref = EvidenceRef.from_dict(source['repeat_reference'] if cid == 'C0031' else source['evidence'])
        value = read(ref.resolve(ROOT))
        validate_evaluation_evidence(value)
        account_refs.append(ref.to_dict())
        q = value['request_identity']
        assert q['strategy_reference'] == 'S015-' + cid
        assert q['content_sha256'] == protocol['registered_content_hashes'][cid]
        assert q['windows'] == [{'end': '2026-10-21', 'start': '2025-02-06', 'window_id': 's011_common'}]
        assert q['costs'] == [{'measurement_tier': 'FORMAL', 'one_way_cost': .001, 'scenario_id': 'standard'}]
        assert q['initial_cash'] == 100000 and q['data_cutoff'] == '2026-10-21'
        assert q['market_rules'] == baseline['manifest']['execution_data']['market_rules']
        assert q['pricing'] == baseline['manifest']['execution_data']['pricing']
        support = value['runs'][0]['signal_support']
        old_support = baseline['manifest']['signal_support']
        for name in ('execution_daily', 'price_limits', 'trading_calendar'):
            assert support['execution_input_identities'][name] == old_support['execution_input_identities'][name]
            assert support['execution_requests'][name] == old_support['execution_requests'][name]
        assert value['data_identity'] == repeated['data_identity']
        assert value['runs'][0]['replay_evidence']['execution_daily'] == repeated['runs'][0]['replay_evidence']['execution_daily']
        binding_audit[cid] = {'execution_input_identities': support['execution_input_identities'],
                              'execution_requests': support['execution_requests'], 'data_identity': value['data_identity']}
        execution = frames(value)
        computed = stats(execution)
        for key in ('net_return', 'maximum_drawdown', 'final_equity', 'fees'):
            assert abs(computed[key] - source['stats'][key]) < 1e-8
        assert list(execution.account_daily.date.astype(str).str[:10]) == list(baseline['account_daily'].date.astype(str).str[:10])
        np.testing.assert_allclose(execution.account_daily.close.astype(float), baseline['account_daily'].close.astype(float), rtol=0, atol=0)
        old_row = old_rows[cid]
        assert old_row['acceptance_status'] == 'PASSED'
        fingerprint = sha256(np.asarray(execution.account_daily.equity, dtype='<f8').tobytes()).hexdigest()
        groups.setdefault(fingerprint, []).append(cid)
        row = {'candidate_id': cid, 'content_sha256': q['content_sha256'], 'original434': 'PASSED',
               **computed, 'net_return_gap': computed['net_return'] - base_stats['net_return'],
               'drawdown_gap': computed['maximum_drawdown'] - base_stats['maximum_drawdown'],
               'old_pareto_layer': old_row.get('pareto_layer'), 'old_rank_min': old_row.get('rank_min'),
               'comparison_origin': 'EX008_REUSED_C0031_AND_EQUIVALENCE_REPEAT' if cid == 'C0031' else 'EX013_NEW_ACCOUNT',
               'evidence': ref.to_dict(), 'equity_path_sha256': fingerprint}
        rows.append(row)
    assert len(rows) == 86 and len(list((EROOT / 'others/results').glob('*.json'))) == 85
    summary = {'status': 'COMPLETE', 'source_assessment': oldref, 'source_mandate': protocol['source_mandate'],
               'baseline': base_stats, 'candidate_count': 86, 'new_accounts': 85, 'precheck_repeats': 3,
               'physical_candidate_evaluations_this_experiment': 88, 'reused_comparisons': 1,
               'original434_pass': 86, 'return_pass': sum(r['return_pass'] for r in rows),
               'drawdown_pass': sum(r['drawdown_pass'] for r in rows),
               'joint_pass': sum(r['joint_pass'] for r in rows),
               'return_only': sum(r['return_pass'] and not r['drawdown_pass'] for r in rows),
               'drawdown_only': sum(r['drawdown_pass'] and not r['return_pass'] for r in rows),
               'neither': sum(not r['return_pass'] and not r['drawdown_pass'] for r in rows),
               'unique_equity_paths': len(groups), 'equity_path_groups': groups,
               'execution_input_audit': binding_audit,
               'baseline_manifest_strategy': baseline['manifest']['strategy'],
               'fingerprint_scope_difference': {'baseline': baseline['manifest']['execution_data']['fingerprint'],
                   'evaluation': repeated['data_identity'],
                   'explanation': 'OldCLI adjusted daily begins2024-12-31; Evaluation begins2025-02-05. RawOHLC/calendar/limits hashes and requests identical, pricing and daily close identical; all86 full execution_daily inputs equal C0031 equivalence repeat.'},
               'verification': ['86 schema7 published account authentication', '86 unchanged candidate identities',
                   '86 exact windows and initial capital', '86 exact standard costs and fill fees',
                   '86 market execution and pricing equal pinned baseline', '86 daily close prices equal pinned baseline',
                   '86 rawOHLC/calendar/limits input hashes and requests identical to pinned baseline',
                   '86 full daily execution replay inputs equal C0031 equivalence repeat',
                   'independent net-return and initial-cash-inclusive drawdown recomputation',
                   'baseline archive hash and exact gate-value reconciliation', 'original434 typed acceptance retained'],
               'rows': rows, 'account_references': account_refs}
    save(EROOT / 'others/dual_window_results.json', summary)
    pd.DataFrame([{k: v for k, v in r.items() if k != 'evidence'} for r in rows]).to_csv(
        EROOT / 'others/dual_window_results.csv', index=False, encoding='utf-8-sig')
    print({k: summary[k] for k in ('candidate_count', 'return_pass', 'drawdown_pass', 'joint_pass', 'unique_equity_paths')}, flush=True)


def pct(value):
    return f'{100 * value:.4f}%'


def report():
    result = read(EROOT / 'others/dual_window_results.json')
    rows = result['rows']
    base = result['baseline']
    high = max(rows, key=lambda r: r['net_return'])
    low = min(rows, key=lambda r: r['maximum_drawdown'])
    return_pass_rows = [r for r in rows if r['return_pass']]
    return_pass_low = min(return_pass_rows, key=lambda r: r['maximum_drawdown']) if return_pass_rows else None
    representatives = sorted(set(['C0031', 'C0201', 'C0204', 'C0307', 'C0401', high['candidate_id'], low['candidate_id']]
                                 + ([] if return_pass_low is None else [return_pass_low['candidate_id']])))
    conclusions = ('没有候选同时通过新比较门，双窗口目标尚未达成；本轮覆盖补证任务已完成。'
                   if result['joint_pass'] == 0 else f"{result['joint_pass']}个候选满足双窗口数值目标；本轮覆盖补证任务已完成。待用户选型，未授权冻结或PTE。")
    text = f'''# S015 固定86候选双窗口补证

Status: COMPLETED

RSCH，2026-10-23。{conclusions}

## 目标与结论

依据用户“同意，请你自主执行”，锁定原 ASSESSMENT/1 中完整通过的86个候选，不修改策略或参数。原434交易日开发池（2025-01-02至2026-10-21）及其经济、双频率、32点扰动和费用压力要求保持不变；补齐415交易日共同窗口（2025-02-06至2026-10-21）的独立10万元、零持仓账户。

共同窗口要求：累计净收益严格大于修复后S011-v1的{pct(base['net_return'])}，最大回撤幅度严格小于{pct(base['maximum_drawdown'])}。按未四舍五入值判定，等于不通过。最终要求是原434日完整通过 AND 415日两项严格通过。415日不是移动开发池，也不是继承旧账户资金和持仓的截取。

- 原434日完整通过：86/86；本轮复用历史 FULL 证据，并完成当前 INTEGRITY 认证。没有重跑3072个扰动账户，未声称本轮重新执行旧FULL统计复算。
- 415日收益严格优于：{result['return_pass']}/86；回撤严格更小：{result['drawdown_pass']}/86；两项同时通过：{result['joint_pass']}/86。
- 仅收益通过{result['return_only']}个，仅回撤通过{result['drawdown_only']}个，两项均未通过{result['neither']}个。
- 覆盖全部86个身份，含{result['unique_equity_paths']}条精确净值路径；重复身份不当作独立机会，也未根据旧窗口行为跳过新窗口账户。

## 代表结果

| 候选 | 415日累计净收益 | 最大回撤 | 收益优于S011 | 回撤小于S011 | 双窗口通过 |
| --- | ---: | ---: | --- | --- | --- |
| S011-v1固定基线 | {pct(base['net_return'])} | {pct(base['maximum_drawdown'])} | — | — | — |
'''
    for cid in representatives:
        r = next(r for r in rows if r['candidate_id'] == cid)
        text += f"| {cid} | {pct(r['net_return'])} | {pct(r['maximum_drawdown'])} | {'是' if r['return_pass'] else '否'} | {'是' if r['drawdown_pass'] else '否'} | {'是' if r['joint_pass'] else '否'} |\n"
    text += f'''
本表为诊断代表，包括净收益最高和回撤最小的候选，不是新增排序或选型。完整86行见[结果表](others/dual_window_results.csv)，精确身份与证据见[结构化结果](others/dual_window_results.json)。最大收益为{pct(high['net_return'])}（{high['candidate_id']}），对应回撤{pct(high['maximum_drawdown'])}；最小回撤为{pct(low['maximum_drawdown'])}（{low['candidate_id']}），对应收益{pct(low['net_return'])}。

最小回撤候选距离S011回撤仍高出{100 * low['drawdown_gap']:.4f}个百分点，同时累计净收益差为{100 * low['net_return_gap']:.4f}个百分点。{'' if return_pass_low is None else f"收益通过组中回撤最小的{return_pass_low['candidate_id']}，收益{pct(return_pass_low['net_return'])}、回撤{pct(return_pass_low['maximum_drawdown'])}，回撤仍高出S011 {100 * return_pass_low['drawdown_gap']:.4f}个百分点。"} 这些差距说明本轮缺口不能概括为漏评或选错原榜首；也不证明未来不存在其他可行机制。

## 覆盖与验证

事前[固定名单与协议](protocols/fixed_set.json)引用 MANDATE/3、ASSESSMENT/1、原final_checks和固定S011比较契约。正式旧comparison的通过身份与独立final_checks一致，每个候选登记内容和实际载荷均重新核对。原交付、原候选资格和全部旧账本保留。

C0031串行/批量预检查的decisions、orders、fills、trades、account_daily五账本及结果哈希一致；其415日资金、持仓、成交数量、价格、费用与EX008存档吻合，复用原比较。最初单项批量调用采用平台串行快速路径；首批8任务因沙箱拒绝创建进程而全部CANCELLED，未提交计算。保留[恢复记录](others/recovery_addendum.json)，取得执行权限后用C0031和首个新候选的两项批次验证真实多进程五账本及结果哈希等价，然后显式恢复余下84个账户。最终3次C0031重复物理评价和85个新账户，共88次实际评价；被拒的8项没有计入实际评价。该额外检查未增加候选或策略搜索。批量执行共享单个8进程池，每进程原生线程1，预检查与正式批次串行使用进程池，检查点放在.tmp。

逐86个schema7正式账户进行公开身份及账本认证，独立重算净收益和包含初始资金高点的最大回撤；检查415个交易日、10万元零持仓起点、单边0.1%实际费用、HFQ_RESEARCH价格、DAILY_RANGE_V3交易规则，逐日收盘价与固定S011完全一致。原始成交OHLC、日历和涨跌停数据的哈希及请求均与固定S011相同，定价锚点和规则相同；86份完整执行日线输入也与C0031等价复核输入一致。旧CLI因附带基准预热，adjusted_daily从2024-12-31开始，新Evaluation执行数据从2025-02-05定价锚点开始，整体执行数据指纹因此不同；不能声称两个整体指纹相等。原始成交数据相同且逐日收盘换算相同，保持同一成交价格口径。S011存档自身指纹与事前固定基线相符，其release身份及目标阈值均核验一致。费用压力仍只在原434日按原约定验证；未额外要求新窗口扰动、压力或逐年同时双优。

当前完整性认证见[历史证据核验](others/historical_integrity.json)，等价预检查见[precheck](others/precheck.json)。最终发布校验见others/publication_validation.json。技术验证PASS仅认证发布和数值链，研究目标是否通过以双窗口逐项结果为准。

## 研究判断与下一步

'''
    if result['joint_pass'] == 0:
        text += '''本次回答了“是否只是漏评历史候选”的问题：原完整合格集合已全部覆盖，不能再以尚未补齐415日比较为由继续等待或进入选型。阶段二没有证实稳定新分钟信息，阶段四也没有找到同时满足新目标的旧候选，继续复制旧规则、缩放仓位或微调邻近阈值缺乏新的研究依据。

建议当前路线受限收口，暂不进入阶段五或PTE。下一轮若继续，先在研究诊断中提出一个能区分竞争解释的具体问题：旧入场机制为何在部分状态承担回撤、现有决策时点信息能否事前区分，以及减少这些风险会错过多少收益。只做已有账本诊断与证据梳理；在得到具体、可证伪且相对历史实验有增量的方法前，不启动新策略搜索。引入新的信息类别、改变数据范围或策略规则，须另行确认研究范围。
'''
    else:
        text += '已通过身份为：' + '、'.join(r['candidate_id'] for r in rows if r['joint_pass']) + '。建议按原事前434日排序政策和证据对合格集合完成选型讨论；本轮未替用户选择候选，未进入冻结或PTE。\n'
    text += '''
## 限制与正式交付范围

所有历史均已参与研究和选择；本次补评不是独立样本验证，结果不等于未来优势。年度表现、收益集中和旧研究族选择偏差继续作为诊断，不增加用户未确认的硬门。交易仍按日价格区间且不考虑成交容量；历史17:30数据发布/修订链未认证，当前运行默认20:31，保留既有时钟证据的局限，不扩张为全部历史可得性证明。

本次以正式实验报告及证据包补齐阶段四覆盖。ASSESSMENT/1的98中心及其历史排序保持原样；未伪造只含86中心的ASSESSMENT/2，也未把平台原434日目标校验冒充新增415日比较的机器验收。旧阶段五技术通过及旧C0031选择记录均为历史，不恢复冻结授权。未合并master、推送、打tag或变更生产。
'''
    (EROOT / 'report.md').write_text(text, encoding='utf-8', newline='\n')
    print({'report': 'WRITTEN', 'joint_pass': result['joint_pass']}, flush=True)


def publish():
    assert not (EROOT / 'others/publication_validation.json').exists()
    ctx, repo = context(), RepositoryContext.discover(ROOT)
    result = read(EROOT / 'others/dual_window_results.json')
    protocol = read(EROOT / 'protocols/fixed_set.json')
    refs = [EvidenceRef.from_dict(x) for x in result['account_references']]
    refs += [EvidenceRef.from_dict(protocol[k]) for k in ('source_checks', 'comparative_gate')]
    refs += [EvidenceRef.from_dict(x) for x in protocol['archive_reuse'].values()]
    refs.append(EvidenceRef.from_dict(read(EROOT / 'others/protocol_ref.json')))
    materials = {}
    paths = list((EROOT / 'src').glob('*.py')) + [EROOT / 'others' / name for name in (
        'historical_integrity.json', 'precheck.json', 'parallel_precheck.json', 'recovery_addendum.json',
        'execution_stats.json', 'dual_window_results.json', 'dual_window_results.csv')]
    for path in paths:
        ref = material(ctx, path.stem, path)
        refs.append(ref)
        materials[path.name] = ref.to_dict()
    report_ref = publish_evidence(ctx, ExperimentReportWrite(EX,
        sha256((EROOT / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(refs)))
    check = validate_experiment(repo, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT / 'others/publication_validation.json', {
        'status': check.status.value, 'experiment': check.to_dict(), 'report': report_ref.to_dict(), 'materials': materials})
    assert check.status.value == 'PASS', check.issues
    intent = dict(read(ROOT / 'research/registrations/S015/family.json')['research_intent'])
    intent.update(current_experiment=EX.to_dict(), selected_candidate=None,
        current_phase=f"阶段四固定86候选双窗口补证完成；共同窗口双优{result['joint_pass']}/86",
        current_comparison_report=report_ref.to_dict(),
        next_gate='固定候选覆盖已完成；等待用户决定受限收口或新研究诊断范围，不自动搜索、冻结或PTE')
    update_research_intent(repo, ResearchBatchRef('S015'), ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='用户批准的原86候选双窗口证据覆盖完成，保留历史验收并记录新比较结论。')
    print({'publication': check.status.value, 'joint_pass': result['joint_pass']}, flush=True)


def overview():
    observed = get_research_overview(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'))
    save(ROOT / '.tmp/s015_ex013_overview_full.json', observed.to_dict())
    state = next(x for x in observed.experiments if x.experiment == EX)
    assert state.report_state.value == 'PUBLISHED'
    counts = [{k: v for k, v in x.to_dict().items() if k != 'sources'} for x in observed.counts]
    value = {'status': 'COMPLETED', 'snapshot_sha256': observed.snapshot.content_sha256,
             'source_count': len(observed.snapshot.sources), 'candidate_count': len(observed.candidates),
             'current_experiment': state.to_dict(), 'counts': counts,
             'limitations': [x.to_dict() for x in observed.limitations]}
    save(EROOT / 'others/overview_closeout.json', value)
    ref = material(context(), 'overview_closeout', EROOT / 'others/overview_closeout.json')
    save(EROOT / 'others/overview_ref.json', ref.to_dict())
    print({'overview': 'COMPLETE', 'snapshot': observed.snapshot.content_sha256,
           'registered_candidates': len(observed.candidates), 'current_report': state.report_state.value}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('analyze', 'report', 'publish', 'overview'))
    args = parser.parse_args()
    {'analyze': analyze, 'report': report, 'publish': publish, 'overview': overview}[args.mode]()
