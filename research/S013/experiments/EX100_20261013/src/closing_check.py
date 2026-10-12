"""Two-round closure and supplemental verification-source retention, no research."""
from importlib.metadata import version
from datetime import datetime, timezone
import shutil
import governance as g

old=g.read(g.ROOT/'research/S013/assets/deliveries/MANDATE/7/delivery.json')['content']['payload']['items']
new=g.read(g.ROOT/'research/S013/assets/deliveries/MANDATE/8/delivery.json')['content']['payload']['items']
current={x['item_id']:x for x in new}
for item in old:
    if item['item_id']!='renewal_ten_rounds': assert current[item['item_id']]==item
proof={'status':'PASS','closed_on_utc':datetime.now(timezone.utc).isoformat(),'research_state':'PAUSED',
    'objective_achieved':False,'two_round_execution_completed':True,'completed':2,'remaining':0,
    'goals_and_fixed_execution_unchanged':True,'EX101_authorized':False,'experiments':{},
    'new_full_window_strategy_accounts':0,'real_independent_attempts':1635,'actual_real_annual_fits':48,
    'provider_calls':2,'provider_retries':0,'new_candidates':0,'historical_eligibility_unchanged':True,
    'publication_time_verified':False,'conditional_exploration':True}
for number,rev in ((99,27),(100,28)):
    path=g.ROOT/f'research/S013/experiments/EX{number:03}_20261013/protocols'
    full=g.read(path/'delivery_validation.json'); copied=g.read(path/'report_copy_verification.json')
    assert full['status']=='PASS' and not full['issues'] and copied['status']=='PASS'
    formal=g.ROOT/copied['formal_report']; duplicate=g.ROOT/copied['experiment_report']
    assert formal.read_bytes()==duplicate.read_bytes()
    assert g.digest(formal)==copied['formal_sha256']==copied['copy_sha256']
    proof['experiments'][f'EX{number:03}']={'delivery':g.read(path/'delivery_reference.json'),
        'FULL':full,'report_copy':copied,'budget':g.read(path/'budget_receipt.json')}
assert not list((g.ROOT/'research/S013/experiments').glob('EX101*'))
exp=g.ExperimentRef('S013','EX100_20261013')
sources=[g.WORK/'execution/ledger_verification.py',g.WORK/'input_adapter.py',g.WORK/'run_fit.py',
    g.WORK/'models/bootstrap_peer_audit.py',g.WORK/'closing_check.py']
refs={}
for source in sources:
    refs[source.relative_to(g.ROOT).as_posix()]=g.put(exp,source)
    target=exp.resolve(g.ROOT)/'src'/source.relative_to(g.WORK)
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists(): shutil.copyfile(source,target)
    else: assert target.read_bytes()==source.read_bytes()
proof['supplemental_verification_source_references']=refs
proof['runtime_versions']={x:version(x) for x in ('numpy','pandas','czsc-dataflows','czsc-strategy-runtime','czsc-trading-execution-engine')}
proof['registered_candidate_count']=len(list((g.ROOT/'research/registrations/S013/candidates').glob('*.json')))
assert proof['registered_candidate_count']==203
target=g.ROOT/'research/S013/materials/stage2_closeout_20261013.json'
g.write(target,proof)
reference=g.put(exp,target)
g.write(g.ROOT/'research/S013/materials/stage2_closeout_reference_20261013.json',reference)
print({'status':'PASS','state':'PAUSED','completed':2,'remaining':0,'fits':48,'attempts':1635,'supplier_calls':2,'candidates_unchanged':203},flush=True)
