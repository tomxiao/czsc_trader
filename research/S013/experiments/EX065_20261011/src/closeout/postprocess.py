"""Source-only single gap exit closeout draft; explicit future root invocation only.

Consume the runner's authenticated native bundle, never create financial accounts.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
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
RUNNER = ROOT / '.tmp/s013-gap-exit-runner'
RUNNER_SHA = '4c665de0464dcf8949272ce331d618a5d39509592c587023557253e600a34af0'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_sources():
    manifest = read(Path(__file__).parent / 'freeze.json')
    if manifest['status'] != 'SOURCE_ONLY_READY':
        raise ValueError('Root-reviewed source-only manifest required')
    for relative, expected in manifest['frozen_files'].items():
        path = (Path(__file__).parent / relative).resolve()
        if not path.is_relative_to(Path(__file__).parent.resolve()) or digest(path) != expected:
            raise ValueError('Frozen closeout source/proof differs before any native reads')


def runner_module():
    if digest(RUNNER / 'runner.py') != RUNNER_SHA:
        raise ValueError('Reviewed financial runner source differs')
    sys.path.insert(0, str(RUNNER))
    name = '_gap_exit_closeout_execution_runner'
    if name in sys.modules:
        module = sys.modules[name]
        if Path(module.__file__).resolve() != (RUNNER / 'runner.py').resolve():
            raise ValueError('Execution runner module collision')
        return module
    if 'prepared_audit' in sys.modules and Path(sys.modules['prepared_audit'].__file__).resolve() != (RUNNER / 'prepared_audit.py').resolve():
        raise ValueError('Prepared audit module collision')
    spec = importlib.util.spec_from_file_location(name, RUNNER / 'runner.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    if analysis['status'] != 'COMPLETE' or set(analysis['rows']) != {'B0', 'N_GAP_EXIT'}:
        raise ValueError('Both fixed outcomes required, including failed center')
    if bundle['all_new_native_accounts'] != state['accounts'] or bundle['new_actual_evaluations'] != state['attempts']:
        raise ValueError('Immutable bundle and journal differ')
    if analysis['selection'] != selection or set(checks) != set(selection['fivecheck_labels']):
        raise ValueError('Frozen preference or complete selected selfcheck scope differs')
    qualified = []
    expected = set()
    for label in ('B0', 'N_GAP_EXIT'):
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
            elif plans[label]['status'] != 'NOT_APPLICABLE':
                raise ValueError('Failed center must explicitly preserve NOT_APPLICABLE plan')
    if bundle['qualified_registration_candidates'] != qualified:
        raise ValueError('Registration scope must be qualified new centers only')
    for label, check in checks.items():
        if check['diagnostic_only'] is not True or check['center_economic_gate_unchanged'] is not True:
            raise ValueError('Selfchecks cannot introduce a new economic gate')
        if label == 'B0' and 'fee-stress-B0' in state['accounts']:
            raise ValueError('Only exact reused baseline fee is allowed')
        if 'fee-stress-' + label in state['accounts']:
            expected.add('fee-stress-' + label)
        elif label != 'B0':
            raise ValueError('Selected new center independent fee account missing')
    if set(state['accounts']) != expected or set(bundle['account_audits']) != expected:
        raise ValueError('Missing or unexpected standard/technical/fee account roles')
    if any(x['status'] != 'COMPLETE' for x in state['accounts'].values()) or state['attempts'] != len(expected):
        raise ValueError('Incomplete, failed, unknown or miscounted native attempts')
    wanted = 35 if qualified else 2
    if state['attempts'] != wanted:
        raise ValueError('Single center budget is exactly2 or35; no extra P00 or fee')
    counts = {'old_standard_unique': 33, 'old_fee_unique': 1,
        'new_business_unique': 1 + (32 if qualified else 0), 'technical_repeat': 1,
        'new_fee_unique': int(bool(qualified)), 'new_actual': wanted}
    if bundle['account_counts'] != counts:
        raise ValueError('Public exact role counts differ')
    if bundle['technical_reference'] != state.get('technical_reference') or not state.get('technical_reference'):
        raise ValueError('Public serial/spawn exact proof missing or mismatched')
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
    readonly_fee_audits: dict


def collect(method_path, work, exploration_reference_path):
    verify_sources()
    runner = runner_module()
    contract = runner.require_method(method_path, work)
    ctx = runner.context(contract)
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
    refs, roles, centers, path_list, public_plans = {}, [], {}, [], {}
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
    add(state['technical_reference'])
    exploration = add(read(exploration_reference_path))
    if not exploration.experiment.experiment_id.startswith('EX064_'):
        raise ValueError('Exact EX064 public exploratory source evidence required')
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
    for label in ('B0', 'N_GAP_EXIT'):
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
        public_plans[label] = plan
        point_econ = []
        for index, (item, audit) in enumerate(zip(native_items, audits, strict=True)):
            ref = add(item['reference'])
            formal = read(ref.resolve(ROOT))
            validate_evaluation_evidence(formal)
            if label == 'B0' and serialize_evaluation_evidence(*pairs[index]) != formal:
                raise ValueError('Original full33 native serialization differs')
            identity = formal['runs'][0]['identity']
            if label != 'B0':
                expected_id = contract.method['reservation']['center'] if index == 0 else contract.method['reservation']['points'][index - 1]
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
    comparisons = bundle['analysis']['mechanism_comparisons']
    if qualified:
        actual_pairing = draft.pairing_status(public_plans['B0'].design, public_plans['N_GAP_EXIT'].design)
        if actual_pairing != comparisons['N_GAP_EXIT']['pairing']:
            raise ValueError('Actual full13 vectors/types pairing differs from published analysis')
        if actual_pairing['status'] == 'EXACT_NUMERIC_PAIRING':
            expected_pairs = [{'index': i,
                'cagr_difference': bundle['account_audits'][f'N_GAP_EXIT-P{i:02}']['economics']['net_cagr'] - original['point_audits'][i]['economics']['net_cagr'],
                'drawdown_difference': bundle['account_audits'][f'N_GAP_EXIT-P{i:02}']['economics']['drawdown'] - original['point_audits'][i]['economics']['drawdown']}
                for i in range(32)]
            if expected_pairs != comparisons['N_GAP_EXIT']['paired_points']:
                raise ValueError('Whole native complete32 pairing outcome differs')
        elif 'paired_points' in comparisons['N_GAP_EXIT']:
            raise ValueError('Nonidentical vectors cannot claim point pairing')
    elif comparisons:
        raise ValueError('Failed center cannot claim unrun parameter comparison')
    for name, item in state['accounts'].items():
        ref = add(item['reference'])
        audit = bundle['account_audits'][name]
        if (audit != read(contract.work / 'audits' / (name + '.json'))
                or audit['status'] != 'PASS' or audit['whole_formal_native_exact'] is not True
                or audit['public_native_reference'] != ref.to_dict()
                or audit['method_reference'] != contract.method_reference.to_dict()
                or audit['signal']['status'] != 'PASS'):
            raise ValueError('Actual audited-account protocol differs from immutable bundle')
        cache = runner.scoped_path(item['cache_path'])
        if digest(cache) != item['cache_sha256']:
            raise ValueError('Full native cache bytes differ before readonly decode')
        request, result = runner.read_native(cache)
        formal = read(ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        if serialize_evaluation_evidence(request, result) != formal:
            raise ValueError('Whole actual native serialization differs')
        if (request.strategy.candidate_id != item['candidate_id']
                or result.request_hash != item['request_hash'] or result.result_hash != item['result_hash']):
            raise ValueError('Retained actual candidate/request/result identity differs')
        if (audit['signal']['state_audit']['status'] != 'PASS'
                or audit['signal']['cash_audit_is_separate'] is not True
                or audit['account']['quantity_reconciliation'] != 'EXACT_EQUAL'):
            raise ValueError('Separate complete cash and independent feature/state certificates required')
        if name.endswith('-technical-spawn'):
            original_name = name.removesuffix('-technical-spawn')
            if read(ref.resolve(ROOT)) != read(add(state['accounts'][original_name]['reference']).resolve(ROOT)):
                raise ValueError('Whole serial/spawn native evidence differs')
    fee_audits = {}
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
        fee_item = state['accounts'].get('fee-stress-' + label, contract.method['baseline_fee_reuse'])
        cache = runner.scoped_path(fee_item['cache_path'])
        if digest(cache) != fee_item['cache_sha256']:
            raise ValueError('Independent fee cache bytes differ before readonly decode')
        fee_pair = runner.read_native(cache)
        if serialize_evaluation_evidence(*fee_pair) != fee:
            raise ValueError('Whole independent fee native/source identity differs')
        if label == 'B0':
            # Public old native + already bound prepared input only. No prepare/evaluate/provider.
            fee_audits[label] = runner.native_audit(ctx, fee_pair, fee_ref, contract)
        else:
            fee_audits[label] = bundle['account_audits']['fee-stress-' + label]
        if (fee_audits[label]['status'] != 'PASS' or fee_audits[label]['whole_formal_native_exact'] is not True
                or fee_audits[label]['signal']['state_audit']['status'] != 'PASS'
                or fee_audits[label]['account']['quantity_reconciliation'] != 'EXACT_EQUAL'):
            raise ValueError('Whole native fee/cash/independent feature-state audit failed')
        if (fee['request_identity']['price_basis'] != 'HFQ_RESEARCH'
                or len(fee['request_identity']['costs']) != 1
                or fee['request_identity']['costs'][0]['one_way_cost'] != .002):
            raise ValueError('Independent exact double-cost HFQ contract differs')
    standard = len(roles)
    technical = sum(n.endswith('-technical-spawn') for n in state['accounts'])
    fee_new = sum(n.startswith('fee-stress-') for n in state['accounts'])
    fee_old = 1
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
    for label in ('B0', 'N_GAP_EXIT'):
        identifier = 'C8880' if label == 'B0' else contract.method['reservation']['center']
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
        tuple(qualified), tuple(path_list), fee_audits)


def report_text(collected):
    names = {'return': '收益', 'annual_drawdown': '年度回撤', 'frequency': '交易频率',
        'negative_buyhold_year_profit': '基准亏损年盈利'}
    lines = ['# 负跳空修复后的持仓退出对照', '', 'B0精确复用原C8880；N_GAP_EXIT仅在原规则会继续持仓时，遇当日开盘低于上一交易日收盘且收盘高于开盘，发出下一交易日市价退出。原入场、13数值参数、时间/区间/状态退出优先级保持。', '',
        '|组别|净年化|全期最大回撤|每60日闭合交易|原四门|32逐项通过率|32联合通过率|Q10净年化|Q90回撤|',
        '|---|---:|---:|---:|---|---|---:|---:|---:|']
    def pct(v):
        return '未运行' if v is None else f'{v:.4%}'
    for label in ('B0', 'N_GAP_EXIT'):
        row = collected.bundle['analysis']['rows'][label]
        econ, s = row['center_economics'], row['parameter_summary']
        gates = '；'.join(f'{names[g]}={"通过" if v else "未过"}' for g, v in econ['gates'].items())
        rates = '；'.join(f'{names[g]}={n}/32 ({n/32:.2%})' for g, n in row['gate_pass_counts'].items()) if row['parameter_references'] else '中心未过原四门，完整32不适用'
        joint = '未运行' if s['joint_pass_count'] is None else f'{s["joint_pass_count"]}/32 ({s["joint_pass_count"]/32:.2%})'
        lines.append(f'|{label}|{pct(econ["net_cagr"])}|{pct(econ["drawdown"])}|{econ["frequency60"]:.4f}|{gates}|{rates}|{joint}|{pct(s["q10_cagr"])}|{pct(s["q90_drawdown"])}|')
    lines += ['', '四门依次检查净年化收益、各自然年回撤、交易频率及基准亏损年份盈利；自然年连续净值计算沿用原冻结口径。Q10表示扰动后较差一端的收益，Q90表示较差一端的回撤，都是开发池事实。', '',
        '新增退出沿用原策略的signal holding状态，不按实际账户position事后挑选。限价买单未成交也可能产生后续hold/exit信号；本轮经济指标只取完整原生订单、成交与现金账本，不能将信号退出直接当实际卖出收益。', '',
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
        '本轮为EX064负面预测结果启发的探索性后继：原修复越强未来收益越好假说失败，5日控制后IC=-0.054454、95%块区间[-0.099498,-0.006396]、6相位5负；原C8880事前机会池不稳。本次改持仓退出位置，不反转原假说结论。修复也可能是好反弹，提前卖出可能错过恢复并增加费用；全池相关性不是账户改善或因果证据。', '',
        '同一已见开发池反复选择未校正，没有新的封存验证。原已知High/Low异常不修价，输入审核按声明严格拒绝。T信号只能在T收盘得到；次日开盘前发生的价格变化不能当成可赚收益。信号BELOW类别不等于实际成交亏损。现金审核与独立状态核对不保证未来绩效。', '',
        '没有优化参数、增加经济门或自动宣布总体稳健目标达成；阶段四交接与后续研究由用户的既有授权和具体结论另行处理。', '']
    return '\n'.join(lines)


def checked_predecessors(mandate, previous, revision):
    if (mandate.strategy_id != 'S013' or mandate.stage is not d.DeliveryStage.MANDATE
            or mandate.revision != 6 or previous.strategy_id != 'S013'
            or previous.stage is not d.DeliveryStage.CANDIDATES or previous.revision != 56
            or revision != 57):
        raise ValueError('Exact S013 Mandate6/CandidateSet56 -> CandidateSet57 required')


def retained_candidates(repository, previous):
    """Public integrity validation then typed exact predecessor candidates, no re-registration."""
    result = validate_delivery(repository, previous, scope=d.DeliveryValidationScope.INTEGRITY)
    if result.status is not d.ValidationStatus.PASS:
        raise ValueError('CandidateSet56 predecessor integrity failed')
    path = ROOT / f'research/S013/assets/deliveries/CANDIDATES/{previous.revision}/delivery.json'
    document = read(path)
    definition = d.DeliveryDefinition.from_dict(document['definition'])
    content = d.DeliveryContent.from_dict(document['content'])
    if (definition.batch != previous.batch or definition.stage is not previous.stage
            or definition.revision != previous.revision or not isinstance(content.payload, d.CandidateSet)):
        raise ValueError('Typed predecessor CandidateSet identity differs')
    return content.payload.candidates


def finalize(collected, mandate, previous, revision):
    runner, contract = collected.runner, collected.contract
    checked_predecessors(mandate, previous, revision)
    retained = retained_candidates(runner.context(contract).repository, previous)
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
    for entry in retained:
        for evaluation in entry.evaluations:
            reference = checked_ref(evaluation.evidence.to_dict())
            refs[reference.repository_path] = reference
    paths = [*collected.material_paths, out / 'registration.json']
    manifest = {'status': 'PASS', 'counts': collected.counts, 'roles': collected.roles,
        'qualified_new_centers': collected.qualified, 'method_reference': contract.method_reference.to_dict(),
        'new_account_evaluations_by_postprocessor': 0, 'new_account_preparations': 0,
        'readonly_fee_audits': collected.readonly_fee_audits,
        'fee_audit_scope': 'B0 existing public native + existing prepared fetched readonly, full cash/features/state re-audit; new fee retained complete audit.',
        'retained_previous_candidate_keys': [entry.identity.key.to_dict() for entry in retained],
        'original_registered_candidates_not_reregistered': True, 'objective_achieved': False}
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
        ref = publish_evidence(ctx, MaterialEvidenceWrite(contract.experiment, 'gap-exit-closeout-' + h[:32], path.read_bytes(), media, suffix))
        refs[ref.repository_path] = ref
    entries = list(retained)
    for label in collected.qualified:
        row = collected.bundle['analysis']['rows'][label]
        center = next(r for r in collected.roles if r['role'] == label + ':center')
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', center['candidate_id']), center['content_sha256']),
            '固定原C8880参数的负跳空修复持仓退出机制：' + label,
            '原四门合格；完整32与五项自检仅诊断，未自动阶段四交接', (d.EvaluationEvidenceRef(checked_ref(row['center_reference'])),)))
    summary = d.SearchSummary(contract.experiment.experiment_id + '-fixed-gap-repair-exit',
        '固定B0/N_GAP_EXIT；原13域完整32/.05/seed13/HALF_EVEN，中心四门合格才运行新32',
        '同已见开发池、原资金费用及HFQ计价；技术重复与费用单列，B0完整33精确复用',
        collected.counts['all_actual_native_evaluations_including_reuse'], collected.counts['standard_unique_configurations'],
        '仅原四门资格；绝对尾部优选=' + str(collected.bundle['analysis']['selection']['preferred']),
        ('研究族反复选择未校正；无新封存验证；统计区间不是未来收益保证',), tuple(refs.values()))
    payload = d.CandidateSet(tuple(entries), (), (summary,), '修复持仓退出对照完整交付，负面结果同等保留，不自动宣告稳健目标达成。')
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
    for name in ('method-reference', 'work', 'mandate-reference', 'previous-reference', 'exploration-reference'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--delivery-revision', type=int, required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    if digest(__file__) != args.source_sha256:
        parser.error('Postprocessor source SHA differs from root-reviewed source')
    mandate, previous = (d.DeliveryReference.from_dict(read(p)) for p in (args.mandate_reference, args.previous_reference))
    checked_predecessors(mandate, previous, args.delivery_revision)
    collected = collect(args.method_reference, args.work, args.exploration_reference)
    reference = finalize(collected, mandate, previous, args.delivery_revision)
    print({'status': 'PASS', 'reference': reference.to_dict(), 'prepare': 0, 'evaluate': 0})


if __name__ == '__main__':
    main()
