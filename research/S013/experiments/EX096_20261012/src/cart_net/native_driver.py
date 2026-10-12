"""EX096 one native original14 CART net centre; phases invoked explicitly by root.

Definition and metadata inspection do not read actual market/account contents.
Preparation authenticates existing cached inputs; execution is one public full
account with no automatic repeat. A centre pass requires a later frozen32/fee
followup and never completes the current research goal on its own.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import ast
from hashlib import sha256
import importlib
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate, canonical_sha256, implementation_sha256
from strategy_evaluator import CandidateAssessmentRequest, QuantileMethod, SelfCheckProtocol, assess_candidates
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, build_assessment_evidence
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK = Path(__file__).resolve().parent
OUT = ROOT / '.tmp/s013-new-goal/result096'
CANDIDATE = 'C9096'
MECHANISM = 'ORIGINAL14_GREEDY_CART_NET_FIXED_EPISODE'
PACKAGE = WORK / 'strategy_runtime'
RUNTIME_FILES = ['strategies/' + name for name in ('confirm_kernel.py', 'confirm_net.py', 'tree_kernel.py', 'cart_net.py')]
OLD80 = ROOT / 'research/S013/experiments/EX080_20261012'
ORACLE = OLD80 / 'src/reproduction/82670d42c540_audit.py'
HELPERS = ROOT / 'research/S013/experiments/EX074_20261011/src'


def candidate_unoccupied():
    occupied = (ROOT / 'research/S013/assets/candidates' / CANDIDATE,
                ROOT / 'research/registrations/S013/candidates' / (CANDIDATE + '.json'))
    if any(path.exists() for path in occupied):
        raise ValueError('Reserved candidate identity is occupied; never overwrite or register implicitly')


def definition():
    """Only public references/source/registry metadata; never actual inputs."""
    candidate_unoccupied()
    for filename in ('checks.json', 'audit_checks.json', 'native_checks.json'):
        checked = g.read(WORK / filename)
        if checked['status'] != 'PASS' or checked['real_inputs_read'] != 0 or not checked['synthetic_only']:
            raise ValueError('Primary, independent and native pure checks required')
    for filename, expected in g.read(WORK / 'checks.json')['source_sha256'].items():
        if g.digest(WORK / filename) != expected:
            raise ValueError('Checked primary source changed: ' + filename)
    native_check = g.read(WORK / 'native_checks.json')
    for filename, expected in native_check['source_sha256'].items():
        if g.digest(PACKAGE / filename) != expected:
            raise ValueError('Checked runtime source changed: ' + filename)
    if g.digest(WORK / 'native_checks.py') != native_check['test_source_sha256']:
        raise ValueError('Native test source changed')
    if (WORK / 'tree_kernel.py').read_bytes() != (PACKAGE / 'strategies/tree_kernel.py').read_bytes():
        raise ValueError('Runtime CART must be exactly pure audited source')
    old = g.read(OLD80 / 'protocols/plan_v2.json')
    parameters = {'confirmation_lookback': 120, 'holding_sessions': 4, 'tree_depth': 2, 'minimum_leaf': 40}
    coordinates = [('confirmation_lookback',40,120,'INTEGER'),('holding_sessions',1,60,'INTEGER'),
                   ('tree_depth',1,4,'INTEGER'),('minimum_leaf',20,120,'INTEGER')]
    payload = {'parameters': parameters, 'runtime': {'contract_version': 1,
        'module': 'strategy_runtime.strategies.cart_net', 'qualname': 'CartNet',
        'source_files': RUNTIME_FILES, 'source_sha256': implementation_sha256(RUNTIME_FILES, source_root=PACKAGE)}}
    source_files = [path.relative_to(ROOT).as_posix() for path in WORK.rglob('*') if path.is_file() and path.suffix in ('.py','.json')]
    source_files += ['.tmp/s013-new-goal/governance.py','.tmp/s013-new-goal/gates_v2.py',
        '.tmp/s013-new-goal/prospective_expression_review.json','.tmp/s013_confirm_execution.py',
        'research/S013/experiments/EX058_20261011/src/common.py',
        ORACLE.relative_to(ROOT).as_posix(),
        (OLD80 / 'src/reproduction/02c394b35938_s013_confirm_execution_v3.py').relative_to(ROOT).as_posix(),
        (OLD80 / 'src/reproduction/f78efbb0b1da_audit_driver.py').relative_to(ROOT).as_posix(),
        *[(OLD80 / 'src/adapter_revision2/strategy_runtime/strategies' / name).relative_to(ROOT).as_posix() for name in ('confirm_kernel.py','confirm_net.py')],
        'research/S013/experiments/EX066_20261011/src/opportunity_statistics.py',
        *[(HELPERS / (name + '.py')).relative_to(ROOT).as_posix() for name in ('economics_reference','account_reference','execution_links')]]
    baseline_ref = g.read(ROOT / 'research/S013/experiments/EX071_20261011/protocols/plan.json')['native_ref']
    oracle_source = ORACLE.read_text('utf-8')
    oracle_functions = {node.name: sha256(ast.get_source_segment(oracle_source, node).encode('utf-8')).hexdigest()
        for node in ast.parse(oracle_source).body if isinstance(node, ast.FunctionDef) and node.name in ('original14','net_labels')}
    return {'question': '原14信息按固定浅树表达局部条件净机会，并按原完整执行兑现，中心能否通过新版四门？',
        'basis': '连续加法表达可能遗漏多条件交互；固定depth2/minleaf40浅树只改变表达，不增加市场信息，也不搜索深度或阈值。',
        'strongest_counter': 'EX080真实净年化仅约2.45%，EX086局部收益改善没有转成净机会；greedy树小样本分裂易过拟合，严格根改进还不能发现对称XOR。',
        'role_of_component': '原14年度成熟训练、ECDF、训练叶净收益均值的完整0/1做多策略原型；不沿C8880价格门。',
        'label': 'O[T+1+H]/O[T+1]*(.999/1.001)-1；只用已经观察且年首前成熟的标签；实际经济门看连续完整账户。',
        'horizon': 'holding_sessions4中心，原1..60全域；年度扩展2020起训练，2021..26可预测；2019只暖特征，2020不入场。',
        'training_support': 'train_n >= max(40,minimum_leaf); minleaf20 never lowers the basic40 mature training requirement',
        'controls': 'EX079原14及净ridge预测公开引用作为元数据对照，不新拟合ridge；C8880只作原执行/费用/完整经济控制，不做OFF父等价。',
        'availability': '当前完整原14价量可得；训练signal过去年度且label_end严格早于年首T；未来当前标签未知仍预测，无未来test数量门。最终BH年标签仅事后验收。',
        'price_basis': '原510500HFQ2019-12-31固定锚0.2803、不叠加现金分红、100万元、整手100、单侧10bp、固定1% LimitBuyHold。',
        'limitations': '同开发池、无新独立信息；阈值候选固定node内orderstat .25/.5/.75，严格SSE改善及固定tie顺序；合成交互不证明真实Alpha。',
        'payload': payload, 'candidate_id': CANDIDATE,
        'parameter_geometry': {'coordinates':coordinates,'protocol':{'radius':.05,'point_count':32,'seed':13,
            'random_generator':'PCG64','integer_rounding':'HALF_EVEN','quantile_method':'LINEAR','distance_tolerance':1e-10,'max_attempts':100000},
            'feasibility':'All four integer coordinates keep full predeclared domains; no unused ridge_alpha',
            'new_numeric_coordinates':['tree_depth','minimum_leaf'],'fixed_structure':{'mechanism':MECHANISM},
            'not_done_before_centre':'No perturbation accounts; centre pass requires separately frozen sameEX32 and independentfee plan'},
        'new_goal':'MANDATE/7; centre and all32 pass new4, pooled positiveBHyear actual exit frequency; annualBHsign ex-post only',
        'stop_or_followup':'Any centre v2 gate failure stops fixed policy, no rescue/search. Centre pass requires frozen sameEX32/fee, never declares robust achieved.',
        'resources':{'maximum_native_centres':1,'new_accounts':1,'provider_calls':0,'automatic_repeat':False},
        'input_references':{'baseline_native.json':baseline_ref,'original14_features.csv':old['input_references']['features.csv'],
                            'original14_net_ridge.json':old['input_references']['net_statistics.json']},
        'native_cache_sha256':old['native_cache_sha256'],
        'original14_and_label_oracle':{'source':ORACLE.relative_to(ROOT).as_posix(),'sha256':g.digest(ORACLE),
            'functions':oracle_functions,'net_labels_original_horizon':4,'noncentre_H':'independent scalar p+1+H; no domain narrowing'},
        'source_files':{name:g.digest(ROOT / name) for name in source_files},'objective_achieved':False}


def candidate(exp, plan):
    return StrategyCandidate('S013', CANDIDATE, plan['payload'], exp.resolve(ROOT) / 'src/cart_net/strategy_runtime')


def local_runtime(source):
    """Private namespace, exact installed public SRT inheritance, no shadowing."""
    prefix = '_s013_cart_preaccount'
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + '.'):
            del sys.modules[name]
    for name, directory in ((prefix,source),(prefix+'.strategies',source/'strategies')):
        module=types.ModuleType(name)
        module.__path__=[str(directory)]
        sys.modules[name]=module
    return importlib.import_module(prefix+'.strategies.cart_net')


def independent_policy(scores, feature, traces, inputs, holding):
    """Independent scalar target/age loop; TIME exit wins, no sameT reentry."""
    axis = scores.index
    entry, rows = None, []
    for i, (day, q) in enumerate(scores.cart_net.items()):
        age = None if entry is None else i-entry
        reason='flat'
        if entry is not None:
            if age >= holding:
                entry=None
                reason='expiry'
            else:
                reason='hold'
        elif day.year>2020 and np.isfinite(q) and q>0:
            entry=i
            age=0
            reason='entry'
        rows.append((float(entry is not None),reason,age,entry,bool(np.isfinite(q) and q>0)))
    history=pd.DataFrame(rows,index=axis.rename('signal_date'),columns=['target_position','signal_reason','policy_age','episode_entry_position','positive_forecast'])
    yearly={row['year']:row for row in traces}
    history['net_forecast']=scores.cart_net
    history['common14_available']=feature.notna().all(axis=1)
    history['confirmation_score']=feature.confirmation_score
    history['train_n']=[yearly.get(t.year,{}).get('train_n',0) for t in axis]
    history['train_max_maturity']=[yearly.get(t.year,{}).get('max_maturity') for t in axis]
    daily=pd.DataFrame(inputs['daily'],copy=False).set_index('Date')
    daily.index=pd.to_datetime(daily.index).as_unit('ns')
    history['close']=daily.Close.reindex(axis)
    return history


def independent_labels(prices, axis, holding, oracle):
    if holding == 4:
        return oracle.net_labels(prices,axis)
    # Distinct scalar reconstruction for original H1..60 effective coordinate.
    locations={t:i for i,t in enumerate(prices.index)}
    rows=[]
    for t in axis:
        i=locations[t]
        end=i+1+holding
        rows.append((float(prices.Open.iloc[end])/float(prices.Open.iloc[i+1])*(.999/1.001)-1,prices.index[end])
                    if end<len(prices) else (np.nan,pd.NaT))
    return pd.DataFrame(rows,index=axis,columns=['return_4','label_end_return_4'])


def compare_history(actual, expected):
    """Compare every expected field, preserving missingness and strict numbers."""
    if not actual.index.equals(expected.index) or any(name not in actual for name in expected):
        raise ValueError('Full policy axis or fields differ')
    for name in expected:
        wanted, supplied = expected[name], actual[name]
        if not wanted.isna().equals(supplied.isna()):
            raise ValueError('Policy missingness differs: ' + name)
        good = wanted.notna()
        if pd.api.types.is_numeric_dtype(wanted.dtype):
            left = pd.to_numeric(supplied[good], errors='raise').to_numpy(float)
            right = wanted[good].to_numpy(float)
            if not np.array_equal(left, right):
                raise ValueError('Policy numeric field differs: ' + name)
        elif supplied[good].tolist() != wanted[good].tolist():
            raise ValueError('Policy categorical field differs: ' + name)


def native(plan, common):
    cache = ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'
    if g.digest(cache) != plan['native_cache_sha256']:
        raise ValueError('Original native cache drift')
    pair, reference = g.base.native(common)
    if reference != plan['input_references']['baseline_native.json']:
        raise ValueError('Baseline public reference drift')
    return pair, reference


def frame(reference):
    value = pd.read_csv(g.public(reference), index_col='signal_date', float_precision='round_trip')
    value.index = pd.to_datetime(value.index).as_unit('ns')
    return value


def declare():
    plan = definition()
    checked = g.read(WORK / 'checks.json')
    checks = {**checked, 'real_inputs': checked['real_inputs_read']}
    exp, plan, refs = g.allocate(96, title='原14固定浅树净机会的完整原生中心', question=plan['question'], plan=plan, checks=checks)
    OUT.mkdir(parents=True, exist_ok=True)
    g.write(OUT / 'declaration.json', {'experiment': exp.to_dict(), 'candidate_id': CANDIDATE, 'quota_slot': 8, 'new_accounts': 0})
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'stage': 'DECLARED', 'new_accounts': 0}, flush=True)


def prepare():
    exp,path,plan,refs=g.stage(96)
    g.write(OUT/'prepare_attempt.json',{'status':'STARTED','new_accounts':0,'automatic_repeat':False})
    c=g.base.common()
    (old,baseline),baseline_ref=native(plan,c)
    ctx=c.context(1)
    strategy=candidate(exp,plan)
    request=replace(old,experiment_id=exp.experiment_id,strategy=strategy,
        runtime_binding={'candidate_id':strategy.reference_id,'source_files':list(strategy.payload['runtime']['source_files']),
                         'implementation_sha256':strategy.payload['runtime']['source_sha256']},input_bindings={},lineage=None)
    bound=ctx.evaluation.prepare(request)
    if bound.execution_data.fingerprint!=old.execution_data.fingerprint or bound.benchmark.to_dict()!=old.benchmark.to_dict() or bound.execution_data.pricing.to_dict()!=old.execution_data.pricing.to_dict():
        raise ValueError('Original execution/pricing/benchmark contract changed')
    binding,original=bound.input_bindings['full'],old.input_bindings['full']
    if set(binding.plan.requests)!=set(original.plan.requests)|{'intraday'}:
        raise ValueError('Only original execution30m promotion is permitted')
    for name in ('daily','execution','calendar'):
        if binding.plan.requests[name]!=original.plan.requests[name]:
            raise ValueError('Original exact runtime request changed: '+name)
    if binding.plan.requests['intraday']!=old.execution_data.requests['execution_30m']:
        raise ValueError('Promoted existing execution30m request differs')
    inputs,identities={},{}
    for name,query in binding.plan.requests.items():
        fetched=ctx.data.fetch(query,prepared=binding.prepared)
        if not fetched.ready:
            raise ValueError('Exact existing prepared input unavailable: '+name)
        inputs[name]=fetched.dataframe
        identities[name]=fetched.identity.content_sha256
    if c.SOURCE_CALLS:
        raise ValueError('Provider access prohibited')
    axis=pd.DatetimeIndex(pd.to_datetime(tuple(binding.plan.signal_dates.values()))).as_unit('ns')
    if len(axis)!=1636 or axis[0]!=pd.Timestamp('2019-12-31') or axis[-1]!=pd.Timestamp('2026-09-29'):
        raise ValueError('Original1636 signal prefix required')
    identity=ctx.runtime.identify(strategy,dependencies=bound.dependencies)
    adapter=local_runtime(strategy.source_root)
    p=deepcopy(plan['payload']['parameters'])
    feature,price=adapter.model_inputs(inputs,axis,p)
    history,labels,scores,traces=adapter.history_from_model(feature,price,axis,p)
    from strategy_runtime import ParameterSet
    actual=adapter.CartNet(ParameterSet(p)).calculate_history(inputs,axis)
    history['close']=actual.close
    compare_history(actual,history)
    rename={'open':'Open','high':'High','low':'Low','close':'Close','vol':'Volume','amount':'Amount'}
    native_prices=bound.execution_data.execution_daily.set_index('dt').rename(columns=rename)
    native_prices.index=pd.to_datetime(native_prices.index).as_unit('ns')
    native_prices=native_prices.loc[native_prices.index<=axis[-1]]
    np.testing.assert_allclose(price[['Open','Close']],native_prices[['Open','Close']],atol=2e-12,rtol=2e-11)
    bars=bound.execution_data.execution_intraday.set_index('dt').rename(columns=rename)
    bars.index=pd.to_datetime(bars.index).as_unit('ns')
    bars=bars.loc[bars.index.normalize()<=axis[-1]]
    daily=pd.DataFrame(inputs['daily'],copy=False).set_index('Date')
    daily.index=pd.to_datetime(daily.index).as_unit('ns')
    oracle=g.base.load('cart_original14_independent',ORACLE)
    expected=oracle.original14(daily,native_prices,bars,axis,p['confirmation_lookback'])
    np.testing.assert_allclose(feature.to_numpy(),expected.to_numpy(),atol=2e-12,rtol=2e-11,equal_nan=True)
    expected_labels=independent_labels(native_prices,axis,p['holding_sessions'],oracle)
    np.testing.assert_allclose(labels.return_4,expected_labels.return_4,atol=2e-13,rtol=2e-11,equal_nan=True)
    pd.testing.assert_series_equal(labels.label_end_return_4,expected_labels.label_end_return_4,check_exact=True)
    auditor=g.base.load('cart_independent_preaccount',path/'src/cart_net/audit_tree.py')
    independent=auditor.verify(feature,labels,scores,traces,max_depth=p['tree_depth'],minimum_leaf=p['minimum_leaf'])
    compare_history(history,independent_policy(scores,feature,traces,inputs,p['holding_sessions']))
    if independent['status']!='PASS':
        raise ValueError('Independent all-node causal preaccount proof required')
    independent={**independent,'original14_source_reconstruction':'PASS','observed_open_labels':'PASS',
        'complete_policy_state':'EXACT','native_pricing_match':'PASS','oracle_sha256':g.digest(ORACLE),'maximum_observation':axis[-1].isoformat()}
    for name,table in (('policy.csv',history),('features.csv',feature),('labels.csv',labels),('scores.csv',scores)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            table.to_csv(stream,index_label='signal_date',float_format='%.17g')
    g.write(OUT/'fit.json',traces)
    g.write(OUT/'independent_preaccount.json',independent)
    c.cache_write(OUT/'prepared.pkl.gz',bound)
    proof={'status':'PASS','new_accounts':0,'all_nodes_and_positive_flags':'PASS','original14_rebuilt':'PASS',
        'original_requests_exact':True,'existing_execution30m_promoted':True,
        'input_bindings':{key:value.to_dict() for key,value in bound.input_bindings.items()},'input_identities':identities,
        'execution_fingerprint':bound.execution_data.fingerprint,'content_sha256':identity.content_sha256,
        'prepared_cache_sha256':g.digest(OUT/'prepared.pkl.gz'),'signal_sessions':1636,'provider_calls':0,
        'baseline_reference':baseline_ref,'no_OFF_parent_equivalence':True}
    g.write(OUT/'prepare.json',proof)
    prepared_refs={name:g.put(ctx,exp,OUT/name) for name in ('prepare.json','policy.csv','features.csv','labels.csv','scores.csv','fit.json','independent_preaccount.json')}
    g.write(path/'protocols/prepare_references.json',prepared_refs)
    if c.SOURCE_CALLS:
        raise ValueError('Provider access prohibited')
    print({'experiment':exp.experiment_id,'stage':'PREPARED','preaccount':'PASS','new_accounts':0},flush=True)


def prepared(exp, path, plan):
    references = g.read(path / 'protocols/prepare_references.json')
    proof = g.read(g.public(references['prepare.json']))
    independent = g.read(g.public(references['independent_preaccount.json']))
    if proof['status'] != 'PASS' or independent['status'] != 'PASS' or g.digest(OUT / 'prepared.pkl.gz') != proof['prepared_cache_sha256']:
        raise ValueError('Authenticated immutable preaccount preparation required')
    c = g.base.common()
    bound = c.cache_read(OUT / 'prepared.pkl.gz')
    if canonical_sha256(bound.strategy.payload) != canonical_sha256(plan['payload']) or bound.strategy.candidate_id != CANDIDATE or bound.experiment_id != exp.experiment_id:
        raise ValueError('Prepared candidate/request differs from frozen plan')
    if {key: value.to_dict() for key, value in bound.input_bindings.items()} != proof['input_bindings']:
        raise ValueError('Prepared input binding drift')
    history = frame(references['policy.csv'])
    return c, bound, proof, independent, history


def execute():
    exp, path, plan, refs = g.stage(96)
    c, bound, proof, independent, history = prepared(exp, path, plan)
    g.write(OUT / 'execute_attempt.json', {'status': 'STARTED', 'maximum_accounts': 1, 'automatic_repeat': False})
    ctx = c.context(1)
    result = ctx.evaluation.evaluate(bound)
    c.cache_write(OUT / 'account.pkl.gz', (bound, result))
    reference = publish_evidence(ctx, EvaluationEvidenceWrite(exp, 'cart-net-fixed-centre-native', bound, result)).to_dict()
    if g.read(g.public(reference)) != serialize_evaluation_evidence(bound, result) or c.SOURCE_CALLS:
        raise ValueError('Complete public native mismatch or forbidden provider access')
    receipt = {'status': 'COMPLETE', 'new_accounts': 1, 'native_ref': reference, 'cache_sha256': g.digest(OUT / 'account.pkl.gz'),
               'request_hash': result.request_hash, 'result_hash': result.result_hash}
    g.write(OUT / 'execution.json', receipt)
    g.write(path / 'protocols/centre_reference.json', reference)
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'stage': 'COMPLETE', 'new_accounts': 1}, flush=True)


def audit():
    exp, path, plan, refs = g.stage(96)
    c, prepared_bound, proof, independent, history = prepared(exp, path, plan)
    receipt = g.read(OUT / 'execution.json')
    if receipt['status'] != 'COMPLETE' or receipt['new_accounts'] != 1 or g.digest(OUT / 'account.pkl.gz') != receipt['cache_sha256']:
        raise ValueError('One authenticated complete account required')
    bound, result = c.cache_read(OUT / 'account.pkl.gz')
    formal = g.read(g.public(receipt['native_ref']))
    validate_evaluation_evidence(formal)
    if serialize_evaluation_evidence(bound, result) != formal or bound.strategy.payload != prepared_bound.strategy.payload or bound.runtime_binding != prepared_bound.runtime_binding:
        raise ValueError('Prepared request/full public native differs')
    if {key: value.to_dict() for key, value in bound.input_bindings.items()} != proof['input_bindings']:
        raise ValueError('Native complete input bindings differ from preparation')
    ctx = c.context(1)
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    if identity.content_sha256 != proof['content_sha256'] or identity.content_sha256 != result.runs[0].identity.content_sha256 or result.data_identity != bound.execution_data.fingerprint or result.runtime_binding_hash != canonical_sha256(bound.runtime_binding):
        raise ValueError('Native runtime/data/payload identity differs')
    if len(result.runs) != 1 or bound.execution_mode != 'FULL' or bound.initial_cash != 1_000_000:
        raise ValueError('One full unlevered original-capital account required')
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit('ns')
    compare_history(decisions, history)
    helpers = {name: g.base.load('cart_' + name, HELPERS / (name + '.py')) for name in ('economics_reference', 'account_reference', 'execution_links')}
    facts = build_assessment_evidence(bound, result)
    economics = helpers['economics_reference'].economics(facts[0])
    cash_account = helpers['account_reference'].verify_account(bound, result)
    links = helpers['execution_links'].verify(bound, result)
    for year, values in economics['annual'].items():
        if abs(values['return'] - cash_account['annual'][year]['net_return']) > 1e-12 or abs(values['drawdown'] - cash_account['annual'][year]['drawdown_magnitude']) > 1e-12:
            raise ValueError('Independent continuous annual accounting mismatch')
    account = result.runs[0].execution.account_daily
    if not np.isfinite(account.equity).all() or (account.quantity < 0).any() or (account.cash < -1e-6).any():
        raise ValueError('Finite cash-only long/no leverage required')
    (old, old_result), baseline_ref = native(plan, c)
    if bound.execution_data.fingerprint != old.execution_data.fingerprint or bound.benchmark.to_dict() != old.benchmark.to_dict() or bound.execution_data.pricing.to_dict() != old.execution_data.pricing.to_dict():
        raise ValueError('Original data/benchmark/price contract changed')
    baseline = helpers['economics_reference'].economics(build_assessment_evidence(old, old_result)[0])
    gates = g.base.load('cart_current_gates', ROOT / '.tmp/s013-new-goal/gates_v2.py')
    review, baseline_review = gates.from_economics(economics), gates.from_economics(baseline)
    protocol = SelfCheckProtocol(version='S013-EX062-three-ledger-checks-missing32-fee-v1', baseline_window='full',
        standard_scenario='baseline', stress_scenario='stress_20bp_per_side', rolling_window_days=126, rolling_step_days=21,
        quantile_method=QuantileMethod.LINEAR, minimum_perturbations=32, minimum_rolling_windows=20,
        bootstrap_repetitions=2000, bootstrap_block_length=20, seed=13, reconciliation_tolerance=1e-6, pbo_blocks=10)
    partial = assess_candidates(CandidateAssessmentRequest((facts[0].candidate,), protocol, (), facts)).to_dict()
    report = {'status': 'PASS', 'new_accounts': 1, 'technical_financial_repeats': 0,
        'independent_signal': independent, 'native_policy_and_metadata': 'EXACT', 'economics': economics,
        'gates_v2': {**asdict(review), 'qualified': review.qualified}, 'old_all_pool_gate_is_diagnostic_only': True,
        'cash_account': cash_account, 'orders_first_touch': links, 'baseline_economics': baseline,
        'baseline_gates_v2': {**asdict(baseline_review), 'qualified': baseline_review.qualified}, 'baseline_reference': baseline_ref,
        'three_ledger_checks': partial, 'full_five_checks_complete': False,
        'parameter32': {'status': 'NOT_RUN', 'Q10': None, 'Q90': None, 'individual_gate_rates': None, 'joint_gate_rate': None},
        'independent_double_fee': {'status': 'NOT_RUN'}, 'pbo': {'status': 'UNAVAILABLE', 'required_blocks': 10, 'reason': 'Complete search-family returns absent'},
        'qualified': review.qualified, 'provider_calls': 0, 'centre_reference': receipt['native_ref'],
        'stop': 'CENTRE_FAILED_STOP_32_FEE_NEIGHBORS' if not review.qualified else 'CENTRE_PASS_FROZEN_SAME_EX_32_FEE_REQUIRED',
        'objective_achieved': False}
    if c.SOURCE_CALLS:
        raise ValueError('Provider access prohibited')
    g.write(OUT / 'verification.json', report)
    published = {name: g.put(ctx, exp, file) for name, file in {'verification.json': OUT / 'verification.json', 'audit_driver.py': Path(__file__)}.items()}
    g.write(path / 'protocols/audit_references.json', published)
    print({'experiment': exp.experiment_id, 'status': 'PASS', 'new_gates': review.gates, 'stop': report['stop']}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'prepare': prepare, 'execute': execute, 'audit': audit}[sys.argv[1]]()
