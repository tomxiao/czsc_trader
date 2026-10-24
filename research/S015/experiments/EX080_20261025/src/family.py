"""Explicit comparable family and public search-bias diagnostics."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from dataclasses import asdict
import json,sys
import numpy as np
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
from strategy_evaluator import research_models as m
from strategy_evaluator import annualized_sharpe,effective_trial_count,deflated_sharpe_ratio,cscv_pbo,ReturnMatrixEvidence
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3];OUT=H/'others';CACHE=ROOT/'.tmp/s015-ex080'
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def short(x):return x.candidate_id.removeprefix('S015-')
def authenticated_proof(ex,name):
 receipt=read(B/ex/'others/published_report.json');ref=next(v for k,v in receipt['materials'].items() if k.replace('\\','/')=='others/'+name);reference=EvidenceRef.from_dict(ref);assert reference.resolve(ROOT).read_bytes()==(B/ex/'others'/name).read_bytes();return ref
def prepare():
 assert not (OUT/'family_protocol_refs.json').exists();sources=read(OUT/'retained_sources.json');accounts=[m.AssessmentEvidence.from_dict(x) for x in read(CACHE/'retained_accounts.json')];pairs=[(a,s) for a,s in zip(accounts,sources,strict=True) if s['source_role']=='family'];assert len(pairs)==627
 byid={short(a.candidate):a for a,s in pairs};assert len(byid)==627;excluded=read(B/'EX066_20261024/others/family_summary.json')['excluded_previous_identities'];assert len(excluded)==11
 new=[('C7300','C7200'),('C7303','C7202'),('C7306','C7203'),('C7309','C7205'),('C7312','C7207'),('C7315','C7208')]
 for old,newid in new:
  assert byid[old].candidate.content_sha256==byid[newid].candidate.content_sha256;excluded.append({'excluded':old,'retained':newid,'reason':'same content identity, stage2 technical repeat'})
 proofs=[authenticated_proof('EX074_20261024','equivalence.json'),authenticated_proof('EX076_20261024','equivalence.json')]
 for ex in ('EX074_20261024','EX076_20261024'):
  proof=read(B/ex/'others/equivalence.json');assert proof['status']=='PASS' and proof['economic_ledgers_exact'] and len(proof['checks'])==20
 for old,newid in [('C7001','C7600'),('C7400','C7600'),('C7005','C7604'),('C7401','C7604')]:excluded.append({'excluded':old,'retained':newid,'reason':'Published two-window five-ledger refactor equivalence chain EX074 then zero-hurdle EX076; keep current center as representative.'})
 for alias in excluded:
  a,b=byid[alias['excluded']],byid[alias['retained']];assert a.account==b.account and a.benchmark_equity==b.benchmark_equity
 ids=[short(a.candidate) for a,s in pairs if short(a.candidate) not in {x['excluded'] for x in excluded}];assert len(ids)==606
 protocol={'source_account_records':627,'retained_columns':606,'old_family_retained_columns':372,'new_stage2_source_records':80,'new_stage3_source_records':164,'excluded':excluded,'proofs':proofs,'retained_ids':ids,'selection_rule':'Highest full-window sample annualized Sharpe is selected only for DSR, never automatically recommended.','methods':{'pbo_blocks':10,'raw_count':606,'effective':'Public correlation-eigenvalue method on full matrix; if undefined, retain explicit unavailable status. Separately disclose a nonconstant-column correlation estimate, keeping zero columns in raw counts, Sharpes and PBO.','zero_variance':'Zero-trading strategy is a valid negative search and stays in family; no jitter or silent filtering.'},'limitations':['Raw columns are retained configuration evidence, not independent hypotheses.','Original176 dependence retained; verified11 EX065 aliases plus10 new exact-identity/refactor duplicates excluded.','12 likely inherited controls and6 same-zero-hurdle old-scale controls remain because no extra full source+ledger alias audit was performed; raw count may overstate distinct choices.','Earlier signals, models, discretionary adaptation and research before comparable sources remain outside this matrix; this is not complete total trial history.','Stage4 points, technical repeats, EX078 replay132, fees and415 overlapping windows do not become new selection columns.','All development data repeatedly seen; PBO and DSR are not future success probabilities.']}
 save(H/'protocols/family.json',protocol);c=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13));refs={}
 for p in (Path(__file__),H/'protocols/family.json'):
  ref=publish_evidence(c,MaterialEvidenceWrite(ExperimentRef('S015',H.name),p.stem,p.read_bytes(),'text/x-python' if p.suffix=='.py' else 'application/json',p.suffix[1:]));refs[p.relative_to(ROOT).as_posix()]=ref.to_dict()
 save(OUT/'family_protocol_refs.json',refs);print('FAMILY_PROTOCOL_FROZEN',606,flush=True)
def build():
 for p,r in read(OUT/'family_protocol_refs.json').items():assert EvidenceRef.from_dict(r).resolve(ROOT).read_bytes()==(ROOT/p).read_bytes()
 protocol=read(H/'protocols/family.json');allitems=[m.AssessmentEvidence.from_dict(x) for x in read(CACHE/'retained_accounts.json')];byid={short(x.candidate):x for x in allitems if x.scenario_id=='standard'};retained=[byid[cid] for cid in protocol['retained_ids']];sessions=tuple(x.session for x in retained[0].account);assert len({(x.context_sha256,x.metric_version,x.scenario_context) for x in retained})==1;assert all(tuple(x.session for x in a.account)==sessions for a in retained)
 matrix=np.array([np.array([x.equity for x in a.account])/np.r_[a.initial_cash,[x.equity for x in a.account[:-1]]]-1 for a in retained]).T;sharpes=np.array([annualized_sharpe(a) for a in matrix.T]);assert np.isfinite(sharpes).all();selected=int(np.argmax(sharpes));constant=np.std(matrix,axis=0,ddof=1)<=0;assert np.all(matrix[:,constant]==0)
 family=m.FamilyReturnEvidence(tuple(a.candidate for a in retained),sessions,tuple(tuple(float(v) for v in r) for r in matrix),retained[selected].candidate,606,tuple(protocol['limitations']));save(CACHE/'family_returns.json',family.to_dict())
 pbo=cscv_pbo(ReturnMatrixEvidence(sessions,tuple(a.candidate.candidate_id for a in retained),family.returns,''),10);raw=deflated_sharpe_ratio(matrix[:,selected],sharpes,606)
 try:eff={'status':'AVAILABLE','value':effective_trial_count(matrix)}
 except ValueError as e:eff={'status':'UNAVAILABLE','value':None,'reason':str(e)}
 subcount=effective_trial_count(matrix[:,~constant]);subdsr=deflated_sharpe_ratio(matrix[:,selected],sharpes,subcount)
 result={'status':'FAMILY_DIAGNOSTICS_COMPLETE_WITH_EXPLICIT_LIMIT','raw_trial_count':606,'distinct_exact_return_paths':len({x.tobytes() for x in matrix.T}),'selected_for_dsr':retained[selected].candidate.to_dict(),'zero_variance_columns':[short(a.candidate) for i,a in enumerate(retained) if constant[i]],'pbo':asdict(pbo),'dsr_raw_public':asdict(raw),'effective_trial_count_full':eff,'supplement_nonconstant_correlation':{'columns':int((~constant).sum()),'effective_trial_count':subcount,'dsr_using_all606_trial_sharpes':asdict(subdsr),'formal_assessment_override':False,'meaning':'Explicit separate diagnostic; constant cash column has undefined correlation. Full family and raw trial count unchanged.'},'excluded':protocol['excluded'],'limitations':protocol['limitations']}
 save(OUT/'family_summary.json',result);print('FAMILY_DIAGNOSTICS',pbo.pbo,raw.probability,subcount,subdsr.probability,flush=True)
if __name__=='__main__':{'prepare':prepare,'build':build}[sys.argv[1]]()
