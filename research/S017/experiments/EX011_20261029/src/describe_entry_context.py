"""Partition original C0036 trades by the existing C0043 SPY20 entry-time fact.

Both accounts are read via public EvidenceRef/SHA/identity authentication. Check
the four primary products, economic contract/window and complete embedded BH
economic path. Authenticate each frozen strategy/definition against pre-run
materials; bind C0043's SPY RAW daily source and 20-session input identity.
C0043 calculates market_last/mean/allowed/observed before applying its portfolio-
dependent target. Review that source and verify fact independence in a small
synthetic held/flat probe. No market download, account replay, public diagnosis,
private checkpoint, new experiment, new threshold or 2026 price access occurs.

Actual C0036 BUY fill -> order -> decision_at must exactly match a C0043 decision
at the same execution/observation boundaries. Missing, duplicate, unavailable or
inconsistent context becomes UNKNOWN, never False or silently dropped. Group
all 555 existing CLOSED cycles by TRUE/FALSE/UNKNOWN and cross with their retained
actual exit-purpose description. Net PnL/net_return are the original trade fields;
fees include both actual entry/exit fills. Every partition reconciles. net_return
quantiles use linear interpolation across actual cycle returns; they are not a
portfolio return and are not added to invent a subgroup account.

This is a conditional description of trades C0036 actually selected under its
own holdings, capital path and available opportunities. A filtered account would
alter those paths and later entries. Deleting one group does NOT estimate the
performance of an entry filter, nor an interaction with crossday holding. Annual
tables are descriptions, never year-based rules. No fee addback or counterfactual
return is produced. SESSION_END remains a recorded branch, not proof that its
last completed close could not also trigger a stop. This evidence only helps
form a bounded question after C0044 returns; it pre-judges no combination.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from strategy_runtime import EquityStrategyDefinition, equity_source_hash

from analyze import load_accounts, ECONOMIC_FIELDS, PRIMARY, economic
from describe_exits import describe as describe_exits, index_unique, equal, at, CATEGORIES, ZONE
from run import ROOT, WORK, EXPERIMENT, read, save


CONTEXT_EXPERIMENT = ExperimentRef('S017', 'EX014_20261029')
CONTEXT_WORK = CONTEXT_EXPERIMENT.resolve(ROOT)
GROUPS = ('TRUE', 'FALSE', 'UNKNOWN')
MARKET_FACTS = ('market_allowed', 'market_last', 'market_mean', 'market_observed')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def bind_source(work, experiment, key, payload):
    pre = read(work/'others/pre_run_evidence.json')
    refs = {}
    for name, relative in (('source', 'src/strategy.py'), ('definitions', 'protocols/definitions.json')):
        ref = EvidenceRef.from_dict(pre[name])
        if ref.experiment != experiment:
            raise ValueError('frozen material belongs to a different experiment')
        content = ref.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != ref.sha256 or content != (work/relative).read_bytes():
            raise ValueError('local frozen source or definition differs from published material')
        refs[name] = ref.to_dict()
    definition = EquityStrategyDefinition.from_dict(read(work/'protocols/definitions.json')[key])
    if (equity_source_hash(work/'src', definition.source_files) != definition.source_sha256
            or definition.content_identity.content_sha256 != payload['request']['content_sha256']):
        raise ValueError('frozen source/definition does not identify the original account')
    return definition, {'materials': refs, 'source_file_sha256': digest(work/'src/strategy.py'),
                        'definition_content_sha256': definition.content_identity.content_sha256}


def verify_market_source(payload, definition):
    if len(definition.auxiliary_inputs) != 1:
        raise ValueError('context source must have exactly its declared SPY input')
    declaration = definition.auxiliary_inputs[0]
    expected = {'name': 'market', 'instrument': {'market': 'US', 'asset_class': 'ETF', 'symbol': 'SPY'},
                'source': {'provider': 'futu', 'revision': 's017-auxiliary-rth-raw-v1-20261029'},
                'frequency': 'daily', 'warmup_bars': 20, 'max_age_seconds': 432000, 'analysis_price': 'RAW'}
    if asdict(declaration) != expected:
        raise ValueError('fixed SPY source contract changed')
    if definition.parameters['context_mode'] != 'MARKET' or definition.parameters['context_sessions'] != 20:
        raise ValueError('only the existing MARKET/20 condition is authorized')
    identities = {}
    for product in ('bars', 'sessions'):
        record = payload['data']['auxiliary:market:'+product]
        metadata = record['metadata']
        if (metadata['instrument'] != expected['instrument'] or metadata['vendor'] != 'futu'
                or metadata['source_revision'] != expected['source']['revision']
                or metadata['coverage_start'] != '2018-11-01' or metadata['coverage_end'] != '2025-12-31'
                or metadata['adjustment'] != 'none'):
            raise ValueError('published auxiliary identity differs from fixed declared source/window')
        identities[product] = record
    spec = importlib.util.spec_from_file_location('authenticated_c0043_context_probe', CONTEXT_WORK/'src/strategy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    primary = pd.DataFrame({'Close': [100.]*261, 'High': [101.]*261, 'Low': [99.]*261})
    market = pd.DataFrame({'Close': [100.+i for i in range(20)],
                           'Date': pd.date_range('2019-01-02', periods=20, tz='UTC')})
    checked = 0
    for last, expected_allowed in ((119., 'True'), (80., 'False')):
        market.loc[market.index[-1], 'Close'] = last
        recorded = []
        for quantity in (0, 1, 100):
            ctx = SimpleNamespace(history=primary.copy(deep=True), portfolio=SimpleNamespace(quantity=quantity),
                parameters=definition.parameters, auxiliary_histories={'market': market.copy(deep=True)})
            decision = module.decide(ctx)
            facts = {item.key: item.text for item in decision.explanation.basis}
            recorded.append({name: facts[name] for name in MARKET_FACTS})
            if facts['market_allowed'] != expected_allowed:
                raise ValueError('synthetic probe did not exercise both fixed market conditions')
            checked += 1
        if recorded[1:] != recorded[:-1]:
            raise ValueError('market condition unexpectedly depends on portfolio holdings')
    return {'declaration': expected, 'published_input_identities': identities,
            'source_review': 'MARKET_FACTS_CALCULATED_FROM_AUXILIARY_BEFORE_HELD_DEPENDENT_TARGET',
            'synthetic_held_flat_fact_probes': checked, 'held_flat_market_facts_identical': True}


def classify_context(origin, matches, max_age):
    if len(matches) != 1:
        return 'UNKNOWN', {}, 'MISSING_OR_DUPLICATE_EXACT_DECISION_TIME'
    context = matches[0]
    if any(at(context[key]) != at(origin[key]) for key in ('execution_start', 'execution_end', 'observed_through')):
        return 'UNKNOWN', {}, 'PRIMARY_EXECUTION_OR_OBSERVATION_BOUNDARY_MISMATCH'
    explanation = context.get('explanation')
    if not isinstance(explanation, dict):
        return 'UNKNOWN', {}, 'MISSING_STRUCTURED_EXPLANATION'
    basis = explanation.get('basis', [])
    facts = {row['key']: row['text'] for row in basis}
    if len(facts) != len(basis) or any(name not in facts for name in MARKET_FACTS):
        return 'UNKNOWN', facts, 'MISSING_OR_DUPLICATE_MARKET_FACTS'
    try:
        latest, mean = float(facts['market_last']), float(facts['market_mean'])
        observed = at(facts['market_observed'])
        age = (at(origin['decision_at'])-observed).total_seconds()
        if (not math.isfinite(latest) or not math.isfinite(mean) or min(latest, mean) <= 0
                or facts['market_allowed'] not in ('True', 'False')
                or (latest > mean) != (facts['market_allowed'] == 'True')
                or facts.get('context_sessions') != '20' or facts.get('context_mode') != 'MARKET'
                or facts.get('gate_role') != 'ENTRY_ONLY' or not 0 <= age <= max_age):
            return 'UNKNOWN', facts, 'INCONSISTENT_OR_NOT_CAUSALLY_AVAILABLE_MARKET_FACT'
    except (ValueError, TypeError):
        return 'UNKNOWN', facts, 'INVALID_MARKET_FACT_TYPE'
    return facts['market_allowed'].upper(), {**{key: facts[key] for key in MARKET_FACTS},
        'market_age_seconds': age, 'context_decision_id': context['decision_id']}, 'EXACT_DECISION_TIME_AND_PUBLISHED_COMPLETE_DAY_FACT'


def aggregate(rows):
    returns = pd.Series([row['net_return'] for row in rows], dtype=float)
    distribution = None if returns.empty else {
        'min': float(returns.min()), 'q10': float(returns.quantile(.1)), 'q25': float(returns.quantile(.25)),
        'median': float(returns.median()), 'q75': float(returns.quantile(.75)), 'q90': float(returns.quantile(.9)),
        'max': float(returns.max()), 'mean': float(returns.mean()), 'quantile_method': 'LINEAR'}
    return {'cycles': len(rows), 'net_pnl': math.fsum(row['net_pnl'] for row in rows),
            'fees': math.fsum(row['fees'] for row in rows),
            'positive_cycles': sum(row['net_pnl'] > 0 for row in rows),
            'negative_cycles': sum(row['net_pnl'] < 0 for row in rows),
            'zero_cycles': sum(row['net_pnl'] == 0 for row in rows),
            'recorded_cycle_net_return_distribution': distribution,
            'net_return_sum_for_partition_check_only': math.fsum(row['net_return'] for row in rows)}


def groups(rows):
    return {name: aggregate([row for row in rows if row['entry_market'] == name]) for name in GROUPS}


def cross(rows):
    return {name: {purpose: aggregate([row for row in rows if row['entry_market'] == name
                  and row['exit_purpose'] == purpose]) for purpose in CATEGORIES} for name in GROUPS}


def check_partition(parts, total, label):
    if sum(part['cycles'] for part in parts) != total['cycles']:
        raise ValueError('partition count mismatch: '+label)
    return {field: equal(math.fsum(part[field] for part in parts), total[field], label+'/'+field)
            for field in ('net_pnl', 'fees', 'net_return_sum_for_partition_check_only')}


def main():
    original, original_refs = load_accounts(WORK, EXPERIMENT, ('C0036',))
    external, external_refs = load_accounts(CONTEXT_WORK, CONTEXT_EXPERIMENT, ('C0043',), exact=True)
    own, other = original['C0036'], external['C0043']
    checks = []
    for field in ECONOMIC_FIELDS:
        if own['request'][field] != other['request'][field]:
            raise ValueError('economic request mismatch: '+field)
        checks.append('request.'+field)
    for product in PRIMARY:
        if own['data'][product] != other['data'][product]:
            raise ValueError('primary product identity mismatch: '+product)
        checks.append('primary.'+product)
    for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
        if economic(own['runs']['buy_hold'][field]) != economic(other['runs']['buy_hold'][field]):
            raise ValueError('embedded BH path mismatch: '+field)
        checks.append('embedded_buy_hold.'+field)
    _, own_source = bind_source(WORK, EXPERIMENT, 'C0036', own)
    definition, other_source = bind_source(CONTEXT_WORK, CONTEXT_EXPERIMENT, 'C0043', other)
    market_binding = verify_market_source(other, definition)
    retained_exit = read(WORK/'others/exit_purpose_description.json')
    if (retained_exit['script_sha256'] != digest(WORK/'src/describe_exits.py')
            or retained_exit['source_accounts']['C0036'] != original_refs['C0036'].to_dict()):
        raise ValueError('retained exit description source/account identity changed')
    actual_exits = describe_exits(own)
    if actual_exits != retained_exit['accounts']['C0036']:
        raise ValueError('retained exit description differs from the exact original ledger')
    run = own['runs']['candidate']
    decisions = index_unique(run['decisions'], 'decision_id')
    orders = index_unique(run['orders'], 'order_id')
    fills = index_unique(run['fills'], 'fill_id')
    trades = index_unique(run['trades'], 'cycle_id')
    context_times = defaultdict(list)
    for point in other['runs']['candidate']['decisions']:
        context_times[at(point['decision_at'])].append(point)
    rows = []
    for cycle in actual_exits['closed_cycles']:
        entry = fills[cycle['entry_fill_id']]
        if entry['side'] != 'BUY' or entry['cycle_id'] != cycle['cycle_id']:
            raise ValueError('original entry cycle join differs')
        order = orders[entry['order_id']]
        decision = decisions[order['decision_id']]
        classification, facts, basis = classify_context(decision, context_times[at(decision['decision_at'])], 432000)
        trade = trades[cycle['cycle_id']]
        if not math.isfinite(trade['net_return']):
            raise ValueError('original cycle net return is unavailable')
        rows.append({'cycle_id': cycle['cycle_id'], 'entry_decision_id': decision['decision_id'],
            'entry_order_id': order['order_id'], 'entry_fill_id': entry['fill_id'],
            'entry_decision_at': decision['decision_at'], 'entry_at': trade['entry_at'],
            'entry_session': at(decision['decision_at']).astimezone(ZONE).date().isoformat(),
            'entry_market': classification, 'classification_basis': basis, 'market_facts': facts,
            'exit_purpose': cycle['category'], 'net_pnl': trade['net_pnl'], 'net_return': trade['net_return'],
            'fees': cycle['fees']})
    total, grouped, crossed = aggregate(rows), groups(rows), cross(rows)
    yearly = {str(year): {'total': aggregate([row for row in rows if row['entry_session'].startswith(str(year))]),
        'entry_market': groups([row for row in rows if row['entry_session'].startswith(str(year))]),
        'entry_market_by_exit_purpose': cross([row for row in rows if row['entry_session'].startswith(str(year))])}
        for year in range(2019, 2026)}
    residuals = {'market_groups': check_partition(list(grouped.values()), total, 'market groups'),
        'cross_table': check_partition([item for group in crossed.values() for item in group.values()], total, 'cross table'),
        'years': check_partition([year['total'] for year in yearly.values()], total, 'all years')}
    for name in GROUPS:
        residuals['cross_'+name] = check_partition(list(crossed[name].values()), grouped[name], 'cross/'+name)
    for year, values in yearly.items():
        residuals[year] = check_partition(list(values['entry_market'].values()), values['total'], year)
        residuals[year+'_cross'] = check_partition(
            [item for group in values['entry_market_by_exit_purpose'].values() for item in group.values()],
            values['total'], year+'/cross')
    if total['cycles'] != 555 or total['cycles'] != len(trades):
        raise ValueError('the original fixed 555 cycles were not all retained')
    equal(total['net_pnl'], actual_exits['totals']['net_pnl'], 'original net pnl')
    equal(total['fees'], actual_exits['totals']['fees'], 'original actual fees')
    evidence = {'schema': 'S017_ORIGINAL_ENTRY_MARKET_CONTEXT_DESCRIPTION_V1', 'status': 'PASS',
        'scope': 'ORIGINAL_C0036_ACTUAL_555_CYCLES_2019_2025',
        'script_sha256': digest(Path(__file__)),
        'source_accounts': {**{key: value.to_dict() for key, value in original_refs.items()},
                            **{key: value.to_dict() for key, value in external_refs.items()}},
        'frozen_sources': {'C0036': own_source, 'C0043': other_source},
        'same_primary_and_economic_contract_and_bh': {'status': 'PASS', 'checked_fields': checks},
        'market_source_and_holding_independence': market_binding,
        'original_exit_description_sha256': digest(WORK/'others/exit_purpose_description.json'),
        'totals': total, 'by_entry_market': grouped, 'entry_market_by_exit_purpose': crossed,
        'by_entry_year': yearly, 'reconciliation_residuals': residuals,
        'unknown_reasons': dict(Counter(row['classification_basis'] for row in rows if row['entry_market'] == 'UNKNOWN')),
        'classification_complete': grouped['UNKNOWN']['cycles'] == 0,
        'limitations': ['ACTUALLY_SELECTED_TRADES_CONDITIONAL_DESCRIPTION_ONLY',
            'HOLDINGS_CAPITAL_AND_OPPORTUNITY_SELECTION_AFFECT_ORIGINAL_TRADES',
            'DO_NOT_DELETE_A_GROUP_TO_ESTIMATE_NEW_FILTER_ACCOUNT',
            'NO_COUNTERFACTUAL_RETURN_NO_FEE_ADDBACK_NO_CAUSAL_CLAIM',
            'CYCLE_RETURN_QUANTILES_NOT_PORTFOLIO_RETURNS', 'UNKNOWN_NEVER_FALSE_OR_DROPPED',
            'ANNUAL_DESCRIPTIONS_NOT_YEAR_RULES', 'NO_NEW_THRESHOLD_SEARCH_OR_EXPERIMENT',
            'CONTEXT_AVAILABILITY_INHERITS_AUTHENTICATED_PUBLIC_SRT_CONTRACT',
            'NO_NEW_DIAGNOSIS_NO_PRIVATE_CHECKPOINT_NO_2026_PRICE'], 'closed_cycles': rows}
    save(WORK/'others/entry_market_context_description.json', evidence)
    for name, value in grouped.items():
        print(name, value, flush=True)
    print('CROSS', {name: {purpose: {key: item[key] for key in ('cycles', 'net_pnl', 'fees')}
                         for purpose, item in group.items()} for name, group in crossed.items()}, flush=True)


if __name__ == '__main__':
    main()
