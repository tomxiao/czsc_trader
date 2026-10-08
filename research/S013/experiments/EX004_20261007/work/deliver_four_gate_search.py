"""Publish bounded S013 research evidence and every four-gate candidate."""
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
import json
from strategy_runtime import StrategyInputBinding
from strategy_manager import CandidateKey
from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, load_candidate,
    publish_evidence, register_candidate, validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, WORK, DEPENDENCIES, context, save, cache_read
from common import request as original_request, candidate as original_candidate
from common_adaptive import request as adaptive_request, candidate as adaptive_candidate
from economics_r4 import summarize
from report_four_gate import build_report, LABELS


def content(stage, revision):
    value = json.loads((ROOT / f'research/S013/deliveries/{stage}/{revision}/delivery.json').read_text(encoding='utf-8'))
    return d.DeliveryContent.from_dict(value['content'])


def reference(stage, revision):
    value = json.loads((ROOT / f'research/S013/deliveries/{stage}/{revision}/receipt.json').read_text(encoding='utf-8'))
    return d.DeliveryReceipt.from_dict(value).reference


def main():
    research, experiment = context(4), ExperimentRef('S013', 'EX004_20261007')
    rows = json.loads((WORK / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    analysis = json.loads((WORK / 'four_gate_search_analysis.json').read_text(encoding='utf-8'))
    quality = json.loads((WORK / 'quality_impact_r4.json').read_text(encoding='utf-8'))
    assert analysis['successful_configurations'] == quality['successful_configurations']
    assert quality['potential_economic_change_count'] == 0
    assert analysis['qualified_ids'] == [r['candidate_id'] for r in rows if r['status'] == 'SUCCEEDED' and r['qualified']]
    refs = {}
    refs['stage-two-data'] = next(e for e in content('COMPONENTS', 1).evidence if e.name == 'stage-two-data')
    refs['stage-two-data'].resolve(ROOT)

    def material(name, filename, media='application/json'):
        path = WORK / filename
        ref = publish_evidence(research, MaterialEvidenceWrite(experiment, name, path.read_bytes(), media, path.suffix[1:]))
        refs[name] = ref
        return ref

    for name, filename in (
        ('four-gate-search-results', 'search_results_r4.json'),
        ('four-gate-search-analysis', 'four_gate_search_analysis.json'),
        ('four-gate-quality-impact', 'quality_impact_r4.json'),
        ('four-gate-loss-diagnostics', 'loss_diagnostics_20261008.json'),
        ('four-gate-adaptive-controls', 'adaptive_controls_20261008.json'),
        ('four-gate-adaptive-attribution', 'adaptive_attribution_20261008.json'),
        ('four-gate-adaptive-input-control', 'adaptive_input_control_20261008.json'),
    ):
        material(name, filename)
    for path in sorted(WORK.glob('four_gate_*_plan.json')):
        comparisons = path.name.replace('_plan.json', '_comparisons.json')
        value = json.loads((WORK / comparisons).read_text(encoding='utf-8'))
        assert value['status'] == 'COMPLETE', path.name
        material(path.stem.replace('_', '-'), path.name)
        material(path.stem.replace('_plan', '-coverage').replace('_', '-'), comparisons)
    stopping = (WORK / 'four_gate_stopping_review.md').read_text(encoding='utf-8')
    material('four-gate-stopping-review', 'four_gate_stopping_review.md', 'text/markdown')
    save('four_gate_continuation_authorization.json', {
        'date': '2026-10-08', 'source': '本主会话真实用户确认', 'user_message': '同意',
        'approved_proposal': '继续阶段三，针对亏损年份研究盈利机制，暂不进入阶段四',
        'scope': '仅S013、510500.SH、原窗口/费用/HFQ单位、现有DFLS与依赖，在codex/s013-research开展机制对照和搜索',
        'phase_four': '本次尚未执行，须另获批准',
    })
    material('four-gate-continuation-authorization', 'four_gate_continuation_authorization.json')
    source_files = sorted({p.name for p in WORK.glob('*.py') if any(key in p.name for key in ('adaptive', 'four_gate', '_r4'))})
    source_files += ['common.py', 'economics.py', 'search.py',
                     'strategy_runtime/strategies/range_reversion.py',
                     'extended_window/strategy_runtime/strategies/range_reversion.py',
                     'adaptive_range/strategy_runtime/strategies/adaptive_range.py',
                     'adaptive_range/strategy_runtime/strategies/range_reversion.py']
    save('four_gate_reproduction_sources.json', {
        'files': {p: {'sha256': sha256((WORK / p).read_bytes()).hexdigest(),
                      'source': (WORK / p).read_text(encoding='utf-8')} for p in source_files},
        'versions': {n: version(n) for n in ('numpy', 'pandas', 'optuna', 'czsc-strategy-runtime')},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'pricing': quality['pricing'], 'execution_data_identity': quality['execution_data_identity'],
        'platform_commit': '93ae9e15', 'platform_changes': '本轮无', 'full_regression': '本轮未执行',
        'data_retention': '保留research/S013/data及原准备引用；Git不含DFLS资产，临时缓存不是正式证据的唯一位置',
    })
    material('four-gate-reproduction-sources', 'four_gate_reproduction_sources.json')
    by_id = {r['candidate_id']: r for r in rows if r['status'] == 'SUCCEEDED'}
    old_entries = {e.identity.key.candidate_id: e for e in content('CANDIDATES', 2).payload.candidates}
    first, baseline = cache_read(ROOT / '.tmp/s013-stage3-hfq/precheck.pkl.gz')
    account_refs = {}

    def account(identifier):
        if identifier in account_refs:
            return account_refs[identifier]
        row = by_id[identifier]
        if identifier in old_entries:
            ref = old_entries[identifier].evaluations[0].evidence
            ref.resolve(ROOT)
        else:
            result = baseline if identifier == 'C0001' else cache_read(ROOT / f'.tmp/s013-stage3-hfq/{identifier}.pkl.gz')
            calculated = summarize(result)
            for k in ('net_cagr', 'closed_trades', 'annual', 'gates', 'result_hash', 'content_sha256'):
                assert calculated[k] == row[k], (identifier, k)
            factory = adaptive_request if 'bull' in row['parameters'] else original_request
            bound = replace(factory(int(identifier[1:]), row['parameters'], first.execution_data), input_bindings={
                run.window_id: StrategyInputBinding.from_mapping(run.signals.support_data['input_binding']) for run in result.runs})
            ref = publish_evidence(research, EvaluationEvidenceWrite(experiment,
                f'four-gate-account-{identifier.lower()}', bound, result))
        account_refs[identifier] = ref
        return ref

    # Preserve both FULL sides of all three source controls; only relevant
    # candidates are registered, avoiding registration of every search trial.
    controls = json.loads((WORK / 'adaptive_controls_20261008.json').read_text(encoding='utf-8'))
    for check in controls['checks']:
        for side in ('original', 'adaptive'):
            c = check[side]['candidate_id']
            refs[f'control-account-{c.lower()}'] = account(c)
    entries, records = [], []
    for c in analysis['retained_ids']:
        row, ref = by_id[c], account(c)
        if c in old_entries:
            identity = old_entries[c].identity
        else:
            factory = adaptive_candidate if 'bull' in row['parameters'] else original_candidate
            registration = register_candidate(research.repository, CandidateRegistrationRequest(
                factory(int(c[1:]), row['parameters']), experiment, (ref,), DEPENDENCIES))
            assert registration.content_sha256 == row['content_sha256']
            identity = d.CandidateIdentityRef(registration.key, registration.content_sha256)
            records.append(registration.to_dict())
        loaded = load_candidate(research.repository, CandidateKey('S013', c))
        assert dict(loaded.payload['parameters']) == row['parameters']
        assert identity.content_sha256 == row['content_sha256']
        failed = '、'.join(LABELS[k] for k, v in row['gates'].items() if not v)
        entries.append(d.CandidateEntry(identity,
            'T日区间反转、相关性过滤及动量状态分工形成T+1可执行策略；具体路线和退出由不可变源码/参数定义。',
            '四项目标同时通过，建议进入阶段四自检' if row['qualified'] else '必要前沿或反证，未通过：' + failed,
            (d.EvaluationEvidenceRef(ref),)))
    save('four_gate_selected_account_references.json', {k: v.to_dict() for k, v in account_refs.items()})
    save('four_gate_selected_registrations.json', {'new_registrations': records, 'retained_ids': analysis['retained_ids']})
    material('four-gate-selected-account-references', 'four_gate_selected_account_references.json')
    report = build_report(analysis, rows, refs, account_refs, stopping, quality)
    conclusion = (f"全部四项达标{len(analysis['qualified_ids'])}个，全部交接；建议进入阶段四标准自检。"
                  if analysis['qualified_ids'] else '当前未发现四门同时达标配置；请按停止评审决定后续方向。')
    searches = tuple(d.SearchSummary(name, 'Optuna固定队列、配置去重、公开TDR完整账户评价',
        '510500.SH原1636交易日、HFQ_RESEARCH、原费用与单位，开发池反复使用',
        group['attempts'], group['successful_configurations'],
        '按用户四项字面条件同时核验，全部达标及已声明前沿/反证保留',
        ('全开发池已见并用于选择，无独立保留样本', '固定对照后按改善线索扩边，不是阶段四正式排名'),
        (refs['four-gate-search-results'], refs['four-gate-search-analysis'])) for name, group in analysis['groups'].items())
    payload = d.CandidateSet(tuple(entries), tuple(CandidateKey('S013', c) for c in analysis['qualified_ids']), searches, conclusion)
    facts = (d.FactValue('qualified_count', len(analysis['qualified_ids']), '个不同配置', d.FactStatus.AVAILABLE,
                         (refs['four-gate-search-results'],)),)
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 3,
                             (reference('MANDATE', 4), reference('CANDIDATES', 2))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, facts, (), report=report,
                          evidence=tuple(dict.fromkeys(refs.values()))))
    checked = validate_delivery(research.repository, receipt.reference)
    assert checked.status == d.ValidationStatus.PASS, checked.to_dict()
    for filename, value in (('stage3_r3_reference.json', receipt.reference.to_dict()),
                            ('stage3_r3_validation.json', checked.to_dict())):
        save(filename, value)
        target = ROOT / 'research/S013/materials' / filename.replace('stage3_r3', 'stage3_candidates').replace('.json', '_r3_20261008.json')
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'validation': checked.to_dict(),
                      'qualified': len(analysis['qualified_ids']), 'retained': len(entries),
                      'new_registrations': len(records)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
