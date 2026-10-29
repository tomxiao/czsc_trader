"""Render and publish one experiment report; shared stage panels are separate."""
from hashlib import sha256
from dataclasses import asdict
import argparse
import json

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, ExperimentOutcome, ExperimentReportWrite,
    MaterialEvidenceWrite, ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity
from czsc_trader.research_tools.experiment_artifacts import ExperimentReportSnapshot
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256
from run import (ROOT, WORK, REPOSITORY, EXPERIMENT, DATA_READINESS, context, read, save,
                 material, configurations, candidate, decision_evidence)
from analyze import (OLD_CONTROLS, comparison_pairs, verify_contracts, verify_hold_path,
                     summarize_run, goals)
from describe_entries import describe


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticated_json(reference):
    content = reference.resolve(ROOT).read_bytes()
    if sha256(content).hexdigest() != reference.sha256:
        raise ValueError('published bytes changed after reference authentication')
    return json.loads(content)


def upstream_evidence():
    """Reuse EX009's immutable published sources; never republish or modify them."""
    origin = ExperimentRef('S017', 'EX009_20261029')
    publication = read(origin.resolve(ROOT) / 'others/publication.json')
    report_ref = EvidenceRef.from_dict(publication['report'])
    if (publication['validation']['status'] != 'PASS'
            or publication['validation']['scope'] != 'REPORT_PUBLICATION'
            or EvidenceRef.from_dict(publication['validation']['report']) != report_ref
            or report_ref.experiment != origin
            or (report_ref.schema, report_ref.schema_version) != ('experiment_report', 1)):
        raise ValueError('EX009 published report identity or validation differs')
    report = ExperimentReportSnapshot.from_dict(authenticated_json(report_ref))
    if report.experiment != origin or report.outcome is not ExperimentOutcome.COMPLETED:
        raise ValueError('EX009 source report is not a completed original publication')
    retained = tuple(EvidenceRef.from_dict(value) for value in publication['evidence'])
    result = {'report': report_ref}
    for name in ('method-sources', 'data-readiness'):
        matches = [ref for ref in retained if ref.name == name]
        if len(matches) != 1 or matches[0].experiment != origin or matches[0] not in report.evidence:
            raise ValueError('EX009 source reference is missing, duplicated or outside its published report: ' + name)
        matches[0].resolve(ROOT)
        result[name] = matches[0]
    if result['data-readiness'].sha256 != digest(DATA_READINESS):
        raise ValueError('joint prepared data readiness differs from the original EX009 evidence')
    return result


def read_account_views(work, experiment, keys, *, exact=False):
    """Rebind immutable views; economic audit belongs to analysis and public diagnosis.

    inputs() also requires the exact analysis source/references and every published
    COMPUTED diagnosis with matching source accounts. This is not an audit cache or
    a substitute for the final public delivery validation.
    """
    records = read(work / 'others/accounts.json')
    if (exact and set(records) != set(keys)) or not set(keys) <= set(records):
        raise ValueError('account manifest differs from the fixed report candidate set')
    payloads, references = {}, {}
    for key in keys:
        record = records[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if (reference.experiment != experiment or reference.media_type != 'application/json'
                or (reference.schema, reference.schema_version) != ('equity_research', 2)):
            raise ValueError('account reference experiment or schema differs')
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('account evidence bytes changed after reference authentication')
        payload = EquityEvaluationResult(record['request_hash'], content).payload
        request = payload['request']
        identity = dict(payload['evaluation_identity'])
        identity['candidate'] = CandidateKey(**identity['candidate'])
        identity = EvaluationIdentity(**identity)
        if (payload.get('schema') != 'equity-research/v2' or payload.get('schema_version') != 2
                or set(payload['runs']) != {'candidate', 'buy_hold'}
                or identity.to_dict() != record['evaluation_identity']
                or identity.evaluation_id != payload['evaluation_id']
                or identity.evaluation_id != record['evaluation_id']
                or identity.candidate != CandidateKey(experiment.strategy_id, key)
                or request['candidate_id'] != key
                or request['experiment'] != {'strategy_id': experiment.strategy_id, 'experiment_id': experiment.experiment_id}
                or identity.content_sha256 != request['candidate_identity']['content_sha256']
                or identity.content_sha256 != request['content_sha256']
                or identity.input_sha256 != request['data_manifest']
                or identity.protocol_sha256 != record['request_hash']
                or identity.environment_sha256 != canonical_sha256(request['engine_sources'])):
            raise ValueError('report account identity differs from the immutable result or manifest')
        payloads[key], references[key] = payload, reference
    return payloads, references


def inputs():
    analysis = read(WORK / 'others/analysis.json')
    precheck = read(WORK / 'others/precheck.json')
    accounts = read(WORK / 'others/accounts.json')
    definitions = read(WORK / 'protocols/definitions.json')
    configs = configurations()
    keys = tuple(configs)
    if analysis['experiment'] != EXPERIMENT.experiment_id or analysis['status'] != 'PASS':
        raise ValueError('this experiment requires complete authenticated analysis before report publication')
    if precheck['status'] != 'PASS' or precheck['strategy_source_sha256'] != digest(WORK / 'src/strategy.py'):
        raise ValueError('precheck does not authenticate the exact strategy source')
    if analysis['analysis_source_sha256'] != digest(WORK / 'src/analyze.py'):
        raise ValueError('analysis source changed after the retained analysis')
    if set(accounts) != set(keys) or set(definitions) != set(keys):
        raise ValueError('accounts and definitions must cover every fixed configuration exactly')
    execution = read(WORK / 'others/execution_status.json')
    if (len(execution) != len(keys) or {row['candidate'] for row in execution} != set(keys)
            or any(row['status'] != 'SUCCEEDED' for row in execution)
            or any(row['publication_status'] != 'PUBLISHED' for row in accounts.values())):
        raise ValueError('failed or unpublished evaluations cannot become a completed report')
    payloads, references = read_account_views(WORK, EXPERIMENT, keys, exact=True)
    for key, experiment in OLD_CONTROLS.items():
        old, old_refs = read_account_views(experiment.resolve(ROOT), experiment, (key,))
        payloads.update(old)
        references.update(old_refs)
    if (analysis['source_accounts'] != {key: ref.to_dict() for key, ref in references.items()}
            or set(analysis['summaries']) != set(payloads)):
        raise ValueError('analysis account references differ from authenticated source accounts')
    if analysis['contract_checks'] != verify_contracts(payloads) or analysis['paired_buyhold_check'] != verify_hold_path(payloads):
        raise ValueError('analysis comparison checks differ from the actual retained inputs')
    for key, payload in payloads.items():
        own = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        benchmark = summarize_run(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        checks = goals(own, benchmark)
        expected = {'candidate': own, 'benchmark': benchmark, 'goals': checks, 'all_goals_met': all(checks.values())}
        if analysis['summaries'][key] != expected:
            raise ValueError('report summary differs from authenticated account facts: ' + key)
    for key in keys:
        cand = candidate(key, configs[key])
        actual = json.loads(json.dumps(cand.definition.to_dict(), default=str))
        identity = accounts[key]['evaluation_identity']
        if (definitions[key] != actual or identity['content_sha256'] != cand.content_identity.content_sha256
                or identity['candidate'] != {'strategy_id': 'S017', 'candidate_id': key}):
            raise ValueError('published candidate source, definition or identity differs: ' + key)
    pre = {key: EvidenceRef.from_dict(value) for key, value in read(WORK / 'others/pre_run_evidence.json').items()}
    expected_material = {
        'design': WORK / 'protocols/design.md', 'authorization': WORK / 'protocols/authorization.md',
        'configurations': WORK / 'protocols/configurations.json',
        'candidate-contracts': WORK / 'protocols/candidate_contracts.json',
        'definitions': WORK / 'protocols/definitions.json', 'runner': WORK / 'src/run.py',
        'precheck': WORK / 'others/precheck.json', 'source': WORK / 'src/strategy.py',
        'data-readiness': DATA_READINESS,
        'primary-preparation': ROOT / 'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json',
        'precheck-source': WORK / 'src/precheck.py',
        'mechanism-check-source': WORK / 'src/check_mechanism.py',
        'mechanism-check': WORK / 'others/precheck_mechanism.json',
    }
    decision_materials, decision_refs = decision_evidence()
    expected_material.update(decision_materials)
    if any(references[key] != reference for key, reference in decision_refs.items()):
        raise ValueError('report controls differ from the original decision evidence')
    if not set(expected_material) <= set(pre) or any(ref.experiment != EXPERIMENT for ref in pre.values()):
        raise ValueError('pre-run materials are missing or belong to a different experiment')
    for name, path in expected_material.items():
        pre[name].resolve(ROOT)
        if pre[name].sha256 != digest(path):
            raise ValueError('pre-run material changed after formal evaluation: ' + name)
    pairs = comparison_pairs(keys)
    if set(analysis['diagnostics']) != {subject + '_vs_' + control for subject, control in pairs}:
        raise ValueError('public diagnoses do not cover the fixed comparisons')
    diagnostic_refs = {}
    for name, value in analysis['diagnostics'].items():
        ref = EvidenceRef.from_dict(value['evidence'])
        if ref.experiment != EXPERIMENT or value['status'] != 'COMPUTED' or value['issues']:
            raise ValueError('diagnosis is incomplete or belongs to another experiment')
        raw = authenticated_json(ref)
        if (raw['status'] != value['status'] or raw['issues'] != value['issues']
                or raw['reconciliation'] != value['reconciliation']):
            raise ValueError('diagnosis summary differs from published diagnosis')
        subject, control = name.split('_vs_')
        if raw['sources'] != [asdict(references[control]), asdict(references[subject])]:
            raise ValueError('public diagnosis uses different original accounts')
        diagnostic_refs[name] = ref
    if (analysis['new_configurations'] != len(keys) or analysis['formal_requests'] != len(keys)
            or analysis['account_replays'] != len(keys) * 2 or analysis['public_diagnoses'] != len(pairs)):
        raise ValueError('analysis counts differ from complete account and diagnosis coverage')
    for item in analysis['method_sources']:
        path = ROOT / item['path']
        if not path.resolve().is_relative_to((ROOT / 'research/S017').resolve()) or digest(path) != item['sha256']:
            raise ValueError('retained method source differs from its recorded identity')
    if (analysis['entry_exit_description_source_sha256'] != digest(WORK / 'src/describe_entries.py')
            or analysis['entry_exit_description'] != {key: describe(payload) for key, payload in payloads.items()}):
        raise ValueError('entry/exit description changed')
    return analysis, keys, definitions, references, pre, diagnostic_refs, pairs


def percent(value):
    return '无完整窗口' if value is None else f'{100 * value:.2f}%'


def render_report(analysis):
    judgment = read(WORK / 'others/judgment.json')
    if judgment['analysis_sha256'] != digest(WORK / 'others/analysis.json') or not judgment['conclusion']:
        raise ValueError('research judgment must bind the completed exact analysis')
    summaries = analysis['summaries']
    rows = [('同合同买入持有', summaries['C0013']['benchmark']),
            ('C0013原入场', summaries['C0013']['candidate']), ('C0047仅30m PAT入场', summaries['C0047']['candidate'])]
    text = ['# EX018：30m PAT回调恢复入场对照', '', judgment['conclusion'], '',
        '本实验只改变入场表达，保留原C13动态均价缓冲退出；它不是移动止损。'
        '无日线、大盘、行业过滤，未搜索参数。精确定义见[事前设计](protocols/design.md)。', '',
        '原20轮额度累计启动10轮，剩余10轮。本实验新增1个配置、策略及配对基准2条账户路径、1项公共诊断。'
        '复用原C13准备引用，四主产品、经济合同与嵌入基准路径一致；原账户不重放，不改历史判断。', '',
        '开发2019-01-02至2025-12-31、预热2018-11至12；USD100000、只做多不加杠杆、常规时段30m，'
        '单边0.1%费用、固定1%限价买入溢价、原后续区间执行。', '',
        '|账户|净年化|30m回撤|日末回撤|闭合周期|60日中位数|至少3笔窗口覆盖|费用USD|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, value in rows:
        text.append(f"|{name}|{percent(value['annualized_return'])}|{percent(value['bar_max_drawdown'])}|"
            f"{percent(value['daily_max_drawdown'])}|{value['closed_cycles']}|{value['rolling_60_closed_cycle_median']}|"
            f"{percent(value['frequency_60_sessions']['coverage_at_least_three'])}|{value['fees']:.2f}|")
    text += ['', '显示取整；判断用完整精度。回撤取连续账户BAR_CLOSE，滚动窗口不是独立样本。', '',
        '|目标|是否满足|', '|---|---|']
    labels = {'annualized_return': '净年化至少正基准1.5倍', 'relative_drawdown': '回撤不超过基准80%',
              'absolute_drawdown': '绝对回撤不超过25%', 'frequency_median': '60日闭合中位数至少6',
              'frequency_coverage': '至少90%完整60日窗口有3个闭合周期'}
    for key, label in labels.items():
        text.append(f"|{label}|{'是' if summaries['C0047']['goals'][key] else '否'}|")
    text += ['', '## 连续账户年度收益', '', '|账户|2019|2020|2021|2022|2023|2024|2025|',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, value in rows:
        text.append('|' + name + '|' + '|'.join(percent(row['net_return']) for row in value['year_returns']) + '|')
    text += ['', '年度继承前期资金及持仓，不重置本金；第一年使用初始资金。', '',
             '## 入场与保留退出的交互', '', judgment['interaction'], '',
             '|账户|闭合周期|入场信号收盘≤当时退出线|首次持仓决策即要求退出|', '|---|---:|---:|---:|']
    for key in ('C0013', 'C0047'):
        value = analysis['entry_exit_description'][key]
        text.append(f"|{key}|{value['closed_cycles']}|{value['groups']['entry_at_or_below_existing_exit']['True']['closed_cycles']}|"
            f"{value['groups']['exit_requested_at_first_held_decision']['True']['closed_cycles']}|")
    text += ['', '这里只描述真实成交和原决策；不能删去某组亏损后推算新策略，亦不能据此认定改退出一定有效。'
        '信号收盘与实际成交价分开留存，前者低于当时退出线不等于成交时已经触发退出。'
        '未闭合周期另列于分析，没有后续持仓决策的记为UNOBSERVED，不算未触发；'
        '不虚构平仓，成交为区间精度，不声称知道柱内先后。', '',
        '## 研究判断与下一步', '', judgment['next_step'], '',
        '## 证据与边界', '',
        '[正式分析及精确引用](others/analysis.json) · [公共账户诊断](others/diagnostics/C0047_vs_C0013.json) · '
        '[合成公开链路检查](others/precheck.json) · [规则边界检查](others/precheck_mechanism.json)', '',
        '合成检查包含169次决策、14笔成交、7个闭合周期；串行与spawn及未来扰动的七表一致；'
        '11项规则边界及100个原C13持仓上下文等价。持仓经济目标和原事实一致，观察提示文本不同。'
        '未执行全仓回归，未修改平台。', '',
        '本轮是在反复观察过的开发池上选择的新表达，不是独立验证；未读取2026 LITE价格绩效。'
        '结论只覆盖本固定PAT入场配合原退出，不推广到所有价格行为方法；'
        '三柱拐点、261柱窗口及单柱恢复触发的尺度风险未检验。', '',
        '本实验独立发布报告，不修改PROTOTYPES/7；未推进阶段三、登记候选、冻结或部署。', '']
    return '\n'.join(text)


def main(action):
    analysis, keys, definitions, accounts, pre, diagnostics, pairs = inputs()
    report = render_report(analysis)
    (WORK / 'report.md').write_bytes(report.encode('utf-8'))
    if action == 'render':
        print('REPORT_RENDERED', EXPERIMENT.experiment_id, flush=True)
        return
    research = context(2)
    references = [*pre.values(), *accounts.values(), *diagnostics.values()]
    materials = {}
    for name, relative in (
        ('analysis', 'others/analysis.json'), ('analysis-source', 'src/analyze.py'),
        ('description-source', 'src/describe_entries.py'), ('judgment', 'others/judgment.json'),
        ('execution-status', 'others/execution_status.json'), ('execution-stats', 'others/execution_stats.json'),
        ('accounts-manifest', 'others/accounts.json'), ('comparisons', 'protocols/comparisons.json'),
        ('publication-source', 'src/publish.py')):
        reference = material(research, name, WORK / relative)
        materials[name] = reference
        references.append(reference)
    definition_refs = {}
    for key in keys:
        content = json.dumps(definitions[key], ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
        reference = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'definition-' + key, content, 'application/json', 'json'))
        definition_refs[key] = reference
        references.append(reference)
    references = tuple(dict.fromkeys(references))
    report_ref = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK / 'report.md'),
        ExperimentOutcome.COMPLETED, references))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK / 'others/publication.json', {'experiment': EXPERIMENT.experiment_id,
        'report': report_ref.to_dict(), 'experiment_validation': validation.to_dict(), 'panel_published': False,
        'accounts': {key: ref.to_dict() for key, ref in accounts.items()},
        'definitions': {key: ref.to_dict() for key, ref in definition_refs.items()},
        'diagnostics': {key: ref.to_dict() for key, ref in diagnostics.items()},
        'materials': {key: ref.to_dict() for key, ref in materials.items()},
        'evidence': [ref.to_dict() for ref in references]})
    if validation.status.value != 'PASS':
        raise RuntimeError('report publication validation failed; inspect actual receipt before retry')
    print('REPORT_PUBLICATION PASS', EXPERIMENT.experiment_id, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['render', 'publish'])
    main(parser.parse_args().action)
