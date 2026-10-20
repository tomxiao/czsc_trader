"""Authenticate, audit, and publish the actual S014 phase-four results."""
import argparse
from hashlib import sha256

import numpy as np
from czsc_trader.application import RepositoryContext
from czsc_trader.research_tools import (
    DeliveryReference, EvidenceRef,
    ParameterEvaluationPlan,
)
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey
from strategy_evaluator import (
    CandidateAssessmentRequest, PerturbationLink,
    SelfCheckProtocol, QuantileMethod, ParameterPerturbationProtocol,
    ResearchMetric, MetricBinSpec, BinRounding, ComparisonPolicy, ParetoBasis,
    MissingEvidencePolicy, ComparisonVariant, assess_candidates,
)
from build_candidate import build
from run_stage4 import ROOT, EX, context, publish, read, write as write_new
from stage4_delivery import read_account, read_delivery_content, publish_candidate_successor, publish_assessment

REQUEST_WORK = ROOT / '.tmp/s014-ex054/assessment_request.json'


def write(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f'Retained output differs: {path.name}')
        return
    write_new(path, value)


def delivery_ref(stage, revision):
    raw = read(ROOT / f'research/S014/assets/deliveries/{stage}/{revision}/receipt.json')
    return DeliveryReference.from_dict(raw['reference'])


def annual(equity, dates, initial=100000.):
    rows, opening = [], initial
    for year in sorted({int(x[:4]) for x in dates}):
        values = np.asarray([v for d, v in zip(dates, equity, strict=True) if int(d[:4]) == year])
        nav = np.r_[opening, values]
        rows.append({'year': year, 'opening': opening, 'ending': float(nav[-1]),
            'return': float(nav[-1]/opening-1), 'drawdown': float(-(nav/np.maximum.accumulate(nav)-1).min()),
            'sessions': len(values)})
        opening = float(nav[-1])
    return rows


def goals(record):
    dates = [p.session for p in record.account]
    years = annual([p.equity for p in record.account], dates, record.initial_cash)
    baseline = annual(record.benchmark_equity, dates, record.initial_cash)
    for actual, bh in zip(years, baseline, strict=True):
        actual.update(buyhold_return=bh['return'], buyhold_drawdown=bh['drawdown'],
            required_return=1.5*bh['return'] if bh['return'] > 0 else 0.,
            return_pass=actual['return'] >= 1.5*bh['return'] if bh['return'] > 0 else actual['return'] > 0,
            drawdown_pass=actual['drawdown'] < bh['drawdown'])
    freq = 60*len(record.closed_cycles)/len(record.account)
    return {'candidate': record.candidate.to_dict(), 'years': years,
        'frequency': freq, 'closed_trades': len(record.closed_cycles),
        'all_targets_pass': bool(all(y['return_pass'] and y['drawdown_pass'] for y in years) and freq >= 3),
        'ending_equity': record.account[-1].equity}


def published_methods(ctx):
    paths = [EX / 'protocols/method.md', EX / 'protocols/technical_retry.md',
             EX / 'protocols/publication_snapshot.md',
             EX / 'others/center_control.json',
             *sorted((EX / 'src').rglob('*.py'))]
    refs = {p.relative_to(EX).as_posix(): publish(ctx, p, 'ex054-method-' + sha256(p.relative_to(EX).as_posix().encode()).hexdigest()[:16]).to_dict()
            for p in paths}
    return refs


def succession():
    ctx = context()
    control = read(EX / 'others/center_control.json')
    assert control['status'] == 'PASS_EXACT_BUSINESS_BEHAVIOR'
    centerref = EvidenceRef.from_dict(control['account'])
    _, records = read_account(ROOT, centerref)
    audit = goals(records[0])
    assert audit['all_targets_pass']
    write(EX / 'others/center_annual_goals.json', audit)
    write(EX / 'protocols/authorization.json', {
        'user_message': '验收通过，请合并当前分支到研究分支，继续完成S014的后续工作',
        'scope': 'Merge accepted DEV into codex/s014-jinniu-research; equivalent successor and phase-four selfchecks.',
        'excluded': ['stage-five selection', 'freeze', 'PTE deployment', 'production writes', 'master merge', 'push', 'tag'],
        'date': '2026-10-20'})
    methods = published_methods(ctx)
    auth = publish(ctx, EX / 'protocols/authorization.json', 'ex054-user-stage4-authorization')
    method = EvidenceRef.from_dict(methods['protocols/method.md'])
    equivalence = EvidenceRef.from_dict(methods['others/center_control.json'])
    original = read(ROOT / 'research/registrations/S014/candidates/C9521.json')['record']
    anchors = []
    repo = RepositoryContext.discover(ROOT)
    for stage, revision in (('CANDIDATES', 14), ('COMPONENTS', 23)):
        reference = delivery_ref(stage, revision)
        retained = read_delivery_content(repo, reference)
        folder = ROOT / f'research/S014/assets/deliveries/{stage}/{revision}'
        anchors.append({'reference': reference.to_dict(),
            'receipt_sha256': sha256((folder / 'receipt.json').read_bytes()).hexdigest(),
            'delivery_json_sha256': sha256((folder / 'delivery.json').read_bytes()).hexdigest(),
            'report_sha256': sha256((folder / 'report.md').read_bytes()).hexdigest(),
            'source_content_authenticated_to_receipt': True,
            'entry_count': len(retained.payload.candidates) if stage == 'CANDIDATES' else len(retained.payload.components)})
    write(EX / 'protocols/source_snapshot_anchors.json', {
        'source_deliveries': anchors, 'old_candidates_exactly_retained': 69,
        'old_search_summaries_exactly_retained': 14,
        'prior_report_material_refs_exactly_retained': 95,
        'current_candidate_accounts_full_checked': 70,
        'prior_component_graph_revalidated_in_this_snapshot': False,
        'original_recursive_attempt': 'Interrupted before publication; no revision15 existed, no immutable artifact replaced.'})
    derivation = CandidateDerivation(CandidateKey('S014', 'C9521'), original['content_sha256'],
        CandidateKey('S014', 'C9524'), control['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
        {'window_contract': 'v2 independent-account initialization; explicit simulated-fill feedback',
         'numeric_interface': 'Expose the same 10 research constants as typed parameters; center unchanged.',
         'economic_equivalence': 'Exact 1642 signals and funded ledgers; not a new independent alpha.'},
        method.sha256, CandidateEvidence('research/S014/' + original['origin']['evidence'][0]['path'],
                                         original['origin']['evidence'][0]['sha256']))
    report = '''# S014 C9521等价接续：C9524

用户已验收DEV并授权返回研究继续。C9524仅将原C9521的窗口契约升级为2、声明模拟成交反馈，并将10个原研究数值显式化以进行自检。中心参数、经济机制及固定交易规则不变。

原窗口2020-01-02至2026-10-15，1642个信号、184笔成交、187张订单、92次闭合交易及完整五类经济账本，与C9521零容差业务一致。年度收益7/7、严格年度回撤7/7，频率92/1642×60=3.3617539586，截止权益1,522,765.495元。原C9521及69条历史候选、搜索轨迹原样保留，新增技术接续候选后为70条，阶段四仅交接C9524；这两个经济等价中心不算两项独立发现。

原年度目标与全部已见历史的限制保持。C9461/C9502仍仅作未达标对照，C9522/C9523为已保留的未登记技术草稿。后续固定32点联合扰动、一次费用压力及账本统计仅作自检，不按结果挑选更赚钱的参数。

模拟成交反馈不是PTE真实成交反馈，股票PTE运行尚不支持此类反馈。此次不冻结、不改生产。具体参数与方法见本实验protocols/method.md；原阶段三报告保留全部机制反证与2021机会成本。
'''
    report += '\n本修订是完整候选快照，前驱绑定原MANDATE/2。原CANDIDATES/14及COMPONENTS/23的回执、内容及报告身份另外认证留证，原69条候选、14份搜索概要和95份必要材料原样保留；本轮FULL核验全部70个当前候选账户，不再次递归重验早期组件交付图。发布组织调整见protocols/publication_snapshot.md，旧交付与原有资格不改。\n'
    registration, receipt, validation = publish_candidate_successor(RepositoryContext.discover(ROOT),
        candidate=build()[0], account_reference=centerref, derivation=derivation, dependencies=(),
        source_candidates=delivery_ref('CANDIDATES', 14), revision=15,
        predecessors=(delivery_ref('MANDATE', 2),),
        equivalence_evidence=equivalence, authorization_evidence=auth,
        hypothesis='原C9521交易机制的契约2及数值显式化等价实现。',
        judgment='原全部经济目标精确继承；技术接续，不是独立新机制或未见样本。',
        conclusion='保留69条历史候选并新增C9524，阶段四交接仅C9524。',
        report=report, additional_evidence=(publish(ctx, EX / 'others/center_annual_goals.json'), method,
            publish(ctx, EX / 'protocols/source_snapshot_anchors.json'),
            EvidenceRef.from_dict(methods['protocols/publication_snapshot.md'])))
    write(EX / 'others/candidate_succession.json', {'candidate': registration.key.to_dict(),
        'delivery': receipt.to_dict(), 'validation': validation.to_dict(), 'methods': methods,
        'authorization': auth.to_dict()})
    (EX / 'others/candidate_successor_report.md').write_text(report, encoding='utf-8', newline='\n')
    print('SUCCESSION_FULL_PASS', receipt.reference.to_dict(), flush=True)


def load_results():
    refs = [EvidenceRef.from_dict(read(EX / 'others/center_control.json')['account'])]
    for index in range(32):
        attempts = [read(p) for p in sorted((EX / 'others').glob(f'point_{index:02}*.json'))]
        success = [x for x in attempts if x['status'] == 'SUCCEEDED']
        assert len(success) == 1, (index, attempts)
        refs.append(EvidenceRef.from_dict(success[0]['account']))
    refs.append(EvidenceRef.from_dict(read(EX / 'others/stress.json')['account']))
    records = []
    docs = []
    for ref in refs:
        doc, rows = read_account(ROOT, ref)
        assert len(rows) == 1
        records.extend(rows)
        docs.append(doc)
    return refs, records, docs


def declared_protocol():
    return SelfCheckProtocol('s014-stage4-v1', 'full', 'baseline', 'double_cost', 252, 21,
        QuantileMethod.LINEAR, 32, 2, 2000, 20, 13, 1e-7, 10, ParameterPerturbationProtocol())


def policy():
    metrics = (ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE,
        ResearchMetric.PARAMETER_RETURN_Q10, ResearchMetric.PARAMETER_DRAWDOWN_Q90,
        ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.STRESS_ANNUAL_LOSS,
        ResearchMetric.PROFIT_CONCENTRATION, ResearchMetric.FULL_SAMPLE_FREQUENCY)
    def bins(ratio, frequency):
        return tuple(MetricBinSpec(m, frequency if m is ResearchMetric.FULL_SAMPLE_FREQUENCY else ratio,
                                   0., BinRounding.FLOOR) for m in metrics)
    return ComparisonPolicy('s014-stage4-ranking-v1', bins(.0001, .01), ParetoBasis.RAW,
        MissingEvidencePolicy.REQUIRE_COMPLETE,
        (ComparisonVariant('coarser-precision', bins(.001, .1)),))


def calculate():
    refs, records, docs = load_results()
    center = records[0]
    assert goals(center)['all_targets_pass']
    from family_evidence import build_family
    family, family_records, family_refs, inventory = build_family(center)
    write(EX / 'others/family_actual_center.json', inventory)
    links = tuple(PerturbationLink(center.candidate, x.candidate, 1., x.derivation_sha256, x.parameter_point)
                  for x in records[1:33])
    planref = EvidenceRef.from_dict(read(EX / 'protocols/parameter_plan_ref.json'))
    plan = ParameterEvaluationPlan.from_dict(read(planref.resolve(ROOT)))
    all_records = tuple({x.evaluation_id: x for x in (*records, *family_records)}.values())
    request = CandidateAssessmentRequest((center.candidate,), declared_protocol(), links,
        all_records, family_returns=family, parameter_designs=(plan.design,))
    panel = assess_candidates(request)
    write(REQUEST_WORK, request.to_dict())
    write(EX / 'others/assessment_panel.json', panel.to_dict())
    write(EX / 'protocols/ranking_policy.json', policy().to_dict())
    checks = []
    for doc, evidence in zip(docs, records, strict=True):
        signals = doc['runs'][0]['ledgers']['decisions']['data']
        daily = doc['runs'][0]['ledgers']['account_daily']['data']
        for row, account in zip(signals, daily, strict=True):
            if row['signal_date'][:10] != account['signal_date'][:10]:
                raise ValueError('Saved signal/next-execution ledger alignment differs')
        # Observed held state refers to signal-day close; the execution ledger
        # carries its position immediately before next-session execution.
        mismatch = [row['signal_date'][:10] for row, account in zip(signals, daily, strict=True)
                    if bool(row['held_at_close']) != bool(account['quantity_before'] > 0)]
        checks.append({'candidate': evidence.candidate.candidate_id, 'scenario': evidence.scenario_id,
                       'shadow_vs_funded_holding_mismatches': mismatch, 'goals': goals(evidence),
                       'observation_source': 'Authenticated published decisions ledger held_at_close compared with next-session account_daily quantity_before',
                       'new_funded_accounts': 0, 'new_market_requests': 0})
    summary = {'center': goals(center), 'point_goal_pass_count': sum(x['goals']['all_targets_pass'] for x in checks[1:33]),
        'account_count': len(records), 'point_count': 32,
        'shadow_holding_checks': checks, 'family_raw_trial_count': family.raw_trial_count,
        'family_paths': len(family.candidates),
        'parameter_actual_moves': {coord.name: sum(p.coordinates[i] != coord.center for p in plan.design.points)
            for i, coord in enumerate(plan.design.space.coordinates)},
        'account_refs': [x.to_dict() for x in refs], 'family_refs': [x.to_dict() for x in family_refs]}
    write(EX / 'others/numeric_summary.json', summary)
    print('ASSESSMENT_COMPUTED', [x.to_dict() for x in panel.rows[0].diagnostics], flush=True)


def finalize():
    ctx = context()
    print('ASSESSMENT_LOADING_AUTHENTICATED_REQUEST', flush=True)
    request = CandidateAssessmentRequest.from_dict(read(REQUEST_WORK))
    print('ASSESSMENT_REQUEST_LOADED', len(request.evidence), flush=True)
    refs = [EvidenceRef.from_dict(x) for name in ('account_refs', 'family_refs')
            for x in read(EX / 'others/numeric_summary.json')[name]]
    methods = published_methods(ctx)
    material_paths = [EX / 'others/numeric_summary.json', EX / 'others/family_actual_center.json',
        EX / 'others/center_annual_goals.json', EX / 'protocols/ranking_policy.json',
        EX / 'protocols/authorization.json', EX / 'others/candidate_succession.json',
        EX / 'others/independent_numeric_audit.json', EX / 'others/independent_contract_audit.json',
        EX / 'others/synthetic_precheck.json',
        EX / 'protocols/source_snapshot_anchors.json',
        *sorted((EX / 'others').glob('point_*.json'))]
    refs.extend(publish(ctx, p, 'ex054-final-' + sha256(p.relative_to(EX).as_posix().encode()).hexdigest()[:16]) for p in material_paths)
    refs.extend(EvidenceRef.from_dict(x) for x in methods.values())
    refs = tuple(dict.fromkeys(refs))
    print('ASSESSMENT_MATERIALS_PUBLISHED', len(refs), flush=True)
    report = (EX / 'protocols/final_report.md').read_text(encoding='utf-8')
    prior = delivery_ref('CANDIDATES', 15)
    planref = EvidenceRef.from_dict(read(EX / 'protocols/parameter_plan_ref.json'))
    receipt, validation, panel, comparison = publish_assessment(RepositoryContext.discover(ROOT),
        request=request, policy=policy(), source_candidates=prior, source_mandate=delivery_ref('MANDATE', 2),
        revision=1, parameter_plans=(planref,), evidence=refs,
        contrary_evidence=tuple(x for x in refs if x.sha256 in {
            sha256((EX / 'others/independent_numeric_audit.json').read_bytes()).hexdigest(),
            sha256((EX / 'others/family_actual_center.json').read_bytes()).hexdigest()}),
        recommendation='原经济目标达标保持，但邻近参数及时间稳定性不足。建议暂缓冻结与交易，不继续按同一已见历史反复微调；由用户决定先做新时段前向验证方案，或选择C9524仅进入阶段五技术检验。',
        pending_decisions=('用户决定先做新时段前向验证方案，还是明确选择C9524进入阶段五技术检验；新增数据窗口和冻结均须相应授权。',), report=report)
    write(EX / 'others/assessment_delivery.json', {'receipt': receipt.to_dict(), 'validation': validation.to_dict(),
        'comparison': comparison.to_dict(), 'candidate': request.centers[0].to_dict()})
    formal = ROOT / f'research/S014/deliveries/ASSESSMENT/{receipt.reference.revision}/report.md'
    (EX / 'others/report.md').write_bytes(formal.read_bytes())
    write(EX / 'protocols/report_copy_verification.json', {'formal': formal.relative_to(ROOT).as_posix(),
        'copy': (EX / 'others/report.md').relative_to(ROOT).as_posix(),
        'sha256': sha256(formal.read_bytes()).hexdigest(),
        'byte_equal': formal.read_bytes() == (EX / 'others/report.md').read_bytes()})
    print('ASSESSMENT_FULL_PASS', receipt.reference.to_dict(), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('succession', 'calculate', 'finalize'))
    {'succession': succession, 'calculate': calculate, 'finalize': finalize}[parser.parse_args().action]()
