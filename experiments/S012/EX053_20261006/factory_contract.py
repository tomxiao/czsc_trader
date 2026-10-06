"""Exact root-frozen post52 risk and optional trailing controls."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input, experiment_source_sha256
from strategy_runtime import implementation_sha256

MODEL_SHA='a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7'
FEATURE_SHA='8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
PROVENANCE_SHA='4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858'
SOURCES=('strategies/s012.py','resources/features.csv')
PREDECESSORS=('EX048_20261006','EX050_20261006','EX052_20261006')
def require(ok,message):
    if not ok:raise ValueError(message)
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def checked(root,ref):
    require(set(ref)=={'path','sha256'} and not Path(ref['path']).is_absolute(),'repository relative evidence path/SHA required')
    path=(root/ref['path']).resolve();path.relative_to(root.resolve())
    require(path.relative_to(root.resolve()).as_posix().startswith(('experiments/S012/','.tmp/s012-stage3-native-20261006/')),'outside S012')
    require(sha256(path.read_bytes()).hexdigest()==ref['sha256'],'evidence SHA mismatch')
    return path
def planned_batches(count):
    require(type(count) is int and count>0,'nonempty FULL control count required')
    return ((0,1),)+tuple((i,min(i+4,count)) for i in range(1,count,4))
def plan(options):
    import re
    require(options['schema_version']==1 and options['root_frozen_controls'] is True
            and options['approval_reason'].strip(),'explicit root-frozen protocol required')
    require(re.fullmatch(r'EX\d{3}_\d{8}',options['experiment_id']) is not None
            and int(options['experiment_id'][2:5])>52,'root must specify successor experiment id')
    require(type(options['candidate_start']) is int and options['candidate_start']>=0
            and type(options['seed']) is int,'root must specify candidate start/seed')
    require(set(options['predecessor_receipts'])==set(PREDECESSORS),'exact48/50/52 signed predecessors required')
    require(type(options['include_trailing']) is bool,'explicit optional trailing choice required')
    row=options['center50']['row'];p=row['parameters']
    require(row['candidate_id']==options['center50']['candidate_id']=='C4603'
            and row['control_label']=='PREMIUM020' and row['record']['status']=='SUCCEEDED','exact50 C4603 required')
    require(p=={'confirm_o01':False,'cooldown':0,'risk_gate':'none','risk_exit':False,'trailing_stop':0.,
                'allocation':1.,'exit_policy':'fixed','min_hold':1,'risk_unknown_policy':'block',
                'hold_days':6,'entry_premium':.02,'opportunity':'momentum','momentum_lookback':10},'exact50 center parameters required')
    recipes=[('VOL_ENTRY_KNOWN_ONLY','center50',{'risk_gate':'vol','risk_unknown_policy':'known_only'}),
             ('KURT_ENTRY_KNOWN_ONLY','center50',{'risk_gate':'kurt','risk_unknown_policy':'known_only'})]
    if options['include_trailing']:
        original=options['center52']['row']
        require(original['candidate_id']==options['center52']['candidate_id']=='C4704'
                and original['control_label']=='TRAIL050_PREMIUM020'
                and original['record']['status']=='SUCCEEDED','exact52 C4704 required')
        require(original['parameters']==dict(p,trailing_stop=.05),'exact52 joint parameters required')
        recipes += [('TRAIL030','center52',{'trailing_stop':.03}),('TRAIL100','center52',{'trailing_stop':.10})]
    else:
        require('center52' not in options,'inactive trailing provenance must be omitted')
    require(len(options['controls'])==len(recipes),'only two risk controls plus explicitly selected two trailing controls')
    groups=[]
    for i,(label,origin,delta) in enumerate(recipes):
        source=options[origin]['row'];parameters=dict(source['parameters'],**delta);cid=f"C{options['candidate_start']+i:04d}"
        require(options['controls'][i]=={'candidate_id':cid,'label':label,'origin':origin,'delta':delta,'parameters':parameters},
                'frozen delta or original parameters changed')
        groups.append({'candidate_id':cid,'kind':'PROSPECTIVE_PAIRED_MECHANISM_CONTROL','label':label,'delta':delta,
            'parameters':parameters,'parameter_sha256':digest(parameters),'source_selection_ids':[
            {'experiment_id':'EX050_20261006' if origin=='center50' else 'EX052_20261006',
             'reference_id':source['candidate_id'],'original_row_sha256':digest(source),
             'original_parameter_sha256':digest(source['parameters'])}]})
    require(len({g['parameter_sha256'] for g in groups})==len(groups),'unique controls required')
    return groups

def authenticate(root,options):
    root=Path(root).resolve()
    for eid in PREDECESSORS:
        require((root/'experiments/S012'/eid/'artifacts/rex/execution_receipt.json').is_file(),
                eid+' complete signed REX required; no partial52 credit or construction')
    groups=plan(options);receipts={}
    for eid in PREDECESSORS:
        exp=root/'experiments/S012'/eid;workspace=exp/'artifacts/rex'
        load_experiment_input(workspace,expected_receipt_sha256=options['predecessor_receipts'][eid])
        receipt=read(workspace/'execution_receipt.json');binding=read(exp/'experiment_binding.json')
        require(experiment_source_sha256(exp,tuple(binding['source_files']))==binding['source_sha256']==receipt['source_sha256'],
                'signed predecessor source closure differs')
        receipts[eid]=receipt
        for name,expected in [('strategy_runtime/strategies/s012.py',MODEL_SHA),
                ('strategy_runtime/resources/features.csv',FEATURE_SHA),('feature_provenance.json',PROVENANCE_SHA)]:
            require(sha256((exp/name).read_bytes()).hexdigest()==expected,'same-source model/features/provenance required')
    for eid,count in [('EX050_20261006',8),('EX052_20261006',5)]:
        trials=root/'experiments/S012'/eid/'artifacts/rex/trials.json';rows=read(trials)
        require(len(rows)==count and all(r['record']['status']=='SUCCEEDED' for r in rows),
                'complete genuine successful predecessor accounts required')
    for origin,eid in [('center50','EX050_20261006')]+([('center52','EX052_20261006')] if options['include_trailing'] else []):
        exp=root/'experiments/S012'/eid;choice=options[origin]
        trials=checked(root,choice['trials'])
        require(trials==exp/'artifacts/rex/trials.json','exact signed trials location required')
        require(receipts[eid]['artifact_sha256']['trials.json']==choice['trials']['sha256'],'actual trials not signed by complete receipt')
        actual=next(r for r in read(trials) if r['candidate_id']==choice['candidate_id'])
        require(digest(actual)==digest(choice['row']),'selected original row changed')
        frozen=next(g for g in read(exp/'witness_plan.json') if g['label']==actual['control_label'])
        require(digest(frozen['parameters'])==digest(actual['parameters'])==frozen['parameter_sha256'],
                'original frozen witness parameters differ')
        reference=actual['record']['result_artifact'];workspace=exp/'artifacts/rex'
        result=(workspace/reference['path']).resolve();result.relative_to(workspace.resolve())
        require(sha256(result.read_bytes()).hexdigest()==reference['sha256'],
                'actual original FULL result SHA differs')
        require(actual['implementation_sha256']==implementation_sha256(SOURCES,source_root=exp/'strategy_runtime')
                and actual['feature_sha256']==FEATURE_SHA,'original runtime/input identity differs')
    return groups
