"""Render and publish one experiment report; shared stage panels are separate."""
from hashlib import sha256
from dataclasses import asdict
from pathlib import Path, PurePosixPath
import argparse
import json
import os

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, ExperimentOutcome, ExperimentReportWrite,
    MaterialEvidenceWrite, ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity
from czsc_trader.research_tools.experiment_artifacts import ExperimentReportSnapshot
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256
from run import (ROOT, WORK, REPOSITORY, EXPERIMENT, DATA_READINESS, context, read, save,
                 material, configurations, candidate, decision_evidence, checked_precheck)
from analyze import (CONTROL_ID, OLD_CONTROLS, comparison_pairs, verify_contracts, verify_hold_path,
                     summarize_run, goals)


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


def scheduling_evidence():
    """Require current independent synthetic coverage of the unchanged scheduler."""
    checked = read(WORK / 'others/analysis_scheduling_check.json')
    background = read(WORK / 'others/analysis_scheduling_original_result.json')
    flags = ('typed_request_result_pickle', 'serial_result_fields_equal',
        'worker_exception_propagated_without_retry', 'wrong_result_type_rejected',
        'noncomputed_status_preserved', 'formal_analysis_source_unchanged',
        'parent_publication_not_invoked', 'native_environment_restored',
        'children_joined', 'active_runner_never_imported', 'three_fixed_pairs_and_utf8_report')
    if (checked['status'] != 'PASS' or checked['synthetic_only'] is not True
            or checked['scope'] != 'EX017_CURRENT_ANALYSIS_SYNTHETIC_SPAWN_ONLY'
            or checked['workers'] != 3 or checked['native_threads'] != 1
            or checked['real_diagnoses'] != 0 or checked['real_replays'] != 0
            or checked['completion_order'] != [2, 1, 0] or checked['returned_order'] != [0, 1, 2]
            or any(checked[name] is not True for name in flags)
            or checked['candidate_sha256'] != digest(WORK / 'src/analyze.py')
            or checked['check_source_sha256'] != digest(WORK / 'src/check_analysis_scheduling.py')
            or checked['original_preparation_result_sha256'] != digest(WORK / 'others/analysis_scheduling_original_result.json')
            or background['status'] != 'PASS' or background['candidate_sha256'] != checked['candidate_sha256']):
        raise ValueError('current analysis scheduling proof or source identity differs')
    dependencies = checked['dependency_sha256']
    if not dependencies:
        raise ValueError('synthetic scheduling proof must record its typed dependencies')
    for relative, expected in dependencies.items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or digest(path) != expected:
            raise ValueError('synthetic scheduling dependency changed: '+relative)
    return checked


def platform_performance_evidence():
    """Pin every explicitly listed DEV material; never execute archived sources."""
    directory = (WORK / 'others/platform_performance').resolve()
    manifest_bytes = (directory / 'manifest.json').read_bytes()

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate platform performance manifest key')
            value[key] = item
        return value

    manifest = json.loads(manifest_bytes, object_pairs_hook=unique_object)
    if (set(manifest) != {'schema', 'status', 'files'}
            or manifest['schema'] != 'S017_DEV_PLATFORM_PERFORMANCE_EVIDENCE_V1'
            or manifest['status'] != 'PASS' or type(manifest['files']) is not dict
            or not manifest['files']):
        raise ValueError('platform performance manifest requires explicit PASS files')
    retained, resolved = {'manifest.json': manifest_bytes}, set()
    for relative, expected in manifest['files'].items():
        path = PurePosixPath(relative)
        suffix = path.suffix.lstrip('.').lower()
        if (not relative or path.is_absolute() or str(path) != relative
                or any(part in ('', '.', '..') for part in relative.split('/'))
                or '\\' in relative or ':' in relative or relative == 'manifest.json'
                or type(expected) is not str or len(expected) != 64
                or not 1 <= len(suffix) <= 12
                or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789' for char in suffix)
                or any(char not in '0123456789abcdef' for char in expected)):
            raise ValueError('invalid relative performance material path or SHA: ' + relative)
        source = (directory / relative).resolve()
        if not source.is_relative_to(directory) or source in resolved or not source.is_file():
            raise ValueError('performance material is missing, aliased or outside its archive: ' + relative)
        content = source.read_bytes()
        if not content or sha256(content).hexdigest() != expected:
            raise ValueError('platform performance material bytes differ: ' + relative)
        resolved.add(source)
        retained[relative] = content
    comparison = json.loads(retained['comparison.json'])
    before_hash = sha256(retained['source/before_equity_context.py.txt']).hexdigest()
    after_hash = sha256(retained['source/after_equity_context.py.txt']).hexdigest()
    if (comparison['status'] != 'PASS'
            or comparison['scope'] != 'DEV_SYNTHETIC_EQUIVALENCE_NO_RESEARCH_ACCOUNT'
            or comparison['before_module_sha256'] != before_hash
            or comparison['after_module_sha256'] != after_hash or before_hash == after_hash
            or comparison['seven_tables_exact'] != ['plain', 'session', 'aux_session']):
        raise ValueError('platform comparison does not bind both original source snapshots')
    tables = ('decisions', 'orders', 'fills', 'corporate_action_entries',
              'account_points', 'account_daily', 'trades')
    for route in comparison['seven_tables_exact']:
        for table in tables:
            before = retained[f'before_validation/{route}_{table}.json']
            after = retained[f'after_validation/{route}_{table}.json']
            if before != after or (table == 'corporate_action_entries' and json.loads(after) != {}):
                raise ValueError('reported seven-table equivalence or empty CA scope differs')
    interruption = json.loads(retained['EX017-interruption.json'])
    if (interruption['status'] != 'CONTROLLED_TECHNICAL_INTERRUPTION_BEFORE_RESULT'
            or interruption['account_result_published'] is not False
            or interruption['new_experiment_round'] is not False):
        raise ValueError('technical interruption must not represent a completed research account')
    profiles = [json.loads(retained[name + '_session_profile.json']) for name in ('before', 'after')]
    if (profiles[0]['module_sha256'] != before_hash or profiles[1]['module_sha256'] != after_hash
            or any(item['scope'] != 'SYNTHETIC_SESSION_ONLY_CONTEXT' for item in profiles)
            or f"{comparison['context_workload_speedup']:.2f}" != '3.36'
            or f"{profiles[0]['timing']['median_seconds'] / profiles[1]['timing']['median_seconds']:.2f}" != '5.21'):
        raise ValueError('reported local timing scope or rounded ratios differ from original measurements')
    return retained, after_hash


def verify_platform_identity(payload, after_hash):
    if (payload['request']['candidate_id'] != 'C0046'
            or payload['request']['engine_sources'].get('strategy_runtime.equity_context') != after_hash):
        raise ValueError('C0046 must retain its new archived platform implementation identity')


def inputs():
    scheduling_evidence()
    analysis = read(WORK / 'others/analysis.json')
    precheck = checked_precheck()
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
    _, after_hash = platform_performance_evidence()
    if keys != ('C0046',):
        raise ValueError('platform restart evidence belongs to the sole fixed C0046')
    verify_platform_identity(payloads['C0046'], after_hash)
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
        'precheck-source': WORK / 'src/precheck.py', 'mechanism-source': WORK / 'src/check_mechanism.py',
        'precheck-mechanism': WORK / 'others/precheck_mechanism.json',
        'data-readiness': DATA_READINESS,
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
        if ref.experiment != EXPERIMENT or value['status'] != 'COMPUTED':
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
    return analysis, keys, definitions, references, pre, diagnostic_refs, pairs


def percent(value):
    return '无完整窗口' if value is None else f'{value * 100:.2f}%'


def flag(value):
    return '是' if value else '否'


def link(path):
    return Path(os.path.relpath(path, WORK)).as_posix()


def render_report(analysis, keys, references, diagnostic_refs, pairs):
    summaries = analysis['summaries']
    rows = [(key, summaries[key]['candidate']) for key in (*OLD_CONTROLS, *keys)]
    rows.append(('同条件买入持有', summaries[CONTROL_ID]['benchmark']))
    passed = [key for key in keys if summaries[key]['all_goals_met']]
    text = [f'# {EXPERIMENT.experiment_id} 阶段二实验报告', '',
        f'本实验完成{len(keys)}个固定配置、{2 * len(keys)}个完整账户路径（各配置及其基准）和{len(pairs)}项公共账户诊断。',
        f'其中{len(passed)}个新配置同时满足已确认的完整区间经济与双频率五项目标' +
        ('：' + '、'.join(passed) + '。' if passed else '。'),
        '技术完成、目标数值与研究采用判断分别记录；本报告不自动推进阶段、登记候选或赋予冻结/PTE资格。', '',
        '## 固定设计与比较条件', '',
        '[本轮运行前设计](protocols/design.md)、[授权](protocols/authorization.md)、[固定参数](protocols/configurations.json)、'
        '[候选输入契约](protocols/candidate_contracts.json)及[合成预检](others/precheck.json)保留原始内容。',
        '开发评价为2019-01-02至2025-12-31，预热始于2018-11-01；LITE单标的、只做多、30分钟常规交易时段，'
        '初始资金100,000美元，每侧费用0.1%，固定买入限价溢价1%。经营和行业认识用于提出假设，不直接作为事件交易条件。',
        '原C0013只读复用EX003、C0037只读复用EX011、C0044只读复用EX015正式证据，不重跑控制账户。'
        '本轮在看到前序完整账户、公共诊断与实际交易量能分组后提出，是反复使用开发池的固定组合研究，不是独立验证。'
        '[决策依据](protocols/decision_evidence.json)绑定原账户、原诊断、描述及源码SHA。'
        'C0046同时启用既有开盘量能门控与跨日持有，保持开盘突破、初始低点、一倍入场日开盘区间、'
        '已完成收盘峰值移动止损、止损锁存、真实周期限次和最后执行区间禁新买入不变；不搜索阈值。'
        'C0046/C0044隔离量能政策，C0046/C0037隔离持有政策，C0046/C0013比较整体机制。'
        'C0036只作为决策材料中的四角背景，不列作本轮新账户或第四项公共诊断；完整交互解释由统一面板处理。'
        '输入保持261根主预热、真实闭合周期反馈、交易session上下文、无辅助行情。'
        '逐账户认证完整input_binding，C46/C37/C44不得存在任何绑定差异；主四项元数据、内容SHA、经济条件及嵌入基准经济路径一致。'
        '跨日持有会改变后续仓位、费用、周期及再入场机会，账户差值不能直接称为隔夜收益；'
        '量能过滤也不能由删除旧账户的部分交易推算。原C44量能未达标组同样贡献正净损益，达标组的胜率、中位数及左尾并不占优，'
        '不能预先声称入场优势或组件组合必然有效。RAW行情不表示含分红总回报，价格行为比较不构成行业因果。',
 '',
        '三项公共诊断使用3个独立spawn工作进程、每进程原生线程1；按固定对照顺序消费结果，'
        '仅主进程发布，异常不重试。'
        '[当前调度合成检查](others/analysis_scheduling_check.json)及[源码](src/check_analysis_scheduling.py)'
        '核验类型传输、乱序完成后的有序返回、异常传播、非COMPUTED状态保留与进程回收，'
        '绑定实际分析源码和类型依赖SHA。检查未调用真实诊断或账户，不代替下述正式经济诊断。', '',
        '## 平台性能修复与同配置技术重跑', '',
        '用户授权DEV修复上下文性能后，原EX017运行在未产生账户结果前受控技术中止，检查点另行归档；'
        '仍以同一固定C0046配置在新平台源码身份下重跑，正式request中的上下文源码SHA必须等于归档after源码，'
        '不伪装沿用旧执行身份。研究假设和配置未增加，仍为第9/20轮、剩余11轮。'
        '[材料清单](others/platform_performance/manifest.json)逐项绑定相对路径及SHA，'
        '[验证说明](others/platform_performance/README.md)区分合成等价、局部计时及后续聚焦测试。'
        '三个US合成路径（无辅助、仅session、辅助加session）的决策等七表逐字节一致；公司行动表为空，'
        '不能据此宣称非空公司行动等价。局部上下文微基准约3.36倍、仅session约5.21倍，'
        '均非正式账户或完整诊断全链路加速比例，也不代替全仓回归。', '',
        '## 完整账户结果', '',
        '|配置|净年化|30分钟回撤|日末回撤|闭合周期|60日闭合数中位数|≥3笔窗口占比|完整窗口数|费用USD|持仓柱占比|持仓日末占比|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, value in rows:
        frequency = value['frequency_60_sessions']
        text.append(f"|{name}|{percent(value['annualized_return'])}|{percent(value['bar_max_drawdown'])}|"
            f"{percent(value['daily_max_drawdown'])}|{value['closed_cycles']}|{value['rolling_60_closed_cycle_median']}|"
            f"{percent(frequency['coverage_at_least_three'])}|{frequency['complete_windows']}|{value['fees']:.2f}|"
            f"{percent(value['holding_bar_fraction'])}|{percent(value['holding_session_close_fraction'])}|")
    text.extend(['', '表格为显示取整；完整精度见[分析结果](others/analysis.json)。持仓比例按正持仓的柱/日末观察点计算，'
        '不是经过时间占比。回撤使用包含初始资金的连续账户高点；日末回撤单独展示，目标采用30分钟BAR_CLOSE回撤。', '',
        '## 五项目标逐项核对', '',
        '|新配置|净年化目标|相对回撤目标|绝对回撤≤25%|60日中位数≥6笔|≥3笔完整窗口覆盖≥90%|全部满足|',
        '|---|---|---|---|---|---|---|'])
    for key in keys:
        values = summaries[key]['goals']
        text.append('|' + '|'.join([key, *(flag(values[field]) for field in
            ('annualized_return', 'relative_drawdown', 'absolute_drawdown', 'frequency_median', 'frequency_coverage')),
            flag(summaries[key]['all_goals_met'])]) + '|')
    text.extend(['', '基准净年化为正时，净年化目标为其1.5倍，否则要求策略净年化为正；'
        '相对回撤目标为不超过基准回撤的80%。频率按实际退出日计入完整滚动60交易日窗口，未闭合持仓不计闭合次数。', '',
        '## 固定对照的账户差值', '',
        '|主体 / 对照|净年化差（百分点）|30分钟回撤差（百分点）|闭合周期差|费用差USD|公共诊断|',
        '|---|---:|---:|---:|---:|---|'])
    for subject, control in pairs:
        left, right = (summaries[key]['candidate'] for key in (subject, control))
        name = subject + '_vs_' + control
        text.append(f"|{subject} / {control}|{100 * (left['annualized_return'] - right['annualized_return']):+.2f}|"
            f"{100 * (left['bar_max_drawdown'] - right['bar_max_drawdown']):+.2f}|"
            f"{left['closed_cycles'] - right['closed_cycles']:+d}|{left['fees'] - right['fees']:+.2f}|"
            f"[COMPUTED]({link(ROOT / diagnostic_refs[name].repository_path)})|")
    text.extend(['', '差值仅为主体减对照的原账户事实；正负号不是统一评分，也不证明行为因果。'
        '具体组件用途、原型保留与下一轮问题由批次统一研究判断补充。', '', '## 连续账户逐年收益', '',
        '|配置|' + '|'.join(str(item['year']) for item in rows[0][1]['year_returns']) + '|',
        '|---|' + '|'.join('---:' for _ in rows[0][1]['year_returns']) + '|'])
    for name, value in rows:
        text.append('|' + name + '|' + '|'.join(percent(item['net_return']) for item in value['year_returns']) + '|')
    text.extend(['', '逐年收益继承上年末资金与持仓，第一年使用初始资金；不逐年重置本金或平均年度收益率。', '',
        '## 原始证据与限制', '', '[可复核分析](others/analysis.json)保留精确账户、公共诊断和方法来源引用。'])
    for key, ref in references.items():
        text.append(f'- [{key}原始账户]({link(ROOT / ref.repository_path)})')
    text.extend(['', '本实验使用反复观察过的开发池；重叠窗口与30分钟观察点不能视作独立样本。'
        '未读取2026保留行情，未进行独立验证或稳健性自检。买入持有基准相同不意味着不同机制具有独立统计证据。',
        '本次仅发布本实验报告。COMPONENTS/PROTOTYPES类型化面板由主流程汇总精确引用及研究判断后单独、串行发布。', ''])
    return '\n'.join(text)


def main(action):
    upstream = upstream_evidence()
    analysis, keys, definitions, accounts, pre, diagnostics, pairs = inputs()
    performance_bytes, _ = platform_performance_evidence()
    report = render_report(analysis, keys, accounts, diagnostics, pairs)
    (WORK / 'report.md').write_bytes(report.encode('utf-8'))
    if action == 'render':
        print('REPORT_RENDERED', EXPERIMENT.experiment_id, flush=True)
        return
    research = context()
    references = [*pre.values(), *accounts.values(), *diagnostics.values(), *upstream.values()]
    materials = {}
    performance_refs = {}
    for relative, content in performance_bytes.items():
        name = ('platform-performance-manifest' if relative == 'manifest.json'
                else 'platform-performance-' + sha256(relative.encode('utf-8')).hexdigest())
        suffix = PurePosixPath(relative).suffix.lstrip('.').lower()
        media = ('application/json' if suffix == 'json' else 'text/plain'
                 if suffix in ('md', 'txt', 'log', 'py') else 'application/octet-stream')
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, content, media, suffix))
        materials[name] = ref
        performance_refs[relative] = ref
        references.append(ref)
    for name, relative in (
        ('analysis', 'others/analysis.json'), ('analysis-source', 'src/analyze.py'),
        ('precheck-source', 'src/precheck.py'), ('execution-status', 'others/execution_status.json'),
        ('execution-stats', 'others/execution_stats.json'), ('accounts-manifest', 'others/accounts.json'),
        ('comparisons', 'protocols/comparisons.json'), ('publication-source', 'src/publish.py'),
        ('analysis-scheduling-check', 'others/analysis_scheduling_check.json'),
        ('analysis-scheduling-source', 'src/check_analysis_scheduling.py'),
        ('analysis-scheduling-preparation-background', 'others/analysis_scheduling_original_result.json'),
    ):
        ref = material(research, name, WORK / relative)
        materials[name] = ref
        references.append(ref)
    definition_refs = {}
    for key in keys:
        content = json.dumps(definitions[key], ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
        ref = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'definition-' + key,
            content, 'application/json', 'json'))
        definition_refs[key] = ref
        references.append(ref)
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
        'platform_performance': {key: ref.to_dict() for key, ref in performance_refs.items()},
        'upstream': {key: ref.to_dict() for key, ref in upstream.items()},
        'evidence': [ref.to_dict() for ref in references]})
    if validation.status.value != 'PASS':
        raise RuntimeError('report publication validation failed; inspect publication.json')
    print('REPORT_PUBLICATION PASS', EXPERIMENT.experiment_id, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['render', 'publish'])
    main(parser.parse_args().action)
