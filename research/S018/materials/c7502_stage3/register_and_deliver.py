"""Prepare, then explicitly publish the complete S018 stage-three candidate set.

Default is a read-only preparation check. --publish registers and loads every
passing unique candidate and publishes CANDIDATES/1; it never runs an account,
starts stage four, or freezes a strategy. Supply all completed stage-three rounds.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, CandidateRegistrationRequest, register_candidate,
    load_candidate, assemble_delivery, create_research_context, publish_evidence,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_runtime.equity_definition import EquityStrategyDefinition, EquityStrategyCandidate


ROOT = Path.cwd()
FAMILY = ROOT/'research/S018'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def verify_reference(value):
    ref = d.EvidenceRef.from_dict(value)
    data = ref.resolve(ROOT).read_bytes()
    assert sha256(data).hexdigest() == ref.sha256
    return ref


def original_gates(metrics, benchmark):
    return dict(calmar=metrics['calmar'] is not None and metrics['calmar'] >= 1.5*benchmark['calmar'],
        dd_absolute=metrics['dd'] <= .25, dd_relative=metrics['dd'] <= .8*benchmark['dd'],
        median=metrics['median'] >= 6, coverage=metrics['coverage'] >= .9)


def dominates(left, right):
    # Trade-off frontier, not an alternative ranking or additional hard gate.
    a = (left['calmar'], -left['dd'], left['median'], left['coverage'])
    b = (right['calmar'], -right['dd'], right['median'], right['coverage'])
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def hypothesis(config):
    common = config.get('common_budget', 1.0)
    other = config.get('other_budget', 0.0)
    percent = lambda value: f'{value*100:g}%'
    if config['common_share'] is None or common == other:
        entry = f'两日回落时统一使用{percent(common)}可用现金预算，作为不按行业分组的对照'
    elif other == 0:
        entry = f'仅参与共同下跌贡献超过{percent(config["common_share"])}的两日回落，使用{percent(common)}可用现金预算'
    elif common > other:
        entry = f'两日回落均可入场；共同下跌组预算{percent(common)}、其余组{percent(other)}，检验行业信息对风险分配的用途'
    else:
        entry = f'两日回落均可入场；共同下跌组预算{percent(common)}、其余组{percent(other)}，作为反向分配对照'
    return entry + f'；第{config["review_after"]}日起按信号价判断续持，最多持有{config["max_hold"]}日后发退出决定。完整参数：' + canonical(config)


def prepare(experiment_ids):
    grouped, rounds, refs = {}, [], []
    benchmark = None
    for eid in sorted(experiment_ids):
        work = FAMILY/'experiments'/eid
        protocol = read(work/'others/protocol.json')
        assert protocol['stage'] == 3, (eid, 'not a stage-three search')
        result = read(work/'others/results.json')
        statuses = read(work/'others/execution_status.json')
        assert all(x['status'] == 'SUCCEEDED' for x in statuses), (eid, 'incomplete execution')
        assert len(statuses) == len(result['accounts']) == len(protocol['configurations'])
        report_ref = verify_reference(read(work/'report_ref.json')['report'])
        available_refs = tuple(verify_reference(x) for x in read(work/'others/evidence_refs.json'))
        round_refs = tuple(dict.fromkeys((*available_refs, report_ref)))
        refs.extend(round_refs)
        if benchmark is None:
            benchmark = result['benchmark']
        assert result['benchmark'] == benchmark, (eid, 'benchmark changed')
        local_configs = set()
        for cid, row in result['accounts'].items():
            assert row['gates'] == original_gates(row['candidate'], benchmark), (cid, 'gate mismatch')
            definition = EquityStrategyDefinition.from_dict(row['definition'])
            candidate = EquityStrategyCandidate('S018', cid, definition, work/'src')
            candidate.verify()
            assert json.loads(definition.parameters_json) == row['config']
            account = verify_reference(row['account_ref'])
            config_key = canonical(row['config'])
            local_configs.add(config_key)
            normalized_definition = dict(row['definition'])
            normalized_definition['parameters_json'] = config_key
            origin = dict(experiment=eid, candidate=cid, account_ref=account.to_dict(),
                          metrics=row['candidate'], gates=row['gates'])
            if config_key in grouped:
                original = grouped[config_key]
                assert original['definition_key'] == canonical(normalized_definition), (
                    cid, 'same parameters have different implementation or execution; do not silently deduplicate')
                assert original['row']['candidate'] == row['candidate'], (cid, 'duplicate results differ')
                original['origins'].append(origin)
            else:
                grouped[config_key] = dict(candidate=candidate, row=row, account=account,
                    experiment=d.ExperimentRef('S018', eid), definition_key=canonical(normalized_definition),
                    origins=[origin])
        rounds.append(dict(experiment=eid, evaluations=len(result['accounts']),
            unique_configurations=len(local_configs), question=protocol['question'],
            protocol=protocol, evidence=round_refs))
    unique = list(grouped.values())
    passed = sorted((x for x in unique if all(x['row']['gates'].values())),
        key=lambda x:(-x['row']['candidate']['calmar'], x['candidate'].candidate_id))
    frontier = [x['candidate'].candidate_id for x in unique
        if x['row']['candidate']['calmar'] is not None and not any(
            y['row']['candidate']['calmar'] is not None and dominates(y['row']['candidate'], x['row']['candidate'])
            for y in unique)]
    manifest = dict(stage=3, experiments=[x['experiment'] for x in rounds],
        evaluations=sum(x['evaluations'] for x in rounds), unique_configurations=len(unique),
        passing_unique_configurations=len(passed),
        passing_order=[x['candidate'].candidate_id for x in passed],
        frontier_definition='Non-dominated on net Calmar up, drawdown down, rolling60 median up, coverage up; diagnostic only.',
        frontier=frontier, benchmark=benchmark,
        objective='net annualized return / maximum close-equity drawdown; original hard gates unchanged',
        selection='All passing unique configurations handed off, sorted by original D; ties by candidate id only.',
        deduplication='Identical full parameters AND same definition; retain first formal account and all occurrences. No behavioral deduplication.',
        limitations=['All research uses repeatedly seen development data 2023-01-03 through 2026-10-30.',
            'Stage-three counts exclude earlier stage-two exploration; prior selection bias remains.',
            'Nearby configurations share signals and capital paths; unique configurations are not independent statistical tests.',
            'No effective independent trial count or out-of-sample success probability is claimed.',
            'Candidate registration and delivery do not establish stage-four robustness or authorize stage four.'],
        configurations=[dict(candidate=x['candidate'].candidate_id, config=x['row']['config'],
            metrics=x['row']['candidate'], gates=x['row']['gates'], origins=x['origins']) for x in unique])
    return manifest, passed, rounds, tuple(dict.fromkeys(refs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiments', nargs='+', help='EX050_20261104 and every successor in this search')
    parser.add_argument('--report', required=True, help='Authored stage-three report, repository-relative path')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    assert len(args.experiments) == len(set(args.experiments))
    report_path = (ROOT/args.report).resolve()
    assert report_path.is_relative_to(ROOT)
    report = report_path.read_text(encoding='utf-8-sig')
    assert report.strip()
    manifest, passing, rounds, refs = prepare(args.experiments)
    transition = read(FAMILY/'materials/c7502_stage3/transition_receipt.json')
    predecessor = d.DeliveryReference.from_dict(transition['delivery'])
    assert predecessor.stage == d.DeliveryStage.PROTOTYPES and predecessor.revision == 1
    assert transition['validation']['status'] == 'PASS'
    summary = {k:v for k,v in manifest.items() if k != 'configurations'}
    if not args.publish:
        print(json.dumps(dict(mode='READ_ONLY_READY', **summary), ensure_ascii=False, indent=2))
        return
    repo = RepositoryContext.discover(ROOT)
    assert passing, 'No passing candidates: author a no-candidate conclusion explicitly instead.'
    entries, registration_receipts = [], []
    for item in passing:
        candidate = item['candidate']
        record = register_candidate(repo, CandidateRegistrationRequest(candidate, item['experiment'],
            (item['account'],), candidate.definition.dependencies))
        loaded = load_candidate(repo, candidate.key)
        loaded.verify()
        assert loaded.content_identity == candidate.content_identity
        registration_receipts.append(dict(candidate=candidate.candidate_id,
            content_sha256=record.content_sha256, loaded_identity_matches=True))
        m = item['row']['candidate']
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(candidate.key, candidate.content_identity.content_sha256),
            hypothesis(item['row']['config']),
            f"原全部经济和频率门通过，净卡玛{m['calmar']:.9f}；开发池优化结果，尚未阶段四自检。",
            (d.EvaluationEvidenceRef(item['account']),)))
        print('REGISTERED_AND_LOAD_VERIFIED', candidate.candidate_id, flush=True)
    manifest['registration'] = registration_receipts
    context = create_research_context(repo, d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=passing[0]['candidate'].definition.execution_spec)
    owner = d.ExperimentRef('S018', sorted(args.experiments)[-1])
    manifest_ref = publish_evidence(context, d.MaterialEvidenceWrite(owner, 'stage3-complete-search-handoff',
        (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8'), 'application/json', 'json'))
    source_ref = publish_evidence(context, d.MaterialEvidenceWrite(owner, 'stage3-registration-delivery-source',
        Path(__file__).read_bytes(), 'text/x-python', 'py'))
    searches = tuple(d.SearchSummary(x['experiment'], '按研究问题组织正式账户参数比较',
        x['question']+'；完整预设参数域见protocol直接证据。', x['evaluations'], x['unique_configurations'],
        '保留全部配置与负面结果，跨轮去重后交接全部通过原硬门的配置，按原D降序。',
        tuple(manifest['limitations']), x['evidence']) for x in rounds)
    content = d.DeliveryContent(d.CandidateSet(tuple(entries), tuple(x.identity.key for x in entries), searches,
        f"{manifest['evaluations']}次正式账户评价，{manifest['unique_configurations']}组唯一参数，"
        f"全部{len(entries)}个达标候选已登记并验证可加载；尚未进行阶段四自检。"),
        d.DeliveryStatus.COMPLETE, (), (), report=report,
        evidence=tuple(dict.fromkeys((*refs, manifest_ref, source_ref))))
    assembled = assemble_delivery(repo,
        d.DeliveryDefinition(d.ResearchBatchRef('S018'), d.DeliveryStage.CANDIDATES, 1, (predecessor,)), content,
        on_progress=lambda progress: print('DELIVERY_PROGRESS', progress.phase.value,
            progress.completed, progress.total, flush=True))
    assert assembled.validation.status.value == 'PASS'
    out = FAMILY/'materials/c7502_stage3'
    (out/'candidate_handoff_summary.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    receipt = dict(delivery=assembled.receipt.reference.to_dict(), validation=assembled.validation.to_dict(),
        registered=registration_receipts, search_manifest=manifest_ref.to_dict(),
        account_runs=0, entered_stage_four=False)
    (out/'candidate_handoff_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
