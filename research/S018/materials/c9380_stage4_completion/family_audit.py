"""Read existing research evidence; report selection-bias coverage without replay."""
from pathlib import Path
import os
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
OUT=Path(__file__).resolve().parent
SCRATCH=ROOT/'.tmp/s018-family-statistics'
SCRATCH.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=os.environ['TMP']=str(SCRATCH)
sys.pycache_prefix=str(SCRATCH/'pycache')
for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'

import argparse
from collections import Counter,defaultdict
from dataclasses import asdict
from hashlib import sha256
import gzip
import json
from time import perf_counter
import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity,build_equity_assessment
from strategy_evaluator import annualized_sharpe,cscv_pbo,effective_trial_count,deflated_sharpe_ratio
from strategy_evaluator.audit_models import ReturnMatrixEvidence
from strategy_evaluator import FamilyReturnEvidence, AssessmentCandidate
from strategy_runtime import canonical_sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')


def ref_path(ref):
    return d.EvidenceRef.from_dict(ref).resolve(ROOT)


def context_proxy(header):
    request=header['request']
    # Same scalar constituents as public assessment context, except the explicit
    # account calendar is checked after extraction. This is a grouping key only.
    version=f"equity-assessment-v4:{request['drawdown_basis']}:{request['concentration_basis']}"
    value={'instrument':request['instrument'],'specification':request['specification'],
        'data':header['data'],'window':request['window'],'history_start':request['history_start'],
        'initial_cash':request['initial_cash'],'benchmark':request['benchmark_sha256'],
        'frequency_window_days':request['frequency_window_days'],'metric_version':version,
        'scenario':{'fee_rate':request['fee_rate'],'measurement_tier':request['measurement_tier'],
            'scenario_id':request['scenario_id'],'window_id':request['window_id'],'benchmark':request['benchmark']}}
    return canonical_sha256(value),value


def inventory():
    refs, reports, unavailable={},[],[]
    for work in sorted((ROOT/'research/S018/experiments').glob('EX*')):
        number=int(work.name[2:5])
        if not 2<=number<=63:
            continue
        locator=work/'report_ref.json'
        if not locator.exists():
            unavailable.append({'experiment':work.name,'reason':'NO_PUBLISHED_REPORT'})
            continue
        report_ref=read(locator)['report']
        raw=ref_path(report_ref).read_bytes()
        assert sha256(raw).hexdigest()==report_ref['sha256']
        report=json.loads(raw)
        reports.append({'experiment':work.name,'reference':report_ref,'outcome':report['outcome']})
        for ref in report['evidence']:
            if ref['schema']!='equity_research':
                continue
            source_number=int(ref['experiment']['experiment_id'][2:5])
            if not 2<=source_number<=63:
                continue
            key=(ref['experiment']['experiment_id'],ref['sha256'])
            entry=refs.setdefault(key,{'reference':ref,'listed_by':[]})
            entry['listed_by'].append(work.name)
    members=[]
    cohorts={}
    for index,entry in enumerate(refs.values()):
        ref=entry['reference']
        raw=ref_path(ref).read_bytes()
        assert sha256(raw).hexdigest()==ref['sha256']
        header=json.loads(raw)
        assert header['schema']=='equity-research/v4'
        request=header['request']
        group,definition=context_proxy(header)
        cohorts.setdefault(group,{'context_constituents':definition,'references':0,'definitions':set(),'experiments':Counter()})
        cohorts[group]['references']+=1
        cohorts[group]['definitions'].add(request['content_sha256'])
        cohorts[group]['experiments'][request['experiment']['experiment_id']]+=1
        members.append({**entry,'candidate_id':request['candidate_id'],'content_sha256':request['content_sha256'],
            'experiment':request['experiment']['experiment_id'],'cohort':group,
            'candidate_account_ref':header['candidate_ref'],'input_ref':header['input_ref'],
            'scenario_id':request['scenario_id'],'fee_rate':request['fee_rate'],
            'drawdown_basis':request['drawdown_basis'],'concentration_basis':request['concentration_basis']})
    for value in cohorts.values():
        value['unique_definitions']=len(value.pop('definitions'))
        value['experiments']=dict(value['experiments'])
    target=[x for x in members if x['candidate_id']=='C9380']
    assert len(target)==1
    return {'scope':'Published EX002..EX063 account evidence, no EX064 sensitivity points',
        'published_reports':reports,'missing_reports':unavailable,'members':members,'cohorts':cohorts,
        'total_references':len(members),'unique_definitions':len({x['content_sha256'] for x in members}),
        'target':target[0]}


def previous_cache():
    """Reuse completed projections from the explicitly interrupted export only."""
    cached={}
    path=SCRATCH/'interrupted_family_assessment_evidence.jsonl.gz'
    if not path.exists():
        return cached
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        try:
            for line in stream:
                value=json.loads(line)
                equity=np.array([r['equity'] for r in value['account']],dtype=float)
                returns=equity/np.r_[value['initial_cash'],equity[:-1]]-1
                identity={k:value[k] for k in ('context_sha256','metric_version','scenario_context','window_id','scenario_id')}
                cached[value['result_sha256']]=(tuple(r['session'] for r in value['account']),returns,identity)
        except (EOFError,json.JSONDecodeError):
            # Only complete decoded lines are retained; the truncated last line
            # was never added. Their source result hashes bind the existing refs.
            pass
    return cached


def extract(member,cached):
    if member['reference']['sha256'] in cached:
        return cached[member['reference']['sha256']]
    path=ref_path(member['reference'])
    header_raw=path.read_bytes()
    assert sha256(header_raw).hexdigest()==member['reference']['sha256']
    # Public cold-read projector verifies owner/input/scenario associations and
    # gives the exact account calendar/initial cash; it does not rerun strategies.
    evidence,=build_equity_assessment(header_raw,lambda item:(path.parent/(item['sha256']+'.json')).read_bytes())
    equity=np.array([row.equity for row in evidence.account],dtype=float)
    returns=equity/np.r_[evidence.initial_cash,equity[:-1]]-1
    assert np.isfinite(returns).all() and (returns>-1).all()
    identity={'context_sha256':evidence.context_sha256,'metric_version':evidence.metric_version,
        'scenario_context':evidence.scenario_context.to_dict(),'window_id':evidence.window_id,'scenario_id':evidence.scenario_id}
    return tuple(row.session for row in evidence.account),returns,identity


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inventory-only',action='store_true')
    parser.add_argument('--prepare-evidence-only',action='store_true')
    parser.add_argument('--reuse-inventory',action='store_true')
    args=parser.parse_args()
    begun=perf_counter()
    inv=read(OUT/'family_inventory.json') if args.reuse_inventory else inventory()
    if not args.reuse_inventory:
        save('family_inventory.json',inv)
    target_group=inv['target']['cohort']
    selected=[m for m in inv['members'] if m['cohort']==target_group]
    print('INVENTORY',inv['total_references'],inv['unique_definitions'],'cohorts',len(inv['cohorts']),
        'target',len(selected),len({x['content_sha256'] for x in selected}),flush=True)
    if args.inventory_only:
        return
    unique={}
    for member in selected:
        unique.setdefault(member['content_sha256'],[]).append(member)
    columns=[]
    mapping=[]
    sessions=None
    context=None
    cached=previous_cache()
    print('REUSE_COMPLETED_PROJECTIONS',len(cached),flush=True)
    for index,(definition,aliases) in enumerate(unique.items()):
        # Definition-equivalent reruns are preserved as aliases; verify all
        # daily series agree before reusing one column.
        primary=next((m for m in aliases if m['candidate_id']=='C9380'),aliases[0])
        days,returns,identity=extract(primary,cached)
        if sessions is None:
            sessions,context=days,identity
        assert days==sessions and identity==context,('Unexpected context/calendar difference',primary['candidate_id'])
        for alias in aliases:
            if alias is primary:
                continue
            alias_days,alias_returns,alias_identity=extract(alias,cached)
            assert alias_days==days and alias_identity==identity and np.array_equal(alias_returns,returns),('Definition rerun differs',alias['candidate_id'])
        columns.append(returns)
        mapping.append({'column':index,'candidate_id':primary['candidate_id'],'content_sha256':definition,
            'primary_reference':primary['reference'],'aliases':[{'candidate_id':m['candidate_id'],'experiment':m['experiment'],
                'reference':m['reference']} for m in aliases]})
        if index%50==0:
            print('READ',index+1,len(unique),'seconds',round(perf_counter()-begun,2),flush=True)
    matrix=np.column_stack(columns)
    constant=np.flatnonzero(np.std(matrix,axis=0,ddof=1)<=0)
    selected_index=next(i for i,m in enumerate(mapping) if m['candidate_id']=='C9380')
    ids=tuple(m['candidate_id'] for m in mapping)
    matrix_sha=sha256(matrix.astype('<f8',copy=False).tobytes()).hexdigest()
    # Explicitly fixed before any result: 10 contiguous blocks, all 252 halves;
    # public PBO is a Sharpe proxy and is not the Calmar research objective.
    data=ReturnMatrixEvidence(sessions,ids,tuple(tuple(float(x) for x in row) for row in matrix),matrix_sha)
    diagnostics={}
    if not args.prepare_evidence_only:
      try:
        pbo=cscv_pbo(data,10)
        diagnostics['PBO_SHARPE_PROXY']={'status':'AVAILABLE','value':pbo.pbo,
            'block_count':10,'split_count':len(pbo.splits),'validation_candidate_counts':sorted(set(x.validation_candidate_count for x in pbo.splits)),
            'selected_c9380_splits':dict(pbo.selection_frequency).get('C9380',0)}
        save('family_pbo_splits.json',pbo.to_dict())
      except (ValueError,FloatingPointError,ZeroDivisionError) as exc:
        diagnostics['PBO_SHARPE_PROXY']={'status':'INSUFFICIENT_DATA','reason':str(exc)}
      sharpes=np.array([annualized_sharpe(matrix[:,i]) for i in range(matrix.shape[1])])
      assert np.isfinite(sharpes).all(), 'No implicit dropping of nonfinite trial Sharpes'
      try:
        dsr=deflated_sharpe_ratio(matrix[:,selected_index],sharpes,float(len(selected)))
        diagnostics['DSR_RAW_COHORT']={'status':'AVAILABLE',**asdict(dsr)}
      except (ValueError,FloatingPointError,ZeroDivisionError) as exc:
        diagnostics['DSR_RAW_COHORT']={'status':'INSUFFICIENT_DATA','reason':str(exc)}
      try:
        effective=effective_trial_count(matrix)
        diagnostics['EFFECTIVE_TRIAL_COUNT']={'status':'AVAILABLE','value':effective}
        dsr=deflated_sharpe_ratio(matrix[:,selected_index],sharpes,effective)
        diagnostics['DSR_EFFECTIVE_COHORT']={'status':'AVAILABLE',**asdict(dsr)}
      except (ValueError,FloatingPointError,ZeroDivisionError) as exc:
        diagnostics['EFFECTIVE_TRIAL_COUNT']={'status':'INSUFFICIENT_DATA','reason':str(exc)}
        diagnostics['DSR_EFFECTIVE_COHORT']={'status':'INSUFFICIENT_DATA','reason':str(exc)}
    series_groups=defaultdict(list)
    for i,m in enumerate(mapping):
        series_groups[sha256(matrix[:,i].astype('<f8',copy=False).tobytes()).hexdigest()].append(m['candidate_id'])
    limitations=[
        'Only the exact comparable cohort containing C9380 is analyzed; earlier differing input contexts remain part of the historical selection process.',
        'The public CSCV PBO uses Sharpe optimization, not the declared net-Calmar objective. DSR also tests Sharpe, not Calmar superiority.',
        'CSCV pseudo-out-of-sample halves reuse previously researched data and do not restore prospective independence.',
        'Raw count is all published evaluations in this cohort including repeated definitions and controls, not a claim of independent trials.',
        'Definition-equivalent reruns are combined only after exact daily-return and context checks; all aliases remain in the inventory.',
        'Identical daily return sequences are descriptive groups, not proof of identical trades or independent successful strategies.',
        'Constant columns remain in the complete matrix; no constant or unsuccessful strategy is silently removed.',
        'Unpublished exploratory ideas and adaptive research choices cannot be exhaustively counted from account publications.',
        'No diagnostic is an additional acceptance gate or a probability of future profitability.'
    ]
    summary={'status':'PREPARED_FOR_FORMAL_PROXY_DIAGNOSTICS' if args.prepare_evidence_only else 'COMPLETED_DESCRIPTIVE_COHORT_DIAGNOSTICS','total_published_account_references':inv['total_references'],
        'total_unique_definitions':inv['unique_definitions'],'target_cohort_references':len(selected),
        'target_cohort_unique_definitions':len(unique),'excluded_other_context_references':len(inv['members'])-len(selected),
        'matrix_shape':list(matrix.shape),'matrix_binary_f64_le_sha256':matrix_sha,'sessions':list(sessions),
        'context':context,'constant_columns':[mapping[i]['candidate_id'] for i in constant],
        'identical_daily_return_group_count':len(series_groups),'selected_candidate':'C9380','diagnostics':diagnostics,
        'limitations':limitations,'elapsed_seconds':perf_counter()-begun,'new_strategy_accounts':0,
        'full_research_family_selection_bias_certified':False,
        'reused_completed_projections':len(cached),
        'formal_panel_integration_limit':'CandidatePerformanceAssessmentRequest baseline evidence permits only centers; no fabricated context or added center is used to bypass this.'}
    save('family_matrix_manifest.json',{'matrix_sha256':matrix_sha,'context':context,'columns':mapping,
        'daily_return_groups':dict(series_groups),'sessions':list(sessions)})
    candidates=tuple(AssessmentCandidate('S018-'+m['candidate_id'],m['content_sha256']) for m in mapping)
    family=FamilyReturnEvidence(candidates,sessions,tuple(tuple(float(x) for x in row) for row in matrix),
        candidates[selected_index],len(selected),tuple(limitations))
    save('family_returns.json',family.to_dict())
    save('family_statistics.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sessions','limitations','context')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
