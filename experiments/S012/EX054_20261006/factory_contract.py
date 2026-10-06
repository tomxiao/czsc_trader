"""Exact signed C4801 single-risk-exit control."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input, experiment_source_sha256
from strategy_runtime import implementation_sha256

MODEL_SHA='a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7'
FEATURE_SHA='8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
PROVENANCE_SHA='4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858'
SOURCES=('strategies/s012.py','resources/features.csv')
PREDECESSORS=('EX048_20261006','EX053_20261006')
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
    require(options['schema_version']==1 and options['experiment_id']=='EX054_20261006'
            and options['root_frozen_controls'] is True and options['approval_reason'].strip(),
            'explicit root-frozen EX054 protocol required')
    require(options['candidate_start']==4900 and type(options['candidate_start']) is int
            and options['seed']==12054 and type(options['seed']) is int,'fixed single-control seed/candidate contract')
    require(set(options['predecessor_receipts'])==set(PREDECESSORS),'exact48/53 complete signed predecessors required')
    row=options['center53']['row'];p=row['parameters']
    require(row['candidate_id']==options['center53']['candidate_id']=='C4801'
            and row['control_label']=='KURT_ENTRY_KNOWN_ONLY' and row['record']['status']=='SUCCEEDED',
            'exact actual53 C4801 required')
    require(p=={'confirm_o01':False,'cooldown':0,'risk_gate':'kurt','risk_exit':False,'trailing_stop':0.,
                'allocation':1.,'exit_policy':'fixed','min_hold':1,'risk_unknown_policy':'known_only',
                'hold_days':6,'entry_premium':.02,'opportunity':'momentum','momentum_lookback':10},'original C4801 economic parameters differ')
    declaration={'candidate_id':'C4900','label':'KURT_ENTRY_EXIT_KNOWN_ONLY','origin':'center53',
        'delta':{'risk_exit':True},'parameters':dict(p,risk_exit=True)}
    require(options['controls']==[declaration],'only exact risk_exit False to True allowed')
    return [{'candidate_id':'C4900','kind':'PROSPECTIVE_SINGLE_MECHANISM_CONTROL','label':declaration['label'],
        'delta':declaration['delta'],'parameters':declaration['parameters'],'parameter_sha256':digest(declaration['parameters']),
        'source_selection_ids':[{'experiment_id':'EX053_20261006','reference_id':'C4801',
            'original_row_sha256':digest(row),'original_parameter_sha256':digest(p)}]}]

def authenticate(root,options):
    root=Path(root).resolve()
    for eid in PREDECESSORS:
        require((root/'experiments/S012'/eid/'artifacts/rex/execution_receipt.json').is_file(),
                eid+' complete signed REX required before any EX054 construction')
    groups=plan(options);receipts={}
    for eid in PREDECESSORS:
        exp=root/'experiments/S012'/eid;workspace=exp/'artifacts/rex'
        load_experiment_input(workspace,expected_receipt_sha256=options['predecessor_receipts'][eid])
        receipt=read(workspace/'execution_receipt.json');binding=read(exp/'experiment_binding.json')
        require(experiment_source_sha256(exp,tuple(binding['source_files']))==binding['source_sha256']==receipt['source_sha256'],
                'signed original source closure differs')
        receipts[eid]=receipt
        for name,expected in [('strategy_runtime/strategies/s012.py',MODEL_SHA),
                ('strategy_runtime/resources/features.csv',FEATURE_SHA),('feature_provenance.json',PROVENANCE_SHA)]:
            require(sha256((exp/name).read_bytes()).hexdigest()==expected,'original model/input/provenance bytes differ')
    audit=read(checked(root,options['audit53']))
    require(audit['status']=='PASS' and audit['errors']==[] and audit['experiments']==['EX053_20261006']
            and audit['verified_receipt_hashes']['EX053_20261006']==options['predecessor_receipts']['EX053_20261006']
            and len(audit['rows'])==4 and all(r['status']=='PASS' for r in audit['rows']),
            'actual independent53 audit PASS for all four accounts required')
    diagnosis=read(checked(root,options['rationale_evidence']))
    require(diagnosis['status']=='PASS' and type(diagnosis['new_accounts']) is int and diagnosis['new_accounts']==0,
            'read-only actual holding diagnosis required')
    for ref in diagnosis['evidence']:checked(root,ref)
    choice=options['center53'];exp=root/'experiments/S012/EX053_20261006';workspace=exp/'artifacts/rex'
    trials=checked(root,choice['trials'])
    require(trials==workspace/'trials.json' and receipts['EX053_20261006']['artifact_sha256']['trials.json']==choice['trials']['sha256'],
            'exact original signed trials required')
    rows=read(trials);require(len(rows)==4 and all(r['record']['status']=='SUCCEEDED' for r in rows),'four genuine FULL results required')
    actual=next(r for r in rows if r['candidate_id']=='C4801')
    require(digest(actual)==digest(choice['row']),'actual original C4801 row changed')
    frozen=next(g for g in read(exp/'witness_plan.json') if g['candidate_id']=='C4801')
    require(frozen['label']=='KURT_ENTRY_KNOWN_ONLY' and digest(frozen['parameters'])==digest(actual['parameters'])==frozen['parameter_sha256'],
            'frozen original parameter SHA or label differs')
    reference=actual['record']['result_artifact'];result=(workspace/reference['path']).resolve();result.relative_to(workspace.resolve())
    require(sha256(result.read_bytes()).hexdigest()==reference['sha256'],'original actual FULL result SHA differs')
    require(actual['implementation_sha256']==implementation_sha256(SOURCES,source_root=exp/'strategy_runtime')
            and actual['feature_sha256']==FEATURE_SHA,'actual runtime/input identity differs')
    return groups
