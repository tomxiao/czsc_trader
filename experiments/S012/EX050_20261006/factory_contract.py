"""Frozen completed-search choices and prospective single-factor witness plan."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input, experiment_source_sha256
from strategy_runtime import implementation_sha256

MODEL_SHA='a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7'
FEATURE_SHA='8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
PROVENANCE_SHA='4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858'
SOURCES=('strategies/s012.py','resources/features.csv')
LOSS_ROUTES={'momentum','momentum_union','m05','o01_m05','n09','all_union'}
def require(ok,message):
    if not ok:raise ValueError(message)
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def checked(root,ref):
    require(set(ref)=={'path','sha256'} and not Path(ref['path']).is_absolute(),'relative path/SHA required')
    path=(root/ref['path']).resolve();path.relative_to(root.resolve())
    require(path.relative_to(root.resolve()).as_posix().startswith(('experiments/S012/','.tmp/s012-stage3-native-20261006/')),'outside S012')
    require(sha256(path.read_bytes()).hexdigest()==ref['sha256'],'evidence byte SHA mismatch')
    return path
def planned_batches(count):
    require(type(count) is int and count>0,'nonempty FULL witness required')
    return ((0,1),)+tuple((i,min(i+8,count)) for i in range(1,count,8))
def plan(options,search):
    require(options['schema_version']==1 and options['source_search']['experiment_id']=='EX049_20261006'
            and options['witness_experiment_id']=='EX048_20261006' and options['approval_reason'].strip(),'root frozen options required')
    rows=search['proposals']
    require(len(rows)==1040 and len({r['proposal_id'] for r in rows})==1040
            and all(r['status']=='COMPLETE' for r in rows),'EX049 must have1040 COMPLETE and0FAILED')
    require(search['frontier_status']=='COMPUTED_FINAL' and search['declared_budget']==1040,'search not actually final complete checkpoint')
    ranked=sorted(rows,key=lambda r:(-r['metrics']['net_cagr'],abs(r['metrics']['max_drawdown']),-r['metrics']['frequency'],r['proposal_id']))
    feasible=[r for r in ranked if r['metrics']['frequency']>=5 and abs(r['metrics']['max_drawdown'])<abs(r['metrics']['benchmark']['max_drawdown'])]
    require(feasible,'no drawdown/frequency feasible center; no fallback')
    chosen={}
    for label,expected in [('primary',ranked[0]),('feasible',feasible[0])]:
        item=options['choices'][label]
        require(item['proposal_id']==expected['proposal_id'] and digest(item['row'])==digest(expected),'frozen chosen original row/ranking mismatch')
        require(expected['parameter_sha256']==digest(expected['parameters']),'original public parameter SHA mismatch')
        chosen[label]=expected
    base=chosen['feasible']['parameters']
    require(base['opportunity'] in LOSS_ROUTES and base['hold_days']>=3,'center cannot legally form declared loss min_hold3 control; root must explicitly revise options')
    require(base['entry_premium'] not in (.015,.02) and base['risk_gate']=='none' and not base['risk_exit']
            and base['trailing_stop']==0 and base['exit_policy']=='fixed' and base['allocation']==1.,'new controls require unchanged EX049 fixed/full center')
    groups=[]
    for label in ('primary','feasible'):
        row=chosen[label];match=next((g for g in groups if digest(g['parameters'])==digest(row['parameters'])),None)
        origin={'selection_role':label,'proposal_id':row['proposal_id'],'original_row_sha256':digest(row),'parameter_sha256':row['parameter_sha256']}
        if match:match['source_selection_ids'].append(origin)
        else:groups.append({'kind':'ORIGINAL_SEARCH_CONTROL','label':label,'parameters':row['parameters'],'delta':{},'source_selection_ids':[origin]})
    controls=[('PREMIUM015',{'entry_premium':.015}),('PREMIUM020',{'entry_premium':.02}),
        ('OPPORTUNITY_LOSS',{'exit_policy':'opportunity_loss','min_hold':3}),('MOM_ENTRY_ONLY',{'risk_gate':'mom','risk_exit':False}),
        ('MOM_ENTRY_EXIT',{'risk_gate':'mom','risk_exit':True}),('TRAIL050',{'trailing_stop':.05})]
    if len(groups)==1:controls.append(('TRAIL100',{'trailing_stop':.1}))
    for label,delta in controls:
        groups.append({'kind':'PROSPECTIVE_SINGLE_FACTOR_CONTROL','label':label,'parameters':dict(base,**delta),
            'delta':delta,'source_selection_ids':[{'selection_role':'feasible','proposal_id':chosen['feasible']['proposal_id'],
                'original_row_sha256':digest(chosen['feasible']),'parameter_sha256':chosen['feasible']['parameter_sha256']}]})
    require(len(groups)==8 and len({digest(g['parameters']) for g in groups})==8,'must form8 unique configs; no silent skip/fallback')
    for i,g in enumerate(groups):g.update(candidate_id=f'C{4600+i:04d}',parameter_sha256=digest(g['parameters']))
    return groups
def authenticate(root,options):
    root=Path(root).resolve();source=options['source_search'];eid=source['experiment_id']
    if 'root_decision' in options:
        require(options['root_decision']=='ROOT_FROZEN_PROSPECTIVE_CONTROLS','root must explicitly freeze prospective choices before construction')
    for old,expected in [('EX048_20261006',options['witness_receipt_sha256']),(eid,source['receipt_sha256'])]:
        workspace=root/'experiments/S012'/old/'artifacts/rex'
        load_experiment_input(workspace,expected_receipt_sha256=expected)
        # Hash original source closure without importing its research program
        # (EX049 legitimately uses Optuna; this fixed FULL does not).
        binding=read(root/'experiments/S012'/old/'experiment_binding.json')
        require(experiment_source_sha256(root/'experiments/S012'/old,tuple(binding['source_files']))
            ==binding['source_sha256']==read(workspace/'execution_receipt.json')['source_sha256'],'actual source closure differs from receipt')
    workspace=root/'experiments/S012'/eid/'artifacts/rex';path=checked(root,source['search']);receipt=read(workspace/'execution_receipt.json')
    require(path==workspace/'search.json' and receipt['artifact_sha256']['search.json']==source['search']['sha256'],'complete original search not receipted')
    groups=plan(options,read(path))
    for label in ('primary','feasible'):
        row=options['choices'][label]['row']
        require(row['scope']['feature_sha256']==FEATURE_SHA and row['scope']['implementation_sha256']==implementation_sha256(
            SOURCES,source_root=root/'experiments/S012/EX048_20261006/strategy_runtime'),'source/feature identity differs from approved model')
        for ref in (row['raw_summary'],*row['raw_ledgers'].values()):
            require(receipt['artifact_sha256'].get(ref['path'])==ref['sha256'],'selected raw evidence not in receipt')
            target=(workspace/ref['path']).resolve();target.relative_to(workspace.resolve())
            require(sha256(target.read_bytes()).hexdigest()==ref['sha256'],'selected raw evidence SHA mismatch')
        summary=read(workspace/row['raw_summary']['path'])
        require(summary['status']=='COMPLETE' and all(row.get(k)==v for k,v in summary.items()),'original row differs from immutable raw summary')
        require(row['raw_ledgers']['account_daily']['rows']==1534,'original actual execution days differ')
    for filename,expected in [('strategy_runtime/strategies/s012.py',MODEL_SHA),('strategy_runtime/resources/features.csv',FEATURE_SHA),('feature_provenance.json',PROVENANCE_SHA)]:
        require(sha256((root/'experiments/S012/EX048_20261006'/filename).read_bytes()).hexdigest()==expected,'EX048 original bytes changed')
    require(sha256((root/'experiments/S012'/eid/'s012_bound_model.py').read_bytes()).hexdigest()==MODEL_SHA,'search source model differs')
    return groups
