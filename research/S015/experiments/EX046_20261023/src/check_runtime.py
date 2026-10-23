"""Extend fixed-mode equivalence to all six family/modes and holds 1..9."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
import ast
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent


def read(p):return json.loads(p.read_bytes())
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def main():
    previous=BASE/'EX042_20261023';successor=BASE/'EX045_20261023';key='src/strategy_runtime/strategies/price_information.py'
    oldref=EvidenceRef.from_dict(read(previous/'others/account_refs.json')[key])
    newref=EvidenceRef.from_dict(read(successor/'others/protocol_refs.json')[key])
    oldsource=previous/key;newsource=successor/key
    assert oldsource.read_bytes()==oldref.resolve(ROOT).read_bytes()
    assert newsource.read_bytes()==newref.resolve(ROOT).read_bytes()
    old=module(oldsource,'original_fixed_42');new=module(newsource,'authenticated_exit_45')
    def feature_ast(p):
        return ast.dump(next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='causal_features'),include_attributes=False)
    assert feature_ast(oldsource)==feature_ast(newsource)
    oldcheckref=EvidenceRef.from_dict(read(successor/'others/protocol_refs.json')['others/runtime_checks.json'])
    oldcheck=read(oldcheckref.resolve(ROOT));assert oldcheck['status']=='PASS'
    assert oldcheck['source_sha256']==sha256(newsource.read_bytes()).hexdigest()
    # Reuse authenticated features; original raw replay equality already passed
    # in EX045 and the unchanged feature AST and source identities are checked.
    feature_ref=EvidenceRef.from_dict(read(BASE/'EX036_20261023/others/published_refs.json')['materials']['others/model_features.csv'])
    features=pd.read_csv(feature_ref.resolve(ROOT));x=features.set_index(pd.to_datetime(features.date))[list(old.COLUMNS)].copy()
    x['feature_ready']=True
    seed=pd.DataFrame([{**{c:0. for c in old.COLUMNS},'feature_ready':False}],index=pd.DatetimeIndex(['2024-12-31']))
    x=pd.concat([seed,x]);x.index.name='date';assert len(x)==435
    schedules={};schedule_refs={}
    for family in ('A','B'):
        r=EvidenceRef.from_dict(read(previous/'others/account_refs.json')[f'others/models_{family}.json'])
        schedules[family]=read(r.resolve(ROOT));schedule_refs[family]=r.to_dict()
    rows=[]
    for family in ('A','B'):
        for mode in ('path','risk','and'):
            for hold in range(1,10):
                params={'family':family,'mode':mode,'hold':hold,'exposure':1.,'schedule':schedules[family]}
                a=old.intentions(x,params);b=new.intentions(x,{**params,'exit_rule':'fixed'})
                pd.testing.assert_frame_equal(a,b,check_exact=True)
                rows.append({'family':family,'mode':mode,'hold':hold,'rows':435,'status':'PASS'})
    # Domain check is read-only and creates neither experiments nor accounts.
    runner=module(HERE/'src/run.py','fixed_domain_46')
    reused=runner.verify_domain();configs=runner.configurations()
    assert len(reused)==45 and len(configs)==67
    result={'status':'PASS','fixed_equivalent_configs':54,'canonical_rows_per_config':435,'development_rows_per_config':434,
      'canonical_output_rows_checked':54*435,'development_output_rows_checked':54*434,
      'permission_runtime_sha256':sha256(newsource.read_bytes()).hexdigest(),'original_fixed_runtime_sha256':sha256(oldsource.read_bytes()).hexdigest(),
      'original_source':oldref.to_dict(),'permission_source':newref.to_dict(),'original_feature_ref':feature_ref.to_dict(),
      'prior_raw_replay_check':oldcheckref.to_dict(),'unchanged_feature_function_ast':True,'schedule_refs':schedule_refs,
      'configurations':rows,'new_configurations':67,'reused_configurations':45,'complete_integer_domain':108,'long_extensions':4,'combined_domain':112,
      'accounts_created':0,'limits':'Exact same-input intent/output equivalence; this check reuses authenticated feature table rather than rerunning DFLS. EX045 source and feature AST match its prior actual raw-data replay and canonical two-window checks. No performance or fees assertion.'}
    (HERE/'others/runtime_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','fixed_equivalent_configs':54,'canonical_output_rows_checked':54*435,'new_configs':67,'combined_domain':112}),flush=True)


if __name__=='__main__':main()
