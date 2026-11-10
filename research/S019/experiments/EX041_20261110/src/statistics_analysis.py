"""Incremental, read-only S019 statistics using immutable prior TDR/SE evidence."""
from pathlib import Path
import os
import sys
from hashlib import sha256
import json
import importlib.util
from collections import defaultdict
from dataclasses import asdict
from itertools import combinations
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
PRIOR = WORK.parent / 'EX039_20261110'
SEARCH = WORK.parent / 'EX040_20261110'
SCRATCH = ROOT / '.tmp/s019-stage4-041/statistics'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True

import numpy as np  # noqa: E402
import strategy_evaluator as se  # noqa: E402
from strategy_evaluator.audit_models import ReturnMatrixEvidence  # noqa: E402
from strategy_runtime import canonical_sha256  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import RepositoryContext, project_selection_window_facts  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source(ref):
    typed = d.EvidenceRef.from_dict(ref)
    path = typed.resolve(ROOT)
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == typed.sha256
    return path, raw, json.loads(raw)


def cache_validation():
    report_ref = read(PRIOR/'report_ref.json')['report']
    _, _, report = source(report_ref)
    files = ['src/statistics_analysis.py', 'protocols/statistics_protocol.json',
             'others/statistics_inventory.json', 'others/statistics_returns.json',
             'others/statistics_selection_projection.json', 'others/statistics_completion.json']
    bindings = {}
    for name in files:
        path = PRIOR/name
        fingerprint = sha256(path.read_bytes()).hexdigest()
        evidence, = [r for r in report['evidence'] if r['sha256'] == fingerprint]
        assert d.EvidenceRef.from_dict(evidence).resolve(ROOT).read_bytes() == path.read_bytes()
        bindings[name] = {'reference': evidence, 'sha256': fingerprint, 'status': 'IMMUTABLE_PUBLICATION_MATCH'}
    done = read(PRIOR/'others/statistics_completion.json')
    assert done['status'] == 'COMPLETE' and done['source_sha256'] == bindings[files[0]]['sha256']
    return {'report_reference': report_ref, 'files': bindings}


def load_base(bindings):
    path = PRIOR/'src/statistics_analysis.py'
    assert sha256(path.read_bytes()).hexdigest() == bindings['files']['src/statistics_analysis.py']['sha256']
    spec = importlib.util.spec_from_file_location('s019_prior_statistics_tools', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORK, module.SCRATCH = WORK, SCRATCH
    os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH))
    return module


def freeze():
    caches = cache_validation()
    prior = read(PRIOR/'others/statistics_inventory.json')
    rows = [{k:v for k,v in r.items() if k != 'aliases'} for p in prior['rows'] for r in [p]+p['aliases']]
    records = read(PRIOR/'others/account_results.json')['accounts']
    additions = [(r['account_ref'], r['definition'], r['candidate_id'], 'EX039_REVIEWED_NEIGHBORHOOD')
                 for r in records.values() if r['label'] != 'STRESS']
    excluded = [{'reference': r['account_ref'], 'reason': 'FEE_STRESS_DIFFERENT_SCENARIO'}
                for r in records.values() if r['label'] == 'STRESS']
    summary = read(SEARCH/'others/summary.json')
    additions += [(r['account'], read(SEARCH/f'others/{name}_definition.json'), r['id'], 'EX040_ADAPTIVE_PROPOSAL')
                  for name,r in summary.items()]
    assert len(additions) == 136
    for reference, definition, cid, origin in additions:
        path, _, header = source(reference)
        req = header['request']
        assert req['candidate_definition'] == definition and req['candidate_id'] == cid
        assert req['fee_rate'] == .001 and req['measurement_tier'] == 'FORMAL'
        assert req['window']['start'].startswith('2022-01-03') and req['window']['end'].startswith('2026-10-30')
        identity = {key:req[key] for key in ('instrument','specification','window','history_start','initial_cash','benchmark_sha256','fee_rate','drawdown_basis','engine_sources','python_version','pandas_version')}
        identity['data'] = header['data']
        rows.append({'candidate_id': cid, 'experiment': reference['experiment']['experiment_id'], 'reference': reference,
                     'content_sha256': req['content_sha256'], 'implementation_sha256': canonical_sha256(definition),
                     'source_sha256': definition['source_sha256'], 'parameters': json.loads(definition['parameters_json']),
                     'context_proxy': canonical_sha256(identity), 'context_components': {k:canonical_sha256(v) for k,v in identity.items()},
                     'candidate_artifact': header['candidate_ref'], 'origin': origin,
                     'candidate_bytes': path.with_name(header['candidate_ref']['sha256']+'.json').stat().st_size})
    assert len(rows) == len({r['reference']['sha256'] for r in rows}) == 374
    by_definition = defaultdict(list)
    for row in rows:
        by_definition[row['implementation_sha256']].append(row)
    inventory = {'published_account_count': len(rows), 'unique_implementations': len(by_definition),
                 'rows': [{**group[0], 'aliases': group[1:]} for group in by_definition.values()],
                 'new_header_reads': len(additions), 'excluded_scenarios': excluded,
                 'history': {'EX005_to_EX038': 238, 'EX039_reviewed_standard_neighborhood': 88,
                             'EX040_imported_observations': 81, 'EX040_new_proposals_and_accounts': 48,
                             'imported_observations_create_new_trials': False,
                             'EX041_selfcheck_points': 'EXCLUDED_FROM_PRIOR_SELECTION_UNIVERSE'},
                 'scope': 'All previously reviewed standard accounts through EX040; exact source/parameter repeats retained as aliases.'}
    assert inventory['unique_implementations'] == 371
    centers = read(WORK/'protocols/centers.json')
    for center in centers:
        row, = [r for r in rows if r['candidate_id'] == center['id']]
        assert row['reference'] == center['account_ref'] and row['content_sha256'] == center['content_hash']
    save(WORK/'others/statistics_inventory.json', inventory)
    protocol = {'version': 'S019-stage-four-statistics-EX041-v1', 'centers': [c['id'] for c in centers],
                'sample': {'start': '2022-01-03', 'end': '2026-10-30', 'sessions': 1212, 'status': 'REPEATEDLY_SEEN_DEVELOPMENT'},
                'inventory_sha256': sha256((WORK/'others/statistics_inventory.json').read_bytes()).hexdigest(),
                'centers_sha256': sha256((WORK/'protocols/centers.json').read_bytes()).hexdigest(),
                'reused_evidence': caches,
                'selection': {'method': 'Reuse published 236-source TDR yearly facts; project only 135 new unique implementations; SE typed request combines exact facts.',
                              'pairs': ['2022->2023','2023->2024','2024->2025','2025->2026_through_10_30'],
                              'rule': 'All six original center gates, then unrounded NAR descending; retain ties.',
                              'benchmark': 'Exact source-specific standard-fee buy-hold; do not fabricate a common binding.',
                              'max_window_facts': 10000, 'max_source_bytes': 18000000000, 'max_shared_bytes': 5000000000},
                'bootstrap': {'repetitions': 10000, 'mean_block_length': 21, 'seed': 20261110, 'interval': 'percentile_95',
                              'pairs': [[c['id'],'MU_BUY_HOLD'] for c in centers]+[list(x) for x in combinations([c['id'] for c in centers],2)],
                              'metrics': ['NAR','negative_MDD','Calmar'], 'mdd_sign': 'Positive difference means smaller MDD magnitude.'},
                'proxy': {'blocks': 10, 'splits': 252, 'objective': 'SHARPE_PROXY', 'raw_count': 374,
                          'effective_count': 'Return-correlation eigenvalue participation ratio'},
                'resources': {'processes': 1, 'native_threads': 1, 'new_strategy_accounts': 0},
                'limitations': ['Frozen after center choice and before EX041 statistical calculations.',
                                'EX039 selfcheck fed EX040 optimization: all 88 reviewed standard neighbors included; 81 imported observations are reused inputs.',
                                'Fixed hindsight candidate universe on repeatedly seen development history; no independent validation.',
                                'Four overlapping annual pairs; 2026 is incomplete; annual gates diagnose sensitivity, formal center gates retain the original full window.',
                                'Stationary block resampling rearranges chronology and conditions on observed history.',
                                'Sharpe proxy PBO/DSR address a different selection objective; actual NAR-plus-hard-gates adaptive selection bias remains NOT_ESTIMATED.',
                                'Published account count and correlation effective count are diagnostic assumptions, not independent choices.',
                                'Current EX041 neighborhoods and all fee-stress accounts are excluded from the prior standard selection universe.']}
    save(WORK/'protocols/statistics_protocol.json', protocol)
    print('PROTOCOL_FROZEN',len(rows),len(by_definition),flush=True)


def bootstrap(values, protocol):
    results = []
    for left, right in protocol['bootstrap']['pairs']:
        a = values[left]
        b = a if right == 'MU_BUY_HOLD' else values[right]
        assert a['sessions'] == b['sessions'] and a['benchmark_returns'] == b['benchmark_returns']
        y = a['benchmark_returns'] if right == 'MU_BUY_HOLD' else b['returns']
        result = se.paired_stationary_bootstrap(np.asarray(a['returns']), np.asarray(y), champion_id=left, comparator_id=right,
                    repetitions=10000, mean_block_length=21, seed=20261110)
        results.append(result.to_dict())
    save(WORK/'others/statistics_bootstrap.json', {'protocol': protocol['bootstrap'], 'comparisons': results,
         'center_references': [values[c]['reference'] for c in protocol['centers']], 'limitations': protocol['limitations']})
    print('BOOTSTRAP_COMPLETE',flush=True)


def selection(inventory, protocol, base):
    previous = d.SelectionWindowFactsResult.from_dict(read(PRIOR/'others/statistics_selection_projection.json'))
    plan_raw = previous.request.plan.to_dict()
    plan_raw['limitations'] = protocol['limitations']
    plan = se.SelectionWindowPlan.from_dict(plan_raw)
    old_refs = {s.evaluation.sha256 for s in previous.request.sources}
    new_rows = [r for r in inventory['rows'] if r['reference']['sha256'] not in old_refs]
    assert len(new_rows) == 135
    path = WORK/'others/statistics_incremental_projection.json'
    request = d.SelectionWindowFactsRequest(tuple(d.SelectionWindowSource(se.AssessmentCandidate('S019-'+r['candidate_id'],r['content_sha256']),d.EvidenceRef.from_dict(r['reference'])) for r in new_rows),
        plan,60,3,d.SelectionProjectionBudget(10000,18000000000,5000000000))
    save(WORK/'others/statistics_incremental_request.json',request.to_dict())
    if path.exists():
        incremental = d.SelectionWindowFactsResult.from_dict(read(path))
        assert incremental.request == request
    else:
        incremental = project_selection_window_facts(RepositoryContext.discover(ROOT),request)
        save(path,incremental.to_dict())
    assert not previous.failures and not incremental.failures
    sources = previous.sources+incremental.sources
    facts = {}
    for fact in previous.facts+incremental.facts:
        key = fact.source_id, fact.window.window_id
        if key in facts:
            assert facts[key] == fact
        facts[key] = fact
    groups = defaultdict(list)
    for binding in sources:
        groups[(binding.context_sha256,canonical_sha256(binding.scenario_context.to_dict()))].append(binding)
    rule = se.SelectionRule('S019-original-center-gates-NAR-v1',sha256((ROOT/'research/S019/materials/stage1_agreement.md').read_bytes()).hexdigest(),
        base.center_targets(),(se.SelectionMetricOrder(se.ResearchMetric.NET_ANNUAL_RETURN,se.SelectionDirection.MAXIMIZE),))
    results = []
    for context, bindings in groups.items():
        ids = {x for b in bindings for x in (b.source_id,b.benchmark_source_id)}
        analysis = se.SelectionStabilityRequest(plan,rule,tuple(bindings),tuple(f for f in facts.values() if f.source_id in ids),base.center_targets())
        result = se.assess_selection_stability(analysis)
        results.append({'context': context,'members':[b.candidate.candidate_id for b in bindings],
                        'request':analysis.to_dict(),'result':result.to_dict()})
    save(WORK/'others/statistics_selection.json',{'groups':results,'prior_projection_reference':protocol['reused_evidence']['files']['others/statistics_selection_projection.json']['reference'],
         'incremental_projection_sha256':sha256(path.read_bytes()).hexdigest(),'incremental_stats':incremental.stats.to_dict(),
         'scope':'Derived typed SE analysis combines two actual public TDR projections; no synthetic all-source TDR receipt.',
         'actual_nar_gated_adaptive_selection_bias':'NOT_ESTIMATED'})
    print('SELECTION_COMPLETE',len(sources),len(groups),flush=True)
    return groups


def proxies(values, groups, inventory, protocol):
    outcomes = []
    for context, bindings in groups.items():
        ids = [b.candidate.candidate_id.removeprefix('S019-') for b in bindings]
        reference = values[ids[0]]
        assert all(tuple(values[c]['sessions'])==tuple(reference['sessions']) and values[c]['benchmark_returns']==reference['benchmark_returns'] for c in ids)
        matrix = np.column_stack([values[c]['returns'] for c in ids])
        digest = sha256(matrix.astype('<f8',copy=False).tobytes()).hexdigest()
        raw_count = sum(1+len(r['aliases']) for r in inventory['rows'] if r['candidate_id'] in ids)
        data = ReturnMatrixEvidence(tuple(reference['sessions']),tuple(ids),tuple(tuple(float(x) for x in row) for row in matrix),digest)
        record = {'context':context,'members':ids,'raw_trials':raw_count,'unique_implementations':len(ids),'matrix_sha256':digest,'diagnostics':{}}
        try:
            pbo=se.cscv_pbo(data,block_count=10)
            assert all(s.validation_candidate_count==len(ids) for s in pbo.splits)
            record['diagnostics']['PBO_SHARPE_PROXY']={'status':'AVAILABLE',**pbo.to_dict()}
        except (ValueError,FloatingPointError,ZeroDivisionError) as error:
            record['diagnostics']['PBO_SHARPE_PROXY']={'status':'INSUFFICIENT_DATA','reason':str(error)}
        sharpes=np.asarray([se.annualized_sharpe(matrix[:,i]) for i in range(len(ids))])
        assert np.isfinite(sharpes).all()
        effective=None
        try:
            effective=se.effective_trial_count(matrix)
            record['diagnostics']['EFFECTIVE_TRIAL_COUNT']={'status':'AVAILABLE','value':effective}
        except (ValueError,FloatingPointError,ZeroDivisionError) as error:
            record['diagnostics']['EFFECTIVE_TRIAL_COUNT']={'status':'INSUFFICIENT_DATA','reason':str(error)}
        for cid in protocol['centers']:
            if cid not in ids:
                continue
            dsr={}
            for label,count in (('RAW',raw_count),('EFFECTIVE',effective)):
                if count is None:
                    dsr[label]={'status':'INSUFFICIENT_DATA','reason':'Effective count unavailable'}
                    continue
                try:
                    dsr[label]={'status':'AVAILABLE',**asdict(se.deflated_sharpe_ratio(matrix[:,ids.index(cid)],sharpes,float(count)))}
                except (ValueError,FloatingPointError,ZeroDivisionError) as error:
                    dsr[label]={'status':'INSUFFICIENT_DATA','reason':str(error)}
            record['diagnostics']['DSR_SHARPE_PROXY_'+cid]=dsr
        outcomes.append(record)
    save(WORK/'others/statistics_search_bias.json',{'groups':outcomes,'actual_nar_gated_adaptive_selection_bias':'NOT_ESTIMATED',
         'limitations':protocol['limitations'],'new_strategy_accounts':0})


def main():
    if '--freeze' in sys.argv:
        freeze()
        return
    started=perf_counter()
    protocol=read(WORK/'protocols/statistics_protocol.json')
    assert cache_validation()==protocol['reused_evidence']
    assert sha256((WORK/'protocols/centers.json').read_bytes()).hexdigest()==protocol['centers_sha256']
    assert sha256((WORK/'others/statistics_inventory.json').read_bytes()).hexdigest()==protocol['inventory_sha256']
    inventory=read(WORK/'others/statistics_inventory.json')
    base=load_base(protocol['reused_evidence'])
    prior_returns=read(PRIOR/'others/statistics_returns.json')
    values={v['candidate_id']:v for v in prior_returns['members']}
    assert len(values)==236
    reused_ids=set(values)
    rows={r['candidate_id']:r for r in inventory['rows']}
    for cid in protocol['centers']:
        values[cid]=base.extract(rows[cid],protocol)
    bootstrap(values,protocol)
    center_seconds=perf_counter()-started
    groups=selection(inventory,protocol,base)
    selection_seconds=perf_counter()-started-center_seconds
    extracted=0
    aliases=[]
    for cid,row in rows.items():
        if cid not in values:
            values[cid]=base.extract(row,protocol)
            extracted+=1
            if extracted%10==0:
                print('INCREMENTAL_READ',extracted,'of 132',round(perf_counter()-started,1),flush=True)
        if cid in reused_ids:
            assert values[cid]['reference']==row['reference'] and values[cid]['implementation_sha256']==row['implementation_sha256']
        for alias in row['aliases']:
            if alias['reference']['experiment']['experiment_id']!='EX040_20261110':
                aliases.append({'canonical':cid,'alias':alias['candidate_id'],'status':'REUSED_PUBLISHED_EX039_VERIFICATION'})
                continue
            other=base.extract(alias,protocol)
            assert all(other[k]==values[cid][k] for k in ('sessions','returns','benchmark_returns','context_sha256','scenario_context'))
            aliases.append({'canonical':cid,'alias':alias['candidate_id'],'status':'EXACT_DAILY_EQUIVALENCE_VERIFIED'})
    save(WORK/'others/statistics_returns.json',{'members':list(values.values()),'reused_members':236,'incremental_unique_members':135,
         'previous_returns_reference':protocol['reused_evidence']['files']['others/statistics_returns.json']['reference'],
         'protocol_sha256':sha256((WORK/'protocols/statistics_protocol.json').read_bytes()).hexdigest(),'alias_verification':aliases})
    proxies(values,groups,inventory,protocol)
    outputs={p.name:sha256(p.read_bytes()).hexdigest() for p in (WORK/'others').glob('statistics*.json')
             if p.name not in ('statistics_completion.json','statistics_summary.json')}
    prior_seconds=read(WORK/'others/statistics_technical_note.json')['first_attempt_log_wall_seconds'] if (WORK/'others/statistics_technical_note.json').exists() else 0.
    save(WORK/'others/statistics_completion.json',{'status':'COMPLETE','elapsed_seconds':perf_counter()-started+prior_seconds,
         'successful_attempt_seconds':perf_counter()-started,'prior_attempt_log_wall_seconds':prior_seconds,
         'center_bootstrap_seconds':center_seconds,'selection_incremental_seconds':selection_seconds,
         'remaining_extraction_proxy_seconds':perf_counter()-started-center_seconds-selection_seconds,
         'reused_implementations':236,'incremental_unique_implementations':135,'new_alias_accounts_verified':1,
         'published_accounts':374,'unique_implementations':371,'new_strategy_accounts':0,
         'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
         'protocol_sha256':sha256((WORK/'protocols/statistics_protocol.json').read_bytes()).hexdigest(),'output_sha256':outputs})
    print('STATISTICS_COMPLETE',round(perf_counter()-started,1),flush=True)


if __name__=='__main__':
    main()
