"""Fail-closed byte-pinned current screening scope; no implicit old witness reuse."""
from hashlib import sha256
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from itertools import product
import importlib.util
import json
from pathlib import Path
import sys

from dataflows import DataRequest, DataCoverageRequirement, NoParameters
from research_experiment import load_experiment_input
from strategy_runtime import StrategyInputBinding, implementation_sha256

SOURCE_FILES = ('strategies/s012.py', 'resources/features.csv')
SCOPE_FIELDS = ('implementation_sha256','feature_sha256','execution_data_fingerprint',
                'execution_policy_sha256','economic_protocol_sha256','gate_sha256')
BASE_FIELDS = tuple(name for name in SCOPE_FIELDS if name not in {'execution_policy_sha256','gate_sha256'})

def plain(value):
    # Exact delivery-prep digest serialization for public ExecutionPolicy.
    if is_dataclass(value):
        return {field.name:plain(getattr(value,field.name)) for field in fields(value)}
    if isinstance(value,Mapping):
        return {str(key):plain(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [plain(item) for item in value]
    return value

def canonical(value):
    return sha256(json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def proposal_scope(strategy, base, gate_sha256):
    require(set(base)==set(BASE_FIELDS),'delivery scope base requires exactly four fields')
    result={**base,'execution_policy_sha256':canonical(strategy.definition.execution),
            'gate_sha256':gate_sha256}
    require(set(result)==set(SCOPE_FIELDS),'proposal scope requires exactly six fields')
    require(all(isinstance(value,str) and len(value)==64
                and all(c in '0123456789abcdef' for c in value) for value in result.values()),
            'proposal scope identities must be lowercase SHA256')
    return result

def parameter_proposals(config):
    """Explicit conditional Cartesian blocks, no inactive-parameter duplicates."""
    shared=config['grid'];fixed=config['fixed']
    require(isinstance(shared,dict) and isinstance(fixed,dict),'fixed and shared grids must be mappings')
    blocks=config.get('blocks',[{'name':'FIXED','grid':{}}])
    require(isinstance(blocks,list) and blocks and len({b['name'] for b in blocks})==len(blocks),
            'explicit uniquely named conditional blocks required')
    rows=[]
    for block in blocks:
        local=block['grid']
        require(isinstance(block['name'],str) and block['name'] and isinstance(local,dict),'invalid block')
        require(not(set(shared)&set(local)) and not((set(shared)|set(local))&set(fixed)),
                'conditional/shared/fixed fields overlap')
        grid={**shared,**local}
        require(all(isinstance(v,list) and v and len({canonical(x) for x in v})==len(v)
                    for v in grid.values()),'empty or duplicate grid choices')
        names=list(grid)
        rows.extend({'block':block['name'],'parameters':{**fixed,**dict(zip(names,choice))}}
                    for choice in product(*(grid[n] for n in names)))
    require(len({canonical(r['parameters']) for r in rows})==len(rows),'conditional grid duplicates literal parameters')
    require(len({tuple(sorted(r['parameters'])) for r in rows})==1,'every proposal must declare the same public parameter fields')
    return rows

def parameter_domains(config):
    rows=parameter_proposals(config)
    return {name:{'choices':list({canonical(row['parameters'][name]):row['parameters'][name]
                                 for row in rows}.values())}
            for name in sorted(rows[0]['parameters'])}

def delivery_contract(path):
    # Use the current delivery preparer's exact read-only scope derivation.
    # The constructor copies these bytes into the bound search source closure.
    name='s012_bound_delivery_contract_'+sha256(Path(path).read_bytes()).hexdigest()
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    require(tuple(value.SCOPE_FIELDS)==SCOPE_FIELDS,'delivery scope field contract changed')
    return value

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def require(value, message):
    if not value:
        raise ValueError(message)

def checked(root, ref):
    path = (root / ref['path']).resolve()
    path.relative_to(root.resolve())
    require(sha256(path.read_bytes()).hexdigest() == ref['sha256'], 'evidence bytes differ: '+ref['path'])
    return path

def reference(root, path):
    return {'path': Path(path).resolve().relative_to(root.resolve()).as_posix(),
            'sha256': sha256(Path(path).read_bytes()).hexdigest()}

def market_request(raw):
    # Current public execution_requests carry NoParameters only. Fail rather
    # than silently discarding a future dataset's typed parameters.
    value = dict(raw)
    require(not value.get('parameters'), 'nonempty market parameters need explicit typed extension')
    value['parameters'] = NoParameters()
    if value.get('coverage') is not None:
        value['coverage'] = DataCoverageRequirement(**value['coverage'])
    return DataRequest(**value)

def authenticated_receipt(root, expected, witness):
    import re
    require(re.fullmatch(r'EX\d{3}_\d{8}',witness) is not None,'invalid witness experiment id')
    exp = root / 'experiments/S012' / witness
    workspace = exp / 'artifacts/rex'
    publication = read(workspace/'execution_receipt.json')
    require(publication['receipt_sha256'] == expected, 'wrong witness receipt')
    evidence = load_experiment_input(workspace, expected_receipt_sha256=expected)
    require(evidence.experiment_id == witness, 'wrong complete witness experiment')
    binding = read(exp/'experiment_binding.json')
    require(implementation_sha256(binding['source_files'], source_root=exp)
            == binding['source_sha256'] == publication['source_sha256'], 'formal witness source changed')
    return exp, workspace, publication, evidence

def derive_scope(root, receipt_sha256, witness_contract, *, delivery_contract_path=None):
    witness=witness_contract['experiment_id']
    count=witness_contract['expected_configs']
    ids=witness_contract['candidate_ids']
    require(type(count) is int and count>0 and len(ids)==count and len(set(ids))==count,
            'witness count and explicit candidate set required')
    exp, workspace, receipt, evidence = authenticated_receipt(root, receipt_sha256, witness)
    trials = read(workspace/'trials.json')
    require(len(trials) == count and len(receipt['trace']['evaluations']) == count,
            'all declared formal witness accounts required')
    require({t['candidate_id'] for t in trials} == set(ids),
            'wrong formal witness candidate set')
    contract_path=Path(delivery_contract_path) if delivery_contract_path is not None else root/'.tmp/s012-stage3-native-20261006/delivery-prep/candidate_delivery.py'
    contract=delivery_contract(contract_path)
    formal_scopes=[contract.derive_formal_scope(root,trial,gate_sha256=None) for trial in trials]
    bases=[{name:value[name] for name in BASE_FIELDS} for value in formal_scopes]
    base_hashes=[contract.gate_scope_base_sha256(value) for value in formal_scopes]
    require(len(set(base_hashes))==1 and len({canonical(value) for value in bases})==1,
            'all witness FULL accounts must share implementation/features/market/economic protocol base')
    require(base_hashes[0]==canonical(bases[0]),'delivery scope base hash serialization differs')
    package = exp/'strategy_runtime'
    source_sha = sha256((package/'strategies/s012.py').read_bytes()).hexdigest()
    feature_sha = sha256((package/'resources/features.csv').read_bytes()).hexdigest()
    implementation = implementation_sha256(SOURCE_FILES, source_root=package)
    provenance = read(exp/'feature_provenance.json')
    require(feature_sha == provenance['feature_sha256'], 'feature provenance changed')
    assets, benchmarks, results = [], [], []
    for trial in trials:
        record = trial['record']
        require(record['status'] == 'SUCCEEDED' and record in receipt['trace']['evaluations'],
                'formal trial failed or not in complete receipt')
        require(trial['implementation_sha256'] == implementation and trial['feature_sha256'] == feature_sha,
                'formal trial differs from new source/features')
        require(trial['payload']['runtime']['source_sha256'] == implementation
                and tuple(trial['payload']['runtime']['source_files']) == SOURCE_FILES,
                'formal runtime closure differs')
        ref = record['result_artifact']
        require(receipt['artifact_sha256'].get(ref['path']) == ref['sha256'], 'result missing from receipt')
        path = checked(workspace, ref)
        result = read(path)
        req = result['request_identity']
        require(result['schema_version'] == 4 and req['execution_mode'] == 'FULL'
                and req['experiment_id'] == witness and canonical(req) == record['request_hash'] == result['request_hash'],
                'not authentic current FULL request')
        require(req['symbol'] == '518850.SH' and req['asset_type'] == 'etf'
                and req['initial_cash'] == 100000. and req['frequency_window_days'] == 60
                and req['data_cutoff'] == '2026-09-30'
                and req['windows'] == [{'end':'2026-09-30','start':'2020-06-08','window_id':'DEVELOPMENT'}]
                and req['costs'] == [{'measurement_tier':'FORMAL','one_way_cost':.001,'scenario_id':'BASE'}],
                'account/window/cost policy differs')
        require(req['benchmark']['execution'] == {'type':'NextOpenBuyHold','lot_size':100}, 'benchmark execution differs')
        require(len(result['runs']) == 1, 'exactly one FULL window/cost required')
        support = result['runs'][0]['signal_support']
        policy=support['execution_policy']
        settings=policy['settings']
        require(policy['policy_type']=='FROZEN_RULE' and settings['instrument']['lot_size']==100
                and settings['instrument']['price_tick']==.001
                and settings['capital']['target_scope']=='entry_cycle'
                and settings['capital']['fee_rate']==.001
                and settings['entry']['order_type']=='LIMIT'
                and settings['exit']['order_type']=='MARKET', 'FULL execution policy differs from permitted accelerator subset')
        typed = StrategyInputBinding.from_mapping(support['input_binding'])
        for raw in support['execution_requests'].values():
            market_request(raw)
        require(set(support['execution_requests']) == {'adjusted_daily','execution_daily','execution_30m','trading_calendar'},
                'incomplete market assets')
        feature_request = typed.plan.requests['features']
        require(feature_request.parameters.source_sha256 == feature_sha, 'prepared features source differs')
        assets.append({'input_binding':support['input_binding'],
                       'execution_requests':support['execution_requests'],
                       'execution_input_identities':support['execution_input_identities'],
                       'prepared_manifest_sha256':typed.prepared.manifest_sha256})
        benchmarks.append(trial['metrics']['benchmark'])
        results.append(reference(root,path))
    require(len({canonical(b) for b in benchmarks}) == 1, 'witness benchmarks differ')
    unique = {canonical(a):a for a in assets}
    return {'schema_version':1, 'witness_experiment_id':witness,'witness_contract':witness_contract,
            'delivery_scope_base':bases[0],
            'delivery_contract_sha256':sha256(contract_path.read_bytes()).hexdigest(),
            'witness_receipt_sha256':receipt_sha256,
            'strategy_file_sha256':source_sha, 'feature_sha256':feature_sha,
            'implementation_sha256':implementation,
            'feature_provenance':reference(root,exp/'feature_provenance.json'),
            'formal_results':results, 'market_assets':[unique[k] for k in sorted(unique)],
            'account':{'initial_cash':100000.,'lot_size':100,'price_tick':.001,
                       'one_way_cost':.001,'target_scope':'entry_cycle','execution_policy':'FROZEN_RULE',
                       'entry_order_type':'LIMIT','exit_order_type':'MARKET','target_values':[0,1]},
            'window':{'start':'2020-06-08','end':'2026-09-30','actual_sessions':1534,
                      'original_start':'2020-06-05','frequency_denominator':1535,'frequency_window_days':60},
            'benchmark':{'policy':req['benchmark'],'metrics':benchmarks[0]},
            'source_time_policy':{'decision_cutoff':'T17','plans':'20:31','execution':'next_session',
                                  'future_label_maturity_filter':False,'future_quality_mask':False},
            'scope_limit':'binary static ENTRY_CYCLE, current strategy public parameter contract; screening only'}

def verify_gate(exp, root, *, candidate_gate=None, candidate_scope=None):
    gate = candidate_gate if candidate_gate is not None else read(exp/'gate.json')
    require(gate['status'] == 'PASS' and gate['schema_version'] == 1, 'new gate not passed')
    scope = candidate_scope if candidate_scope is not None else read(exp/'scope.json')
    require(canonical(scope) == gate['scope_sha256'], 'scope digest differs')
    contract_path=exp/'delivery_contract.py'
    require(sha256(contract_path.read_bytes()).hexdigest()==scope['delivery_contract_sha256'],
            'bound delivery scope contract bytes changed')
    require(canonical(derive_scope(root,scope['witness_receipt_sha256'],scope['witness_contract'],
                                  delivery_contract_path=contract_path)) == gate['scope_sha256'],
            'current formal inputs differ from gated scope')
    require(gate['scope_base_sha256']==canonical(scope['delivery_scope_base']),
            'gate delivery base differs from full scope')
    proofs = {key:read(checked(root,gate[key])) for key in ('real_comparison','synthetic_comparison')}
    real, synthetic = proofs['real_comparison'], proofs['synthetic_comparison']
    contract=scope['witness_contract']
    require(real['experiment_id'] == contract['experiment_id'] and real['status'] == 'PASS'
            and real['passed'] == contract['expected_configs']
            and real['complete_formal_witness_pass'] is True and len(real['rows']) == contract['expected_configs']
            and all(row['status']=='PASS' for row in real['rows']), 'new complete declared FULL equivalence required')
    require({row['candidate_id'] for row in real['rows']}=={'S012-'+cid for cid in contract['candidate_ids']},
            'real comparison candidate closure differs from declared set')
    require(gate['comparison_summary']=={'status':'PASS','witness_experiment_id':contract['experiment_id'],
                'real_full_expected':contract['expected_configs'],'real_full_passed':real['passed'],
                'synthetic_expected':8,'synthetic_passed':len(synthetic['cases'])},
            'gate comparison count summary differs from actual proofs')
    require(gate['evidence_files']==[gate['real_comparison'],gate['synthetic_comparison']],
            'gate proof file references differ from delivery evidence files')
    trials=read(root/'experiments/S012'/contract['experiment_id']/'artifacts/rex/trials.json')
    expected_attempts=[{name:trial['record'][name] for name in ('experiment_id','attempt_id','evaluation_ids')}
                       for trial in trials]
    require(gate['full_reference_attempts']==expected_attempts,'gate full references differ from actual trial records')
    require(synthetic['status']=='PASS' and len(synthetic['cases']) == 8
            and all(case['comparison']['status']=='PASS' for case in synthetic['cases']),
            'eight current synthetic transaction witnesses required')
    for filename, digest in gate['source_sha256'].items():
        require(sha256((exp/filename).read_bytes()).hexdigest()==digest, 'gated source changed '+filename)
    require(set(gate['source_sha256'])=={'s012_accelerator.py','s012_bound_model.py'},'incomplete gated source set')
    require(gate['source_sha256']['s012_bound_model.py']==scope['strategy_file_sha256']==real['bound_model_sha256'],
            'current strategy not covered by real proof')
    require(real['accelerator_sha256']==synthetic['accelerator_sha256']==gate['source_sha256']['s012_accelerator.py'],
            'current accelerator not covered by both proofs')
    expected = {x['prepared_manifest_sha256'] for x in scope['market_assets']}
    observed = {c['prepared_manifest_sha256'] for row in real['rows'] for c in row['comparisons']}
    require(expected == observed, 'prepared manifest scope differs from real proof')
    expected_results={canonical(r) for r in scope['formal_results']}
    observed_results={canonical(c['full_result_artifact']) for row in real['rows'] for c in row['comparisons']}
    require(expected_results==observed_results
            and all(row['source_sha256']==scope['implementation_sha256'] for row in real['rows'])
            and all(c['signal_rows']==1534 and c['economics']['status']=='PASS'
                    for row in real['rows'] for c in row['comparisons']),
            'real proof does not cover all exact current FULL results/signals/source')
    require(real['source_bound']==read(root/'experiments/S012'/contract['experiment_id']/'experiment_binding.json')['source_sha256'],
            'comparison not bound to current experiment source')
    return scope, gate
