"""Render and publish one experiment report; shared stage panels are separate."""
from hashlib import sha256
from dataclasses import asdict
from pathlib import Path
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


def inputs():
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
        'precheck-mechanism': WORK / 'others/precheck_mechanism.json',
        'precheck-source': WORK / 'src/precheck.py', 'mechanism-source': WORK / 'src/check_mechanism.py',
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


def entry_market_inputs(own_ref):
    """Authenticate and reproduce the retained description without a new audit."""
    from describe_entry_market import describe
    retained = read(WORK / 'others/entry_market_description.json')
    origin = ExperimentRef('S017', 'EX014_20261029')
    context_ref = EvidenceRef.from_dict(read(origin.resolve(ROOT) / 'others/accounts.json')['C0043']['evidence'])
    if (own_ref.experiment != EXPERIMENT or own_ref.name != 'account-C0044'
            or context_ref.experiment != origin or context_ref.name != 'account-C0043'
            or context_ref.media_type != 'application/json'
            or (context_ref.schema, context_ref.schema_version) != ('equity_research', 2)
            or retained['schema'] != 'S017_C0044_ORIGINAL_ENTRY_MARKET_DESCRIPTION_V1'
            or retained['status'] != 'PASS' or retained['scope'] != 'ORIGINAL_C0044_ACTUAL_CYCLES_2019_2025'
            or retained['source_accounts'] != {'C0044': own_ref.to_dict(), 'C0043': context_ref.to_dict()}
            or retained['script_sha256'] != digest(WORK / 'src/describe_entry_market.py')):
        raise ValueError('entry market description source or original account references changed')
    expected_methods = {
        (WORK / 'src/analyze.py').relative_to(ROOT).as_posix(),
        'research/S017/experiments/EX014_20261029/src/describe_entry_difference.py',
        'research/S017/experiments/EX011_20261029/src/describe_entry_context.py',
        'research/S017/experiments/EX011_20261029/src/describe_exits.py',
    }
    methods = retained['method_sources']
    if len(methods) != len(expected_methods) or {item['path'] for item in methods} != expected_methods:
        raise ValueError('entry market description must identify every reused method source')
    for item in methods:
        if digest(ROOT / item['path']) != item['sha256']:
            raise ValueError('entry market description method source changed')
    originals = {'C0044': own_ref, 'C0043': context_ref}
    context_pre = read(origin.resolve(ROOT) / 'others/pre_run_evidence.json')
    for name in ('source', 'definitions'):
        ref = EvidenceRef.from_dict(retained['frozen_sources']['C0043']['materials'][name])
        if ref.experiment != origin or ref != EvidenceRef.from_dict(context_pre[name]):
            raise ValueError('context source/definition must retain its original published reference')
        if digest(ref.resolve(ROOT)) != ref.sha256:
            raise ValueError('context source/definition bytes changed')
        originals['C0043-'+name] = ref
    # describe() rebinds full account identities, frozen source/definitions,
    # economic/primary/BH inputs and the exact actual BUY order/decision/fill join.
    # It performs descriptive arithmetic only and never invokes public diagnosis.
    reproduced = json.loads(json.dumps(describe(), allow_nan=False))
    if reproduced != retained:
        raise ValueError('entry market description cannot be reproduced from its original sources')
    return retained, originals


def entry_volume_inputs(account_refs):
    """Reproduce stable volume facts; preserve the description-time audit status."""
    from describe_entry_volume import describe
    from describe_entry_market import bind_source
    from analyze import ECONOMIC_FIELDS, economic
    retained = read(WORK / 'others/entry_volume_description.json')
    if (retained['schema'] != 'S017_C0044_ACTUAL_ENTRY_VOLUME_DESCRIPTION_V1'
            or retained['status'] != 'PASS'
            or retained['scope'] != 'PUBLISHED_S017_C0044_ACTUAL_BUY_FACTS_AND_C0036_C0037_ORIGINAL_ACCOUNTS_ONLY'
            or retained['script_sha256'] != digest(WORK / 'src/describe_entry_volume.py')):
        raise ValueError('entry volume description source identity changed')
    expected_helpers = {
        'research/S017/experiments/EX011_20261029/src/describe_exits.py',
        (WORK / 'src/analyze.py').relative_to(ROOT).as_posix(),
        (WORK / 'src/run.py').relative_to(ROOT).as_posix(),
    }
    if set(retained['helper_sources']) != expected_helpers or any(
            digest(ROOT / path) != value for path, value in retained['helper_sources'].items()):
        raise ValueError('entry volume helper source identity changed')
    earlier = ExperimentRef('S017', 'EX011_20261029')
    payloads, refs = read_account_views(WORK, EXPERIMENT, ('C0044',), exact=True)
    old, old_refs = read_account_views(earlier.resolve(ROOT), earlier, ('C0036', 'C0037'))
    payloads.update(old)
    refs.update(old_refs)
    if (retained['source_accounts'] != {key: ref.to_dict() for key, ref in refs.items()}
            or any(refs[key] != account_refs[key] for key in ('C0044', 'C0036'))):
        raise ValueError('entry volume description differs from the original account references')
    originals = dict(refs)
    primary = payloads['C0044']
    for key, payload in payloads.items():
        if (any(payload['request'][field] != primary['request'][field] for field in ECONOMIC_FIELDS)
                or payload['data'] != primary['data']):
            raise ValueError('entry volume account economic or data identity differs: '+key)
        for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
            if economic(payload['runs']['buy_hold'][field]) != economic(primary['runs']['buy_hold'][field]):
                raise ValueError('entry volume original BH path differs: '+key+'/'+field)
        if retained['original_account_summaries'][key] != summarize_run(
                payload['runs']['candidate'], payload['request']['initial_cash']):
            raise ValueError('entry volume original account summary changed: '+key)
        origin = EXPERIMENT if key == 'C0044' else earlier
        _, source = bind_source(origin.resolve(ROOT), origin, key, payload)
        for name, value in source['materials'].items():
            originals[key+'-'+name] = EvidenceRef.from_dict(value)
    if json.loads(json.dumps(describe(primary), allow_nan=False)) != retained['description']:
        raise ValueError('entry volume actual-trade description cannot be reproduced')
    diagnosis = retained['retained_public_diagnoses']['C0037_vs_C0036']
    ref = EvidenceRef.from_dict(diagnosis['evidence'])
    raw = authenticated_json(ref)
    analysis_path = earlier.resolve(ROOT) / 'others/analysis.json'
    analysis = read(analysis_path)
    if (diagnosis['status'] != 'COMPUTED' or ref.experiment != earlier
            or diagnosis['analysis_path'] != analysis_path.relative_to(ROOT).as_posix()
            or diagnosis['analysis_sha256'] != digest(analysis_path)
            or ref != EvidenceRef.from_dict(analysis['diagnostics']['C0037_vs_C0036']['evidence'])
            or raw['status'] != 'COMPUTED'
            or raw['sources'] != [asdict(refs['C0036']), asdict(refs['C0037'])]
            or any(diagnosis[field] != raw[field]
                   for field in ('issues', 'protocol', 'sources', 'reconciliation'))):
        raise ValueError('entry volume original public C0037/C0036 diagnosis differs')
    originals['diagnosis-C0037_vs_C0036'] = ref
    # The raw description was generated before the C44/C36 analysis existed.
    # Do not call its main()/retained_diagnosis(), rewrite that historical fact,
    # or compare it to a later analysis. inputs() authenticates current diagnoses.
    if retained['retained_public_diagnoses']['C0044_vs_C0036'] != {
            'status': 'NOT_AVAILABLE_AT_DESCRIPTION', 'experiment': EXPERIMENT.to_dict(),
            'name': 'C0044_vs_C0036', 'new_diagnosis_requested': False}:
        raise ValueError('entry volume description-time diagnosis record changed')
    return retained, originals


def percent(value):
    return '无完整窗口' if value is None else f'{value * 100:.2f}%'


def flag(value):
    return '是' if value else '否'


def link(path):
    return Path(os.path.relpath(path, WORK)).as_posix()


def entry_market_section(description, originals):
    total = description['closed_cycle_totals']
    rows = ['', '## 实际入场时的大盘条件（事后描述）', '',
        f"保留C0044全部{total['cycles']}个原已闭合周期，将实际BUY订单和成交对应的决策时点与"
        f"[C0043原账户]({link(ROOT / originals['C0043'].repository_path)})的结构化SPY20条件精确关联。"
        '两个账户的身份、冻结源码、经济条件、主四项数据和完整买入持有路径均已核验。', '',
        '|入场时SPY条件|原闭合周期|原净损益USD|实际双侧费用USD|周期净收益中位数|周期净收益均值|',
        '|---|---:|---:|---:|---:|---:|']
    for key in ('TRUE', 'FALSE', 'UNKNOWN'):
        value = description['by_entry_market'][key]
        distribution = value['recorded_cycle_net_return_distribution']
        median = '无周期' if distribution is None else percent(distribution['median'])
        mean = '无周期' if distribution is None else percent(distribution['mean'])
        rows.append(f"|{key}|{value['cycles']}|{value['net_pnl']:.2f}|{value['fees']:.2f}|{median}|{mean}|")
    rows.extend(['',
        f"原闭合周期净损益合计{total['net_pnl']:.2f}美元、双侧费用{total['fees']:.2f}美元；"
        f"未闭合周期{len(description['unclosed_cycles_separate'])}个，单独保留，不伪造退出或未来卖出费用。"
        'UNKNOWN显式保留，不作为FALSE或排除。周期收益分布不是分组账户收益。', '',
        '|原周期入场年|TRUE周期数 / 净损益USD|FALSE周期数 / 净损益USD|UNKNOWN周期数 / 净损益USD|',
        '|---|---:|---:|---:|'])
    for year, value in description['by_entry_year'].items():
        parts = [value['market_groups'][key] for key in ('TRUE', 'FALSE', 'UNKNOWN')]
        rows.append('|' + year + '|' + '|'.join(f"{part['cycles']} / {part['net_pnl']:.2f}" for part in parts) + '|')
    rows.extend(['', '上表按原周期入场年归属完整周期损益，不是逐年账户收益，也不能成为按年份交易的规则。'
        '本样本FALSE组在七年中六年净正，TRUE组仅2025年净正；FALSE组中位数更低而均值更高，'
        '说明不能简单把大盘条件为假的原入场都称为失败启动。', '',
        '这是看到C0044正式账户后的条件分组，受其自身持仓、资金和机会选择影响。'
        '不能删除某组推算过滤账户、把组内损益归因于大盘条件，或反向推出只做FALSE有效；'
        '不能据此承诺跨日持有与SPY门控组合有效。描述只作逐项算术核对，不替代本报告的公共经济诊断。', '',
        '[完整描述](others/entry_market_description.json)保留精确原引用、所有周期、分位数、逐年分组和加总核对；'
        '[描述脚本](src/describe_entry_market.py)提供只读重算。复用的EX014账本关联及EX011市场事实/成交解释方法'
        '继续使用原文件，完整路径和SHA保存在描述的method_sources中；原C0043账户、策略及定义引用原样纳入证据，'
        '不在本实验重新托管。'])
    return rows


def entry_volume_section(retained, originals):
    description = retained['description']
    rows = ['', '## 实际入场时的开盘量能（事后描述）', '',
        '按C0044实际BUY决策已记录的首根开盘柱成交量，是否严格大于此前14个完整会话首柱成交量均值分组。'
        '相等归FALSE，缺失或不一致归UNKNOWN；没有使用已关闭过滤器的volume_allowed字段代替量能事实。', '',
        '|量能条件|原闭合周期|原净损益USD|实际双侧费用USD|盈利周期比例|周期净收益中位数|周期净收益均值|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for key in ('TRUE', 'FALSE', 'UNKNOWN'):
        value = description['groups'][key]
        distribution = value['recorded_net_return_distribution']
        shown = ['无周期' if item is None else percent(item) for item in (
            value['positive_cycle_fraction'], distribution['median'], distribution['mean'])]
        rows.append(f"|{key}|{value['closed_cycles']}|{value['net_pnl']:.2f}|{value['fees']:.2f}|"
            + '|'.join(shown) + '|')
    rows.extend(['', '|原周期分布|最小净收益|净收益25%分位|净收益95%分位|持有自然日中位数|前三大盈利占正损益比例|',
        '|---|---:|---:|---:|---:|---:|'])
    for key in ('TRUE', 'FALSE'):
        value = description['groups'][key]
        distribution = value['recorded_net_return_distribution']
        rows.append(f"|{key}|{percent(distribution['min'])}|{percent(distribution['q25'])}|"
            f"{percent(distribution['q95'])}|{value['holding_calendar_days_distribution']['median']:.2f}|"
            f"{percent(value['top_3_share_of_positive_pnl'])}|")
    rows.extend(['', '高量组的盈利周期比例、中位数及下侧收益分布较弱，但均值和95%分位较高，'
        '不能只选其中一个统计量断言筛选有利。美元损益使用各原周期实际资金，不是等额投入收益。', '',
        '|原周期入场年|TRUE周期数 / 净损益USD|FALSE周期数 / 净损益USD|UNKNOWN周期数 / 净损益USD|',
        '|---|---:|---:|---:|---:|'])
    for year, values in description['by_entry_year'].items():
        rows.append('|' + year + '|' + '|'.join(
            f"{values[key]['closed_cycles']} / {values[key]['net_pnl']:.2f}" for key in ('TRUE', 'FALSE', 'UNKNOWN')) + '|')
    old = retained['original_account_summaries']
    rows.extend(['',
        f"原日内量能对照C0036→C0037的闭合周期为{old['C0036']['closed_cycles']}→{old['C0037']['closed_cycles']}，"
        f"60会话周期中位数为{old['C0036']['rolling_60_closed_cycle_median']:g}→"
        f"{old['C0037']['rolling_60_closed_cycle_median']:g}。"
        f"[原C0037/C0036公共诊断]({link(ROOT / originals['diagnosis-C0037_vs_C0036'].repository_path)})"
        '只检验原日内持有政策下的量能过滤；这里高量组仅121个原周期，提示关注机会数量，'
        '不能据此推算新过滤账户的闭合数、滚动频率或收益。跨日持有与量能条件的交互尚未被本分组检验。', '',
        '原描述生成时记录C0044/C0036诊断为NOT_AVAILABLE_AT_DESCRIPTION，该字段保留当时事实。'
        '它不代替本报告发布前另行认证的已完成公共诊断，也不表示报告发布时诊断仍缺失。', '',
        '[完整量能描述](others/entry_volume_description.json)及[源码](src/describe_entry_volume.py)保留全部原交易、'
        '分布、逐年分组、费用与账本核对；复用helper的原路径和SHA随描述保存。'
        'C0044/C0037/C0036账户、冻结源码/定义及C0037/C0036诊断沿用原正式引用，不重新托管。'
        '这仍是反复观察过开发池的事后条件描述，不能删组构造新账户或宣称因果贡献，'
        '不直接决定新实验、组件采用或阶段推进。'])
    return rows


def render_report(analysis, keys, references, diagnostic_refs, pairs, entry_description, entry_originals,
                  volume_description, volume_originals):
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
        '原C0013只读复用EX003正式证据，原C0036只读复用EX011正式证据，不重新计算控制账户。'
        '本实验在看到C0036账户与首项公共诊断后提出，是自适应结构对照，不是独立验证。'
        '[决策依据](protocols/decision_evidence.json)保留原账户引用、诊断及描述文件实际SHA。'
        '唯一政策改变是允许合法持仓跨日，最后执行区间仍禁止新买入；入场、入场日开盘锚点、'
        '一倍入场日区间宽度、完成Close峰值、止损触发保持及真实周期限次沿用原C0036规则。'
        '跨日改变后续仓位、入场、费用和周期，账户差值不能直接称为隔夜收益。'
        '主标的四项输入的完整元数据和内容哈希、执行条件及费用均核对一致；'
        '辅助输入允许使用不同联合准备清单，但不得改换主标的来源。所有嵌入基准已核对相同经济路径。', '',
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
    text.extend(['', '逐年收益继承上年末资金与持仓，第一年使用初始资金；不逐年重置本金或平均年度收益率。'])
    text.extend(entry_market_section(entry_description, entry_originals))
    text.extend(entry_volume_section(volume_description, volume_originals))
    text.extend(['', '## 原始证据与限制', '',
        '[可复核分析](others/analysis.json)保留精确账户、公共诊断和方法来源引用。'])
    for key, ref in references.items():
        text.append(f'- [{key}原始账户]({link(ROOT / ref.repository_path)})')
    text.extend(['', '本实验使用反复观察过的开发池；重叠窗口与30分钟观察点不能视作独立样本。'
        '未读取2026保留行情，未进行独立验证或稳健性自检。买入持有基准相同不意味着不同机制具有独立统计证据。',
        '本次仅发布本实验报告。COMPONENTS/PROTOTYPES类型化面板由主流程汇总精确引用及研究判断后单独、串行发布。', ''])
    return '\n'.join(text)


def main(action):
    upstream = upstream_evidence()
    analysis, keys, definitions, accounts, pre, diagnostics, pairs = inputs()
    entry_description, entry_originals = entry_market_inputs(accounts['C0044'])
    volume_description, volume_originals = entry_volume_inputs(accounts)
    report = render_report(analysis, keys, accounts, diagnostics, pairs, entry_description, entry_originals,
                           volume_description, volume_originals)
    (WORK / 'report.md').write_bytes(report.encode('utf-8'))
    if action == 'render':
        print('REPORT_RENDERED', EXPERIMENT.experiment_id, flush=True)
        return
    research = context()
    references = [*pre.values(), *accounts.values(), *diagnostics.values(), *upstream.values(),
                  *entry_originals.values(), *volume_originals.values()]
    materials = {}
    for name, relative in (
        ('analysis', 'others/analysis.json'), ('analysis-source', 'src/analyze.py'),
        ('precheck-source', 'src/precheck.py'), ('execution-status', 'others/execution_status.json'),
        ('execution-stats', 'others/execution_stats.json'), ('accounts-manifest', 'others/accounts.json'),
        ('comparisons', 'protocols/comparisons.json'), ('publication-source', 'src/publish.py'),
        ('entry-market-description', 'others/entry_market_description.json'),
        ('entry-market-description-source', 'src/describe_entry_market.py'),
        ('entry-volume-description', 'others/entry_volume_description.json'),
        ('entry-volume-description-source', 'src/describe_entry_volume.py'),
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
        'entry_market_original_evidence': {key: ref.to_dict() for key, ref in entry_originals.items()},
        'entry_volume_original_evidence': {key: ref.to_dict() for key, ref in volume_originals.items()},
        'materials': {key: ref.to_dict() for key, ref in materials.items()},
        'upstream': {key: ref.to_dict() for key, ref in upstream.items()},
        'evidence': [ref.to_dict() for ref in references]})
    if validation.status.value != 'PASS':
        raise RuntimeError('report publication validation failed; inspect publication.json')
    print('REPORT_PUBLICATION PASS', EXPERIMENT.experiment_id, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['render', 'publish'])
    main(parser.parse_args().action)
