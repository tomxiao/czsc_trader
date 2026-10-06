"""Exact signed predecessors and five root-frozen prospective FULL controls."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input, experiment_source_sha256
from strategy_runtime import implementation_sha256

MODEL_SHA='a19077a4e490ff000ee1db1567e01e8b5dfa8847be914d6ea45310f0448cadf7'
FEATURE_SHA='8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
PROVENANCE_SHA='4c33418cb0da1e21e0bea973dcd24698d545b0e3925e6476ece7159fdd028858'
SOURCES=('strategies/s012.py','resources/features.csv')
PREDECESSORS=('EX048_20261006','EX050_20261006','EX051_20261006')
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
    require(options['schema_version']==1 and options['experiment_id']=='EX052_20261006'
            and options['root_frozen_controls'] is True and options['approval_reason'].strip(),'explicit root-frozen EX052 protocol required')
    require(set(options['predecessor_receipts'])==set(PREDECESSORS),'exact48/50/51 signed predecessors required')
    center=options['center51']['row'];baseline=options['baseline50']['row'];trailing=options['trailing50']['row']
    require(center['proposal_id']==options['center51']['proposal_id']=='OPTUNA_0081'
            and center['status']=='COMPLETE' and center['parameter_sha256']==digest(center['parameters']),'exact complete51 center/parameter SHA required')
    p=center['parameters']
    require(p['opportunity']=='momentum' and p['momentum_lookback']==10 and p['hold_days']==6 and p['cooldown']==0
            and p['entry_premium']==.02 and p['risk_gate']=='none' and not p['risk_exit'] and p['trailing_stop']==0
            and p['exit_policy']=='fixed' and p['allocation']==1. and p['risk_unknown_policy']=='block','center51 economic parameters differ from root protocol')
    q=baseline['parameters']
    require(baseline['candidate_id']==options['baseline50']['candidate_id']=='C4605'
            and baseline['control_label']=='MOM_ENTRY_ONLY' and baseline['record']['status']=='SUCCEEDED','exact succeeded50 MOM_ENTRY_ONLY original required')
    require(q['opportunity']=='momentum' and q['momentum_lookback']==10 and q['hold_days']==6 and q['cooldown']==0
            and q['entry_premium']==.01 and q['risk_gate']=='mom' and not q['risk_exit'] and q['trailing_stop']==0
            and q['exit_policy']=='fixed' and q['allocation']==1. and q['risk_unknown_policy']=='block','baseline50 frozen parameters differ')
    r=trailing['parameters']
    require(trailing['candidate_id']==options['trailing50']['candidate_id']=='C4607'
            and trailing['control_label']=='TRAIL050' and trailing['record']['status']=='SUCCEEDED','exact succeeded50 TRAIL050 original required')
    require(r==dict(p,entry_premium=.01,trailing_stop=.05),'trailing50 complete frozen parameters differ from declared source')
    recipes=[('H5_C1','center51',{'hold_days':5,'cooldown':1}),('H6_C2','center51',{'cooldown':2}),
             ('H6_C1','center51',{'cooldown':1}),('MOM_UNKNOWN_KNOWN_ONLY','baseline50',{'risk_unknown_policy':'known_only'}),
             ('TRAIL050_PREMIUM020','trailing50',{'entry_premium':.02})]
    require(len(options['controls'])==5,'exact5 prospective controls required')
    groups=[]
    for i,(label,origin,delta) in enumerate(recipes):
        declaration=options['controls'][i];base={'center51':p,'baseline50':q,'trailing50':r}[origin]
        parameters=dict(base,**delta)
        require(declaration=={'candidate_id':f'C{4700+i:04d}','label':label,'origin':origin,'delta':delta,'parameters':parameters},
                'root frozen control delta/parameters differ; no automatic domain expansion')
        source={'center51':center,'baseline50':baseline,'trailing50':trailing}[origin]
        groups.append({'candidate_id':f'C{4700+i:04d}','kind':'PROSPECTIVE_PREDECLARED_INTERACTION_CONTROL' if origin=='trailing50'
                       else 'PROSPECTIVE_SINGLE_MECHANISM_CONTROL','label':label,
            'parameters':parameters,'parameter_sha256':digest(parameters),'delta':delta,
            'source_selection_ids':[{'experiment_id':'EX051_20261006' if origin=='center51' else 'EX050_20261006',
                'reference_id':source['proposal_id'] if origin=='center51' else source['candidate_id'],
                'original_row_sha256':digest(source),'original_parameter_sha256':digest(base)}]})
    require(len({g['parameter_sha256'] for g in groups})==5,'5 unique controls required')
    return groups
def authenticate(root,options):
    root=Path(root).resolve()
    # Refuse before constructing a draft while any actual predecessor is incomplete.
    for eid in PREDECESSORS:
        require((root/'experiments/S012'/eid/'artifacts/rex/execution_receipt.json').is_file(),
                eid+' requires complete signed REX before EX052 construction; partial FULL records are insufficient')
    groups=plan(options);receipts={}
    for eid in PREDECESSORS:
        exp=root/'experiments/S012'/eid;workspace=exp/'artifacts/rex'
        load_experiment_input(workspace,expected_receipt_sha256=options['predecessor_receipts'][eid])
        receipt=read(workspace/'execution_receipt.json');binding=read(exp/'experiment_binding.json')
        require(experiment_source_sha256(exp,tuple(binding['source_files']))==binding['source_sha256']==receipt['source_sha256'],
                'signed predecessor source closure differs')
        receipts[eid]=receipt
    workspace=root/'experiments/S012/EX051_20261006/artifacts/rex';choice=options['center51']
    path=checked(root,choice['search'])
    require(path==workspace/'search.json' and receipts['EX051_20261006']['artifact_sha256']['search.json']==choice['search']['sha256'],
            'center search not actual signed complete51 original')
    search=read(path);rows=search['proposals']
    require(len(rows)==195 and all(r['status']=='COMPLETE' for r in rows) and search['frontier_status']=='COMPUTED_FINAL','complete51 must have195 COMPLETE/0FAILED')
    original=next(r for r in rows if r['proposal_id']==choice['proposal_id'])
    require(digest(original)==digest(choice['row']),'center51 row differs from actual original')
    feasible=[r for r in rows if r['metrics']['frequency']>=5 and abs(r['metrics']['max_drawdown'])<abs(r['metrics']['benchmark']['max_drawdown'])]
    best=sorted(feasible,key=lambda r:(-r['metrics']['net_cagr'],abs(r['metrics']['max_drawdown']),-r['metrics']['frequency'],r['proposal_id']))
    require(best and best[0]['proposal_id']==choice['proposal_id'],'root center not actual complete51 feasible primary')
    for ref in (original['raw_summary'],*original['raw_ledgers'].values()):
        target=(workspace/ref['path']).resolve();target.relative_to(workspace.resolve())
        require(receipts['EX051_20261006']['artifact_sha256'].get(ref['path'])==ref['sha256']
                and sha256(target.read_bytes()).hexdigest()==ref['sha256'],'center51 raw ledger integrity differs')
    require(original['raw_ledgers']['account_daily']['rows']==1534,'actual center51 execution window differs')
    summary=read(workspace/original['raw_summary']['path'])
    require(all(original.get(k)==v for k,v in summary.items()),'center original row differs from raw summary')
    exp=root/'experiments/S012/EX051_20261006';gate=checked(root,choice['gate'])
    require(gate==exp/'gate.json' and choice['gate']['sha256']==original['scope']['gate_sha256'],'current center51 gate differs; no accelerator credit assigned')
    require(read(gate)['status']=='PASS','actual original center51 gate not PASS')
    require(sha256((exp/'s012_bound_model.py').read_bytes()).hexdigest()==MODEL_SHA,'center51 source model differs')
    workspace=root/'experiments/S012/EX050_20261006/artifacts/rex';choice=options['baseline50'];path=checked(root,choice['trials'])
    require(path==workspace/'trials.json' and receipts['EX050_20261006']['artifact_sha256']['trials.json']==choice['trials']['sha256'],'baseline50 trials not signed')
    trials=read(path);require(len(trials)==8 and all(r['record']['status']=='SUCCEEDED' for r in trials),'complete50 must have8 genuine successful FULL accounts')
    verified50=[]
    for key,label in [('baseline50','MOM_ENTRY_ONLY'),('trailing50','TRAIL050')]:
        choice=options[key]
        require(checked(root,choice['trials'])==path and choice['trials']==options['baseline50']['trials'],'50 source rows require same signed actual trials')
        original=next(r for r in trials if r['candidate_id']==choice['candidate_id'])
        require(digest(original)==digest(choice['row']),key+' full row differs from actual original')
        frozen=next(g for g in read(root/'experiments/S012/EX050_20261006/witness_plan.json') if g['candidate_id']==choice['candidate_id'])
        require(frozen['label']==label and digest(frozen['parameters'])==digest(original['parameters'])
                and frozen['parameter_sha256']==digest(original['parameters']),key+' differs from frozen forward plan')
        reference=original['record']['result_artifact'];target=(workspace/reference['path']).resolve();target.relative_to(workspace.resolve())
        require(sha256(target.read_bytes()).hexdigest()==reference['sha256'],key+' actual FULL result artifact differs')
        verified50.append(original)
    for eid in ('EX048_20261006','EX050_20261006'):
        for name,expected in [('strategy_runtime/strategies/s012.py',MODEL_SHA),('strategy_runtime/resources/features.csv',FEATURE_SHA),('feature_provenance.json',PROVENANCE_SHA)]:
            require(sha256((root/'experiments/S012'/eid/name).read_bytes()).hexdigest()==expected,'original source/features/provenance bytes differ')
    implementation=implementation_sha256(SOURCES,source_root=root/'experiments/S012/EX048_20261006/strategy_runtime')
    require(options['center51']['row']['scope']['implementation_sha256']==implementation
            and options['center51']['row']['scope']['feature_sha256']==FEATURE_SHA
            and all(r['implementation_sha256']==implementation and r['feature_sha256']==FEATURE_SHA for r in verified50),'baseline source/input identity differs')
    return groups
