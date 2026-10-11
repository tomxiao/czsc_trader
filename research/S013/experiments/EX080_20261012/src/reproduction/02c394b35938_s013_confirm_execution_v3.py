"""EX080 fixed native centre: declare, exact preparation, one full account."""
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate, implementation_sha256
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-confirm-net-execution'
OUT = ROOT / '.tmp/s013-confirm-net-execution-result/revision2'
CANDIDATE = 'C9080'


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def common():
    # Historical pickle retains this module name; authenticate its frozen source.
    return load('common', ROOT / 'research/S013/experiments/EX058_20261011/src/common.py')


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S013':
        raise ValueError('S013 only')
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Public SHA mismatch')
    return path


def put(ctx, exp, path):
    path = Path(path)
    media = {'.py': 'text/x-python', '.csv': 'text/csv', '.md': 'text/markdown'}.get(path.suffix, 'application/json')
    return publish_evidence(ctx, MaterialEvidenceWrite(exp, 'confirm-net-' + path.stem.replace('_', '-'), path.read_bytes(), media, path.suffix[1:])).to_dict()


def native(c):
    pair = c.cache_read(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz')
    ref = read(ROOT / 'research/S013/experiments/EX071_20261011/protocols/plan.json')['native_ref']
    if pair[0].strategy.candidate_id != 'C8880' or serialize_evaluation_evidence(*pair) != read(public(ref)):
        raise ValueError('Original full native mismatch')
    return pair, ref


def check(plan):
    for name, expected in plan['source_files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen source drift: ' + name)
    if digest(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz') != plan['native_cache_sha256']:
        raise ValueError('Original cache drift')
    for ref in plan['input_references'].values():
        public(ref)


def stage():
    exp = ExperimentRef.from_dict(read(OUT / 'experiment.json'))
    path = exp.resolve(ROOT)
    plan = read(path / 'protocols/plan_v2.json')
    refs = read(path / 'protocols/method_references_v2.json')
    if read(public(refs['plan.json'])) != plan:
        raise ValueError('Prospective binding drift')
    check(plan)
    return exp, path, plan


def candidate(exp, plan):
    return StrategyCandidate('S013', CANDIDATE, plan['payload'], exp.resolve(ROOT) / 'src/adapter_revision2/strategy_runtime')


def declare():
    prospective = read(WORK / 'prospective.json')
    check(prospective)
    if read(WORK / 'focused_checks.json')['status'] != 'PASS':
        raise ValueError('Synthetic checks required')
    if any(p.exists() for p in (ROOT / 'research/S013/assets/candidates' / CANDIDATE, ROOT / 'research/registrations/S013/candidates' / (CANDIDATE + '.json'))):
        raise ValueError('Candidate occupied')
    c = common()
    (old, _), baseline = native(c)
    ctx = c.context(1)
    exp = create_experiment(ctx, ExperimentRequest('确认净机会的原执行兑现', '固定年度确认净预测与四日时钟，在原1%限价、费用和非重叠资金下是否仍能满足原四门？', date(2026, 10, 12)))
    if exp.experiment_id != 'EX080_20261012':
        raise ValueError('Budget slot2 allocation differs; never allocate again')
    write(OUT / 'experiment.json', exp.to_dict())
    source = exp.resolve(ROOT) / 'src/adapter_revision2/strategy_runtime'
    for name in ('confirm_kernel.py', 'confirm_net.py'):
        target = source / 'strategies' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((WORK / name).read_bytes())
    files = ['strategies/confirm_kernel.py', 'strategies/confirm_net.py']
    payload = {'parameters': {'confirmation_lookback': 120, 'holding_sessions': 4, 'ridge_alpha': 10.0}, 'runtime': {'contract_version': 1, 'module': 'strategy_runtime.strategies.confirm_net', 'qualname': 'ConfirmNet', 'source_files': files, 'source_sha256': implementation_sha256(files, source_root=source)}}
    identity = ctx.runtime.identify(StrategyCandidate('S013', CANDIDATE, payload, source), dependencies=old.dependencies)
    plan = {**prospective, 'experiment': exp.to_dict(), 'payload': payload, 'content_sha256': identity.content_sha256, 'declared_utc': datetime.now(timezone.utc).isoformat(), 'baseline_native': baseline, 'baseline_execution_fingerprint': old.execution_data.fingerprint, 'benchmark': old.benchmark.to_dict(), 'pricing': old.execution_data.pricing.to_dict()}
    write(exp.resolve(ROOT) / 'protocols/plan.json', plan)
    refs = {'plan.json': put(ctx, exp, exp.resolve(ROOT) / 'protocols/plan.json')}
    for name in plan['source_files']:
        refs[name] = put(ctx, exp, ROOT / name)
    for name in ('focused_checks.json', 'scientific_plan.json', 'original_binding_metadata.json'):
        refs[name] = put(ctx, exp, WORK / name)
    write(exp.resolve(ROOT) / 'protocols/method_references.json', refs)
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'quota_started': 2, 'completed': 1}, flush=True)


def frame(ref):
    value = pd.read_csv(public(ref), index_col='signal_date', float_precision='round_trip')
    value.index = pd.to_datetime(value.index).as_unit('ns')
    return value


def prepare():
    exp, path, plan = stage()
    write(OUT / 'prepare_attempt_v2.json', {'status': 'STARTED', 'accounts': 0})
    c = common()
    (old, _), _ = native(c)
    ctx = c.context(1)
    strategy = candidate(exp, plan)
    request = replace(old, experiment_id=exp.experiment_id, strategy=strategy, runtime_binding={'candidate_id': strategy.reference_id, 'source_files': list(strategy.payload['runtime']['source_files']), 'implementation_sha256': strategy.payload['runtime']['source_sha256']}, input_bindings={}, lineage=None)
    bound = ctx.evaluation.prepare(request)
    if bound.execution_data.fingerprint != old.execution_data.fingerprint or bound.benchmark.to_dict() != old.benchmark.to_dict() or bound.execution_data.pricing.to_dict() != old.execution_data.pricing.to_dict():
        raise ValueError('Original execution/pricing/benchmark changed')
    b = bound.input_bindings['full']
    original = old.input_bindings['full']
    for name in ('daily', 'execution', 'calendar'):
        if b.plan.requests[name] != original.plan.requests[name]:
            raise ValueError('Original runtime input request changed: ' + name)
    for name, key in (('intraday', 'execution_30m'),):
        if b.plan.requests[name] != old.execution_data.requests[key]:
            raise ValueError('Promoted native request differs: ' + name)
    inputs = {}
    identities = {}
    for name, req in b.plan.requests.items():
        got = ctx.data.fetch(req, prepared=b.prepared)
        if not got.ready:
            raise ValueError('Exact prepared input unavailable: ' + name)
        inputs[name] = got.dataframe
        identities[name] = got.identity.content_sha256
    if c.SOURCE_CALLS:
        raise ValueError('No provider call allowed')
    signals = pd.DatetimeIndex(pd.to_datetime(tuple(b.plan.signal_dates.values()))).as_unit('ns')
    if len(signals) != 1636 or signals[0] != pd.Timestamp('2019-12-31') or signals[-1] != pd.Timestamp('2026-09-29'):
        raise ValueError('Original full signal prefix changed')
    kernel = load('s013_confirm_preaccount_kernel', path / 'src/adapter_revision2/strategy_runtime/strategies/confirm_kernel.py')
    prices = bound.execution_data.execution_daily.rename(columns={'dt': 'Date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'vol': 'Volume', 'amount': 'Amount'})
    bars = bound.execution_data.execution_intraday.rename(columns={'dt': 'Date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'vol': 'Volume', 'amount': 'Amount'})
    features = kernel.rebuild(inputs['daily'], prices, bars, signals)
    p = prices.set_index('Date')
    p.index = pd.to_datetime(p.index).as_unit('ns')
    scores, fit = kernel.annual_forecasts(features, p, signals)
    history = kernel.episode_history(scores, signals)
    oldfeatures = frame(plan['input_references']['features.csv'])
    if not features.index[1:].equals(oldfeatures.index):
        raise ValueError('Original14 signal axis changed')
    np.testing.assert_allclose(features.iloc[1:].to_numpy(), oldfeatures[list(kernel.FEATURES)].to_numpy(), atol=2e-12, rtol=2e-11, equal_nan=True)
    forecasts = read(public(plan['input_references']['net_statistics.json']))['forecasts']
    prior = np.array([row['scores']['confirmation_only'] if row['scores']['confirmation_only'] is not None else np.nan for row in forecasts])
    np.testing.assert_allclose(scores.iloc[1:].to_numpy(), prior, atol=2e-13, rtol=2e-11, equal_nan=True)
    np.testing.assert_array_equal(scores.iloc[1:].to_numpy() > 0, prior > 0)
    for name, value in {'features.csv': features, 'scores.csv': scores.to_frame(), 'policy.csv': history}.items():
        with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
            value.to_csv(stream, index_label='signal_date', float_format='%.17g')
    write(OUT / 'fit.json', fit)
    c.cache_write(OUT / 'prepared.pkl.gz', bound)
    proof = {'status': 'PASS', 'new_accounts': 0, 'original_forecasts_checked': 1635, 'strict_positive_flags_exact': True, 'original14_checked': True, 'original_requests_exact': True, 'input_bindings': {k: v.to_dict() for k, v in bound.input_bindings.items()}, 'input_identities': identities, 'execution_fingerprint': bound.execution_data.fingerprint, 'prepared_cache_sha256': digest(OUT / 'prepared.pkl.gz'), 'provider_calls': 0}
    write(OUT / 'prepare.json', proof)
    refs = {name: put(ctx, exp, OUT / name) for name in ('prepare.json', 'features.csv', 'scores.csv', 'fit.json', 'policy.csv')}
    write(path / 'protocols/prepare_references_v2.json', refs)
    print({'status': 'PREPARED', 'accounts': 0, 'old_forecasts_equal': 1635}, flush=True)


def execute():
    exp, path, _ = stage()
    proof = read(public(read(path / 'protocols/prepare_references_v2.json')['prepare.json']))
    if proof['status'] != 'PASS' or digest(OUT / 'prepared.pkl.gz') != proof['prepared_cache_sha256']:
        raise ValueError('Authenticated preparation required')
    write(OUT / 'execute_attempt.json', {'status': 'STARTED', 'maximum_accounts': 1, 'automatic_repeat': False})
    c = common()
    ctx = c.context(1)
    bound = c.cache_read(OUT / 'prepared.pkl.gz')
    result = ctx.evaluation.evaluate(bound)
    c.cache_write(OUT / 'account.pkl.gz', (bound, result))
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(exp, 'confirm-net-fixed-centre-native', bound, result)).to_dict()
    if read(public(ref)) != serialize_evaluation_evidence(bound, result) or c.SOURCE_CALLS:
        raise ValueError('Native publication mismatch or provider attempted')
    receipt = {'status': 'COMPLETE', 'new_accounts': 1, 'native_ref': ref, 'cache_sha256': digest(OUT / 'account.pkl.gz'), 'request_hash': result.request_hash, 'result_hash': result.result_hash}
    write(OUT / 'execution.json', receipt)
    write(path / 'protocols/centre_reference.json', ref)
    print({'experiment': exp.experiment_id, 'candidate': CANDIDATE, 'new_accounts': 1, 'status': 'COMPLETE'}, flush=True)


if __name__ == '__main__':
    {'declare': declare, 'prepare': prepare, 'execute': execute}[sys.argv[1]]()
