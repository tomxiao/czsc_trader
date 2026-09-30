"""Build read-only stage-four evidence union and delivery identities."""
from pathlib import Path
from hashlib import sha256
import json
import shutil
import numpy as np
import pandas as pd
from research_experiment import load_experiment,load_experiment_input
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=Path(__file__).resolve().parents[2]
OUTPUT=REPO/'.tmp/s011-stage4-delivery'
FIELDS=['tail_weight','spx_weight','entry','exit','max_days','lookback','premium']


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    contracts=[]
    for number in (26,27):
        root=REPO/f'experiments/S011/20260930_S011_EX{number}'
        validate_experiment_archive(root); loaded=load_experiment(root)
        receipt=json.loads((root/'artifacts/execution_receipt.json').read_text())['receipt_sha256']
        load_experiment_input(root/'artifacts',expected_receipt_sha256=receipt)
        contracts.append({'experiment':root.name,'receipt':receipt,'source_sha256':loaded.binding.source_sha256,
            'manifest_sha256':sha256((root/'experiment_manifest.json').read_bytes()).hexdigest()})
    old=pd.read_csv(REPO/'research/S011/stage3/iteration_02/unique_parameters.csv',float_precision='round_trip')
    # EX27 serializes through the public evaluator and a DataFrame CSV round trip.
    # Compare economic values before reusing an old account key; do not hash
    # immaterial floating-point CSV differences as new trading behavior.
    behaviors={}
    for r in old.drop_duplicates('account_key').itertuples():
        account=pd.read_csv(REPO/f'experiments/S011/20260930_S011_{r.experiment}/artifacts/trials/T{r.trial:03}/account_daily.csv.gz',float_precision='round_trip')
        behaviors[r.account_key]=account[['cash','quantity','equity']].to_numpy()
    root=REPO/'experiments/S011/20260930_S011_EX27'; rows=[]; numeric_replays=[]
    for row in pd.read_csv(root/'artifacts/trials.csv',float_precision='round_trip').to_dict('records'):
        folder=root/f'artifacts/trials/T{row["trial"]:03}'
        params=json.loads((folder/'payload.json').read_text())['parameters']
        account=pd.read_csv(folder/'standard/account_daily.csv.gz',float_precision='round_trip')
        raw_key=sha256(account[['date','cash','quantity','equity']].to_csv(index=False).encode()).hexdigest()
        values=account[['cash','quantity','equity']].to_numpy()
        equivalent=[k for k,a in behaviors.items() if np.array_equal(a[:,1],values[:,1]) and np.allclose(a[:,[0,2]],values[:,[0,2]],rtol=0,atol=1e-8)]
        assert len(equivalent)<=1
        behavior=equivalent[0] if equivalent else raw_key
        if equivalent:
            numeric_replays.append({'reference':f'EX27T{row["trial"]:03}','max_money_difference':float(np.abs(behaviors[behavior][:,[0,2]]-values[:,[0,2]]).max())})
        else:behaviors[behavior]=values
        rows.append({**row,'experiment':'EX27','reference':f'EX27T{row["trial"]:03}',
            'parameter_key':json.dumps(params,sort_keys=True),'account_key':behavior,'raw_account_key':raw_key})
    union=pd.concat([old,pd.DataFrame(rows)],ignore_index=True)
    for key,group in union.groupby('parameter_key'):
        assert group.account_key.nunique()==1,('replay account mismatch',key)
    unique=union.drop_duplicates('parameter_key'); eligible=unique.loc[unique.qualified].copy()
    eligible.to_csv(OUTPUT/'qualified_parameters.csv',index=False)
    unique.to_csv(OUTPUT/'unique_parameters.csv',index=False)
    representative=rows[0]
    matches=unique.loc[unique.account_key.eq(representative['account_key']),'reference'].tolist()
    identity=json.loads((root/'artifacts/trials/T000/identity.json').read_text())
    fixed={'status':'STAGE_FOUR_DEVELOPMENT_REPRESENTATIVE','research_judgment':'可交接',
        'original_reference':'S011-EX25T014','replay_reference':'S011-EX27T000','candidate_id':'EX27T000','strategy_id':'S011',
        'path_base':'repository_root','source_root':root.relative_to(REPO).as_posix()+'/runtime/strategy_runtime',
        'strategy_payload':json.loads((root/'artifacts/trials/T000/payload.json').read_text()),
        'identity':identity,'equivalent_existing_references':matches,
        'metrics':{k:representative[k] for k in ('cagr','drawdown','closed_trades','frequency','end_equity')},
        'proof_scope':'Development-only, local one-axis support; no full joint cube or independent forward proof',
        'cio_candidate_package_created':False,'freeze_or_deployment_authorized':False}
    (OUTPUT/'representative.json').write_text(json.dumps(fixed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    qualified27=sum(r['qualified'] for r in rows)
    result={'stage_four_complete':True,'research_judgment':'可交接','development_only':True,
        'new_account_evaluations':216+120,'new_parameter_proposals':15,'new_unique_parameters':len(unique)-len(old),
        'comparable_standard_trial_paths':573+15,'unique_parameters':len(unique),'distinct_accounts':unique.account_key.nunique(),
        'qualified_parameters':len(eligible),'qualified_accounts':eligible.account_key.nunique(),
        'ex27_qualified_points':qualified27,'ex27_qualified_neighbors':qualified27-1,
        'ex27_distinct_accounts':len({r['account_key'] for r in rows}),'archives':contracts,
        'account_equality_money_atol':1e-8,'account_equality_quantity_exact':True,'numeric_replays':numeric_replays,
        'no_new_hard_gates':True,'platform_modified':False,'stage_five_complete':False}
    (OUTPUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name,path in [('EX26',REPO/'.tmp/s011-stage4-ex26-verification'),('EX27',REPO/'.tmp/s011-stage4-ex27-verification'),('statistics',REPO/'.tmp/s011-stage4-statistics-verification')]:
        assert json.loads((path/'verification.json').read_text())['status']=='PASS'
        shutil.copytree(path,OUTPUT/'verification'/name,dirs_exist_ok=True)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
