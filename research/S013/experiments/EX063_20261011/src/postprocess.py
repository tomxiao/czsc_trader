"""Source-only management closeout draft; explicit future root invocation only.

Consume the runner's authenticated native bundle, never create financial accounts.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader.application import (CandidateRegistrationRequest, assemble_delivery,
    load_candidate, publish_evidence, register_candidate, validate_delivery)
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from strategy_evaluator import AssessmentPanel
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateKey

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
RUNNER = ROOT / '.tmp/s013-management-runner'
RUNNER_SHA = '8a9d86a30d1c5f98a4a621ef1dc4c26387ec7db0e1f365e8fc28952b364e82e8'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def runner_module():
    if digest(RUNNER / 'runner.py') != RUNNER_SHA:
        raise ValueError('Reviewed financial runner source differs')
    sys.path.insert(0, str(RUNNER))
    import runner
    if Path(runner.__file__).resolve() != (RUNNER / 'runner.py').resolve():
        raise ValueError('Financial runner module collision')
    return runner


def checked_ref(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S013':
        raise ValueError('Only S013 published evidence')
    ref.resolve(ROOT)  # Public API verifies immutable bytes and path.
    return ref


def validate_shape(bundle, state, plans, gates, selection):
    """Pure completeness/count checks, no new economic acceptance criteria."""
    if bundle['status'] != 'NATIVE_EVIDENCE_BUNDLE_COMPLETE' or state['status'] != 'STANDARD_ACCOUNTS_COMPLETE':
        raise ValueError('Complete native bundle and terminal standard-account state required')
    analysis, checks = bundle['analysis'], bundle['fivechecks']
    if analysis['status'] != 'COMPLETE' or set(analysis['rows']) != {'B0', 'N_LOCK', 'N_CURRENT'}:
        raise ValueError('All three economic outcomes required, including failed centers')
    if bundle['all_new_native_accounts'] != state['accounts'] or bundle['new_actual_evaluations'] != state['attempts']:
        raise ValueError('Immutable bundle and journal differ')
    if analysis['selection'] != selection or set(checks) != set(selection['fivecheck_labels']):
        raise ValueError('Frozen preference or complete selected selfcheck scope differs')
    qualified = []
    expected = set()
    for label in ('B0', 'N_LOCK', 'N_CURRENT'):
        row = analysis['rows'][label]
        econ = row['center_economics']
        if set(econ['gates']) != set(gates) or any(type(v) is not bool for v in econ['gates'].values()):
            raise ValueError('Exactly original four boolean gates required')
        if econ['qualified'] is not all(econ['gates'].values()):
            raise ValueError('Original qualification differs from four gates')
        full = label == 'B0' or econ['qualified']
        if len(row['parameter_references']) != (32 if full else 0):
            raise ValueError('Conditional full32 mismatch')
        if label != 'B0':
            expected.update((label, label + '-technical-spawn'))
            if (plans[label]['status'] == 'DECLARED') is not full:
                raise ValueError('Plan status must match center original-four-gate qualification')
            if full:
                qualified.append(label)
                expected.update(f'{label}-P{i:02}' for i in range(32))
                expected.add(label + '-P00-technical-spawn')
            elif plans[label]['status'] != 'NOT_APPLICABLE':
                raise ValueError('Failed center must explicitly preserve NOT_APPLICABLE plan')
    if bundle['qualified_registration_candidates'] != qualified:
        raise ValueError('Registration scope must be qualified new centers only')
    for label, check in checks.items():
        if check['diagnostic_only'] is not True or check['center_economic_gate_unchanged'] is not True:
            raise ValueError('Selfchecks cannot introduce a new economic gate')
        if 'fee-stress-' + label in state['accounts']:
            expected.add('fee-stress-' + label)
        elif label != 'B0':
            raise ValueError('Selected new center independent fee account missing')
    if set(state['accounts']) != expected or set(bundle['account_audits']) != expected:
        raise ValueError('Missing or unexpected standard/technical/fee account roles')
    if any(x['status'] != 'COMPLETE' for x in state['accounts'].values()) or state['attempts'] != len(expected):
        raise ValueError('Incomplete, failed, unknown or miscounted native attempts')
    if state['attempts'] > 72:
        raise ValueError('Frozen actual evaluation budget exceeded')
    return qualified


@dataclass(frozen=True)
class Collected:
    runner: object
    contract: object
    bundle: dict
    centers: dict
    roles: tuple
    evidence: tuple
    counts: dict
    qualified: tuple
    material_paths: tuple


def collect(method_path, work):
    runner = runner_module()
    contract = runner.require_method(method_path, work)
    state = runner.journal(contract)
    local = read(contract.work / 'closeout.json')
    bundle_ref = checked_ref(local['public_bundle_reference'])
    bundle = read(bundle_ref.resolve(ROOT))
    if {k: v for k, v in local.items() if k != 'public_bundle_reference'} != bundle:
        raise ValueError('Actual published native bundle differs from local closeout')
    if bundle['method_reference'] != contract.method_reference.to_dict():
        raise ValueError('Native bundle belongs to another public method')
    if bundle['analysis'] != read(contract.work / 'analysis.json') or bundle['fivechecks'] != read(contract.work / 'selfchecks.json'):
        raise ValueError('Published analysis/selfchecks differ from actual complete artifacts')
    draft, _, _, _ = runner.capabilities()
    original = runner.records(contract)['B0']  # SHA-bound prior prepared cache; no fetch or reassessment.
    point_manifest_ref = checked_ref(state['point_plans_reference'])
    point_manifest = read(point_manifest_ref.resolve(ROOT))
    plan_records = point_manifest['plans']
    summaries = []
    for label, row in bundle['analysis']['rows'].items():
        econ, summary = row['center_economics'], row['parameter_summary']
        summaries.append(draft.Summary(label, tuple(econ['gates'][g] for g in draft.GATES),
            econ['net_cagr'], econ['drawdown'], summary['q10_cagr'], summary['q90_drawdown'], summary['joint_pass_count']))
    qualified = validate_shape(bundle, state, plan_records, draft.GATES, draft.selection(tuple(summaries)))
    refs, roles, centers, path_list = {}, [], {}, []
    def add(value):
        ref = checked_ref(value)
        refs[ref.repository_path] = ref
        return ref
    add(bundle_ref.to_dict())
    add(contract.method_reference.to_dict())
    for key in ('collision_reference', 'input_primer_reference', 'mapping_reference', 'feasibility_reference'):
        add(contract.method[key])
    add(state['records_reference'])
    add(state['point_plans_reference'])
    def linked_refs(value):
        if isinstance(value, dict):
            if {'experiment', 'evidence_id', 'sha256', 'media_type', 'name'} <= set(value):
                add(value)
            else:
                for child in value.values():
                    linked_refs(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                linked_refs(child)
    linked_refs(contract.method)
    linked_refs(read(checked_ref(contract.method['input_primer_reference']).resolve(ROOT)))
    linked_refs(point_manifest)
    for label in ('B0', 'N_LOCK', 'N_CURRENT'):
        row = bundle['analysis']['rows'][label]
        if label == 'B0':
            native_items = [contract.method['baseline_reuse']['center'], *contract.method['baseline_reuse']['points']]
            audits = [original['center_audit'], *original['point_audits']]
            pairs = [original['center'], *original['points']]
            if len(pairs) != 33 or len(audits) != 33:
                raise ValueError('Original full33 authenticated baseline proof missing')
            centers[label] = original['center']
            plan_ref = add(contract.method['baseline_reuse']['plan_reference'])
        else:
            names = [label] + [f'{label}-P{i:02}' for i in range(len(row['parameter_references']))]
            native_items = [state['accounts'][n] for n in names]
            audits = [bundle['account_audits'][n] for n in names]
            if not audits or audits[0]['economics'] != row['center_economics']:
                raise ValueError('Audited center economics differ from published analysis')
            plan_ref = None if plan_records[label]['status'] == 'NOT_APPLICABLE' else add(plan_records[label]['reference'])
        expected_refs = [row['center_reference'], *row['parameter_references']]
        if [x['reference'] for x in native_items] != expected_refs:
            raise ValueError('Published complete center/point reference ordering differs')
        plan = None if plan_ref is None else read_parameter_plan(plan_ref, ROOT)
        point_econ = []
        for index, (item, audit) in enumerate(zip(native_items, audits, strict=True)):
            ref = add(item['reference'])
            formal = read(ref.resolve(ROOT))
            validate_evaluation_evidence(formal)
            identity = formal['runs'][0]['identity']
            if label != 'B0':
                key = 'lock' if label == 'N_LOCK' else 'current'
                expected_id = contract.method['reservation'][key + '_center'] if index == 0 else contract.method['reservation'][key + '_points'][index - 1]
                if item['candidate_id'] != expected_id:
                    raise ValueError('Prospectively collision-checked candidate/point ID differs')
            if (audit['status'] != 'PASS' or audit['whole_formal_native_exact'] is not True
                    or audit['public_native_reference'] != ref.to_dict()
                    or audit['content_sha256'] != item['content_sha256']
                    or audit['method_reference'] != contract.method_reference.to_dict()
                    or audit['signal']['status'] != 'PASS'
                    or identity['content_sha256'] != item['content_sha256']
                    or identity['candidate'] != {'strategy_id': 'S013', 'candidate_id': item['candidate_id']}
                    or formal['request_hash'] != item['request_hash'] or formal['result_hash'] != item['result_hash']):
                raise ValueError('Retained full native/authentication/public identity mismatch')
            if (formal['request_identity']['price_basis'] != 'HFQ_RESEARCH'
                    or len(formal['request_identity']['costs']) != 1
                    or formal['request_identity']['costs'][0]['one_way_cost'] != .001):
                raise ValueError('Frozen standard HFQ/cost contract differs')
            if index and (plan is None or formal['request_identity']['parameter_binding'] != plan.bind_point(plan_ref, index - 1, repository_root=ROOT).to_dict()):
                raise ValueError('Original/native parameter plan role binding differs')
            if index:
                point_econ.append(audit['economics'])
            else:
                if audit['economics'] != row['center_economics']:
                    raise ValueError('Baseline or new center audited economics differ')
                if label != 'B0':
                    derivation = CandidateDerivation.from_dict(formal['request_identity']['lineage'])
                    if derivation.kind is not CandidateDerivationKind.IMPLEMENTATION or derivation.parent != CandidateKey('S013', 'C8880'):
                        raise ValueError('New center must retain exact IMPLEMENTATION parent C8880')
            roles.append({'role': label + (':center' if index == 0 else f':P{index-1:02}'), **item})
        summary = row['parameter_summary']
        counts = {gate: sum(e['gates'][gate] for e in point_econ) for gate in draft.GATES}
        if point_econ:
            actual = draft.summarize(row['center_economics']['net_cagr'], row['center_economics']['drawdown'],
                [e['net_cagr'] for e in point_econ], [e['drawdown'] for e in point_econ],
                [tuple(e['gates'][g] for g in draft.GATES) for e in point_econ])
            if actual != summary:
                raise ValueError('Complete32 retained audited summary differs')
        row['gate_pass_counts'] = counts  # Local report projection; published result is never rewritten.
    for name, item in state['accounts'].items():
        ref = add(item['reference'])
        audit = bundle['account_audits'][name]
        if (audit != read(contract.work / 'audits' / (name + '.json'))
                or audit['status'] != 'PASS' or audit['whole_formal_native_exact'] is not True
                or audit['public_native_reference'] != ref.to_dict()
                or audit['method_reference'] != contract.method_reference.to_dict()
                or audit['signal']['status'] != 'PASS'):
            raise ValueError('Actual audited-account protocol differs from immutable bundle')
        if name.endswith('-technical-spawn'):
            original_name = name.removesuffix('-technical-spawn')
            if read(ref.resolve(ROOT)) != read(add(state['accounts'][original_name]['reference']).resolve(ROOT)):
                raise ValueError('Whole serial/spawn native evidence differs')
    for label, item in bundle['fivechecks'].items():
        AssessmentPanel.from_dict(item['panel'])
        fee_ref = add(item['fee_reference'])
        if 'fee-stress-' + label in state['accounts']:
            if item['fee_reference'] != state['accounts']['fee-stress-' + label]['reference']:
                raise ValueError('Independent fee native evidence differs')
        elif contract.method.get('baseline_fee_reuse') is None or item['fee_reference'] != contract.method['baseline_fee_reuse']['reference']:
            raise ValueError('Missing exact declared baseline fee reuse')
        fee = read(fee_ref.resolve(ROOT))
        validate_evaluation_evidence(fee)
        if (fee['request_identity']['price_basis'] != 'HFQ_RESEARCH'
                or len(fee['request_identity']['costs']) != 1
                or fee['request_identity']['costs'][0]['one_way_cost'] != .002):
            raise ValueError('Independent exact double-cost HFQ contract differs')
    standard = len(roles)
    technical = sum(n.endswith('-technical-spawn') for n in state['accounts'])
    fee_new = sum(n.startswith('fee-stress-') for n in state['accounts'])
    fee_old = int('fee-stress-B0' not in state['accounts'])
    unique = len({r['content_sha256'] for r in roles})
    counts = {'standard_roles': standard, 'standard_unique_configurations': unique,
        'reused_baseline_accounts': 33, 'new_standard_business_evaluations': standard - 33,
        'new_unique_standard_configurations': len({r['content_sha256'] for r in roles}
            - {r['content_sha256'] for r in roles if r['role'].startswith('B0:')}),
        'new_technical_evaluations': technical, 'new_fee_evaluations': fee_new,
        'reused_fee_accounts': fee_old, 'new_actual_evaluations': state['attempts'],
        'all_actual_native_evaluations_including_reuse': 33 + state['attempts'] + fee_old}
    if state['attempts'] != standard - 33 + technical + fee_new:
        raise ValueError('Standard/technical/fee accounting does not conserve')
    path_list += [contract.work / n for n in ('journal.json', 'closeout.json', 'analysis.json', 'selfchecks.json')]
    path_list += list(contract.work.glob('*.json'))  # Includes retained protocol/technical failures.
    path_list += list((contract.work / 'audits').glob('*.json'))
    path_list += list((contract.experiment.resolve(ROOT) / 'protocols').glob('*.json'))
    path_list += [ROOT / n for n in contract.method['external_source_files']]
    path_list += [RUNNER / n for n in contract.method['runner_source_files']]
    for label in ('B0', 'N_LOCK', 'N_CURRENT'):
        identifier = 'C8880' if label == 'B0' else contract.method['reservation']['lock_center' if label == 'N_LOCK' else 'current_center']
        candidate = draft.candidate(label, identifier, contract.method['policy_parameters'][label])
        formal_root = runner.scoped_path(contract.method['source_roots'][label])
        for relative in candidate.payload['runtime']['source_files']:
            if digest(formal_root / relative) != digest(candidate.source_root / relative):
                raise ValueError('Formal runtime closure differs from frozen policy source')
            path_list.append(formal_root / relative)
    source_manifest = read(Path(__file__).parent / 'freeze.json')
    for relative, h in source_manifest['frozen_files'].items():
        path = Path(__file__).parent / relative
        if digest(path) != h:
            raise ValueError('Reviewed closeout closure drift')
        path_list.append(path)
    path_list.append(Path(__file__).parent / 'freeze.json')
    return Collected(runner, contract, bundle, centers, tuple(roles), tuple(refs.values()), counts,
        tuple(qualified), tuple(path_list))


def report_text(collected):
    names = {'return': '收益', 'annual_drawdown': '年度回撤', 'frequency': '交易频率',
        'negative_buyhold_year_profit': '基准亏损年盈利'}
    lines = ['# 持仓管理最小机制对照', '', 'B0保留原规则；N_LOCK关闭行情类别变化时的立即退出；N_CURRENT在持仓中改用当前行情类别的管理规则。入场身份、持有时钟、锚点及退出记忆均保持冻结定义。', '',
        '|组别|净年化|全期最大回撤|每60日闭合交易|原四门|32逐项通过率|32联合通过率|Q10净年化|Q90回撤|',
        '|---|---:|---:|---:|---|---|---:|---:|---:|']
    def pct(v):
        return '未运行' if v is None else f'{v:.4%}'
    for label in ('B0', 'N_LOCK', 'N_CURRENT'):
        row = collected.bundle['analysis']['rows'][label]
        econ, s = row['center_economics'], row['parameter_summary']
        gates = '；'.join(f'{names[g]}={"通过" if v else "未过"}' for g, v in econ['gates'].items())
        rates = '；'.join(f'{names[g]}={n}/32 ({n/32:.2%})' for g, n in row['gate_pass_counts'].items()) if row['parameter_references'] else '中心未过原四门，完整32不适用'
        joint = '未运行' if s['joint_pass_count'] is None else f'{s["joint_pass_count"]}/32 ({s["joint_pass_count"]/32:.2%})'
        lines.append(f'|{label}|{pct(econ["net_cagr"])}|{pct(econ["drawdown"])}|{econ["frequency60"]:.4f}|{gates}|{rates}|{joint}|{pct(s["q10_cagr"])}|{pct(s["q90_drawdown"])}|')
    lines += ['', '四门依次检查净年化收益、各自然年回撤、交易频率及基准亏损年份盈利；自然年连续净值计算沿用原冻结口径。Q10表示扰动后较差一端的收益，Q90表示较差一端的回撤，都是开发池事实。', '',
        '优选：' + str(collected.bundle['analysis']['selection']['preferred']) + '。仅原四门合格的新中心登记；没有优选或全部新机制失败时也完整交付负面结果。自检与尾部诊断不增加经济资格门。', '', '五项自检（参数、时间、盈利集中、独立双倍费用、统计不确定性）：', '']
    metrics = {'PARAMETER_RETURN_DEGRADATION': '参数扰动收益退化',
        'PARAMETER_DRAWDOWN_DEGRADATION': '参数扰动回撤退化', 'ROLLING_EXCESS_Q10': '时间窗口较差端超额收益',
        'STRESS_ANNUAL_LOSS': '双倍费用年化损失', 'PROFIT_CONCENTRATION': '盈利集中度',
        'FULL_SAMPLE_FREQUENCY': '全样本交易频率', 'NET_ANNUAL_RETURN': '净年化收益',
        'DRAWDOWN_MAGNITUDE': '回撤幅度', 'FREQUENCY_MEDIAN': '窗口频率中位数', 'FREQUENCY_Q10': '窗口频率较差端'}
    for label, item in collected.bundle['fivechecks'].items():
        lines += [label + '：', '', '|诊断|实际值|公共状态|', '|---|---:|---|']
        for row in item['panel']['rows']:
            for diagnostic in row['diagnostics']:
                lines.append(f'|{metrics[diagnostic["metric"]]}|{diagnostic["value"]}|{diagnostic["status"]}|')
            lines += ['', '统计不确定性（公共SE原始结果）：' + json.dumps(row['uncertainty'], ensure_ascii=False), '']
    lines += ['', '|组别|自然年|策略净收益|策略回撤|基准净收益|基准回撤|', '|---|---|---:|---:|---:|---:|']
    for label, row in collected.bundle['analysis']['rows'].items():
        econ = row['center_economics']
        for year, annual in econ['annual'].items():
            benchmark = econ['benchmark_annual'][year]
            lines.append(f'|{label}|{year}|{pct(annual["return"])}|{pct(annual["drawdown"])}|{pct(benchmark["return"])}|{pct(benchmark["drawdown"])}|')
    lines += ['', '实际评价与复用计数：' + json.dumps(collected.counts, ensure_ascii=False), '',
        '本轮使用同一已见开发池，研究族反复选择未校正，也没有新的封存样本验证。此前已知行情High/Low异常保留原状。既有现金审核与独立状态核对不能保证未来收益、未来回撤或全部成交政策。结果只评价这两个固定管理变化，不证明所有新策略表达都不可能。', '',
        '没有优化参数、增加经济门或自动宣布总体稳健目标达成；阶段四交接与后续研究由用户的既有授权和具体结论另行处理。', '']
    return '\n'.join(lines)


def finalize(collected, mandate, previous, revision):
    runner, contract = collected.runner, collected.contract
    out = contract.work / 'formal-closeout'
    if out.exists():
        raise ValueError('Existing closeout attempt cannot be silently overwritten or retried')
    out.mkdir()
    ctx = runner.context(contract)
    registration = []
    for label in collected.qualified:
        item = runner.journal(contract)['accounts'][label]
        path = runner.scoped_path(item['cache_path'])
        if digest(path) != item['cache_sha256']:
            raise ValueError('Center cache differs before registration decode')
        request, result = runner.read_native(path)
        reference = checked_ref(item['reference'])
        if serialize_evaluation_evidence(request, result) != read(reference.resolve(ROOT)):
            raise ValueError('Exact center native serialization differs before registration')
        derivation = request.lineage.derivation
        if derivation.kind is not CandidateDerivationKind.IMPLEMENTATION or derivation.parent != CandidateKey('S013', 'C8880'):
            raise ValueError('Only actual IMPLEMENTATION-derived new centers may register')
        if (dict(request.strategy.payload['parameters']) != contract.method['policy_parameters'][label]
                or request.strategy.source_root.resolve() != runner.scoped_path(contract.method['source_roots'][label])
                or derivation.parent_content_sha256 != contract.method['baseline_reuse']['center']['content_sha256']):
            raise ValueError('Actual frozen center parameters/source/parent content differ')
        record = register_candidate(ctx.repository, CandidateRegistrationRequest(request.strategy,
            contract.experiment, (reference,), request.dependencies, derivation))
        if ctx.runtime.identify(load_candidate(ctx.repository, record.key), dependencies=request.dependencies).content_sha256 != item['content_sha256']:
            raise ValueError('Registered runtime identity differs')
        registration.append(record.to_dict())
        runner.write(out / 'registration.json', {'status': 'IN_PROGRESS', 'registrations': registration})
    runner.write(out / 'registration.json', {'status': 'PASS', 'registrations': registration,
        'baseline_not_reregistered': True, 'parameter_points_not_registered': True})
    refs = {r.repository_path: r for r in collected.evidence}
    paths = [*collected.material_paths, out / 'registration.json']
    manifest = {'status': 'PASS', 'counts': collected.counts, 'roles': collected.roles,
        'qualified_new_centers': collected.qualified, 'method_reference': contract.method_reference.to_dict(),
        'new_account_evaluations_by_postprocessor': 0, 'new_account_preparations': 0}
    runner.write(out / 'verification.json', manifest)
    paths.append(out / 'verification.json')
    report = report_text(collected)
    (out / 'report.md').write_text(report, encoding='utf-8')
    seen = set()
    for path in paths:
        h = digest(path)
        if h in seen:
            continue
        seen.add(h)
        suffix = path.suffix.removeprefix('.')
        media = 'application/json' if suffix == 'json' else 'text/plain'
        ref = publish_evidence(ctx, MaterialEvidenceWrite(contract.experiment, 'management-closeout-' + h[:32], path.read_bytes(), media, suffix))
        refs[ref.repository_path] = ref
    entries = []
    for label in collected.qualified:
        row = collected.bundle['analysis']['rows'][label]
        center = next(r for r in collected.roles if r['role'] == label + ':center')
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', center['candidate_id']), center['content_sha256']),
            '固定原C8880参数的持仓管理机制对照：' + label,
            '原四门合格；完整32与五项自检仅诊断，未自动阶段四交接', (d.EvaluationEvidenceRef(checked_ref(row['center_reference'])),)))
    summary = d.SearchSummary(contract.experiment.experiment_id + '-fixed-management',
        '固定B0/N_LOCK/N_CURRENT；原13域完整32/.05/seed13/HALF_EVEN，中心四门合格才运行新32',
        '同已见开发池、原资金费用及HFQ计价；技术重复与费用单列，B0完整33精确复用',
        collected.counts['all_actual_native_evaluations_including_reuse'], collected.counts['standard_unique_configurations'],
        '仅原四门资格；绝对尾部优选=' + str(collected.bundle['analysis']['selection']['preferred']),
        ('研究族反复选择未校正；无新封存验证；统计区间不是未来收益保证',), tuple(refs.values()))
    payload = d.CandidateSet(tuple(entries), (), (summary,), '固定管理对照完整交付，负面结果同等保留，不自动宣告稳健目标达成。')
    for ref in refs.values():
        report += f'\n- [证据 {ref.name}](../../../assets/deliveries/CANDIDATES/{revision}/{ref.path})'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES,
        revision, (mandate, previous)), d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(refs.values())))
    runner.write(out / 'delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    runner.write(out / 'delivery_validation.json', validation.to_dict())
    if validation.status.value != 'PASS':
        raise ValueError('Actual FULL validation failed; preserve receipt and failure, no implicit retry')
    return receipt.reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('method-reference', 'work', 'mandate-reference', 'previous-reference'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--delivery-revision', type=int, required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    if digest(__file__) != args.source_sha256:
        parser.error('Postprocessor source SHA differs from root-reviewed source')
    mandate, previous = (d.DeliveryReference.from_dict(read(p)) for p in (args.mandate_reference, args.previous_reference))
    if (mandate.strategy_id != 'S013' or mandate.stage is not d.DeliveryStage.MANDATE
            or previous.strategy_id != 'S013' or previous.stage is not d.DeliveryStage.CANDIDATES
            or args.delivery_revision <= previous.revision):
        parser.error('S013 mandate and previous candidate delivery with increasing revision required')
    collected = collect(args.method_reference, args.work)
    reference = finalize(collected, mandate, previous, args.delivery_revision)
    print({'status': 'PASS', 'reference': reference.to_dict(), 'prepare': 0, 'evaluate': 0})


if __name__ == '__main__':
    main()
