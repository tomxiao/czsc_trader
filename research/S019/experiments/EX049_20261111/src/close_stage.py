"""Publish all eligible implementations from this authorized stage-three allocation."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, CandidateRegistrationRequest,
    ResearchIntentUpdate, assemble_delivery, create_research_context, get_research_overview,
    load_candidate, publish_evidence, register_candidate, update_research_intent, validate_delivery)
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash

ROOT = Path.cwd()
BATCH = ROOT/'research/S019'
sys.path.insert(0, str(BATCH/'experiments/EX013_20261110/src'))
from runner import metrics  # noqa: E402

def read(path):
    return json.loads(path.read_bytes())

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def historical_row(ref, origin_kind):
    """Normalize an authenticated original account, retaining its original ID/source."""
    source = ref.resolve(ROOT)
    raw = source.read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    header = json.loads(raw)

    def resolve(item):
        data = source.with_name(item['sha256']+'.json').read_bytes()
        assert sha256(data).hexdigest() == item['sha256']
        return data

    payload = materialize_equity(raw, resolve).payload
    request = payload['request']
    assert request['fee_rate'] == .001 and request['window_id'] == 'FULL' and request['scenario_id'] == 'STANDARD'
    assert request['measurement_tier'] == 'FORMAL' and request['initial_cash'] == 100000.
    definition = request['candidate_definition']
    parameters = json.loads(definition['parameters_json'])
    assert parameters['participation_policy'] == 'linear'
    family = {'hard':'hard_linear','ramp':'ramp_linear','ramp_rebuild':'rebuild_linear'}[parameters['exit_policy']]
    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
    return {'id':request['candidate_id'], 'account':ref.to_dict(), 'definition':definition,
        'parameters':parameters, 'content_hash':request['content_sha256'], 'family':family,
        'request_sha256':header['request_hash'], 'candidate':metrics(run,bh['metrics']['daily_max_drawdown']),
        'buy_hold':metrics(bh,bh['metrics']['daily_max_drawdown']),
        'source_root':(ref.experiment.resolve(ROOT)/'src').relative_to(ROOT).as_posix(),
        'origin_kind':origin_kind}


def predecessor_rows(repo):
    """Read the exact approved prototype panel after public integrity authentication."""
    receipt = d.DeliveryReceipt.from_dict(read(BATCH/'deliveries/PROTOTYPES/3/receipt.json'))
    validation = validate_delivery(repo,receipt.reference,scope=d.DeliveryValidationScope.INTEGRITY)
    assert validation.status is d.ValidationStatus.PASS
    root = BATCH/'assets/deliveries/PROTOTYPES/3'
    assert read(root/'receipt.json') == receipt.to_dict()
    document_file = next(item for item in receipt.files if item.path == 'delivery.json')
    assert digest(root/'delivery.json') == document_file.sha256
    panel = d.PrototypePanel.from_dict(read(root/'delivery.json')['content']['payload'])
    wanted = {'C0720','C0801','C0804'}
    rows = []
    for prototype in panel.prototypes:
        if prototype.prototype_id not in wanted:
            continue
        assert len(prototype.evaluations) == 1
        ref = prototype.evaluations[0].evidence
        row = historical_row(ref,'APPROVED_PREDECESSOR_PROTOTYPE')
        definition_ref = prototype.definition.evidence
        assert digest(definition_ref.resolve(ROOT)) == definition_ref.sha256
        assert read(definition_ref.resolve(ROOT)) == row['definition']
        assert row['id'] == prototype.prototype_id == prototype.identity.key.candidate_id
        assert row['content_hash'] == prototype.identity.content_sha256
        row['prototype_reference'] = d.PrototypeReference(receipt.reference,prototype.prototype_id).to_dict()
        rows.append(row)
    assert {row['id'] for row in rows} == wanted
    return receipt.reference, rows, validation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--next-action')
    parser.add_argument('--prepare-only',action='store_true')
    args = parser.parse_args()
    work = args.experiment.resolve()
    assert work.parent == BATCH/'experiments'
    if not args.prepare_only:
        assert args.report is not None and args.report.is_file(), 'Publication requires a written stage report'
        assert args.next_action and args.next_action.strip(), 'Publication requires the next research action'
    assert not (work/'others/stage_publication.json').exists()
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage'] == 'STAGE_THREE' and not intent.get('active_experiment')
    budget = intent['continuous_stage3_budget']
    assert budget['rounds'][-1]['experiment'] == work.name
    previous_budget = intent['joint_search_budget']
    predecessor, rows, predecessor_validation = predecessor_rows(repo)
    evidence = [d.EvidenceRef.from_dict(row['account']) for row in rows]
    summaries, fee_diagnostics = [], []
    for record in budget['rounds']:
        exp_work = BATCH/'experiments'/record['experiment']
        pub = read(exp_work/'others/publication.json')
        assert pub['validation']['status'] == 'PASS'
        report = d.EvidenceRef.from_dict(pub['report'])
        assert digest(report.resolve(ROOT)) == report.sha256
        assert read(report.resolve(ROOT))['report_sha256'] == digest(exp_work/'report.md')
        assert read(exp_work/'others/budget_settlement.json')['status'] == 'SETTLED_ONCE'
        evidence.append(report)
        adaptive = (exp_work/'protocols/search.json').exists()
        fee_diagnostic = (exp_work/'protocols/fee_pairs.json').exists()
        assert not (adaptive and fee_diagnostic)
        if adaptive:
            data = list(read(exp_work/'others/summary.json').values())
            proposal_identities = {row['content_hash'] for row in data}
            config = read(exp_work/'protocols/search.json')
            for paths in config['imported_observations'].values():
                for relative in paths:
                    item = read(ROOT/relative)
                    item['source_root'] = (BATCH/'experiments'/item['account']['experiment']['experiment_id']/'src').relative_to(ROOT).as_posix()
                    item['origin_kind'] = 'IMPORTED_HISTORICAL_OBSERVATION'
                    data.append(item)
            # Startup excludes replayed controls from imported trials, but original
            # controls remain authoritative identities for exact-content deduplication.
            for family in config['families']:
                ref = d.EvidenceRef.from_dict(read(ROOT/family['control_account']))
                item = historical_row(ref,'HISTORICAL_CONTROL_REFERENCE')
                item['family'] = family['name']
                data.append(item)
        else:
            completed = read(exp_work/'others/results.json')
            assert completed['status'] == 'COMPLETE'
            data = [{'id':r['candidate_id'],'account':r['account_ref'],**r} for r in completed['accounts'].values()]
            proposal_identities = {row['content_hash'] for row in data}
            for row in data:
                if row['role'] == 'REUSED_EVIDENCE':
                    ref = d.EvidenceRef.from_dict(row['account'])
                    row['source_root'] = (ref.experiment.resolve(ROOT)/'src').relative_to(ROOT).as_posix()
                    row['origin_kind'] = 'REUSED_PUBLISHED_ACCOUNT'
            if fee_diagnostic:
                fee_protocol = read(exp_work/'protocols/fee_pairs.json')
                assert fee_protocol['standard_fee_rate'] == .001 and fee_protocol['pressure_fee_rate'] == .002
                assert set(completed['accounts']) == set(completed['pressure_accounts']) == {p['label'] for p in fee_protocol['pairs']}
                pressure_evidence = []
                for label, pressure in completed['pressure_accounts'].items():
                    standard = completed['accounts'][label]
                    assert pressure['content_hash'] == standard['content_hash'] and pressure['definition'] == standard['definition']
                    assert pressure['candidate_id'] == standard['candidate_id'] and pressure['parameters'] == standard['parameters']
                    assert 'gates' not in pressure['candidate'] and 'eligible' not in pressure['candidate']
                    ref = d.EvidenceRef.from_dict(pressure['account_ref'])
                    assert digest(ref.resolve(ROOT)) == ref.sha256
                    header = read(ref.resolve(ROOT))
                    assert header['request']['fee_rate'] == .002
                    assert header['request']['candidate_definition'] == pressure['definition']
                    assert header['request']['content_sha256'] == pressure['content_hash']
                    assert header['request']['candidate_id'] == pressure['candidate_id']
                    evidence.append(ref)
                    pressure_evidence.append({'label':label,'candidate_id':pressure['candidate_id'],
                        'content_hash':pressure['content_hash'],'standard_account':standard['account_ref'],
                        'pressure_account':ref.to_dict(),'pressure_metrics':pressure['candidate'],
                        'pressure_gates':pressure['pressure_gates'],'pressure_eligible':pressure['pressure_eligible'],
                        'frequency_diagnostic':pressure['frequency_diagnostic']})
                fee_diagnostics.append({'experiment':exp_work.name,'protocol_sha256':digest(exp_work/'protocols/fee_pairs.json'),
                    'paired_configurations':len(pressure_evidence),'pairs':pressure_evidence,
                    'scope':'Development fee diagnosis. Standard accounts alone enter center qualification, deduplication and NAR ordering; pressure evidence remains separate.'})
        for item in data:
            row = dict(item)
            row.setdefault('source_root',(exp_work/'src').relative_to(ROOT).as_posix())
            row.setdefault('origin_kind','CONTROL_REPLAY_OR_NEW_PROPOSAL')
            row['stage_three_experiment'] = exp_work.name
            assert row['candidate']['eligible'] == all(row['candidate']['gates'].values())
            ref = d.EvidenceRef.from_dict(row['account'])
            evidence.append(ref)
            rows.append(row)
        summaries.append(d.SearchSummary('CONTINUOUS-'+exp_work.name,
            'Optuna约束多变量TPE、固定反馈与历史观察导入' if adaptive else
            '少数代表的配对费用开发诊断：标准账户复用、同参数每侧0.2%费用新回放' if fee_diagnostic else
            '事前固定局部因素及交互诊断，保留全部账户',
            '同候选标准与压力场景配对，无新参数；压力门独立核对，标准六门与NAR排序保持。' if fee_diagnostic else
            '有效参数、参数域和明确点集见实验事前方案；原六门与原NAR目标保持。',
            record['design_configurations'],len(proposal_identities),
            '全部原中心六门通过后按未舍入NAR降序；开发性敏感度诊断另列',
            ('连续已见开发样本和自适应选择','完整阶段四邻域及费用压力待批准','有限预算与未检参数选择风险'),
            (report,)))
    # C0720 and C0798 have exact economic parity but different source/content
    # identities. Keep both identities and preserve the existing parity evidence.
    parity_path = BATCH/'experiments/EX046_20261111/others/qualified_linear_hard_center_parity.json'
    parity = read(parity_path)
    old = next(row for row in rows if row['id'] == 'C0720')
    adapted = next(row for row in rows if row['id'] == 'C0798')
    assert parity['status'] == 'PASS' and read(ROOT/parity['control']) == old['account']
    assert parity['new_account'] == adapted['account']
    assert parity['daily_and_bar_economic_paths'] == parity['targets_and_fills'] == 'EXACT_EQUAL'
    assert old['parameters'] == adapted['parameters'] and old['candidate'] == adapted['candidate']
    assert old['content_hash'] != adapted['content_hash']
    predecessor_identity = {'delivery':predecessor.to_dict(), 'validation':predecessor_validation.to_dict(),
        'prototype_ids':['C0720','C0801','C0804'],
        'economic_parity_distinct_implementations':{'original_id':'C0720','adapted_id':'C0798',
            'original_content':old['content_hash'],'adapted_content':adapted['content_hash'],
            'parity_path':parity_path.relative_to(ROOT).as_posix(),'parity_sha256':digest(parity_path)},
        'counting':'Predecessor prototypes and original control references are not new proposals or account replays.'}
    groups = {}
    for row in rows:
        key = row['content_hash']
        if key in groups:
            old = groups[key][0]
            assert old['parameters'] == row['parameters'] and old['candidate'] == row['candidate']
        groups.setdefault(key,[]).append(row)
    qualified = []
    aliases = []
    for content, group in groups.items():
        canonical = min(group,key=lambda r:(r['id'],r['account']['sha256']))
        aliases.append({'content_hash':content,'canonical_id':canonical['id'],
            'candidate_ids':sorted({r['id'] for r in group}),
            'account_refs':list({r['account']['sha256']:r['account'] for r in group}.values()),
            'eligible':canonical['candidate']['eligible']})
        if canonical['candidate']['eligible']:
            qualified.append(canonical)
    qualified.sort(key=lambda r:(-r['candidate']['nar'],r['id']))
    assert len({r['id'] for r in qualified}) == len(qualified)
    counts = {'authorized_rounds':10,'used_rounds':budget['used_rounds'],'remaining_rounds':budget['remaining_rounds'],
        'candidate_runs':budget['candidate_accounts'],'benchmark_runs':budget['benchmark_accounts'],
        'unique_content_identities_including_imported':len(groups),'qualified_unique_implementations':len(qualified),
        'qualified_ids_by_nar':[r['id'] for r in qualified],'rounds':budget['rounds'],
        'predecessor_prototype_ids':['C0720','C0801','C0804'],
        'economic_parity_with_distinct_content':[{'original':'C0720','adapted':'C0798'}],
        'fee_development_diagnostic_pairs':sum(item['paired_configurations'] for item in fee_diagnostics),
        'original_goals_unchanged':True,'formal_stage_four_executed':False}
    validated = []
    for row in qualified:
        ref = d.EvidenceRef.from_dict(row['account'])
        assert digest(ref.resolve(ROOT)) == ref.sha256
        header = read(ref.resolve(ROOT))
        assert header['request']['candidate_definition'] == row['definition']
        assert header['request']['content_sha256'] == row['content_hash']
        assert header['request']['candidate_id'] == row['id']
        assert header['request']['fee_rate'] == .001 and header['request']['scenario_id'] == 'STANDARD'
        source = ROOT/row['source_root']
        definition = EquityStrategyDefinition.from_dict(row['definition'])
        assert equity_source_hash(source,definition.source_files) == definition.source_sha256
        candidate = EquityStrategyCandidate('S019',row['id'],definition,source)
        assert candidate.content_identity.content_sha256 == row['content_hash']
        validated.append((row, ref, header, candidate))
    # Exclude only validation timing/statistics from the deterministic review
    # contract. Candidate definitions, IDs, accounts, aliases and both budgets
    # must still match the saved review exactly before any registry mutation.
    review_contract = {'experiment':work.name, 'source_sha256':digest(Path(__file__)),
        'qualified':qualified, 'aliases':aliases, 'budget':budget, 'historical_budget':previous_budget,
        'counts':counts, 'fee_diagnostics':fee_diagnostics,
        'predecessor_identity':{key:value for key,value in predecessor_identity.items() if key != 'validation'},
        'evidence':[ref.to_dict() for ref in dict.fromkeys(evidence)],
        'searches':[summary.to_dict() for summary in summaries]}
    review_hash = sha256(json.dumps(review_contract,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    preparation_path = work/'others/stage_preparation.json'
    if args.prepare_only:
        if preparation_path.exists():
            existing = read(preparation_path)
            assert existing['review_contract'] == review_contract and existing['review_sha256'] == review_hash, 'Saved stage preparation drifted; inspect before preparing a revision'
        else:
            save(preparation_path, {'status':'PREPARED_NOT_PUBLISHED', 'qualified':qualified, 'aliases':aliases,
                'predecessor_identity':predecessor_identity, 'budget':budget, 'counts':counts,'fee_diagnostics':fee_diagnostics,
                'review_contract':review_contract, 'review_sha256':review_hash,
                'candidate_registration_performed':False, 'delivery_published':False, 'intent_updated':False})
        print('STAGE_THREE_PREPARED',len(qualified),'remaining',budget['remaining_rounds'],review_hash)
        return
    assert preparation_path.is_file(), 'Prepare and review the exact candidate set before publication'
    preparation = read(preparation_path)
    assert preparation['status'] == 'PREPARED_NOT_PUBLISHED'
    assert preparation['review_contract'] == review_contract and preparation['review_sha256'] == review_hash, 'Stage preparation drifted; publication stopped before registration'
    context = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    entries, registrations = [], []
    for row, ref, header, candidate in validated:
        registration = register_candidate(repo,CandidateRegistrationRequest(candidate,ref.experiment,(ref,),tuple(candidate.definition.dependencies)))
        loaded = load_candidate(repo,CandidateKey('S019',row['id']))
        assert loaded.content_identity.content_sha256 == row['content_hash']
        registrations.append(registration.to_dict())
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(candidate.key,row['content_hash']),
            '前日下跌后首30分钟恢复入场，季度相对走势与连续成交参与配置仓位，ATR退出及五日上限。',
            '完整连续账户通过原中心全部经济与频率门槛；阶段三开发性诊断与完整阶段四自检分别留证。',
            (d.EvaluationEvidenceRef(ref,(header['evaluation_id'],)),)))
    save(work/'others/stage_qualified_candidates.json',qualified)
    save(work/'others/stage_exact_aliases.json',aliases)
    save(work/'others/candidate_registrations.json',registrations)
    save(work/'others/stage_predecessor_identity.json',predecessor_identity)
    save(work/'others/stage_fee_diagnostics.json',fee_diagnostics)
    save(work/'others/stage_summary.json',counts)
    exp = d.ExperimentRef('S019',work.name)
    for path in (Path(__file__),work/'others/stage_qualified_candidates.json',work/'others/stage_exact_aliases.json',
                 work/'others/candidate_registrations.json',work/'others/stage_summary.json',
                 work/'others/stage_predecessor_identity.json',work/'others/stage_fee_diagnostics.json',parity_path,preparation_path):
        suffix = path.suffix[1:]
        evidence.append(publish_evidence(context,d.MaterialEvidenceWrite(exp,'stage-three-'+path.stem,
            path.read_bytes(),{'py':'text/x-python','json':'application/json'}[suffix],suffix)))
    versions = [int(p.name) for p in (BATCH/'deliveries/CANDIDATES').iterdir() if p.is_dir() and p.name.isdecimal()]
    revision = max(versions)+1
    result = assemble_delivery(repo,d.DeliveryDefinition(batch,d.DeliveryStage.CANDIDATES,revision,(predecessor,)),
        d.DeliveryContent(d.CandidateSet(tuple(entries),tuple(e.identity.key for e in entries),tuple(summaries),
            '新授权阶段三已完成；全部中心达标实现精确去重并按NAR交接，正式阶段四等待用户批准。'),
            d.DeliveryStatus.COMPLETE,(),(),report=args.report.read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys(evidence))))
    assert result.validation.status is d.ValidationStatus.PASS
    assert result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    save(work/'others/stage_publication.json',result.to_dict())
    fresh = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert fresh['continuous_stage3_budget'] == budget and fresh['joint_search_budget'] == previous_budget
    fresh.update(continuous_stage3_status='COMPLETE',continuous_stage3_delivery=result.receipt.reference.to_dict(),
        continuous_stage3_qualified_candidates=[r['id'] for r in qualified],
        continuous_stage3_next_stage_approval='PENDING_USER_APPROVAL',next_action=args.next_action)
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=fresh),actor='RSCH',
        reason='完成已授权阶段三研究与完整达标候选交接，下一阶段按用户批准推进。')
    save(work/'others/final_overview.json',get_research_overview(repo,batch).to_dict())
    print('STAGE_THREE_PUBLISHED',len(qualified),result.receipt.reference.content_sha256,'remaining',budget['remaining_rounds'])

if __name__ == '__main__':
    main()
