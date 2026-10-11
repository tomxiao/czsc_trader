"""Independent causal reconstruction and native cash/account checks; no evaluation."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from strategy_runtime import canonical_sha256
from strategy_evaluator import CandidateAssessmentRequest, SelfCheckProtocol, QuantileMethod, assess_candidates
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution_v3 as d


def proof_bindings(bound):
    return {k: v.to_dict() for k, v in bound.input_bindings.items()}


def precheck(reuse=False):
    exp, path, plan = d.stage()
    c = d.common()
    bound = c.cache_read(d.OUT / 'prepared.pkl.gz')
    proof = d.read(d.public(d.read(path / 'protocols/prepare_references_v2.json')['prepare.json']))
    if d.digest(d.OUT / 'prepared.pkl.gz') != proof['prepared_cache_sha256']:
        raise ValueError('Prepared cache authentication')
    ctx = c.context(1)
    refs = d.read(path / 'protocols/prepare_references_v2.json')
    features = d.frame(refs['features.csv'])
    scores = d.frame(refs['scores.csv']).iloc[:, 0]
    history = d.frame(refs['policy.csv'])
    fit = d.read(d.public(refs['fit.json']))
    if reuse:
        independent = d.read(d.public(d.read(path / 'protocols/independent_preaccount_reference_v2.json')))
        if independent['status'] != 'PASS' or independent['signals'] != len(features):
            raise ValueError('Same frozen preaccount independent proof required')
    else:
        binding = bound.input_bindings['full']
        got = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
        if not got.ready or got.identity.content_sha256 != proof['input_identities']['daily']:
            raise ValueError('Authenticated original daily input required')
        daily = pd.DataFrame(got.dataframe, copy=False).set_index('Date')
        daily.index = pd.to_datetime(daily.index).as_unit('ns')
        rename = {'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'vol': 'Volume', 'amount': 'Amount'}
        prices = bound.execution_data.execution_daily.set_index('dt').rename(columns=rename)
        prices.index = pd.to_datetime(prices.index).as_unit('ns')
        bars = bound.execution_data.execution_intraday.set_index('dt').rename(columns=rename)
        bars.index = pd.to_datetime(bars.index).as_unit('ns')
        oracle = d.load('confirm_independent_oracle', ROOT / '.tmp/s013-confirm-net-execution-audit/audit.py')
        independent = oracle.verify(daily, prices, bars, features.index, features, scores, fit, history)
    if c.SOURCE_CALLS:
        raise ValueError('No provider')
    return exp, path, plan, c, ctx, bound, features, scores, fit, history, independent


def run():
    exp, path, plan, c, ctx, bound, features, scores, fit, history, independent = precheck(reuse=sys.argv[1] == 'verify')
    if sys.argv[1] == 'precheck':
        d.write(d.OUT / 'independent_preaccount.json', independent)
        ref = d.put(ctx, exp, d.OUT / 'independent_preaccount.json')
        d.write(path / 'protocols/independent_preaccount_reference_v2.json', ref)
        print(independent, flush=True)
        return
    receipt = d.read(d.OUT / 'execution.json')
    if d.digest(d.OUT / 'account.pkl.gz') != receipt['cache_sha256']:
        raise ValueError('Account cache authentication')
    actual_bound, result = c.cache_read(d.OUT / 'account.pkl.gz')
    formal = d.read(d.public(receipt['native_ref']))
    validate_evaluation_evidence(formal)
    if (actual_bound.strategy.payload != bound.strategy.payload
            or actual_bound.runtime_binding != bound.runtime_binding
            or {k: v.to_dict() for k, v in actual_bound.input_bindings.items()} != proof_bindings(bound)
            or serialize_evaluation_evidence(actual_bound, result) != formal):
        raise ValueError('Prepared/request/public full native differs')
    identity = ctx.runtime.identify(actual_bound.strategy, dependencies=actual_bound.dependencies)
    if (identity.content_sha256 != plan['content_sha256'] or identity.content_sha256 != result.runs[0].identity.content_sha256
            or result.data_identity != actual_bound.execution_data.fingerprint
            or result.runtime_binding_hash != canonical_sha256(actual_bound.runtime_binding)):
        raise ValueError('Runtime/data identity')
    if len(result.runs) != 1 or actual_bound.execution_mode != 'FULL' or actual_bound.initial_cash != 1_000_000:
        raise ValueError('One original full account')
    decisions = result.runs[0].execution.decisions.copy()
    axis = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit('ns')
    if not axis.equals(features.index):
        raise ValueError('Actual full native signal prefix differs')
    decisions.index = axis
    for name in history:
        if name in ('signal_reason', 'positive_forecast'):
            np.testing.assert_array_equal(decisions[name], history[name])
        else:
            actual = pd.to_numeric(decisions[name], errors='raise').to_numpy(float) if name in decisions else np.full(len(axis), np.nan)
            np.testing.assert_allclose(actual, history[name].to_numpy(float), atol=2e-12, rtol=2e-10, equal_nan=True)
    np.testing.assert_array_equal(decisions.common14_available, features.notna().all(axis=1))
    np.testing.assert_allclose(pd.to_numeric(decisions.confirmation_score), features.confirmation_score, atol=2e-11, rtol=2e-10, equal_nan=True)
    expected_train = [fit.get(str(t.year), {}).get('train_n', 0) for t in axis]
    np.testing.assert_array_equal(decisions.train_n, expected_train)
    helpers = {name: d.load('confirm_' + name, ROOT / 'research/S013/experiments/EX074_20261011/src' / (name + '.py'))
               for name in ('economics_reference', 'account_reference', 'execution_links')}
    facts = build_assessment_evidence(actual_bound, result)
    economics = helpers['economics_reference'].economics(facts[0])
    account = helpers['account_reference'].verify_account(actual_bound, result)
    links = helpers['execution_links'].verify(actual_bound, result)
    for year, row in account['annual'].items():
        if abs(row['net_return'] - economics['annual'][year]['return']) > 1e-12:
            raise ValueError('Independent annual accounting mismatch')
    acc = result.runs[0].execution.account_daily
    if (not np.isfinite(acc.equity).all() or (acc.quantity < 0).any() or (acc.cash < -1e-6).any()):
        raise ValueError('Long only finite unlevered cash account required')
    (old, old_result), baseline_ref = d.native(c)
    baseline = helpers['economics_reference'].economics(build_assessment_evidence(old, old_result)[0])
    protocol = SelfCheckProtocol(
        version='S013-EX062-three-ledger-checks-missing32-fee-v1', baseline_window='full',
        standard_scenario='baseline', stress_scenario='stress_20bp_per_side',
        rolling_window_days=126, rolling_step_days=21, quantile_method=QuantileMethod.LINEAR,
        minimum_perturbations=32, minimum_rolling_windows=20, bootstrap_repetitions=2000,
        bootstrap_block_length=20, seed=13, reconciliation_tolerance=1e-6, pbo_blocks=10,
    )
    partial = assess_candidates(CandidateAssessmentRequest((facts[0].candidate,), protocol, (), facts)).to_dict()
    if (actual_bound.execution_data.fingerprint != old.execution_data.fingerprint
            or actual_bound.benchmark.to_dict() != old.benchmark.to_dict()
            or actual_bound.execution_data.pricing.to_dict() != old.execution_data.pricing.to_dict()):
        raise ValueError('Original execution/benchmark/pricing changed')
    report = {'status': 'PASS', 'new_accounts': 1, 'technical_financial_repeats': 0,
              'independent_signal': independent, 'native_policy_and_metadata': 'EXACT',
              'economics': economics, 'cash_account': account, 'orders_first_touch': links,
              'baseline_economics': baseline, 'baseline_reference': baseline_ref,
              'three_ledger_checks': partial, 'full_five_checks_complete': False,
              'qualified': economics['qualified'], 'provider_calls': len(c.SOURCE_CALLS),
              'centre_reference': receipt['native_ref'],
              'stop': 'CENTRE_FAILED_STOP_32_FEE_NEIGHBORS' if not economics['qualified'] else 'CENTRE_PASS_FUTURE_32_FEE_REQUIRED'}
    d.write(d.OUT / 'verification.json', report)
    refs = {name: d.put(ctx, exp, p) for name, p in {
        'verification.json': d.OUT / 'verification.json', 'audit_driver.py': Path(__file__),
    }.items()}
    d.write(path / 'protocols/audit_references.json', refs)
    print({'status': 'PASS', 'economics': economics, 'stop': report['stop']}, flush=True)


if __name__ == '__main__':
    run()
