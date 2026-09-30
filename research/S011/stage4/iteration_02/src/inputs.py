"""Read immutable S011 evidence and register version-aware configuration identities."""
from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from contracts import Configuration, Registry, fingerprint

REPO=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file() and (p/'research').is_dir())
FIELDS=['tail_weight','spx_weight','entry','exit','max_days','lookback','premium']
LEDGERS=['decisions','orders','fills','account_daily','trades']


def evidence_digest_bytes(relative,raw):
    # Git normalizes ordinary text to LF. Immutable experiment bytes remain raw.
    if not relative.startswith('experiments/') and Path(relative).suffix in ('.py','.md','.json','.csv'):
        raw=raw.replace(b'\r\n',b'\n')
    return sha256(raw).hexdigest()


def evidence_digest(path):
    return evidence_digest_bytes(path.relative_to(REPO).as_posix(),path.read_bytes())


class Sources:
    def __init__(self): self.hashes={}
    def record(self,path):
        path=Path(path)
        if not path.is_absolute(): path=REPO/path
        relative=path.relative_to(REPO).as_posix()
        digest=evidence_digest(path)
        if relative in self.hashes and self.hashes[relative]!=digest:raise ValueError('input changed: '+relative)
        self.hashes[relative]=digest; return path
    def json(self,path):return json.loads(self.record(path).read_text(encoding='utf-8'))
    def csv(self,path):return pd.read_csv(self.record(path),float_precision='round_trip')
    def validate(self):
        for name,digest in self.hashes.items():
            if evidence_digest(REPO/name)!=digest: raise ValueError('input hash changed: '+name)


def metrics(account,trades):
    eq=account.equity.to_numpy(float); n=len(eq)
    cagr=float((eq[-1]/1e6)**(252/n)-1)
    dd=float(np.min(eq/np.maximum.accumulate(np.r_[1e6,eq])[1:]-1))
    cycles=int(trades.status.eq('CLOSED').sum())
    return {'cagr':cagr,'drawdown':dd,'drawdown_magnitude':-dd,'closed_trades':cycles,'frequency':60*cycles/n,'end_equity':float(eq[-1])}


def qualifies(m,b):
    return bool(m['cagr']>=1.5*b['cagr'] and (b['cagr']>0 or(m['cagr']>0 and m['cagr']>b['cagr'])) and m['drawdown']>b['drawdown'] and 4<=m['frequency']<=6)


def load(sources):
    for n in range(13,28):
        root=REPO/f'experiments/S011/20260930_S011_EX{n}'
        validate_experiment_archive(root)
        sources.record(root/'experiment_manifest.json')
        for name in ('01_goal.md','02_design.md','04_conclusion.md','experiment_binding.json'):
            if (root/name).exists():sources.record(root/name)
    bdir=REPO/'experiments/S011/20260930_S011_EX16/artifacts'
    bh=sources.csv(bdir/'benchmark_account_daily.csv.gz')
    benchmark=metrics(bh,sources.csv(bdir/'benchmark_trades.csv.gz'))
    prior=REPO/'research/S011/stage3/iteration_02'
    original=sources.csv(prior/'all_evaluations.csv')
    later=sources.csv('experiments/S011/20260930_S011_EX27/artifacts/trials.csv')
    legacy=sources.csv('experiments/S011/20260930_S011_EX14/artifacts/trials.csv')
    ex23sources=sources.json('experiments/S011/20260930_S011_EX23/artifacts/source_trials.json')
    registry=[]; byfingerprint={}; evaluations=[]; accounts={}; frames_by_id={}; standard_paths={}; ref_to_id={}
    seeds=[]
    for row in legacy.to_dict('records'): seeds.append((14,row,'NONCOMPARABLE_LEGACY'))
    for row in original.to_dict('records'): seeds.append((int(row['experiment'][2:]),row,'COMPARABLE_DEVELOPMENT'))
    for row in later.to_dict('records'): seeds.append((27,row,'COMPARABLE_DEVELOPMENT'))
    for number,row,scope in seeds:
        t=int(row['trial']); ref=f'EX{number}T{t:03}'
        root=REPO/f'experiments/S011/20260930_S011_EX{number}'
        folder=root/f'artifacts/trials/T{t:03}'
        payload=sources.json(folder/'payload.json'); fp=fingerprint(payload)
        identity=sources.json(folder/'identity.json')
        runtime_root=root/'runtime/strategy_runtime'
        for name in payload['runtime']['source_files']: sources.record(runtime_root/name)
        if fp not in byfingerprint:
            cid=f'S011-CFG-{len(registry)+1:06}'
            config=Configuration(config_id=cid,config_fingerprint=fp,definition=payload,source_root=runtime_root.relative_to(REPO).as_posix(),first_reference=ref,references=[ref],scope=scope).model_dump()
            registry.append(config); byfingerprint[fp]=config
        config=byfingerprint[fp]; cid=config['config_id']; ref_to_id[ref]=cid
        if ref not in config['references']:config['references'].append(ref)
        account_folder=folder/'standard' if number==27 else folder
        frames={name:sources.csv(account_folder/(name+'.csv.gz')) for name in LEDGERS}
        account=frames['account_daily']; m=metrics(account,frames['trades'])
        assert len(account)==403 and account.date.equals(bh.date)
        assert account.cash.ge(-1e-8).all() and account.quantity.mod(100).eq(0).all()
        assert np.allclose(account.cash+account.quantity*account.close,account.equity,rtol=0,atol=1e-8)
        if cid in accounts:
            pd.testing.assert_frame_equal(account[['date','cash','quantity','equity']],accounts[cid][['date','cash','quantity','equity']],rtol=0,atol=1e-8)
        else:
            accounts[cid]=account; frames_by_id[cid]=frames; standard_paths[cid]=account_folder.relative_to(REPO).as_posix()
        behavior=sha256(account[['date','cash','quantity','equity']].to_csv(index=False).encode()).hexdigest()
        actual_ref=ex23sources[t]['candidate_id'] if number==23 else ref
        item={'evaluation_id':f'S011-EVAL-{ref}-standard','config_id':cid,'reference':ref,'source_candidate_id':actual_ref,
            'source_experiment':root.name,'scenario':'standard','scope':scope,'state':'COMPLETE','qualified':qualifies(m,benchmark) if scope=='COMPARABLE_DEVELOPMENT' else None,
            'original_reported_qualified':bool(row['qualified']),'raw_behavior_hash':behavior,'evidence':account_folder.relative_to(REPO).as_posix(),
            'data_identity':identity['data_identity'],'request_hash':identity['request_hash'],'result_hash':identity['result_hash'],
            'return_pass':bool(m['cagr']>=1.5*benchmark['cagr']) if scope=='COMPARABLE_DEVELOPMENT' else None,
            'drawdown_pass':bool(m['drawdown']>benchmark['drawdown']) if scope=='COMPARABLE_DEVELOPMENT' else None,
            'frequency_pass':bool(4<=m['frequency']<=6) if scope=='COMPARABLE_DEVELOPMENT' else None,
            'payload_path':(folder/'payload.json').relative_to(REPO).as_posix(),'failure_reason':None,**m}
        evaluations.append(item)
    existing=REPO/'research/S011/configurations.json'
    if existing.exists():
        old=Registry.model_validate(sources.json(existing))
        for entry in old.configurations:
            new=byfingerprint.get(entry['config_fingerprint'])
            if new is None or new['config_id']!=entry['config_id'] or new['definition']!=entry['definition']:
                raise ValueError('existing registry identity conflict')
    registry_doc=Registry(configurations=registry).model_dump()
    table=pd.DataFrame(evaluations)
    # Economic equality is scoped to this same window and cash/execution contract.
    behavior_arrays=[]; behavior_ids=[]; config_behavior={}
    for cid in table.loc[table.scope.eq('COMPARABLE_DEVELOPMENT'),'config_id'].drop_duplicates():
        values=accounts[cid][['cash','quantity','equity']].to_numpy()
        matching=[i for i,a in enumerate(behavior_arrays) if np.array_equal(a[:,1],values[:,1]) and np.allclose(a[:,[0,2]],values[:,[0,2]],rtol=0,atol=1e-8)]
        if not matching:
            behavior_arrays.append(values); behavior_ids.append('S011-BEH-'+sha256(values.tobytes()).hexdigest()[:16]); index=len(behavior_ids)-1
        else:
            assert len(matching)==1; index=matching[0]
        config_behavior[cid]=behavior_ids[index]
    table['behavior_id']=table.config_id.map(config_behavior)
    # Cost records retain original runtime identity; no cross-version imputation.
    costs={}; cost_evidence={}; cost_records=[]
    for row in sources.csv('experiments/S011/20260930_S011_EX26/artifacts/cost_sensitivity.csv').to_dict('records'):
        if row['is_benchmark']:
            cost_records.append({'evaluation_id':f'S011-EX26-EX16BH-{row["scenario"]}','config_id':None,'reference':'EX16BH',**row})
            continue
        folder=REPO/f'experiments/S011/20260930_S011_EX26/artifacts/accounts/{row["reference"]}'
        payload=sources.json(folder/'identity.json')['payload']; cid=byfingerprint[fingerprint(payload)]['config_id']
        key=(cid,row['scenario']); costs[key]=row; cost_evidence[key]=(folder/row['scenario']).relative_to(REPO).as_posix()
        cost_records.append({'evaluation_id':f'S011-EX26-{row["reference"]}-{row["scenario"]}','config_id':cid,**row})
    for row in sources.csv('experiments/S011/20260930_S011_EX27/artifacts/cost_sensitivity.csv').to_dict('records'):
        cid=ref_to_id[f'EX27T{int(row["trial"]):03}']; key=(cid,row['scenario'])
        costs[key]=row; cost_evidence[key]=f'experiments/S011/20260930_S011_EX27/artifacts/trials/T{int(row["trial"]):03}/{row["scenario"]}'
        cost_records.append({'evaluation_id':f'S011-EX27-T{int(row["trial"]):03}-{row["scenario"]}','config_id':cid,'reference':f'EX27T{int(row["trial"]):03}','one_way_cost':row['fee'],'is_benchmark':False,**row})
    for key,path in cost_evidence.items():
        account=sources.csv(REPO/path/'account_daily.csv.gz'); trades=sources.csv(REPO/path/'trades.csv.gz')
        m=metrics(account,trades)
        if not np.allclose([m['cagr'],m['drawdown']],[costs[key]['cagr'],costs[key]['drawdown']],rtol=0,atol=1e-12):raise ValueError('cost metric mismatch')
    history=[]
    for number in (13,17,18,19,21):
        root=REPO/f'experiments/S011/20260930_S011_EX{number}'
        manifest=sources.json(root/'experiment_manifest.json')
        failures=sorted((root/'artifacts').rglob('failure.json'))
        for path in failures:
            item=sources.json(path)
            history.append({'experiment':root.name,'state':'TECHNICAL_FAILURE','evidence':path.relative_to(REPO).as_posix(),'detail':item})
        if not failures:history.append({'experiment':root.name,'state':manifest['status'],'evidence':(root/'04_conclusion.md').relative_to(REPO).as_posix(),'detail':{'successful_inherited_trials_counted_once':number in (19,21)}})
    return {'registry':registry_doc,'evaluations':table,'accounts':accounts,'frames':frames_by_id,'paths':standard_paths,
        'ref_to_id':ref_to_id,'behaviors':config_behavior,'benchmark_account':bh,'benchmark':benchmark,
        'costs':costs,'cost_evidence':cost_evidence,'cost_evaluations':pd.DataFrame(cost_records),'history':history}
