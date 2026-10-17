"""Deduplicate all observed account candidates and reconcile the ten-round budget."""
from pathlib import Path
from hashlib import sha256
import json
import math

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
FIELDS=('ending_equity','total_return','full_max_drawdown','closed_trades','open_trades',
        'frequency_per_60','frequency_pass','annual_return_pass_count',
        'annual_drawdown_pass_count','annual_both_pass_count','all_targets_pass')

def main():
    dest=EX/'others/budget_summary.json'
    if dest.exists():raise RuntimeError('Preserve completed research summary')
    assert (EX/'others/account_audit.json').exists()
    records={};sources={};checks=0
    for path in sorted(EX.parent.glob('EX*/others/comparison.json')):
        value=json.loads(path.read_text(encoding='utf-8'))
        for row in value.get('summaries',[]):
            if not all(k in row for k in ('candidate','annual_both_pass_count')):continue
            sources[path.relative_to(ROOT).as_posix()]=sha256(path.read_bytes()).hexdigest()
            key=row['candidate']
            years=[a for a in value['annual'] if a['variant']==row['variant']]
            assert len(years)==7 and {a['year'] for a in years}==set(range(2020,2027))
            if key in records:
                old=records[key]
                for name in FIELDS:
                    a,b=old[name],row[name]
                    assert (a==b if isinstance(a,bool) else math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-10)),(key,name,a,b)
                    checks+=1
                oldyears={a['year']:a for a in old['annual']}
                for a in years:
                    b=oldyears[a['year']]
                    for name in ('return','max_drawdown','return_pass','drawdown_pass','both_pass'):
                        assert (a[name]==b[name] if isinstance(a[name],bool) else math.isclose(a[name],b[name],rel_tol=1e-12,abs_tol=1e-10)),(key,a['year'],name)
                        checks+=1
            else:
                records[key]={'candidate':key,'variant':row['variant'],**{k:row[k] for k in FIELDS},
                    'source_comparison':path.relative_to(ROOT).as_posix(),'source_evidence':row.get('source_evidence'),
                    'annual':sorted(years,key=lambda a:a['year'])}
    rounds=[];new_ids=set()
    for number in range(20,30):
        folder=EX.parent/f'EX{number:03}_20261018'
        lockpath=folder/'protocols/comparison_lock.json';lock=json.loads(lockpath.read_text(encoding='utf-8'))
        runpath=folder/'others/account_results.json';runs=json.loads(runpath.read_text(encoding='utf-8'))['records']
        assert all(r['status']=='SUCCEEDED' for r in runs)
        ids={r['candidate'] for r in runs}
        assert not ids&new_ids and ids<=records.keys()
        assert len(ids)==len(lock['new_variants'])==len(runs)
        new_ids|=ids
        rounds.append({'round':number-19,'experiment':folder.name,'new_accounts':len(ids),
                       'candidate_ids':sorted(ids),'all_targets_pass_count':sum(records[k]['all_targets_pass'] for k in ids)})
        for p in (lockpath,runpath):sources[p.relative_to(ROOT).as_posix()]=sha256(p.read_bytes()).hexdigest()
    assert len(records)==66 and len(new_ids)==52 and len(records.keys()-new_ids)==14
    passing=[r['candidate'] for r in records.values() if r['all_targets_pass']]
    best=max(r['annual_both_pass_count'] for r in records.values())
    frontier=[r for r in records.values() if r['annual_both_pass_count']==best]
    for row in frontier:
        row['failed_return_years']=[a['year'] for a in row['annual'] if not a['return_pass']]
        row['failed_drawdown_years']=[a['year'] for a in row['annual'] if not a['drawdown_pass']]
    result={'status':'PASS','new_accounts':0,'upstream_calls':0,'reuse_consistency_checks':checks,
            'total_authorized_rounds':10,'completed_account_rounds':10,'additional_rounds_authorized':0,
            'autonomous_new_accounts':52,'prior_accounts':14,'unique_candidate_ids':66,
            'all_targets_pass_count':len(passing),'all_targets_pass_candidates':passing,
            'max_annual_both_pass_count':best,'max_annual_both_candidates':frontier,
            'rounds':rounds,'candidate_summaries':list(records.values()),'source_sha256':sources,
            'limitations':['Candidate identity counts include economically identical paths and overlapping data; not independent experiments or supported strategies.',
                          'Annual both-pass count is a reporting diagnostic, never a replacement objective, ranking rule or acceptance threshold.',
                          'All original seven-year return and drawdown requirements plus frequency remain necessary; no annual winner stitching.',
                          'This summary reconciles existing audited comparisons and actual run records; it does not execute accounts or assert a new holdout.',
                          'Final public registration and FULL delivery validation are completed separately after this calculation.']}
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ('status','reuse_consistency_checks','autonomous_new_accounts','unique_candidate_ids','all_targets_pass_count','max_annual_both_pass_count')}))
    print([(r['candidate'],r['failed_return_years'],r['failed_drawdown_years']) for r in frontier])

if __name__=='__main__':main()
