"""Observed permission-run bound with original authenticated runtime replay."""
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent


def read(p):return json.loads(p.read_bytes())
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    original=BASE/'EX042_20261023';successor=BASE/'EX045_20261023';source_key='src/strategy_runtime/strategies/price_information.py'
    oldref=EvidenceRef.from_dict(read(original/'others/account_refs.json')[source_key])
    newref=EvidenceRef.from_dict(read(successor/'others/protocol_refs.json')[source_key]);source=successor/source_key
    assert source.read_bytes()==newref.resolve(ROOT).read_bytes()
    assert (original/source_key).read_bytes()==oldref.resolve(ROOT).read_bytes()
    runtime=module(source,'authenticated_permission_boundary')
    def feature_ast(p):return ast.dump(next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='causal_features'),include_attributes=False)
    assert feature_ast(source)==feature_ast(original/source_key)
    replayref=EvidenceRef.from_dict(read(successor/'others/protocol_refs.json')['others/runtime_checks.json'])
    assert read(replayref.resolve(ROOT))['source_sha256']==sha256(source.read_bytes()).hexdigest()
    feature_ref=EvidenceRef.from_dict(read(BASE/'EX036_20261023/others/published_refs.json')['materials']['others/model_features.csv'])
    features=pd.read_csv(feature_ref.resolve(ROOT))
    x=features.set_index(pd.to_datetime(features.date))[list(runtime.COLUMNS)].copy();x['feature_ready']=True
    seed=pd.DataFrame([{**{c:0. for c in runtime.COLUMNS},'feature_ready':False}],index=pd.DatetimeIndex(['2024-12-31']))
    x=pd.concat([seed,x]);x.index.name='date';assert len(x)==435
    schedules={};schedule_refs={}
    for family in ('A','B'):
        ref=EvidenceRef.from_dict(read(original/'others/account_refs.json')[f'others/models_{family}.json'])
        schedules[family]=read(ref.resolve(ROOT));schedule_refs[family]=ref.to_dict()
    runner=module(HERE/'src/run.py','permission_domain_47');maxima={};records=[];comparison_rows=0;scalar_rows=0
    for family in ('A','B'):
        for mode in ('path','risk','and'):
            params={'family':family,'mode':mode,'hold':434,'exposure':1.,'exit_rule':'permission','schedule':schedules[family]}
            unlimited=runtime.intentions(x,params);permission=unlimited.permission.to_numpy(bool)
            runs=[];start=None
            for i,allowed in enumerate(permission):
                if allowed and start is None:start=i
                if start is not None and (not allowed or i==len(permission)-1):
                    end=i if allowed else i-1
                    runs.append({'start':x.index[start].date().isoformat(),'end':x.index[end].date().isoformat(),'length':end-start+1,'truncated_at_end':bool(allowed and i==len(permission)-1)})
                    start=None
            maximum=max(r['length'] for r in runs);name=f'{family}/{mode}';maxima[name]=maximum
            outputs={434:unlimited}
            for hold in (maximum,maximum+1):outputs[hold]=runtime.intentions(x,{**params,'hold':hold})
            for hold in (maximum+1,434):
                pd.testing.assert_frame_equal(outputs[maximum],outputs[hold],check_exact=True);comparison_rows+=435
            # Independently infer the age within each true run. With a cap no
            # shorter than the longest run, no forced exit occurs on a true day.
            ages=[];age=0
            for allowed in permission:
                age=age+1 if allowed else 0;ages.append(age)
            np.testing.assert_array_equal(outputs[maximum].intent_age,ages)
            np.testing.assert_array_equal(outputs[maximum].target_position,permission.astype(float));scalar_rows+=435
            records.append({'family':family,'mode':mode,'maximum_run':maximum,'holds_checked':[maximum,maximum+1,434],
              'all_columns_exactly_equal':True,'canonical_rows':435,'true_runs':runs,
              'permission_sha256':sha256(permission.astype(np.uint8).tobytes()).hexdigest()})
    assert maxima==runner.MAX_RUNS,{'observed':maxima,'predeclared':runner.MAX_RUNS}
    redundancy=[]
    for family,mode,hold in [('A','and',9),('B','path',30),('B','and',15),('B','and',30)]:
        params={'family':family,'mode':mode,'hold':hold,'exposure':1.,'exit_rule':'permission','schedule':schedules[family]}
        high=runtime.intentions(x,params);representative=runtime.intentions(x,{**params,'hold':maxima[f'{family}/{mode}']})
        pd.testing.assert_frame_equal(high,representative,check_exact=True);comparison_rows+=435
        redundancy.append({'family':family,'mode':mode,'hold':hold,'representative_hold':maxima[f'{family}/{mode}'],'canonical_rows':435,'status':'PASS'})
    prior=runner.verify_domain(require_results=False)
    result={'status':'PASS','maximum_permission_runs':maxima,'permission_runtime_sha256':sha256(source.read_bytes()).hexdigest(),
      'permission_source':newref.to_dict(),'original_source':oldref.to_dict(),'feature_ref':feature_ref.to_dict(),
      'prior_raw_replay_check':replayref.to_dict(),'unchanged_feature_AST':True,'schedule_refs':schedule_refs,
      'groups':records,'pair_comparison_rows':comparison_rows,'independent_scalar_rows':scalar_rows,
      'above_bound_redundant_identities':redundancy,'new_configurations':47,'reused_parameter_identities':112,'combined_parameter_identities':159,
      'fixed_representatives':54,'permission_representatives':sum(maxima.values()),'finite_domain_representatives':155,
      'prior_domain_source_counts':{k:sum(r['basis']==k for r in prior) for k in ('completed_result','frozen_plan_not_completed_result')},
      'proof':'Permission depends only on the fixed input/model schedule, not hold. Start in cash intent. Every false day resets active age to 0 and cannot open a cycle. On a true run of length L<=M and hold>=M, the kth true day starts with age k-1<hold, so target stays positive and end-of-day age=k. The next false day resets all caps to 0; at sample-end truncation the states still agree. Induction across runs proves identical full outputs for all hold>=M on this fixed sequence, not only the three tested caps.',
      'limitations':'This is a finite seen-development-path bound, not a future maximum duration. It requires identical inputs, trained schedule, permission rule, canonical cash start and execution contract. The 155 representatives are parameter expressions, not necessarily 155 distinct target paths. No full-account performance is computed here.',
      'accounts_created':0}
    (HERE/'others/runtime_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','maximum_permission_runs':maxima,'pair_comparison_rows':comparison_rows,'independent_scalar_rows':scalar_rows,'prior_domain_source_counts':result['prior_domain_source_counts']}),flush=True)


if __name__=='__main__':main()
