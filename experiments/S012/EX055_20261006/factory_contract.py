"""Exact signed49 boundary rows and complete53/54 predecessors."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input, experiment_source_sha256
from strategy_runtime import implementation_sha256

ORIGINAL_MODEL_SHA='a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7'
MODEL_SHA='5ce40cf173a06d069ea1672e25732c3b0db7e94b5fe7eb1ee552a6e5322cd700'
SOURCE_CHANGE={'old_model_sha256': 'a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7', 'new_model_sha256': '5ce40cf173a06d069ea1672e25732c3b0db7e94b5fe7eb1ee552a6e5322cd700', 'guard_replacements': 1, 'legal_hold_min': 1, 'legal_hold_max': 120}
FEATURE_SHA='8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
PROVENANCE_SHA='4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858'
SOURCES=('strategies/s012.py','resources/features.csv')
PREDECESSORS=('EX049_20261006','EX053_20261006','EX054_20261006')
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
    require(type(count) is int and count==4,'exact four requests required; no empty or fallback batches')
    return ((0,4),)

def plan(options):
    require(options['schema_version']==1 and options['experiment_id']=='EX055_20261006'
            and options['root_frozen_controls'] is True and options['approval_reason'].strip(),'root-frozen EX055 protocol required')
    require(type(options['candidate_start']) is int and options['candidate_start']==5000
            and type(options['seed']) is int and options['seed']==12055,'explicit C5000/seed12055 required')
    require(set(options['predecessor_receipts'])==set(PREDECESSORS),'complete49/53/54 signed predecessors required')
    require(options['source_change']==SOURCE_CHANGE,'only one original hold guard 60 to120 change allowed')
    require(len(options['controls'])==4,'exact four explicit controls required')
    common={'confirm_o01':False,'cooldown':0,'risk_gate':'none','risk_exit':False,'trailing_stop':0.,'allocation':1.,
            'exit_policy':'fixed','min_hold':1,'risk_unknown_policy':'block','hold_days':60}
    origins=[('all_union49','OPTUNA_1011',dict(common,opportunity='all_union',momentum_lookback=3,entry_premium=-.005)),
             ('momentum_union49','OPTUNA_0607',dict(common,opportunity='momentum_union',momentum_lookback=5,entry_premium=.005))]
    groups=[]
    for origin,pid,expected in origins:
        choice=options[origin];row=choice['row']
        require(choice['proposal_id']==row['proposal_id']==pid and row['status']=='COMPLETE'
                and row['parameters']==expected and row['parameter_sha256']==digest(expected),'exact complete original49 row/parameters required')
        for hold in (60,80):
            i=len(groups);cid=f'C{5000+i:04d}';label=('ALL_UNION' if origin=='all_union49' else 'MOMENTUM_UNION5')+f'_H{hold}'
            delta={} if hold==60 else {'hold_days':80};parameters=dict(expected,hold_days=hold)
            declaration={'candidate_id':cid,'label':label,'origin':origin,'delta':delta,'parameters':parameters}
            require(options['controls'][i]==declaration,'prospective four-control delta/source parameters changed')
            groups.append({'candidate_id':cid,'kind':'SOURCE_EXTENSION_H60_BEHAVIOR_CONTROL' if hold==60 else 'PROSPECTIVE_H80_BOUNDARY_CONTROL',
                'label':label,'delta':delta,'parameters':parameters,'parameter_sha256':digest(parameters),
                'source_selection_ids':[{'experiment_id':'EX049_20261006','reference_id':pid,
                    'original_row_sha256':digest(row),'original_parameter_sha256':digest(expected)}]})
    require(len(options['controls'])==4 and len({g['parameter_sha256'] for g in groups})==4,'exact4 unique controls required')
    return groups

def authenticate(root,options):
    root=Path(root).resolve()
    for eid in PREDECESSORS:
        require((root/'experiments/S012'/eid/'artifacts/rex/execution_receipt.json').is_file(),
                eid+' complete signed REX required before any EX055 construction')
    groups=plan(options);receipts={}
    for eid in PREDECESSORS:
        exp=root/'experiments/S012'/eid;workspace=exp/'artifacts/rex'
        load_experiment_input(workspace,expected_receipt_sha256=options['predecessor_receipts'][eid])
        receipt=read(workspace/'execution_receipt.json');binding=read(exp/'experiment_binding.json')
        require(experiment_source_sha256(exp,tuple(binding['source_files']))==binding['source_sha256']==receipt['source_sha256'],
                'original signed source closure differs')
        receipts[eid]=receipt
        for name,expected in [('strategy_runtime/strategies/s012.py',ORIGINAL_MODEL_SHA),('strategy_runtime/resources/features.csv',FEATURE_SHA)]:
            require(sha256((exp/name).read_bytes()).hexdigest()==expected,'original model/features byte SHA differs')
        if eid!='EX049_20261006':
            require(sha256((exp/'feature_provenance.json').read_bytes()).hexdigest()==PROVENANCE_SHA,'original provenance differs')
    audit=read(checked(root,options['audit54']))
    require(audit['status']=='PASS' and audit['errors']==[] and audit['experiments']==['EX054_20261006']
            and audit['verified_receipt_hashes']['EX054_20261006']==options['predecessor_receipts']['EX054_20261006']
            and len(audit['rows'])==1 and audit['rows'][0]['status']=='PASS','actual independent54 audit PASS required')
    workspace=root/'experiments/S012/EX049_20261006/artifacts/rex';source=options['all_union49']['search']
    search=checked(root,source)
    require(search==workspace/'search.json' and receipts['EX049_20261006']['artifact_sha256']['search.json']==source['sha256'],
            'exact signed49 search required')
    document=read(search);rows=document['proposals']
    require(len(rows)==1040 and all(r['status']=='COMPLETE' for r in rows) and document['frontier_status']=='COMPUTED_FINAL',
            'complete original49 checkpoint required')
    for origin in ('all_union49','momentum_union49'):
        choice=options[origin];require(choice['search']==source,'both rows require same signed49 original')
        actual=next(r for r in rows if r['proposal_id']==choice['proposal_id'])
        require(digest(actual)==digest(choice['row']),'actual original49 row changed')
        require(actual['scope']['feature_sha256']==FEATURE_SHA
                and actual['scope']['implementation_sha256']==implementation_sha256(SOURCES,source_root=root/'experiments/S012/EX049_20261006/strategy_runtime'),
                'actual49 original implementation/input identity differs')
        for reference in list(actual['raw_ledgers'].values())+[actual['raw_summary']]:
            target=(workspace/reference['path']).resolve();target.relative_to(workspace.resolve())
            require(sha256(target.read_bytes()).hexdigest()==reference['sha256']
                    and receipts['EX049_20261006']['artifact_sha256'][reference['path']]==reference['sha256'],
                    'actual49 original signed raw ledger byte SHA differs')
    for eid,count in [('EX053_20261006',4),('EX054_20261006',1)]:
        exp=root/'experiments/S012'/eid;workspace=exp/'artifacts/rex';rows=read(workspace/'trials.json')
        require(len(rows)==count and all(r['record']['status']=='SUCCEEDED' for r in rows),'actual complete predecessor FULLs required')
        for row in rows:
            reference=row['record']['result_artifact'];target=(workspace/reference['path']).resolve();target.relative_to(workspace.resolve())
            require(sha256(target.read_bytes()).hexdigest()==reference['sha256'],'original predecessor FULL result byte SHA differs')
    choice=options['pair54'];workspace=root/'experiments/S012/EX054_20261006/artifacts/rex'
    require(choice['candidate_id']=='C4900' and checked(root,choice['trials'])==workspace/'trials.json'
            and receipts['EX054_20261006']['artifact_sha256']['trials.json']==choice['trials']['sha256'],
            'exact signed54 pair reference required')
    actual=read(workspace/'trials.json')[0]
    require(actual['candidate_id']=='C4900' and digest(actual)==digest(choice['row']),'actual54 pair row changed')
    frozen=read(root/'experiments/S012/EX054_20261006/witness_plan.json')[0]
    require(frozen['candidate_id']=='C4900' and frozen['label']=='KURT_ENTRY_EXIT_KNOWN_ONLY'
            and digest(frozen['parameters'])==digest(actual['parameters'])==frozen['parameter_sha256'],
            'actual54 frozen pair differs')
    return groups
