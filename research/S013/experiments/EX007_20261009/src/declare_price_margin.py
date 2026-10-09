"""Prospectively publish existing-component bull price-amplitude confirmations."""
from copy import deepcopy
from hashlib import sha256

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite

from common import CACHE, EXPERIMENT, PROTOCOLS, RUNS, SOURCE, SOURCE_CALLS, cache_read, config_hash, context, read, write
from diagnose import rows


def main():
    plan_path = PROTOCOLS / 'price_margin_plan.json'
    assert not plan_path.exists(), 'Prospective price-margin plan already exists'
    observed = [row for row in rows() if row['candidate_id'] == 'C3107']
    assert len(observed) == 1 and observed[0]['status'] == 'SUCCEEDED'
    origin, result = cache_read(CACHE / 'C3107.pkl.gz')
    assert result.result_hash == observed[0]['result_hash']
    original = deepcopy(observed[0]['parameters'])
    assert dict(origin.strategy.payload['parameters']) == original
    assert original['regime_window'] == 20 and original['regime_threshold'] == .005
    assert original['bull']['momentum_min'] is None
    assert original['bull']['cooldown'] == original['bear']['cooldown'] == 0
    assert original['opportunity_confirmation']['application'] == 'ordinary_entries'
    assert original['opportunity_confirmation']['route_scope'] == 'bull'
    attribution = read(RUNS / 'path_attribution.json')
    assert attribution['status'] == 'PASS'
    configs = []
    for index, margin in enumerate((0., .0025, .005, .01)):
        parameters = deepcopy(original)
        floor = .005 + margin
        parameters['bull']['momentum_min'] = floor
        configs.append({'candidate_id': f'C{3200 + index}', 'parent': 'C2308',
                       'origin_configuration': 'C3107', 'price_margin': margin,
                       'bull_momentum_floor': floor, 'parameters': parameters,
                       'config_hash': config_hash(parameters),
                       'label': f'C3107-bull-all-entries-price-margin-{margin:g}'})
    source_files = {path.relative_to(SOURCE).as_posix(): sha256(path.read_bytes()).hexdigest()
                    for path in SOURCE.rglob('*.py')}
    assert len(source_files) == 5
    initial = read(PROTOCOLS / 'initial_plan.json')
    assert source_files == initial['source_files'], 'Runtime source changed since prior prospective plan'
    plan = {'name': 'cost_confirmation_price_margin', 'configurations': configs,
            'prechecked_controls': ['C3200'], 'precheck_file': 'price_margin_precheck.json',
            'origin_configuration': 'C3107', 'origin_result_hash': result.result_hash,
            'origin_configuration_hash': config_hash(original),
            'attribution_sha256': sha256((RUNS / 'path_attribution.json').read_bytes()).hexdigest(),
            'source_files': source_files,
            'authorized_scope': 'Continue approved S013 stage-three research on the same research branch; reuse only existing 510500.SH developer-pool data 2020-01-02..2026-09-30 and existing warmup.',
            'hypothesis': 'Price distance above the existing bull state boundary may confirm buys that amount/volume absolute ranks do not distinguish. The existing momentum_min component applies to every bull entry, including regime reentry.',
            'expression': 'bull momentum20 >= .005 + price_margin; momentum20 and regime_momentum are the same causal 20-session price expression in this configuration.',
            'scope': 'Only bull.momentum_min changes. C3107 ordinary-bull supplementary gate remains ordinary-only, original reentry gate remains unchanged, all exits and both zero cooldowns remain unchanged.',
            'control': 'C3200 margin zero must reproduce all C3107 signals, five ledgers, semantics and benchmark exactly with relational identifiers normalized.',
            'known_information': 'All 38 EX007 configurations and the full previously seen S013 developer pool were examined. The 2023 losing bull/regime cohorts, score nonseparation and low-boundary-margin entry dates were inspected before this plan. This is adaptive development, with no holdout or out-of-sample claim.',
            'competing_explanations': ['Known-year selection bias', 'Delayed entry and missed profitable opportunities',
                                      'Reduced frequency below the existing gate', 'Price-path and lot-size changes across the continuous account'],
            'hard_gates': 'The same four user-confirmed gates at baseline one-way 10bp; no additional acceptance gates.',
            'diagnostics': 'Price margin is a causal price amplitude, not a probability or waiting-day count. Annual price/fees, route cohorts, concentration and 20/30bp sensitivity remain report-only.',
            'excluded': ['Fixed waiting-day cooldown', 'Other research-batch data/results', 'External source acquisition',
                         'New runtime source or dependencies', 'Platform edits', 'Production/freeze/stage advancement', 'Merge/tag/push'],
            'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13}}
    write(plan_path, plan)
    reference = publish_evidence(context(1), MaterialEvidenceWrite(
        EXPERIMENT, 'cost-confirmation-price-margin-plan', plan_path.read_bytes(),
        'application/json', 'json'))
    write(PROTOCOLS / 'price_margin_references.json', {'plan': reference.to_dict()})
    assert not SOURCE_CALLS
    print({'published': True, 'configurations': len(configs), 'control': 'C3200'}, flush=True)


if __name__ == '__main__':
    main()
